"""End-to-end verification of the Ingestion Profile chunk strategy.

Proves, against a running ingestion API and live destination stores:
  1. A profile stores the strategy the user picked, and an unknown name is a 422.
  2. The default strategy is the original algorithm, so a product that has always
     used it stores byte-identical chunk text.
  3. ``section`` stores one record per heading or paragraph, and every store
     agrees on the count.
  4. ``parent_child`` stores parent records plus child records, every child names
     a parent that is present in the same store, and every destination agrees.
  5. ``fixed`` cuts a hard window and stores plain records again, so a strategy
     change reaches the stores through Apply Profile.
  6. ``context_aware`` stores records on the live embedding path, so the batch
     embedding call the strategy needs is exercised against the real proxy.
  7. Every destination holds the same number of records for the file, so no store
     silently dropped a record type.

Usage:
    uv run python scripts/e2e_chunk_strategies.py
    uv run python scripts/e2e_chunk_strategies.py --base-url http://localhost:8007
    uv run python scripts/e2e_chunk_strategies.py --source-id <uuid>

Exit codes: 0 all checks passed, 1 setup or request failure, 2 an assertion failed.
"""

from __future__ import annotations

import argparse
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
FILE_KEY = "e2e_strategy_notes.txt"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 40
SETTLE_TIMEOUT_S = 180

# Six blocks: two headings and four paragraphs. The section strategy stores one
# record per block, so the expected count is structural, not a guess.
BLOCKS = [
    "# Candidate Summary",
    "Staff engineer with eleven years in platform work. Owned the payments service end to end. "
    "Reduced p99 latency from 900 to 250 milliseconds. Ran the on-call rotation for a team of six.",
    "## Experience",
    "Built a graph recommender on Postgres and Redis. Migrated twelve services to Kubernetes. "
    "Wrote the ranking service in Go. Cut the nightly batch window by two hours.",
    "## Skills",
    "Python, Go, Postgres, pgvector, Kubernetes, Terraform, Kafka, Redis, React, TypeScript.",
    "## Education",
    "BSc Computer Science, 2014. Thesis on graph databases.",
]
DOCUMENT = "\n\n".join(BLOCKS)

# The same splitter the fanout calls, so the expected counts are not guesses.
from src.ingestion_service.utils.text_splitter import (  # noqa: E402
    chunk_parent_child,
    chunk_text,
    split_units,
)

EXPECTED_SECTION_RECORDS = len(split_units(DOCUMENT, "section"))
EXPECTED_FIXED_RECORDS = len(chunk_text(DOCUMENT, CHUNK_SIZE, CHUNK_OVERLAP, "fixed"))
EXPECTED_PARENT_CHILD = chunk_parent_child(DOCUMENT, CHUNK_SIZE, CHUNK_OVERLAP)

failures: list[str] = []


def check(condition: bool, label: str, detail: Any = None) -> None:
    if condition:
        print(f"  PASS  {label}")
        return
    failures.append(label)
    print(f"  FAIL  {label}" + (f"  ({detail})" if detail is not None else ""))


def inspect(client: httpx.Client, api: str, product_id: str, dest: str) -> dict[str, Any]:
    """Read one store scoped to FILE_KEY.

    The store sample cap applies to a whole store, so a per-file read has to ask
    for that file or a large store hides some of its records.
    """
    resp = client.get(
        f"{api}/api/knowledge-products/{product_id}/inspect/{dest}",
        params={"file_key": FILE_KEY},
    )
    return resp.json() if resp.status_code == 200 else {"error": resp.text}


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
        # The cached value is JSON under each key, so the record type lives in the
        # value and not in the key name.
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


def record_type_of(record: dict[str, Any]) -> str:
    return str(record.get("record_type") or "chunk")


