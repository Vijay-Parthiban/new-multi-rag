"""Verify Knowledge Product pause and resume.

  1. Pause All Destinations stops every write; the file is still read from the
     bucket and recorded, but nothing reaches a destination.
  2. Resume All catches up: the file lands in every destination.
  3. A per-destination pause excludes exactly that destination.

Usage:
    uv run python scripts/e2e_knowledge_pause.py
    uv run python scripts/e2e_knowledge_pause.py --base-url http://localhost:8007

Exit codes: 0 all checks passed, 1 setup failure, 2 an assertion failed.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from typing import Any

import httpx

DEST_TYPES = ["vector_qdrant", "lexical_opensearch", "relational_pgvector", "cache_redisvl"]
FILE_KEY = "e2e_pause.txt"
PAUSE_SETTLE_S = 12
RESUME_TIMEOUT_S = 120

failures: list[str] = []


def check(condition: bool, label: str, detail: Any = None) -> None:
    if condition:
        print(f"  PASS  {label}")
        return
    failures.append(label)
    print(f"  FAIL  {label}" + (f"  ({detail})" if detail is not None else ""))


def dest_total(client: httpx.Client, api: str, product_id: str, dest: str) -> int:
    resp = client.get(f"{api}/api/knowledge-products/{product_id}/inspect/{dest}")
    if resp.status_code != 200:
        return -1
    payload = resp.json()
    return sum(
        payload.get(key) or 0
        for key in ("total_points", "total_docs", "total_rows", "total_cached_keys")
    )


def dest_hits(client: httpx.Client, api: str, product_id: str, dest: str, file_key: str) -> int:
    resp = client.get(f"{api}/api/knowledge-products/{product_id}/inspect/{dest}")
    if resp.status_code != 200:
        return -1
    payload = resp.json()
    if dest == "vector_qdrant":
        return sum(1 for p in payload.get("points") or [] if (p.get("payload") or {}).get("file_key") == file_key)
    if dest == "lexical_opensearch":
        return sum(1 for d in payload.get("documents") or [] if d.get("file_key") == file_key)
    if dest == "relational_pgvector":
        return sum(1 for r in payload.get("rows") or [] if r.get("file_key") == file_key)
    pages = 0
    for k in payload.get("keys") or []:
        key = str(k.get("key") or "")
        if f":{file_key}:" in key and not key.endswith((":children", ":summary")):
            pages += 1
    return pages


def wait_hits(client, api, product_id, dest, file_key, expect, timeout_s):
    deadline = time.time() + timeout_s
    found = -1
    while time.time() < deadline:
        found = dest_hits(client, api, product_id, dest, file_key)
        if found == expect:
            return found
        time.sleep(3)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8007")
    args = parser.parse_args()
    api = args.base_url.rstrip("/")
    report: dict[str, Any] = {}

    with httpx.Client(timeout=120.0) as client:
        sources = client.get(f"{api}/api/sources").json()
        source_id = next(
            (s["id"] for s in sources if s.get("minio_bucket") and not str(s["minio_bucket"]).startswith("local-")),
            None,
        ) or (sources[0]["id"] if sources else None)
        if not source_id:
            print("No source available.")
            return 1

        client.delete(f"{api}/api/sources/{source_id}/files", params={"key": FILE_KEY})

        name = f"E2E Pause {int(time.time())}"
        resp = client.post(
            f"{api}/api/knowledge-products",
            json={
                "name": name,
                "enabled": True,
                "monitor_mode": "live",
                "source_ids": [source_id],
                "destinations": [
                    {"destination_type": d, "enabled": True, "config": {}} for d in DEST_TYPES
                ],
            },
        )
        if resp.status_code not in (200, 201):
            print("create failed:", resp.status_code, resp.text[:300])
            return 1
        product = resp.json()
        product_id = product["id"]
        print(f"Created {name} ({product_id})")

        try:
            print("\n=== 0. Let the initial sync of the pre-existing bucket settle ===")
            deadline = time.time() + RESUME_TIMEOUT_S
            while time.time() < deadline:
                state = client.get(f"{api}/api/knowledge-products/{product_id}").json()
                if state["status"] != "syncing" and state["files_pending"] == 0:
                    break
                time.sleep(3)
            report["settled"] = {"status": state["status"], "files_total": state["files_total"]}

            print("\n=== 1. Pause All Destinations stops every write ===")
            paused = client.post(f"{api}/api/knowledge-products/{product_id}/pause-all")
            check(paused.status_code == 200, "pause-all returns 200", paused.text[:200])
            state = client.get(f"{api}/api/knowledge-products/{product_id}").json()
            check(
                all(not d["enabled"] for d in state["destinations"]),
                "every destination reports enabled=false",
                [(d["destination_type"], d["enabled"]) for d in state["destinations"]],
            )

            before = {d: dest_total(client, api, product_id, d) for d in DEST_TYPES}
            client.post(
                f"{api}/api/sources/{source_id}/files",
                files={"file": (FILE_KEY, io.BytesIO(b"paused-content"), "text/plain")},
            )
            time.sleep(PAUSE_SETTLE_S)
            after = {d: dest_total(client, api, product_id, d) for d in DEST_TYPES}
            report["paused_totals"] = {"before": before, "after": after}
            check(before == after, "no destination grew while paused", report["paused_totals"])

            files = client.get(f"{api}/api/knowledge-products/{product_id}/files").json()
            entry = next((f for f in files["files"] if f["file_key"] == FILE_KEY), None)
            # A product with every destination paused stops polling, so it may
            # not have noticed the file yet. Either way it must not be synced.
            report["paused_ledger_entry"] = entry and {
                "status": entry["status"],
                "destinations_synced": entry["destinations_synced"],
            }
            check(
                entry is None or entry["destinations_synced"] == [],
                "the ledger shows no destination holds the file",
                report["paused_ledger_entry"],
            )

            print("\n=== 2. Resume All catches up ===")
            resumed = client.post(f"{api}/api/knowledge-products/{product_id}/resume-all")
            check(resumed.status_code == 200, "resume-all returns 200", resumed.text[:200])
            caught_up = True
            for dest in DEST_TYPES:
                hits = wait_hits(client, api, product_id, dest, FILE_KEY, 1, RESUME_TIMEOUT_S)
                if hits != 1:
                    caught_up = False
                report.setdefault("resume_hits", {})[dest] = hits
            check(caught_up, "the paused file reached every destination after resume", report.get("resume_hits"))

            print("\n=== 3. Per-destination pause excludes exactly one destination ===")
            qdrant = next(d for d in state["destinations"] if d["destination_type"] == "vector_qdrant")
            other_file = "e2e_partial.txt"
            client.delete(f"{api}/api/sources/{source_id}/files", params={"key": other_file})
            toggled = client.patch(
                f"{api}/api/knowledge-products/{product_id}/destinations/{qdrant['id']}",
                json={"enabled": False},
            )
            check(toggled.status_code == 200, "PATCH destination returns 200", toggled.text[:200])
            check(toggled.json().get("enabled") is False, "the destination reports disabled")

            client.post(
                f"{api}/api/sources/{source_id}/files",
                files={"file": (other_file, io.BytesIO(b"partial-content"), "text/plain")},
            )
            got = {}
            for dest in DEST_TYPES:
                expect = 0 if dest == "vector_qdrant" else 1
                got[dest] = wait_hits(client, api, product_id, dest, other_file, expect, RESUME_TIMEOUT_S)
            report["partial_hits"] = got
            check(got["vector_qdrant"] == 0, "the paused destination stayed empty", got["vector_qdrant"])
            check(
                all(got[d] == 1 for d in DEST_TYPES if d != "vector_qdrant"),
                "the other three destinations received the file",
                got,
            )

            entry2 = next(
                (f for f in client.get(f"{api}/api/knowledge-products/{product_id}/files").json()["files"]
                 if f["file_key"] == other_file),
                None,
            )
            if entry2:
                report["partial_ledger"] = entry2["destinations_synced"]
                check(
                    "vector_qdrant" not in entry2["destinations_synced"],
                    "the ledger omits the paused destination",
                    entry2["destinations_synced"],
                )
                check(
                    entry2["status"] == "synced",
                    "the file is synced for the destinations that are enabled",
                    entry2["status"],
                )

            print("\n=== 4. Resuming one destination catches it up ===")
            toggled_back = client.patch(
                f"{api}/api/knowledge-products/{product_id}/destinations/{qdrant['id']}",
                json={"enabled": True},
            )
            check(toggled_back.status_code == 200, "PATCH destination back to enabled", toggled_back.text[:200])
            hits = wait_hits(client, api, product_id, "vector_qdrant", other_file, 1, RESUME_TIMEOUT_S)
            report["resumed_qdrant_hits"] = hits
            check(hits == 1, "the resumed destination received the file", hits)

            state2 = client.get(f"{api}/api/knowledge-products/{product_id}").json()
            report["final_status"] = state2["status"]
        finally:
            print("\n=== Cleanup ===")
            for key in (FILE_KEY, "e2e_partial.txt"):
                client.delete(f"{api}/api/sources/{source_id}/files", params={"key": key})
            time.sleep(6)
            print("  deleted product:", client.delete(f"{api}/api/knowledge-products/{product_id}").status_code)

    report["failures"] = failures
    print("\n=== SUMMARY ===")
    print(json.dumps(report, indent=2))
    print(f"\n{len(failures)} check(s) failed." if failures else "\nAll checks passed.")
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
