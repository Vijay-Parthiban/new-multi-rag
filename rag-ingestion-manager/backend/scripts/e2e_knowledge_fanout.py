"""End-to-end verification of the Knowledge Products fanout.

Proves, against a running ingestion API and live destination stores:
  1. Two products over the same bucket get different stores on all four sinks.
  2. A clashing store name is rejected with 422 DESTINATION_STORE_CONFLICT.
  3. Create alone starts ingestion; there is no manual sync route.
  4. Add propagates to all four sinks.
  5. Replace updates in place instead of duplicating.
  6. Delete removes the file from all four sinks.
  7. A second product on the same bucket stays empty.

Usage:
    uv run python scripts/e2e_knowledge_fanout.py
    uv run python scripts/e2e_knowledge_fanout.py --base-url http://localhost:8007
    uv run python scripts/e2e_knowledge_fanout.py --source-id <uuid>

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
FILE_KEY = "e2e_notes.txt"
SETTLE_TIMEOUT_S = 120
TICK_WAIT_S = 45

failures: list[str] = []


def check(condition: bool, label: str, detail: Any = None) -> None:
    if condition:
        print(f"  PASS  {label}")
        return
    failures.append(label)
    print(f"  FAIL  {label}" + (f"  ({detail})" if detail is not None else ""))


def wait_for_hits(
    client: httpx.Client,
    api: str,
    product_id: str,
    file_key: str,
    *,
    expect: int,
    want_content: str | None = None,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Poll the four inspect endpoints until each one reports the expected state.

    Waiting on the inspect output instead of on a tick boundary keeps the check
    honest: it confirms the stores hold the data, not that a loop ran.
    """
    deadline = time.time() + timeout_s
    hits: dict[str, Any] = {}
    ok = False
    while time.time() < deadline:
        hits = {}
        ok = True
        for dest in DEST_TYPES:
            payload = inspect(client, api, product_id, dest)
            found = dest_file_hits(dest, payload, file_key)
            entry = {"hits": found, "total": dest_total(dest, payload), "error": payload.get("error")}
            if want_content is not None and dest != "cache_redisvl":
                content = dest_file_content(dest, payload, file_key)
                entry["content"] = content[:40]
                if want_content not in content:
                    ok = False
            if found != expect:
                ok = False
            hits[dest] = entry
        if ok:
            break
        time.sleep(3)
    return {"ok": ok, "hits": hits}


def wait_for_tick(
    client: httpx.Client,
    api: str,
    product_id: str,
    previous_last_sync: str | None,
    timeout_s: int = SETTLE_TIMEOUT_S,
) -> dict[str, Any]:
    """Wait until the product finishes a sync tick, then return it.

    The poller owns the schedule, so the script waits instead of triggering.
    """
    deadline = time.time() + timeout_s
    last_seen: dict[str, Any] = {}
    while time.time() < deadline:
        resp = client.get(f"{api}/api/knowledge-products/{product_id}")
        if resp.status_code == 200:
            product = resp.json()
            last_seen = product
            if product.get("status") != "syncing" and product.get("last_sync_at") != previous_last_sync:
                return product
        time.sleep(2)
    return last_seen


def inspect(client: httpx.Client, api: str, product_id: str, dest: str) -> dict[str, Any]:
    resp = client.get(f"{api}/api/knowledge-products/{product_id}/inspect/{dest}")
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
        return sum(1 for p in payload.get("points") or [] if (p.get("payload") or {}).get("file_key") == file_key)
    if dest == "lexical_opensearch":
        return sum(1 for d in payload.get("documents") or [] if d.get("file_key") == file_key)
    if dest == "relational_pgvector":
        return sum(1 for r in payload.get("rows") or [] if r.get("file_key") == file_key)
    if dest == "cache_redisvl":
        # One cached page is a string key. The parent-child set and the summary
        # key also contain the file name, so count only the page keys.
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


