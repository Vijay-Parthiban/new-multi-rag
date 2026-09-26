"""Time the OpenSearch lexical search the way the retrieval service does it.

    docker cp scripts/check_opensearch.py backend-rag-api-1:/tmp/check_opensearch.py
    docker exec backend-rag-api-1 python /tmp/check_opensearch.py

Prints the cluster state, the indices, and a timed search per index, so a timeout
can be told apart from a missing index.
"""

from __future__ import annotations

import sys
import time

import httpx

from rag_shared.config import get_settings

s = get_settings()
base = s.opensearch_url.rstrip("/")
auth = (s.opensearch_username, s.opensearch_password) if s.opensearch_username else None
print(f"opensearch_url = {base}")
print(f"auth           = {'set' if auth else 'none'}\n")


def timed(label: str, url: str, body: dict | None = None, timeout: float = 20.0) -> None:
    t0 = time.monotonic()
    try:
        r = httpx.post(url, json=body, auth=auth, timeout=timeout) if body else httpx.get(url, auth=auth, timeout=timeout)
        dt = time.monotonic() - t0
        print(f"  ok   {label:42} {r.status_code:>4}  {dt:6.2f}s  {len(r.content):>7}b")
        return r
    except Exception as exc:  # noqa: BLE001
        dt = time.monotonic() - t0
        print(f"  FAIL {label:42} {type(exc).__name__}  {dt:6.2f}s")
        return None


print("cluster:")
timed("GET /", base)
r = timed("GET /_cluster/health", f"{base}/_cluster/health")
if r is not None:
    try:
        print("       " + str(r.json()))
    except Exception:  # noqa: BLE001
        pass

print("\nindices:")
r = timed("GET /_cat/indices?format=json", f"{base}/_cat/indices?format=json")
names: list[str] = []
if r is not None:
    try:
        names = sorted(i["index"] for i in r.json() if not i["index"].startswith("."))
        for i in names:
            print(f"       {i}")
    except Exception as exc:  # noqa: BLE001
        print(f"       cannot parse: {exc}")

print("\nsearches (this is the call that times out):")
targets = names or []
for index in targets:
    timed(f"POST /{index}/_search", f"{base}/{index}/_search", {"size": 20, "query": {"match_all": {}}})

if not targets:
    print("  (no indices, so nothing to search)")

sys.exit(0)
