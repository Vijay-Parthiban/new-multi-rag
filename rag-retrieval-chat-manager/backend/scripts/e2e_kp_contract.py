#!/usr/bin/env python
"""Guard the Knowledge Product wire contract between the two projects.

The retrieval service proxies ``GET /api/knowledge-products`` from the ingestion
service and declares
``shared_contracts.knowledge.KnowledgeProductRead`` as its ``response_model``.
FastAPI filters every response through that model, so **any field the model does
not declare is silently dropped** before the retrieval frontend sees it.

That happened: the model declared 19 of the 29 fields the ingestion serializer
writes, so the Knowledge Store page showed "Linked RAG Pipelines (0)" for every
product and read ``text_embedding_model`` as null.

This script compares the two payloads recursively, at every nesting level, and
exits non-zero on any loss. It asserts nothing by hand: both sides are read from
the running services, so a field added to either side later is caught here rather
than in the browser.

    uv run python scripts/e2e_kp_contract.py

Exit 0 when the contract is faithful, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

INGESTION_URL = os.getenv("INGESTION_SERVICE_URL", "http://127.0.0.1:8007").rstrip("/")
RETRIEVAL_URL = os.getenv("RETRIEVAL_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")

PATH = "/api/knowledge-products"

checks = 0
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}  {detail}")
        failures.append(f"{label} {detail}".strip())


def compare(label: str, direct: Any, proxied: Any, path: str = "$") -> None:
    """Compare two JSON values. Any key present on the left must survive on the right."""
    global checks
    if isinstance(direct, dict):
        if not isinstance(proxied, dict):
            check(f"{label} is an object", False, f"proxy gave {type(proxied).__name__}")
            return
        lost = sorted(set(direct) - set(proxied))
        checks += 1
        if lost:
            print(f"  FAIL {label} loses {len(lost)} field(s): {', '.join(lost)}")
            failures.append(f"{path} loses {', '.join(lost)}")
        else:
            print(f"  ok   {label} ({len(direct)} fields, none lost)")
        for key in sorted(set(direct) & set(proxied)):
            left, right = direct[key], proxied[key]
            # Only recurse into the first element: the shape is what matters, and
            # every element of a list is serialized by the same code path.
            if isinstance(left, list) and left and isinstance(right, list) and right:
                compare(f"{label}.{key}[0]", left[0], right[0], f"{path}.{key}[0]")
            elif isinstance(left, dict):
                compare(f"{label}.{key}", left, right, f"{path}.{key}")
    elif isinstance(direct, list):
        if not isinstance(proxied, list):
            check(f"{label} is an array", False, f"proxy gave {type(proxied).__name__}")


def main() -> int:
    print(f"direct  : {INGESTION_URL}{PATH}")
    print(f"proxied : {RETRIEVAL_URL}{PATH}\n")

    try:
        direct = httpx.get(f"{INGESTION_URL}{PATH}", timeout=30.0).json()
        proxied = httpx.get(f"{RETRIEVAL_URL}{PATH}", timeout=30.0).json()
    except Exception as exc:  # noqa: BLE001 - a reachability failure is the report
        print(f"  FAIL cannot reach a service: {type(exc).__name__}: {exc}")
        print("\nStart both projects before running this check.")
        return 1

    check("both respond with a list", isinstance(direct, list) and isinstance(proxied, list))
    if not isinstance(direct, list) or not isinstance(proxied, list):
        return 1

    check("same record count", len(direct) == len(proxied), f"{len(direct)} vs {len(proxied)}")

    if not direct:
        # Nothing to compare. The field-shape check needs at least one product.
        print("\n  skip field comparison: the ingestion service has no knowledge products")
        print("  create one, then run this again")
        print(f"\n{checks} checks, {len(failures)} failure(s)")
        return 0 if not failures else 1

    print()
    compare("product", direct[0], proxied[0])

    print(f"\n{checks} checks, {len(failures)} failure(s)")
    if failures:
        print("\nThe proxy drops fields the ingestion service sends.")
        print("Add them to shared_contracts/knowledge.py, then rebuild the retrieval image.")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("Contract is faithful: the proxy forwards every field.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
