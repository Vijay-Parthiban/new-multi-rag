"""End-to-end verification of the Ingestion Profile modality.

Proves, against a running ingestion API and live destination stores:
  1. A profile carries no connection value and no vector dimension, and its store
     names are absent until the product copy derives them.
  2. The vector dimension is derived from the embedding model output, so a Qdrant
     write succeeds without the user typing a size.
  3. Text mode stores no record tagged as an image.
  4. Switching the profile to ``text_images`` re-ingests the file, and every
     destination receives one record per document page, embedded from the page
     image rather than from the text.
  5. Every page image is stored in the source bucket under ``_pages/``, and the
     stored record names it.
  6. The four destinations agree on the page count, so none dropped a record.
  7. ``text_images`` with an empty image embedding model is rejected at save time.

Usage:
    uv run python scripts/e2e_ingestion_modality.py
    uv run python scripts/e2e_ingestion_modality.py --base-url http://localhost:8007
    uv run python scripts/e2e_ingestion_modality.py --source-id <uuid>

Exit codes: 0 all checks passed, 1 setup or request failure, 2 an assertion failed.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

DEST_TYPES = ["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]
NAMESPACE_KEY = {
    "vector_qdrant": "collection_name",
    "lexical_opensearch": "index_name",
    "relational_pgvector": "schema_name",
    "cache_redisvl": "index_prefix",
}
FILE_KEY = "e2e_modality_pages.pdf"
IMAGE_EMBEDDING_MODEL = "nvidia-embed-multimodal"
PAGES = 3
CHUNK_SIZE = 600
CHUNK_OVERLAP = 60
# The test product links a real source bucket, so a sync run also processes every
# other document in that bucket. The waits are long enough for this file's own row
# and records to appear behind the rest, and a genuine failure still ends the run.
SETTLE_TIMEOUT_S = 600

# Keys that must never come back from the options route or a profile payload.
CONNECTION_KEYS = {
    "url",
    "api_key",
    "endpoint_url",
    "connection_url",
    "redis_url",
    "litellm_base_url",
    "litellm_api_key",
    "username",
    "password",
    "auth_type",
}
DERIVED_KEYS = {"vector_size", "collection_name", "index_name", "schema_name", "index_prefix"}

failures: list[str] = []


def check(condition: bool, label: str, detail: Any = None) -> None:
    if condition:
        print(f"  PASS  {label}")
        return
    failures.append(label)
    print(f"  FAIL  {label}" + (f"  ({detail})" if detail is not None else ""))


def pages_pdf() -> bytes:
    """A three-page PDF, one text layer per page.

    Built here so no binary fixture is committed. Three pages make "one record per
    page" and "one stored object per page" countable rather than a guess.
    """
    import fitz

    doc = fitz.open()
    for index in range(PAGES):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            f"Page {index + 1} of the quarterly capacity review. Region North shipped "
            f"{1200 + index} units and region South shipped 900 units, so the combined "
            "total for the period rose against the previous quarter.",
        )
    payload = doc.tobytes()
    doc.close()
    return payload


def page_image_keys(bucket: str, file_key: str) -> list[str]:
    """The page images the fanout wrote for one file, read straight from the bucket.

    Read from object storage, because that object is what a later reader downloads.
    """
    import asyncio

    from src.shared.storage.s3_client import list_objects

    try:
        objects = asyncio.run(list_objects(bucket, f"_pages/{file_key}/"))
    except Exception as exc:
        print("could not list the source bucket:", exc)
        return []
    return sorted(obj.key for obj in objects)


def inspect(client: httpx.Client, api: str, product_id: str, dest: str) -> dict[str, Any]:
    """Read one store scoped to FILE_KEY.

    The store sample cap applies to a whole store, so a per-file count has to ask
    for that file or a large store hides some of its records.

    The call is retried and its failure is returned, not raised: an inspect reads a
    live store while the API also serves the fanout for a product that syncs the
    whole bucket, and a dropped connection must not end the run.
    """
    last_error: Any = None
    for _ in range(3):
        try:
            resp = client.get(
                f"{api}/api/knowledge-products/{product_id}/inspect/{dest}",
                params={"file_key": FILE_KEY},
            )
            return resp.json() if resp.status_code == 200 else {"error": resp.text}
        except Exception as exc:
            last_error = exc
            time.sleep(3)
    return {"error": f"inspect failed after 3 attempts: {last_error}"}


def dest_total(dest: str, payload: dict[str, Any]) -> int:
    if dest == "vector_qdrant":
        return int(payload.get("total_points") or 0)
    if dest == "lexical_opensearch":
        return int(payload.get("total_docs") or 0)
    if dest == "relational_pgvector":
        return int(payload.get("total_rows") or 0)
    if dest == "cache_redisvl":
        return int(payload.get("total_cached_keys") or 0)
    return 0


def dest_file_records(dest: str, payload: dict[str, Any], file_key: str) -> list[dict[str, Any]]:
    """The stored records for one file, normalised to a dict per record."""
    if dest == "vector_qdrant":
        return [
            dict(p.get("payload") or {})
            for p in payload.get("points") or []
            if (p.get("payload") or {}).get("file_key") == file_key
        ]
    if dest == "lexical_opensearch":
        return [dict(d) for d in payload.get("documents") or [] if d.get("file_key") == file_key]
    if dest == "relational_pgvector":
        return [dict(r) for r in payload.get("rows") or [] if r.get("file_key") == file_key]
    if dest == "cache_redisvl":
        # The cached value is JSON under each key, so the stored record carries the
        # modality and the page reference even though the key name does not.
        out: list[dict[str, Any]] = []
        for entry in payload.get("keys") or []:
            key = str(entry.get("key") or "")
            if f":{file_key}:" not in key or key.endswith((":children", ":summary")):
                continue
            value = entry.get("value")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = {"content": value}
            out.append(dict(value) if isinstance(value, dict) else {"content": str(value)})
        return out
    return []


def image_records(dest: str, payload: dict[str, Any], file_key: str) -> list[dict[str, Any]]:
    return [
        r
        for r in dest_file_records(dest, payload, file_key)
        if str(r.get("modality") or "") == "image"
    ]


def wait_for_images(
    client: httpx.Client,
    api: str,
    product_id: str,
    *,
    min_images: int,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll until every destination holds at least ``min_images`` image records.

    A minimum, not an exact count, because a store can hold other files of the same
    bucket. That the four destinations agree on their count is checked separately,
    since that is the cross-store invariant.
    """
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    ok = False
    while time.time() < deadline:
        state = {}
        ok = True
        for dest in DEST_TYPES:
            payload = inspect(client, api, product_id, dest)
            found = image_records(dest, payload, FILE_KEY)
            state[dest] = {
                "images": len(found),
                "error": payload.get("error"),
                "sample": (found[0].get("content") or "")[:120] if found else "",
                "kinds": sorted({str(r.get("record_type") or "") for r in found}),
                "refs": [r.get("image_ref") for r in found],
            }
            if len(found) < min_images:
                ok = False
        if ok:
            break
        time.sleep(3)
    return {"ok": ok, "state": state}


