"""End-to-end check for the reworked Offline Evaluation path.

Uploads a real CSV through the live API, runs an evaluation on one row, and asserts the
custom metrics and the per-category block come back. Cleans up after itself.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = "http://127.0.0.1:8001"
CSV_PATH = Path(__file__).resolve().parent.parent / "tcs_policies_golden_dataset.csv"
DATASET_NAME = "E2E CSV Probe"

RESULTS: list[tuple[bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}{(' -- ' + detail) if detail else ''}", flush=True)
    RESULTS.append((ok, label))


def call(method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:200]


def upload_csv(path: Path, name: str) -> tuple[int, str]:
    """A real multipart upload, the way the browser sends it."""
    boundary = "----probe" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    url = f"{API}/evaluate/datasets/upload?replace=true&name={urllib.parse.quote(name)}"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def main() -> int:
    import urllib.parse  # noqa: F401  (used by upload_csv)

    if not CSV_PATH.exists():
        print(f"missing reference CSV at {CSV_PATH}")
        return 2

    print("=== 1. upload the CSV ===", flush=True)
    status, out = upload_csv(CSV_PATH, DATASET_NAME)
    check("CSV upload accepted", status == 200, f"HTTP {status} {out[:150]}")
    if status != 200:
        return 1
    created = json.loads(out)
    dataset_id = created["dataset_id"]
    check("all 22 rows imported", created.get("item_count") == 22, f"item_count={created.get('item_count')}")
    check("name applied", created.get("name") == DATASET_NAME, created.get("name", ""))

    print("\n=== 2. a bad CSV is rejected ===", flush=True)
    bad = Path(CSV_PATH.parent) / "_bad_probe.csv"
    bad.write_text("id,foo\n1,bar\n", encoding="utf-8")
    try:
        status, out = upload_csv(bad, "E2E Bad Probe")
        check("a CSV with no question column is rejected", status == 422, f"HTTP {status}")
        check("the error names the missing column", "question" in out, out[:120])
    finally:
        bad.unlink(missing_ok=True)

    print("\n=== 3. run the evaluation on one row ===", flush=True)
    # The run must read a real Knowledge Product's stores, exactly as the page does. Without
    # them the evaluator falls back to the default scrape collection, which does not exist,
    # and every item fails before a metric is computed.
    ingest = "http://127.0.0.1:8007"
    pstatus, pbody = 0, "[]"
    try:
        with urllib.request.urlopen(f"{ingest}/api/pipelines", timeout=60) as r:
            pstatus, pbody = r.status, r.read().decode()
    except Exception as exc:  # noqa: BLE001
        print(f"   could not reach the ingestion service: {exc}", flush=True)
    pipelines = json.loads(pbody) if pstatus == 200 and pbody.strip().startswith("[") else []
    usable = [p for p in pipelines if (p.get("knowledge_product") or {}).get("destinations")]
    if not usable:
        print("   no pipeline with a Knowledge Product is available; skipping the run section", flush=True)
        failed = [label for ok, label in RESULTS if not ok]
        print(f"\n=== {len(RESULTS) - len(failed)}/{len(RESULTS)} passed (run section skipped) ===", flush=True)
        for label in failed:
            print(f"  FAILED: {label}", flush=True)
        return 1 if failed else 0

    pipeline = usable[0]
    product = pipeline["knowledge_product"]
    dest = {d["destination_type"]: d for d in product.get("destinations", []) if d.get("enabled")}
    qdrant = dest.get("vector_qdrant") or {}
    opensearch = dest.get("lexical_opensearch") or {}
    pg = dest.get("relational_pgvector") or {}
    print(f"   pipeline: {pipeline.get('name')} · strategy={pipeline.get('rag_strategy')}", flush=True)
    print(f"   collection={qdrant.get('config', {}).get('collection_name')} index={opensearch.get('config', {}).get('index_name')}", flush=True)

    run_id = None
    config = {
        "retrieval_mode": "dense",
        "retrieve_limit": 10,
        "rerank_enabled": False,
        "top_k": 5,
        "sample_size": 2,
        "judge_model": None,
        # The pipeline's own chat_model is `llama-3.3-70b-versatile`, which this proxy does
        # not serve, so every generation 400s before a metric is computed. Pin a served model
        # so the probe exercises the scoring path rather than the model catalog.
        "generation_model": "Gpt-oss-20b",
        "rag_strategy": pipeline.get("rag_strategy"),
        "collection": (qdrant.get("config") or {}).get("collection_name"),
        "embedding_model": product.get("text_embedding_model"),
        "opensearch_index": (opensearch.get("config") or {}).get("index_name"),
        "pg_schema": (pg.get("config") or {}).get("schema_name"),
        "pg_table": (pg.get("config") or {}).get("table_name"),
    }
    status, out = call("POST", "/evaluate/runs", {"dataset_id": dataset_id, "config": config})
    check("run queued", status == 200, f"HTTP {status} {out[:160]}")
    if status != 200:
        return 1
    run_id = json.loads(out)["run_id"]

    deadline = time.time() + 900
    final = None
    while time.time() < deadline:
        time.sleep(5)
        s, b = call("GET", f"/evaluate/runs/{run_id}")
        final = json.loads(b)
        if final.get("status") in ("completed", "failed"):
            break

    check("run reached a terminal state", final and final.get("status") in ("completed", "failed"), (final or {}).get("status", ""))
    agg = (final or {}).get("aggregate_metrics") or {}
    print("\n=== 4. the aggregate carries the new keys ===", flush=True)
    check("categories block present", "categories" in agg, str(sorted(agg.keys()))[:160])
    gen = agg.get("generation") or {}
    print("   generation keys:", sorted(gen.keys())[:12], flush=True)
    check(
        "a custom metric appears in the aggregate",
        any(k in gen for k in ("mean_behavior_match", "mean_keypoint_coverage")),
        str([k for k in gen if "behavior" in k or "keypoint" in k]),
    )

    print("\n=== 5. per-item metrics ===", flush=True)
    s, b = call("GET", f"/evaluate/runs/{run_id}/items")
    items = json.loads(b).get("items", []) if s == 200 else []
    check("run items exist", 1 <= len(items) <= 2, f"{len(items)} items")
    if items:
        gm = items[0].get("generation_metrics") or {}
        print("   item generation_metrics:", sorted(gm.keys())[:14], flush=True)
        check(
            "the item carries a custom metric",
            any(k in gm for k in ("behavior_match", "keypoint_coverage")),
            str([k for k in gm if "behavior" in k or "keypoint" in k]),
        )

    print("\n=== 6. clean up ===", flush=True)
    s, _ = call("DELETE", f"/evaluate/datasets/{dataset_id}")
    check("probe dataset deleted", s == 204, f"HTTP {s}")
    listing = json.loads(call("GET", "/evaluate/datasets")[1]).get("items", [])
    check("no probe dataset remains", not any(d["name"] == DATASET_NAME for d in listing))

    failed = [label for ok, label in RESULTS if not ok]
    print(f"\n=== {len(RESULTS) - len(failed)}/{len(RESULTS)} passed ===", flush=True)
    for label in failed:
        print(f"  FAILED: {label}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
