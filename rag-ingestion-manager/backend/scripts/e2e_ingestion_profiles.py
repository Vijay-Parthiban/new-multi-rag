"""End-to-end verification of Ingestion Profiles.

Proves, against a running ingestion API and live destination stores:
  1. A profile carries no store name and no connection value; the product copy
     derives and assigns the namespaced store names.
  2. Create with an Ingestion Profile alone starts ingestion.
  3. The profile's chunk_size splits every page, and the ledger keeps counting
     source pages.
  4. Two products over one bucket with different profiles chunk differently and
     keep separate stores and separate ledgers.
  5. Apply Profile re-copies the profile and purges the stores it replaces.
  6. A profile a product references cannot be deleted.
  7. Chunk overlap at or above the chunk size is rejected.

Usage:
    uv run python scripts/e2e_ingestion_profiles.py
    uv run python scripts/e2e_ingestion_profiles.py --base-url http://localhost:8007
    uv run python scripts/e2e_ingestion_profiles.py --source-id <uuid>

Exit codes: 0 all checks passed, 1 setup or request failure, 2 an assertion failed.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import uuid
from typing import Any

import httpx

DEST_TYPES = ["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]
NAMESPACE_KEY = {
    "vector_qdrant": "collection_name",
    "lexical_opensearch": "index_name",
    "relational_pgvector": "schema_name",
    "cache_redisvl": "index_prefix",
}
FILE_KEY = "e2e_profile_notes.txt"
SMALL_CHUNK_SIZE = 200
SMALL_CHUNK_OVERLAP = 20
LARGE_CHUNK_SIZE = 8000  # the API ceiling; still far above the test document
SETTLE_TIMEOUT_S = 180

# Three paragraphs of 40 words each: about 1200 characters, so the small profile
# splits it into several chunks and the large one keeps it whole.
PARAGRAPHS = 3
PARAGRAPH = " ".join(["knowledge"] * 40)
DOCUMENT = "\n\n".join(PARAGRAPH for _ in range(PARAGRAPHS))

# The same splitter the fanout calls, so the expected count is not a guess.
from src.ingestion_service.utils.text_splitter import chunk_text  # noqa: E402

EXPECTED_SMALL_CHUNKS = len(chunk_text(DOCUMENT, SMALL_CHUNK_SIZE, SMALL_CHUNK_OVERLAP))
EXPECTED_LARGE_CHUNKS = len(chunk_text(DOCUMENT, LARGE_CHUNK_SIZE, 50))

failures: list[str] = []


def check(condition: bool, label: str, detail: Any = None) -> None:
    if condition:
        print(f"  PASS  {label}")
        return
    failures.append(label)
    print(f"  FAIL  {label}" + (f"  ({detail})" if detail is not None else ""))


def inspect(client: httpx.Client, api: str, product_id: str, dest: str) -> dict[str, Any]:
    """Read one store scoped to FILE_KEY.

    The store sample cap applies to a whole store, so a per-file count has to ask
    for that file or a large store hides some of its records.
    """
    resp = client.get(
        f"{api}/api/knowledge-products/{product_id}/inspect/{dest}",
        params={"file_key": FILE_KEY},
    )
    return resp.json() if resp.status_code == 200 else {"error": resp.text}


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


def dest_file_hits(dest: str, payload: dict[str, Any], file_key: str) -> int:
    if dest == "vector_qdrant":
        return sum(
            1 for p in payload.get("points") or [] if (p.get("payload") or {}).get("file_key") == file_key
        )
    if dest == "lexical_opensearch":
        return sum(1 for d in payload.get("documents") or [] if d.get("file_key") == file_key)
    if dest == "relational_pgvector":
        return sum(1 for r in payload.get("rows") or [] if r.get("file_key") == file_key)
    if dest == "cache_redisvl":
        pages = 0
        for k in payload.get("keys") or []:
            key = str(k.get("key") or "")
            if f":{file_key}:" not in key:
                continue
            if key.endswith(":children") or key.endswith(":summary"):
                continue
            pages += 1
        return pages
    return 0


def dest_chunk_indexes(dest: str, payload: dict[str, Any], file_key: str) -> list[int]:
    """chunk_index values the store holds for one file, sorted."""
    if dest == "vector_qdrant":
        found = [
            (p.get("payload") or {}).get("chunk_index")
            for p in payload.get("points") or []
            if (p.get("payload") or {}).get("file_key") == file_key
        ]
    elif dest == "lexical_opensearch":
        found = [d.get("chunk_index") for d in payload.get("documents") or [] if d.get("file_key") == file_key]
    elif dest == "relational_pgvector":
        found = [r.get("chunk_index") for r in payload.get("rows") or [] if r.get("file_key") == file_key]
    else:
        found = [
            int(str(k.get("key") or "").rsplit(":", 1)[-1])
            for k in payload.get("keys") or []
            if f":{file_key}:" in str(k.get("key") or "")
            and not str(k.get("key") or "").endswith((":children", ":summary"))
        ]
    return sorted(int(v) for v in found if v is not None)


def ledger_row(client: httpx.Client, api: str, product_id: str) -> dict[str, Any] | None:
    resp = client.get(f"{api}/api/knowledge-products/{product_id}/files", params={"limit": 50})
    if resp.status_code != 200:
        return None
    for row in resp.json().get("files", []):
        if row.get("file_key") == FILE_KEY:
            return row
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


def wait_for_exact_hits(
    client: httpx.Client,
    api: str,
    product_id: str,
    *,
    expect: int,
    types: list[str] | None = None,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll until every named destination holds exactly ``expect`` documents for the file."""
    targets = types or DEST_TYPES
    deadline = time.time() + timeout_s
    hits: dict[str, Any] = {}
    ok = False
    while time.time() < deadline:
        hits = {}
        ok = True
        for dest in targets:
            payload = inspect(client, api, product_id, dest)
            found = dest_file_hits(dest, payload, FILE_KEY)
            hits[dest] = {
                "hits": found,
                "total": dest_total(dest, payload),
                "chunk_indexes": dest_chunk_indexes(dest, payload, FILE_KEY),
                "error": payload.get("error"),
            }
            if found != expect:
                ok = False
        if ok:
            break
        time.sleep(3)
    return {"ok": ok, "hits": hits}


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
            if str(product.get("name") or "").startswith("E2E Profile "):
                client.delete(f"{api}/api/knowledge-products/{product['id']}")
        for profile in client.get(f"{api}/api/ingestion-profiles").json():
            if str(profile.get("name") or "").startswith("E2E "):
                client.delete(f"{api}/api/ingestion-profiles/{profile['id']}")
    except Exception as exc:
        print("stale cleanup skipped:", exc)