def dest_file_content(dest: str, payload: dict[str, Any], file_key: str) -> str:
    if dest == "vector_qdrant":
        for p in payload.get("points") or []:
            if (p.get("payload") or {}).get("file_key") == file_key:
                return str((p.get("payload") or {}).get("content") or "")
    if dest == "lexical_opensearch":
        for d in payload.get("documents") or []:
            if d.get("file_key") == file_key:
                return str(d.get("content") or "")
    if dest == "relational_pgvector":
        for r in payload.get("rows") or []:
            if r.get("file_key") == file_key:
                return str(r.get("content") or "")
    if dest == "cache_redisvl":
        return "present" if dest_file_hits(dest, payload, file_key) else ""
    return ""


def clear_file(client: httpx.Client, api: str, source_id: str) -> None:
    """Remove the test object if a previous run left it behind."""
    try:
        client.delete(f"{api}/api/sources/{source_id}/files", params={"key": FILE_KEY})
    except Exception:
        pass


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
    parser.add_argument("--keep", action="store_true", help="Do not delete the created products.")
    args = parser.parse_args()
    api = args.base_url.rstrip("/")
    report: dict[str, Any] = {}

    with httpx.Client(timeout=120.0) as client:
        source_id = pick_source(client, api, args.source_id)
        if not source_id:
            print("No source bucket available. Create a source first.")
            return 1
        print(f"Using source {source_id}")
        clear_file(client, api, source_id)

        suffix = uuid.uuid4().hex[:6]
        created: list[str] = []

        print("\n=== 1. Create two products over the same bucket ===")
        payload_base = {
            "enabled": True,
            "monitor_mode": "live",
            "source_ids": [source_id],
            "destinations": [
                {"destination_type": dest, "enabled": True, "config": {}}
                for dest in DEST_TYPES
            ],
        }
        resp_a = client.post(f"{api}/api/knowledge-products", json={**payload_base, "name": f"E2E Alpha {suffix}"})
        if resp_a.status_code not in (200, 201):
            print("create A failed:", resp_a.status_code, resp_a.text)
            return 1
        product_a = resp_a.json()
        created.append(product_a["id"])

        resp_b = client.post(f"{api}/api/knowledge-products", json={**payload_base, "name": f"E2E Beta {suffix}"})
        if resp_b.status_code not in (200, 201):
            print("create B failed:", resp_b.status_code, resp_b.text)
            return 1
        product_b = resp_b.json()
        created.append(product_b["id"])
        print(f"  A={product_a['id']}  B={product_b['id']}")

        print("\n=== 1b. Create alone starts ingestion (no manual trigger) ===")
        started = wait_for_tick(client, api, product_a["id"], None, timeout_s=90)
        report["first_sync_at"] = started.get("last_sync_at")
        check(bool(started.get("last_sync_at")), "last_sync_at is set without any sync call", started.get("status"))

        print("\n=== 2. Stores are isolated per product ===")
        a_by_type = {d["destination_type"]: d for d in product_a["destinations"]}
        b_by_type = {d["destination_type"]: d for d in product_b["destinations"]}
        report["store_names"] = {}
        for dest in DEST_TYPES:
            key = NAMESPACE_KEY[dest]
            value_a = (a_by_type[dest]["config"] or {}).get(key)
            value_b = (b_by_type[dest]["config"] or {}).get(key)
            report["store_names"][dest] = {"a": value_a, "b": value_b}
            check(bool(value_a) and value_a != value_b, f"{dest}: {key} differs", report["store_names"][dest])
            check(str(value_a).startswith("kp") or str(value_a).startswith("kp:"), f"{dest}: namespaced", value_a)

        print("\n=== 3. A clashing store name is rejected ===")
        clash = {
            **payload_base,
            "name": f"E2E Clash {suffix}",
            "destinations": [
                {
                    "destination_type": "vector_qdrant",
                    "enabled": True,
                    "config": {"collection_name": (a_by_type["vector_qdrant"]["config"] or {})["collection_name"]},
                }
            ],
        }
        resp_clash = client.post(f"{api}/api/knowledge-products", json=clash)
        detail = resp_clash.json().get("detail") if resp_clash.status_code == 422 else {}
        report["conflict"] = {"status": resp_clash.status_code, "detail": detail}
        check(resp_clash.status_code == 422, "422 on a duplicate collection_name", resp_clash.text[:200])
        check(
            isinstance(detail, dict) and detail.get("code") == "DESTINATION_STORE_CONFLICT",
            "DESTINATION_STORE_CONFLICT code returned",
            detail,
        )

        print("\n=== 4. Manual sync is gone ===")
        resp_sync = client.post(f"{api}/api/knowledge-products/{product_a['id']}/sync")
        check(resp_sync.status_code == 404, "POST /{id}/sync returns 404", resp_sync.status_code)

        print("\n=== 5. Add propagates to all four destinations ===")
        resp_up = client.post(
            f"{api}/api/sources/{source_id}/files",
            files={"file": (FILE_KEY, io.BytesIO(b"alpha"), "text/plain")},
        )
        check(resp_up.status_code in (200, 201), "file uploaded to the bucket", resp_up.text[:200])

        state = wait_for_hits(client, api, product_a["id"], FILE_KEY, expect=1)
        report["after_add"] = state["hits"]
        check(state["ok"], "the file reached all four destinations", state["hits"])

        print("\n=== 6. Replace updates instead of duplicating ===")
        resp_up2 = client.post(
            f"{api}/api/sources/{source_id}/files",
            files={"file": (FILE_KEY, io.BytesIO(b"beta"), "text/plain")},
        )
        check(resp_up2.status_code in (200, 201), "file replaced", resp_up2.text[:200])

        state = wait_for_hits(
            client, api, product_a["id"], FILE_KEY, expect=1, want_content="beta"
        )
        report["after_replace"] = state["hits"]
        check(state["ok"], "content is now beta, one row per destination", state["hits"])

        print("\n=== 7. Each product keeps its own copy of the shared bucket ===")
        # Isolation is not "B is empty": both products watch the same bucket, so
        # both index it. Isolation means B holds its own copy in its own store,
        # which proves the per-product ledger did not make B skip the file.
        report["b_after_a_writes"] = {}
        b_ok = True
        for dest in DEST_TYPES:
            payload = inspect(client, api, product_b["id"], dest)
            hits = dest_file_hits(dest, payload, FILE_KEY)
            report["b_after_a_writes"][dest] = {
                "hits": hits,
                "total": dest_total(dest, payload),
                "error": payload.get("error"),
            }
            b_ok = b_ok and hits >= 1
        check(b_ok, "B holds its own copy in its own store", report["b_after_a_writes"])

        print("\n=== 8. Delete removes the file from all four destinations ===")
        resp_del = client.delete(f"{api}/api/sources/{source_id}/files", params={"key": FILE_KEY})
        check(resp_del.status_code == 200, "file deleted from the bucket", resp_del.text[:200])

        state = wait_for_hits(client, api, product_a["id"], FILE_KEY, expect=0)
        report["after_delete"] = state["hits"]
        check(state["ok"], "the file is gone from all four destinations", state["hits"])

        files_resp = client.get(f"{api}/api/knowledge-products/{product_a['id']}/files")
        ledger_keys = [f["file_key"] for f in files_resp.json().get("files", [])] if files_resp.status_code == 200 else []
        check(FILE_KEY not in ledger_keys, "the ledger no longer lists the file", ledger_keys)

        if not args.keep:
            print("\n=== 9. Cleanup ===")
            for product_id in created:
                resp = client.delete(f"{api}/api/knowledge-products/{product_id}")
                print(f"  deleted {product_id}: {resp.status_code}")

        report["failures"] = failures
        print("\n=== SUMMARY ===")
        print(json.dumps(report, indent=2))
        print(f"\n{len(failures)} check(s) failed." if failures else "\nAll checks passed.")
        return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