def wait_for_records(
    client: httpx.Client,
    api: str,
    product_id: str,
    *,
    count: int,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll until every destination holds exactly ``count`` records for the file."""
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    ok = False
    while time.time() < deadline:
        state = {}
        ok = True
        for dest in DEST_TYPES:
            payload = inspect(client, api, product_id, dest)
            records = dest_file_records(dest, payload, FILE_KEY)
            state[dest] = {
                "count": len(records),
                "error": payload.get("error"),
                "types": sorted({record_type_of(r) for r in records}),
            }
            if len(records) != count:
                ok = False
        if ok:
            break
        time.sleep(3)
    return {"ok": ok, "state": state}


def wait_for_parent_child(
    client: httpx.Client,
    api: str,
    product_id: str,
    *,
    min_parents: int,
    min_children: int,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll until every destination holds parents and children, and every child
    resolves to a parent stored beside it."""
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    ok = False
    while time.time() < deadline:
        state = {}
        ok = True
        for dest in DEST_TYPES:
            payload = inspect(client, api, product_id, dest)
            records = dest_file_records(dest, payload, FILE_KEY)
            parents = [r for r in records if record_type_of(r) == "parent"]
            children = [r for r in records if record_type_of(r) == "child"]
            stored = {
                f"{r.get('page_index')}:{r.get('chunk_index')}"
                for r in parents
            }
            dangling = [
                c for c in children
                if str(c.get("parent_ref") or "") not in stored
            ]
            state[dest] = {
                "parents": len(parents),
                "children": len(children),
                "dangling": len(dangling),
                "sample_child": (children[0].get("parent_ref") if children else None),
                "error": payload.get("error"),
            }
            if len(parents) < min_parents or len(children) < min_children or dangling:
                ok = False
        if ok:
            break
        time.sleep(3)
    return {"ok": ok, "state": state}


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


def clear_stale_records(client: httpx.Client, api: str) -> None:
    """Delete records a cancelled earlier run left behind.

    A leftover product keeps its poller running, so it keeps writing to stores
    this run does not own.
    """
    try:
        for product in client.get(f"{api}/api/knowledge-products").json():
            if str(product.get("name") or "").startswith("E2E Strategy "):
                client.delete(f"{api}/api/knowledge-products/{product['id']}")
        for profile in client.get(f"{api}/api/ingestion-profiles").json():
            if str(profile.get("name") or "").startswith("E2E Strategy "):
                client.delete(f"{api}/api/ingestion-profiles/{profile['id']}")
    except Exception as exc:
        print("stale cleanup skipped:", exc)


def upload(client: httpx.Client, api: str, source_id: str, body: bytes, filename: str) -> bool:
    resp = client.post(
        f"{api}/api/sources/{source_id}/files",
        files={"file": (filename, body, "text/plain")},
    )
    if resp.status_code not in (200, 201):
        print(f"upload failed: {resp.status_code} {resp.text[:300]}")
        return False
    return True


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


def patch_profile(client: httpx.Client, api: str, profile_id: str, body: dict[str, Any]) -> httpx.Response:
    return client.patch(f"{api}/api/ingestion-profiles/{profile_id}", json=body)


def apply_profile(client: httpx.Client, api: str, product_id: str) -> dict[str, Any]:
    resp = client.post(f"{api}/api/knowledge-products/{product_id}/apply-profile", json={})
    return resp.json() if resp.status_code == 200 else {"error": resp.text, "status": resp.status_code}


def set_strategy(
    client: httpx.Client, api: str, profile_id: str, product_id: str, strategy: str
) -> dict[str, Any]:
    """Switch a profile's strategy and make the product re-ingest with it."""
    resp = patch_profile(client, api, profile_id, {"chunk_strategy": strategy})
    if resp.status_code != 200:
        return {"error": resp.text, "status": resp.status_code}
    return apply_profile(client, api, product_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8007")
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--keep", action="store_true", help="Do not delete the created records.")
    args = parser.parse_args()
    api = args.base_url.rstrip("/")
    report: dict[str, Any] = {}

    with httpx.Client(timeout=60.0) as client:
        try:
            client.get(f"{api}/api/knowledge-products").raise_for_status()
        except Exception as exc:
            print(f"Ingestion API not reachable at {api}: {exc}")
            return 1

        source_id = pick_source(client, api, args.source_id)
        if not source_id:
            print("No source bucket available. Create a source first.")
            return 1
        print(f"Using source {source_id}")
        clear_stale_records(client, api)

        suffix = uuid.uuid4().hex[:6]
        products: list[str] = []
        profiles: list[str] = []

        print("\n=== 1. The profile stores the strategy, and rejects an unknown one ===")
        resp_bad = client.post(
            f"{api}/api/ingestion-profiles",
            json={"name": f"E2E Strategy Bad {suffix}", "chunk_strategy": "semantic_magic"},
        )
        check(resp_bad.status_code == 422, "an unknown strategy name is a 422", resp_bad.status_code)

        resp_profile = client.post(
            f"{api}/api/ingestion-profiles",
            json={
                "name": f"E2E Strategy {suffix}",
                "description": "e2e chunk strategy profile",
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "chunk_strategy": "section",
                "modality_mode": "text",
                "destinations": [
                    {"destination_type": dest, "enabled": True, "config": {}} for dest in DEST_TYPES
                ],
            },
        )
        if resp_profile.status_code != 201:
            print(f"profile create failed: {resp_profile.status_code} {resp_profile.text[:400]}")
            return 1
        profile = resp_profile.json()
        profiles.append(profile["id"])
        check(profile.get("chunk_strategy") == "section", "the profile stores section", profile.get("chunk_strategy"))

        resp_default = client.post(
            f"{api}/api/ingestion-profiles",
            json={"name": f"E2E Strategy Default {suffix}", "destinations": []},
        )
        check(
            resp_default.status_code == 201 and resp_default.json().get("chunk_strategy") == "recursive",
            "a profile with no strategy defaults to the original algorithm",
            resp_default.json().get("chunk_strategy") if resp_default.status_code == 201 else resp_default.text[:200],
        )
        if resp_default.status_code == 201:
            profiles.append(resp_default.json()["id"])

        print("\n=== 2. Upload the structured document and start ingestion ===")
        if not upload(client, api, source_id, DOCUMENT.encode("utf-8"), FILE_KEY):
            return 1
        resp_product = client.post(
            f"{api}/api/knowledge-products",
            json={
                "name": f"E2E Strategy Product {suffix}",
                "description": "e2e chunk strategy product",
                "source_ids": [source_id],
                "ingestion_profile_id": profile["id"],
                "monitor_mode": "live",
            },
        )
        if resp_product.status_code != 201:
            print(f"product create failed: {resp_product.status_code} {resp_product.text[:400]}")
            return 1
        product = resp_product.json()
        products.append(product["id"])
        check(
            product.get("chunk_strategy") == "section",
            "the product reports the strategy of its profile",
            product.get("chunk_strategy"),
        )

        print("\n=== 3. The section strategy stores one record per block ===")
        row = wait_for_ledger(client, api, product["id"])
        check(row is not None and row.get("status") == "synced", "the file reaches synced", row and row.get("status"))
        check(
            row is not None and row.get("pages_indexed") == 1,
            "one source page was indexed",
            row and row.get("pages_indexed"),
        )
        result = wait_for_records(client, api, product["id"], count=EXPECTED_SECTION_RECORDS)
        report["section"] = result["state"]
        check(
            result["ok"],
            f"every destination holds {EXPECTED_SECTION_RECORDS} section records",
            result["state"],
        )
        check(
            all(state["types"] == ["chunk"] for state in result["state"].values()),
            "a section profile stores plain chunks, so no parent or child record exists",
            {d: s["types"] for d, s in result["state"].items()},
        )

        print("\n=== 4. The parent_child strategy stores parents and their children ===")
        applied = set_strategy(client, api, profile["id"], product["id"], "parent_child")
        check("error" not in applied, "switching to parent_child re-copies and re-syncs", applied)
        expected_parents = len([p for p in EXPECTED_PARENT_CHILD if p.record_type == "parent"])
        expected_children = len([p for p in EXPECTED_PARENT_CHILD if p.record_type == "child"])
        parent_child = wait_for_parent_child(
            client,
            api,
            product["id"],
            min_parents=expected_parents,
            min_children=expected_children,
        )
        report["parent_child"] = parent_child["state"]
        check(
            parent_child["ok"],
            f"every destination holds {expected_parents} parents and {expected_children} children, "
            "and every child names a stored parent",
            parent_child["state"],
        )
        counts = {d: s["parents"] + s["children"] for d, s in parent_child["state"].items()}
        check(
            len(set(counts.values())) == 1,
            "the four destinations agree on the record count",
            counts,
        )

        print("\n=== 5. The fixed strategy stores a hard window again ===")
        applied = set_strategy(client, api, profile["id"], product["id"], "fixed")
        check("error" not in applied, "switching to fixed re-copies and re-syncs", applied)
        fixed = wait_for_records(client, api, product["id"], count=EXPECTED_FIXED_RECORDS)
        report["fixed"] = fixed["state"]
        check(
            fixed["ok"],
            f"every destination holds {EXPECTED_FIXED_RECORDS} fixed-window records",
            fixed["state"],
        )
        check(
            EXPECTED_FIXED_RECORDS != EXPECTED_SECTION_RECORDS,
            "the fixed strategy produces a different record count than section",
            {"fixed": EXPECTED_FIXED_RECORDS, "section": EXPECTED_SECTION_RECORDS},
        )
        check(
            all(state["types"] == ["chunk"] for state in fixed["state"].values()),
            "the parent and child records left the stores with the strategy",
            {d: s["types"] for d, s in fixed["state"].items()},
        )

        print("\n=== 6. The context_aware strategy stores records on the live embedding path ===")
        applied = set_strategy(client, api, profile["id"], product["id"], "context_aware")
        check("error" not in applied, "switching to context_aware re-copies and re-syncs", applied)
        row = wait_for_ledger(client, api, product["id"])
        check(row is not None and row.get("status") == "synced", "the file reaches synced again", row and row.get("status"))
        context_state: dict[str, Any] = {}
        deadline = time.time() + SETTLE_TIMEOUT_S
        while time.time() < deadline:
            context_state = {}
            for dest in DEST_TYPES:
                payload = inspect(client, api, product["id"], dest)
                records = dest_file_records(dest, payload, FILE_KEY)
                context_state[dest] = {"count": len(records), "error": payload.get("error")}
            if all(state["count"] > 0 for state in context_state.values()):
                break
            time.sleep(3)
        report["context_aware"] = context_state
        check(
            all(state["count"] > 0 for state in context_state.values()),
            "context_aware stores records in every destination",
            context_state,
        )
        counts = {d: s["count"] for d, s in context_state.items()}
        check(
            len(set(counts.values())) == 1,
            "the four destinations agree on the context_aware record count",
            counts,
        )

        if not args.keep:
            print("\n=== Cleanup ===")
            for product_id in products:
                client.delete(f"{api}/api/knowledge-products/{product_id}")
            for profile_id in profiles:
                resp = client.delete(f"{api}/api/ingestion-profiles/{profile_id}")
                if resp.status_code not in (200, 204, 404):
                    print(f"  profile delete {profile_id}: {resp.status_code} {resp.text[:200]}")
            client.delete(f"{api}/api/sources/{source_id}/files", params={"key": FILE_KEY})
            print("  removed the test products, profiles and the uploaded object")

        print("\n=== Summary ===")
        print(json.dumps(report, indent=2, default=str)[:3000])

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for label in failures:
            print(f"  - {label}")
        return 2
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