def pick_source(client: httpx.Client, api: str, requested: str | None) -> str | None:
    resp = client.get(f"{api}/api/sources")
    if resp.status_code != 200:
        print("could not list sources:", resp.status_code, resp.text)
        return None
    sources = resp.json()
    if requested:
        return requested
    for src in sources:
        if src.get("minio_bucket") and not str(src["minio_bucket"]).startswith("local-"):
            return src["id"]
    return sources[0]["id"] if sources else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8007")
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--keep", action="store_true", help="Do not delete the created records.")
    args = parser.parse_args()
    api = args.base_url.rstrip("/")
    report: dict[str, Any] = {}

    with httpx.Client(timeout=180.0) as client:
        source_id = pick_source(client, api, args.source_id)
        if not source_id:
            print("No source bucket available. Create a source first.")
            return 1
        print(f"Using source {source_id}")
        clear_stale_records(client, api)
        clear_file(client, api, source_id)

        suffix = uuid.uuid4().hex[:6]
        products: list[str] = []
        profiles: list[str] = []

        print("\n=== 1. Create a profile; it carries no store name ===")
        small_destinations = [
            {"destination_type": dest, "enabled": True, "config": {}} for dest in DEST_TYPES
        ]
        resp_small = client.post(
            f"{api}/api/ingestion-profiles",
            json={
                "name": f"E2E Small {suffix}",
                "description": "e2e chunking profile",
                "chunk_size": SMALL_CHUNK_SIZE,
                "chunk_overlap": SMALL_CHUNK_OVERLAP,
                "destinations": small_destinations,
            },
        )
        if resp_small.status_code not in (200, 201):
            print("create profile failed:", resp_small.status_code, resp_small.text)
            return 1
        small_profile = resp_small.json()
        profiles.append(small_profile["id"])
        small_by_type = {d["destination_type"]: d for d in small_profile["destinations"]}

        check(small_profile["chunk_size"] == SMALL_CHUNK_SIZE, "chunk_size stored", small_profile["chunk_size"])
        check(len(small_profile["destinations"]) == len(DEST_TYPES), "all destinations stored", len(small_profile["destinations"]))
        check(
            all(
                key not in (d["config"] or {})
                for d in small_profile["destinations"]
                for key in ("collection_name", "index_name", "schema_name", "index_prefix")
            ),
            "the profile carries no store name",
            [d["config"] for d in small_profile["destinations"]],
        )
        check(
            all(
                key not in (d["config"] or {})
                for d in small_profile["destinations"]
                for key in (
                    "url",
                    "api_key",
                    "endpoint_url",
                    "connection_url",
                    "redis_url",
                    "litellm_base_url",
                    "litellm_api_key",
                    "vector_size",
                )
            ),
            "the profile carries no connection value",
            [d["config"] for d in small_profile["destinations"]],
        )

        print("\n=== 1b. Overlap at or above the size is rejected ===")
        resp_bad = client.post(
            f"{api}/api/ingestion-profiles",
            json={"name": f"E2E Bad {suffix}", "chunk_size": 200, "chunk_overlap": 200},
        )
        detail = resp_bad.json().get("detail") if resp_bad.status_code == 422 else {}
        check(resp_bad.status_code == 422, "422 on overlap == size", resp_bad.status_code)
        check(
            isinstance(detail, dict) and detail.get("code") == "CHUNK_OVERLAP_TOO_LARGE",
            "CHUNK_OVERLAP_TOO_LARGE code returned",
            detail,
        )

        print("\n=== 2. Create a product from the profile alone ===")
        resp_a = client.post(
            f"{api}/api/knowledge-products",
            json={
                "name": f"E2E Profile A {suffix}",
                "enabled": True,
                "monitor_mode": "live",
                "source_ids": [source_id],
                "ingestion_profile_id": small_profile["id"],
            },
        )
        if resp_a.status_code not in (200, 201):
            print("create product A failed:", resp_a.status_code, resp_a.text)
            return 1
        product_a = resp_a.json()
        products.append(product_a["id"])
        a_by_type = {d["destination_type"]: d for d in product_a["destinations"]}

        check(product_a["ingestion_profile_name"] == small_profile["name"], "profile name on the product", product_a["ingestion_profile_name"])
        check(product_a["chunk_size"] == SMALL_CHUNK_SIZE, "chunk_size on the product", product_a["chunk_size"])
        check(product_a["chunk_overlap"] == SMALL_CHUNK_OVERLAP, "chunk_overlap on the product", product_a["chunk_overlap"])
        check(len(product_a["destinations"]) == len(DEST_TYPES), "one destination row per profile entry", len(product_a["destinations"]))

        report["namespaces"] = {}
        for dest in DEST_TYPES:
            key = NAMESPACE_KEY[dest]
            value = (a_by_type[dest]["config"] or {}).get(key)
            report["namespaces"][dest] = value
            check(
                str(value).startswith("kp"),
                f"{dest}: {key} is namespaced to the product",
                value,
            )
            check(
                str(value) != str((small_by_type[dest]["config"] or {}).get(key)),
                f"{dest}: {key} differs from the profile value",
                value,
            )
        check(
            all(
                str((a_by_type[dest]["config"] or {}).get(NAMESPACE_KEY[dest], "")).startswith("kp")
                for dest in DEST_TYPES
            ),
            "the product copy assigns the store name",
            {dest: (a_by_type[dest]["config"] or {}).get(NAMESPACE_KEY[dest]) for dest in DEST_TYPES},
        )

        print("\n=== 3. Upload the document and wait for the small profile ===")
        resp_up = client.post(
            f"{api}/api/sources/{source_id}/files",
            files={"file": (FILE_KEY, io.BytesIO(DOCUMENT.encode("utf-8")), "text/plain")},
        )
        check(resp_up.status_code in (200, 201), "file uploaded to the bucket", resp_up.text[:200])

        row_a = wait_for_ledger(client, api, product_a["id"])
        report["ledger_a"] = row_a
        check(bool(row_a) and row_a.get("status") == "synced", "product A ledger is synced", row_a)

        state_a = wait_for_exact_hits(client, api, product_a["id"], expect=EXPECTED_SMALL_CHUNKS)
        report["a_hits"] = state_a["hits"]
        check(
            state_a["ok"],
            f"every destination holds the {EXPECTED_SMALL_CHUNKS} chunks the splitter produces",
            state_a["hits"],
        )
        check(
            row_a is not None and row_a.get("pages_indexed") == 1,
            "the ledger still counts source pages, not chunks",
            row_a.get("pages_indexed") if row_a else None,
        )
        small_counts = {dest: state_a["hits"][dest]["hits"] for dest in DEST_TYPES}
        check(len(set(small_counts.values())) == 1, "all four destinations hold the same chunk count", small_counts)
        for dest in DEST_TYPES:
            indexes = state_a["hits"][dest]["chunk_indexes"]
            check(
                indexes == list(range(EXPECTED_SMALL_CHUNKS)),
                f"{dest}: chunk_index runs 0..{EXPECTED_SMALL_CHUNKS - 1} with no gaps",
                indexes,
            )

        print("\n=== 4. A second, larger-chunk profile over the same bucket ===")
        resp_large = client.post(
            f"{api}/api/ingestion-profiles",
            json={
                "name": f"E2E Large {suffix}",
                "chunk_size": LARGE_CHUNK_SIZE,
                "chunk_overlap": 50,
                "destinations": small_destinations,
            },
        )
        if resp_large.status_code not in (200, 201):
            print("create large profile failed:", resp_large.status_code, resp_large.text)
            return 1
        large_profile = resp_large.json()
        profiles.append(large_profile["id"])

        resp_b = client.post(
            f"{api}/api/knowledge-products",
            json={
                "name": f"E2E Profile B {suffix}",
                "enabled": True,
                "monitor_mode": "live",
                "source_ids": [source_id],
                "ingestion_profile_id": large_profile["id"],
            },
        )
        if resp_b.status_code not in (200, 201):
            print("create product B failed:", resp_b.status_code, resp_b.text)
            return 1
        product_b = resp_b.json()
        products.append(product_b["id"])
        b_by_type = {d["destination_type"]: d for d in product_b["destinations"]}

        row_b = wait_for_ledger(client, api, product_b["id"])
        report["ledger_b"] = row_b
        check(bool(row_b) and row_b.get("status") == "synced", "product B ledger is synced", row_b)
        state_b = wait_for_exact_hits(client, api, product_b["id"], expect=EXPECTED_LARGE_CHUNKS)
        report["b_hits"] = state_b["hits"]
        check(
            state_b["ok"] and EXPECTED_LARGE_CHUNKS == 1,
            "the large profile keeps the page whole",
            {"expected": EXPECTED_LARGE_CHUNKS, "hits": state_b["hits"]},
        )
        check(
            EXPECTED_SMALL_CHUNKS > EXPECTED_LARGE_CHUNKS,
            "the two profiles split the same document differently",
            {"small": EXPECTED_SMALL_CHUNKS, "large": EXPECTED_LARGE_CHUNKS},
        )
        check(
            row_b is not None and row_b.get("pages_indexed") == 1,
            "product B counts one source page",
            row_b.get("pages_indexed") if row_b else None,
        )
        for dest in DEST_TYPES:
            key = NAMESPACE_KEY[dest]
            check(
                (b_by_type[dest]["config"] or {}).get(key) != (a_by_type[dest]["config"] or {}).get(key),
                f"{dest}: the two products keep different stores",
                (b_by_type[dest]["config"] or {}).get(key),
            )

        print("\n=== 5. A profile in use cannot be deleted ===")
        resp_del = client.delete(f"{api}/api/ingestion-profiles/{small_profile['id']}")
        detail = resp_del.json().get("detail") if resp_del.status_code == 409 else {}
        report["in_use"] = {"status": resp_del.status_code, "detail": detail}
        check(resp_del.status_code == 409, "409 while a product references the profile", resp_del.status_code)
        check(
            isinstance(detail, dict) and detail.get("code") == "PROFILE_IN_USE",
            "PROFILE_IN_USE code returned",
            detail,
        )
        check(
            isinstance(detail, dict) and detail.get("product_count") == 1,
            "the conflict reports the referencing product count",
            detail,
        )

        print("\n=== 6. Apply Profile re-copies and purges the replaced store ===")
        # The knob is hnsw_m, not a store name: a profile can no longer hold a
        # store name, and apply_store_namespace overwrites one unconditionally.
        resp_patch = client.patch(
            f"{api}/api/ingestion-profiles/{small_profile['id']}",
            json={
                "destinations": [
                    {
                        "destination_type": "vector_qdrant",
                        "enabled": True,
                        "config": {"hnsw_m": 32},
                    }
                ]
            },
        )
        check(resp_patch.status_code == 200, "profile patched", resp_patch.text[:200])
        patched = resp_patch.json()
        check(
            {d["destination_type"] for d in patched["destinations"]} == {"vector_qdrant"},
            "the destination payload replaces the whole set",
            [d["destination_type"] for d in patched["destinations"]],
        )
        report["patched_hnsw_m"] = 32

        resp_apply = client.post(f"{api}/api/knowledge-products/{product_a['id']}/apply-profile", json={})
        applied = resp_apply.json() if resp_apply.status_code == 200 else {}
        report["apply"] = {"status": resp_apply.status_code, "body": applied}
        check(resp_apply.status_code == 200, "apply-profile returns 200", resp_apply.text[:300])
        check(applied.get("profile_name") == small_profile["name"], "the applied profile is named", applied.get("profile_name"))
        check("vector_qdrant" in (applied.get("updated") or []), "the changed store is reported updated", applied.get("updated"))
        check(
            sorted(applied.get("removed") or []) == ["cache_redisvl", "lexical_opensearch", "relational_pgvector"],
            "the stores the profile dropped are reported removed",
            applied.get("removed"),
        )
        check(int(applied.get("purged_files") or 0) >= 1, "purge ran for the removed stores", applied.get("purged_files"))

        product_a_after = client.get(f"{api}/api/knowledge-products/{product_a['id']}").json()
        report["a_after_apply"] = [d["destination_type"] for d in product_a_after["destinations"]]
        check(
            [d["destination_type"] for d in product_a_after["destinations"]] == ["vector_qdrant"],
            "product A now has only the profile's destination",
            report["a_after_apply"],
        )
        after_config = product_a_after["destinations"][0]["config"] or {}
        check(
            after_config.get("hnsw_m") == 32,
            "the new hnsw_m landed on the product",
            after_config.get("hnsw_m"),
        )
        check(
            str(after_config.get("collection_name", "")).startswith("kp"),
            "the store name is still derived, not copied from the profile",
            after_config.get("collection_name"),
        )

        state_after = wait_for_exact_hits(
            client, api, product_a["id"], expect=EXPECTED_SMALL_CHUNKS, types=["vector_qdrant"]
        )
        report["a_after_hits"] = state_after["hits"]
        check(
            state_after["ok"],
            f"the re-applied store holds the {EXPECTED_SMALL_CHUNKS} chunks again",
            state_after["hits"],
        )

        print("\n=== 7. Cleanup ===")
        if not args.keep:
            for product_id in products:
                resp = client.delete(f"{api}/api/knowledge-products/{product_id}")
                print(f"  deleted product {product_id}: {resp.status_code}")
            for profile_id in profiles:
                resp = client.delete(f"{api}/api/ingestion-profiles/{profile_id}")
                print(f"  deleted profile {profile_id}: {resp.status_code}")
            clear_file(client, api, source_id)

        report["failures"] = failures
        print("\n=== SUMMARY ===")
        print(json.dumps(report, indent=2))
        print(f"\n{len(failures)} check(s) failed." if failures else "\nAll checks passed.")
        return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
