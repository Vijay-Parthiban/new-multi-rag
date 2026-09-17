"""End-to-end Knowledge Fanout profile delete, recreate, sync, and inspect verification."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import httpx

API = "http://localhost:8007"
PROFILE_ID = "a92d7a29-9294-4a3a-aa78-3193b7007c4f"
SOURCE_IDS = [
    "5d2edc8f-1a4a-41d2-80ac-4f10639d9504",  # v-res
    "5f4d24f4-ce4b-4eba-af82-0206fed37158",  # manual-vj
]
DEST_TYPES = [
    "vector_qdrant",
    "lexical_opensearch",
    "graph_neo4j",
    "relational_pgvector",
    "cache_redisvl",
]

DESTINATION_CONFIGS = [
    {
        "destination_type": "vector_qdrant",
        "enabled": True,
        "config": {
            "url": "http://localhost:6335",
            "api_key": "qdrant",
            "collection_name": "knowledge_qdrant_collection",
            "vector_size": 2048,
        },
    },
    {
        "destination_type": "lexical_opensearch",
        "enabled": True,
        "config": {
            "endpoint_url": "http://localhost:9200",
            "index_name": "knowledge_lexical_index",
        },
    },
    {
        "destination_type": "graph_neo4j",
        "enabled": True,
        "config": {
            "bolt_uri": "bolt://localhost:7687",
            "http_url": "http://localhost:7474",
            "username": "neo4j",
            "password": "password",
        },
    },
    {
        "destination_type": "relational_pgvector",
        "enabled": True,
        "config": {
            "connection_url": "postgresql://ingestion:ingestion@localhost:5432/ingestion",
            "table_name": "knowledge_chunks",
        },
    },
    {
        "destination_type": "cache_redisvl",
        "enabled": True,
        "config": {
            "redis_url": "redis://localhost:6379",
            "index_prefix": "knowledge_cache",
            "ttl_seconds": 86400,
        },
    },
]


def summarize_inspect(dest_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if dest_type == "vector_qdrant":
        return {
            "total_points": payload.get("total_points", 0),
            "sample_points": len(payload.get("points", [])),
            "error": payload.get("error"),
        }
    if dest_type == "lexical_opensearch":
        return {
            "total_docs": payload.get("total_docs", 0),
            "sample_docs": len(payload.get("documents", [])),
            "terms": len(payload.get("terms", [])),
            "error": payload.get("error"),
        }
    if dest_type == "graph_neo4j":
        return {
            "total_nodes": payload.get("total_nodes", 0),
            "total_edges": payload.get("total_edges", 0),
            "error": payload.get("error"),
        }
    if dest_type == "relational_pgvector":
        return {
            "total_rows": payload.get("total_rows", 0),
            "sample_rows": len(payload.get("rows", [])),
            "error": payload.get("error"),
        }
    if dest_type == "cache_redisvl":
        return {
            "total_cached_keys": payload.get("total_cached_keys", 0),
            "sample_keys": len(payload.get("keys", [])),
            "error": payload.get("error"),
        }
    return {"raw": payload}


def inspect_all(client: httpx.Client, profile_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dest in DEST_TYPES:
        resp = client.get(f"{API}/api/knowledge-profiles/{profile_id}/inspect/{dest}")
        data = resp.json() if resp.status_code == 200 else {"error": resp.text}
        out[dest] = summarize_inspect(dest, data)
    return out


def wait_for_sync(client: httpx.Client, profile_id: str, timeout_s: int = 300) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get(f"{API}/api/knowledge-profiles/{profile_id}")
        profile = resp.json()
        status = profile.get("status")
        print(f"  sync status: {status}")
        if status != "syncing":
            return profile
        time.sleep(3)
    raise TimeoutError(f"Profile {profile_id} did not finish syncing within {timeout_s}s")


def main() -> int:
    report: dict[str, Any] = {"steps": []}

    with httpx.Client(timeout=60.0) as client:
        print("=== BEFORE DELETE: inspect existing profile ===")
        before_delete = inspect_all(client, PROFILE_ID)
        report["before_delete"] = before_delete
        print(json.dumps(before_delete, indent=2))

        print("\n=== DELETE profile (with destination purge) ===")
        del_resp = client.delete(f"{API}/api/knowledge-profiles/{PROFILE_ID}")
        delete_body = del_resp.json() if del_resp.status_code == 200 else {"error": del_resp.text}
        report["delete"] = {"status_code": del_resp.status_code, "body": delete_body}
        print(json.dumps(delete_body, indent=2))

        print("\n=== AFTER DELETE: direct destination checks ===")
        after_delete = {
            "qdrant_points": _qdrant_count(),
            "opensearch_docs": _opensearch_count(),
            "neo4j_nodes": _neo4j_node_count(),
            "postgres_rows": _postgres_row_count(),
            "redis_keys": _redis_key_count(),
        }
        report["after_delete_direct"] = after_delete
        print(json.dumps(after_delete, indent=2))

        print("\n=== CREATE new Knowledge Fanout profile ===")
        create_payload = {
            "name": "Enterprise Multi-RAG Fanout Profile",
            "description": "E2E recreated profile with all 5 sinks and both sources",
            "enabled": True,
            "source_ids": SOURCE_IDS,
            "destinations": DESTINATION_CONFIGS,
        }
        create_resp = client.post(f"{API}/api/knowledge-profiles", json=create_payload)
        if create_resp.status_code not in {200, 201}:
            print("CREATE FAILED:", create_resp.text)
            report["create_error"] = create_resp.text
            print(json.dumps(report, indent=2))
            return 1

        new_profile = create_resp.json()
        new_id = new_profile["id"]
        report["create"] = {"id": new_id, "name": new_profile.get("name")}
        print(f"Created profile {new_id}")

        print("\n=== RESET indexed_files to force full re-sync ===")
        _clear_indexed_files_for_sources()

        print("\n=== TRIGGER SYNC ===")
        sync_resp = client.post(f"{API}/api/knowledge-profiles/{new_id}/sync")
        report["sync_trigger"] = sync_resp.json()
        print(sync_resp.json())

        print("\n=== WAIT FOR SYNC COMPLETION ===")
        final_profile = wait_for_sync(client, new_id)
        report["final_profile_status"] = final_profile.get("status")

        print("\n=== AFTER SYNC: inspect all destinations (visualizer API) ===")
        after_sync = inspect_all(client, new_id)
        report["after_sync_inspect"] = after_sync
        print(json.dumps(after_sync, indent=2))

        visualization_ok = all(
            _dest_has_data(dest, after_sync.get(dest, {}))
            for dest in DEST_TYPES
        )
        report["visualization_ok"] = visualization_ok
        report["all_destinations_populated"] = visualization_ok

        print("\n=== SUMMARY ===")
        print(json.dumps(report, indent=2))
        return 0 if visualization_ok else 2


def _dest_has_data(dest: str, summary: dict[str, Any]) -> bool:
    if summary.get("error"):
        return False
    if dest == "vector_qdrant":
        return int(summary.get("total_points") or 0) > 0
    if dest == "lexical_opensearch":
        return int(summary.get("total_docs") or 0) > 0
    if dest == "graph_neo4j":
        return int(summary.get("total_nodes") or 0) > 0
    if dest == "relational_pgvector":
        return int(summary.get("total_rows") or 0) > 0
    if dest == "cache_redisvl":
        return int(summary.get("total_cached_keys") or 0) > 0
    return False


def _qdrant_count() -> int:
    try:
        r = httpx.get(
            "http://localhost:6335/collections/knowledge_qdrant_collection",
            headers={"api-key": "qdrant"},
            timeout=10,
        )
        return int(r.json().get("result", {}).get("points_count", 0))
    except Exception as exc:
        return -1


def _opensearch_count() -> int:
    try:
        r = httpx.get("http://localhost:9200/knowledge_lexical_index/_count", timeout=10)
        return int(r.json().get("count", 0))
    except Exception as exc:
        return -1


def _neo4j_node_count() -> int:
    try:
        r = httpx.post(
            "http://localhost:7474/db/neo4j/tx/commit",
            json={"statements": [{"statement": "MATCH (n) RETURN count(n) AS c"}]},
            timeout=10,
        )
        rows = r.json().get("results", [{}])[0].get("data", [])
        return int(rows[0].get("row", [0])[0]) if rows else 0
    except Exception:
        return -1


def _postgres_row_count() -> int:
    try:
        import psycopg2

        with psycopg2.connect("postgresql://ingestion:ingestion@localhost:5432/ingestion") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM knowledge_chunks")
                return int(cur.fetchone()[0])
    except Exception:
        return -1


def _clear_indexed_files_for_sources() -> None:
    try:
        import psycopg2

        with psycopg2.connect("postgresql://ingestion:ingestion@localhost:5432/ingestion") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM indexed_files WHERE source_id = ANY(%s::uuid[])",
                    (SOURCE_IDS,),
                )
    except Exception as exc:
        print(f"  warning: could not clear indexed_files: {exc}")


def _redis_key_count() -> int:
    try:
        import redis

        client = redis.from_url("redis://localhost:6379")
        return len(client.keys("knowledge_cache:*"))
    except Exception:
        return -1


if __name__ == "__main__":
    sys.exit(main())