def wait_for_text_hits(
    client: httpx.Client,
    api: str,
    product_id: str,
    *,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll until every destination holds at least one record for the file."""
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    ok = False
    while time.time() < deadline:
        state = {}
        ok = True
        for dest in DEST_TYPES:
            payload = inspect(client, api, product_id, dest)
            records = dest_file_records(dest, payload, FILE_KEY)
            state[dest] = {"records": len(records), "error": payload.get("error")}
            if not records:
                ok = False
        if ok:
            break
        time.sleep(3)
    return {"ok": ok, "state": state}


def ledger_row(client: httpx.Client, api: str, product_id: str) -> dict[str, Any] | None:
    """The ledger row for FILE_KEY, or None.

    The route orders by ``updated_at`` and caps one page at 200 rows, and a product
    that links a whole bucket holds more rows than one page. So the search pages
    until it finds the row or runs out of rows.
    """
    offset = 0
    while offset < 1000:
        resp = client.get(
            f"{api}/api/knowledge-products/{product_id}/files",
            params={"limit": 200, "offset": offset},
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        for row in body.get("files", []):
            if row.get("file_key") == FILE_KEY:
                return row
        offset += 200
        if offset >= int(body.get("total") or 0):
            return None
    return None


def wait_for_ledger(
    client: httpx.Client, api: str, product_id: str, *, timeout_s: int = SETTLE_TIMEOUT_S
) -> dict[str, Any] | None:
    deadline = time.time() + timeout_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = ledger_row(client, api, product_id)
        if last and last.get("status") == "synced":
            return last
        time.sleep(3)
    return last


def clear_file(client: httpx.Client, api: str, source_id: str) -> None:
    try:
        client.delete(f"{api}/api/sources/{source_id}/files", params={"key": FILE_KEY})
    except Exception:
        pass


def clear_stale_records(client: httpx.Client, api: str) -> None:
    """Delete records a cancelled earlier run left behind.

    Leftover products keep their pollers running, so they keep writing to stores
    this run does not own.
    """
    try:
        for product in client.get(f"{api}/api/knowledge-products").json():
            if str(product.get("name") or "").startswith("E2E Modality "):
                client.delete(f"{api}/api/knowledge-products/{product['id']}")
        for profile in client.get(f"{api}/api/ingestion-profiles").json():
            if str(profile.get("name") or "").startswith("E2E Modality "):
                client.delete(f"{api}/api/ingestion-profiles/{profile['id']}")
    except Exception as exc:
        print("stale cleanup skipped:", exc)


def pick_source(client: httpx.Client, api: str, requested: str | None) -> tuple[str, str] | None:
    """(source id, bucket) for a source the fanout can list."""
    resp = client.get(f"{api}/api/sources")
    if resp.status_code != 200:
        print("could not list sources:", resp.status_code, resp.text)
        return None
    sources = resp.json()
    for src in sources:
        if requested and src.get("id") != requested:
            continue
        if src.get("minio_bucket") and not str(src["minio_bucket"]).startswith("local-"):
            return src["id"], str(src["minio_bucket"])
    if sources:
        return sources[0]["id"], str(sources[0].get("minio_bucket") or "")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8007")
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--keep", action="store_true", help="Do not delete the created records.")
    args = parser.parse_args()
    api = args.base_url.rstrip("/")
    report: dict[str, Any] = {}

    # 300s: an inspect reads four live stores, and the API also serves the fanout
    # while the test product syncs the whole bucket.
    with httpx.Client(timeout=300.0) as client:
        try:
            client.get(f"{api}/api/knowledge-products").raise_for_status()
        except Exception as exc:
            print(f"Ingestion API not reachable at {api}: {exc}")
            return 1

        picked = pick_source(client, api, args.source_id)
        if not picked:
            print("No source bucket available. Create a source first.")
            return 1
        source_id, bucket = picked
        print(f"Using source {source_id} (bucket {bucket})")
        clear_stale_records(client, api)
        clear_file(client, api, source_id)

        suffix = uuid.uuid4().hex[:6]
        products: list[str] = []
        profiles: list[str] = []

        print("\n=== 1. A profile carries no connection value and no dimension ===")
        resp_profile = client.post(
            f"{api}/api/ingestion-profiles",
            json={
                "name": f"E2E Modality Text {suffix}",
                "description": "e2e modality profile",
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "modality_mode": "text",
                "text_embedding_model": "nvidia-embed-textonly",
                "destinations": [
                    {"destination_type": dest, "enabled": True, "config": {}} for dest in DEST_TYPES
                ],
            },
        )
        if resp_profile.status_code not in (200, 201):
            print("create profile failed:", resp_profile.status_code, resp_profile.text)
            return 1
        profile = resp_profile.json()
        profiles.append(profile["id"])
        report["profile"] = {
            "id": profile["id"],
            "modality_mode": profile["modality_mode"],
            "text_embedding_model": profile["text_embedding_model"],
            "image_embedding_model": profile["image_embedding_model"],
            "chunk_config": profile["chunk_config"],
        }

        check(
            profile["modality_mode"] == "text",
            "the profile stores text mode",
            profile["modality_mode"],
        )
        check(
            bool(profile.get("text_embedding_model")),
            "the profile stores a text embedding model",
            profile.get("text_embedding_model"),
        )
        check(
            profile.get("chunk_config") == {},
            "a profile created with no strategy settings stores an empty config",
            profile.get("chunk_config"),
        )
        check(
            all(
                not (set(d["config"] or {}) & (CONNECTION_KEYS | DERIVED_KEYS))
                for d in profile["destinations"]
            ),
            "no connection value or store name in the profile config",
            [
                sorted(set(d["config"] or {}) & (CONNECTION_KEYS | DERIVED_KEYS))
                for d in profile["destinations"]
            ],
        )

        print("\n=== 1b. The strategy catalogue reaches the form ===")
        specs = client.get(f"{api}/api/ingestion-profiles/chunk-strategies")
        report["chunk_strategies"] = [
            {"value": s["value"], "params": [p["key"] for p in s["params"]]}
            for s in (specs.json() if specs.status_code == 200 else [])
        ]
        check(specs.status_code == 200, "the catalogue route answers", specs.status_code)
        if specs.status_code == 200:
            by_value = {s["value"]: s for s in specs.json()}
            check(
                len(by_value) == 8,
                "the catalogue offers eight strategies",
                sorted(by_value),
            )
            check(
                {"recursive", "fixed", "section", "context_aware", "parent_child", "contextual",
                 "page_level", "sentence_window"} == set(by_value),
                "the catalogue names the eight strategies",
                sorted(by_value),
            )
            contextual = {
                p["key"]: p for p in by_value.get("contextual", {}).get("params", [])
            }
            check(
                contextual.get("context_model", {}).get("model_kind") == "chat"
                and contextual.get("context_model", {}).get("required") is True,
                "contextual declares a required chat model",
                contextual.get("context_model"),
            )
            semantic = {
                p["key"]: p for p in by_value.get("context_aware", {}).get("params", [])
            }
            check(
                len(semantic.get("semantic_threshold_type", {}).get("options") or []) == 3,
                "semantic declares three breakpoint measures",
                semantic.get("semantic_threshold_type"),
            )

        print("\n=== 1c. A bad strategy config is rejected ===")
        resp_bad_config = client.patch(
            f"{api}/api/ingestion-profiles/{profile['id']}",
            json={"chunk_strategy": "sentence_window", "chunk_config": {"bogus": 1}},
        )
        detail = resp_bad_config.json().get("detail") if resp_bad_config.status_code == 422 else {}
        report["bad_config"] = {"status": resp_bad_config.status_code, "detail": detail}
        check(
            resp_bad_config.status_code == 422,
            "422 when a strategy config names an unknown key",
            resp_bad_config.status_code,
        )
        check(
            isinstance(detail, dict) and detail.get("code") == "CHUNK_CONFIG_INVALID",
            "CHUNK_CONFIG_INVALID code returned",
            detail,
        )

        print("\n=== 1d. Images with an empty model are rejected ===")
        resp_422 = client.patch(
            f"{api}/api/ingestion-profiles/{profile['id']}",
            json={"modality_mode": "text_images", "image_embedding_model": ""},
        )
        detail = resp_422.json().get("detail") if resp_422.status_code == 422 else {}
        report["image_model_required"] = {"status": resp_422.status_code, "detail": detail}
        check(
            resp_422.status_code == 422,
            "422 when images are enabled with an empty model",
            resp_422.status_code,
        )
        check(
            isinstance(detail, dict) and detail.get("code") == "IMAGE_EMBEDDING_MODEL_REQUIRED",
            "IMAGE_EMBEDDING_MODEL_REQUIRED code returned",
            detail,
        )

        print("\n=== 1e. The options route offers no connection field ===")
        options = client.get(f"{api}/api/knowledge-products/destinations/options").json()
        offered = {f["key"] for o in options for f in (o.get("fields") or [])}
        report["offered_fields"] = sorted(offered)
        check(
            not (offered & (CONNECTION_KEYS | DERIVED_KEYS)),
            "no connection or store-name field is offered to the client",
            sorted(offered & (CONNECTION_KEYS | DERIVED_KEYS)),
        )
        check(len(offered) == 15, "15 destination fields remain", len(offered))

        print("\n=== 2. A product from the profile ingests in text mode ===")
        resp_product = client.post(
            f"{api}/api/knowledge-products",
            json={
                "name": f"E2E Modality Product {suffix}",
                "enabled": True,
                "monitor_mode": "live",
                "source_ids": [source_id],
                "ingestion_profile_id": profile["id"],
            },
        )
        if resp_product.status_code not in (200, 201):
            print("create product failed:", resp_product.status_code, resp_product.text)
            return 1
        product = resp_product.json()
        products.append(product["id"])
        report["product"] = {
            "id": product["id"],
            "modality_mode": product.get("modality_mode"),
            "text_embedding_model": product.get("text_embedding_model"),
            "image_embedding_model": product.get("image_embedding_model"),
        }

        check(
            product.get("modality_mode") == "text",
            "text mode on the product",
            product.get("modality_mode"),
        )
        check(
            bool(product.get("text_embedding_model")),
            "the embedding model is reported on the product",
            product.get("text_embedding_model"),
        )
        by_type = {d["destination_type"]: d for d in product["destinations"]}
        check(
            all(
                str((by_type[dest]["config"] or {}).get(NAMESPACE_KEY[dest], "")).startswith("kp")
                for dest in DEST_TYPES
            ),
            "the product copy derives every store name",
            {
                dest: (by_type[dest]["config"] or {}).get(NAMESPACE_KEY[dest])
                for dest in DEST_TYPES
            },
        )
        check(
            all("vector_size" not in (by_type[dest]["config"] or {}) for dest in DEST_TYPES),
            "no configured vector dimension on the product",
            [by_type[dest]["config"] for dest in DEST_TYPES],
        )

        print(f"\n=== 3. Upload the {PAGES}-page PDF ===")
        resp_up = client.post(
            f"{api}/api/sources/{source_id}/files",
            files={"file": (FILE_KEY, io.BytesIO(pages_pdf()), "application/pdf")},
        )
        check(
            resp_up.status_code in (200, 201),
            "the PDF is uploaded to the bucket",
            resp_up.text[:200],
        )

        row = wait_for_ledger(client, api, product["id"])
        report["ledger"] = row
        check(bool(row) and row.get("status") == "synced", "the ledger reaches synced", row)
        check(
            row is not None and row.get("pages_indexed") == PAGES,
            f"the ledger counts {PAGES} source pages",
            row.get("pages_indexed") if row else None,
        )

        text_state = wait_for_text_hits(client, api, product["id"])
        report["text_mode"] = text_state["state"]
        check(
            text_state["ok"],
            "every destination holds the text chunks",
            text_state["state"],
        )

        print("\n=== 4. The vector dimension is derived, so Qdrant accepts the write ===")
        qdrant_payload = inspect(client, api, product["id"], "vector_qdrant")
        points = dest_file_records("vector_qdrant", qdrant_payload, FILE_KEY)
        report["qdrant_points"] = len(points)
        report["qdrant_total"] = dest_total("vector_qdrant", qdrant_payload)
        check(
            dest_total("vector_qdrant", qdrant_payload) > 0,
            "Qdrant holds points without a configured vector_size",
            {"points": len(points), "error": qdrant_payload.get("error")},
        )

        print("\n=== 5. Text mode stores no image record ===")
        text_images = {
            dest: len(image_records(dest, inspect(client, api, product["id"], dest), FILE_KEY))
            for dest in DEST_TYPES
        }
        report["text_mode_images"] = text_images
        check(
            all(count == 0 for count in text_images.values()),
            "no destination holds an image record in text mode",
            text_images,
        )

        print("\n=== 6. Switch to text_images and re-apply ===")
        resp_patch = client.patch(
            f"{api}/api/ingestion-profiles/{profile['id']}",
            json={"modality_mode": "text_images", "image_embedding_model": IMAGE_EMBEDDING_MODEL},
        )
        check(
            resp_patch.status_code == 200,
            "the profile switches to text_images",
            resp_patch.text[:200],
        )
        patched = resp_patch.json()
        report["patched"] = {
            "modality_mode": patched.get("modality_mode"),
            "image_embedding_model": patched.get("image_embedding_model"),
        }
        check(
            patched.get("modality_mode") == "text_images",
            "text_images stored on the profile",
            patched.get("modality_mode"),
        )
        check(
            patched.get("image_embedding_model") == IMAGE_EMBEDDING_MODEL,
            "the image embedding model stored on the profile",
            patched.get("image_embedding_model"),
        )

        resp_apply = client.post(
            f"{api}/api/knowledge-products/{product['id']}/apply-profile", json={}
        )
        applied = resp_apply.json() if resp_apply.status_code == 200 else {}
        report["apply"] = {
            "status": resp_apply.status_code,
            "updated": applied.get("updated"),
            "purged": applied.get("purged_files"),
        }
        check(resp_apply.status_code == 200, "apply-profile returns 200", resp_apply.text[:300])
        check(
            sorted(applied.get("updated") or []) == sorted(DEST_TYPES),
            "a modality change marks every destination for a rebuild",
            applied.get("updated"),
        )
        check(
            int(applied.get("purged_files") or 0) >= 1,
            "the old records are purged",
            applied.get("purged_files"),
        )

        print(f"\n=== 7. Every destination receives one record per page ===")
        image_state = wait_for_images(client, api, product["id"], min_images=PAGES)
        report["image_mode"] = image_state["state"]
        check(
            image_state["ok"],
            f"every destination holds {PAGES} page records",
            image_state["state"],
        )

        if image_state["ok"]:
            counts = [entry["images"] for entry in image_state["state"].values()]
            check(
                len(set(counts)) == 1,
                "the four destinations agree on the page count",
                counts,
            )
            check(
                all(entry["kinds"] == ["page"] for entry in image_state["state"].values()),
                "every image record is tagged as a page",
                {dest: e["kinds"] for dest, e in image_state["state"].items()},
            )
            samples = {dest: entry["sample"] for dest, entry in image_state["state"].items()}
            report["pages"] = samples
            check(
                all(sample.strip() for sample in samples.values()),
                "every stored page record carries the page text",
                samples,
            )
            refs = [
                ref
                for entry in image_state["state"].values()
                for ref in entry["refs"]
                if isinstance(ref, dict)
            ]
            check(
                bool(refs) and all(str(ref.get("key") or "").startswith("_pages/") for ref in refs),
                "the page record names its stored page image",
                refs[:3],
            )

            keys = page_image_keys(bucket, FILE_KEY)
            report["page_images"] = keys
            check(
                len(keys) == PAGES,
                f"the bucket holds {PAGES} page images under _pages/",
                keys,
            )
            check(
                len({Path(key).name for key in keys}) == len(keys),
                "each page image has its own object name",
                keys,
            )

            after_row = wait_for_ledger(client, api, product["id"])
            report["ledger_after"] = after_row
            check(
                after_row is not None and after_row.get("status") == "synced",
                "the ledger returns to synced after the rebuild",
                after_row,
            )

        print("\n=== 8. Cleanup ===")
        if not args.keep:
            for product_id in products:
                client.delete(f"{api}/api/knowledge-products/{product_id}")
            for profile_id in profiles:
                client.delete(f"{api}/api/ingestion-profiles/{profile_id}")
            clear_file(client, api, source_id)
            print("  removed test products, profiles and the uploaded object")

    report_path = Path(tempfile.gettempdir()) / "e2e_ingestion_modality_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}")

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for label in failures:
            print(f"  - {label}")
        return 2
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
