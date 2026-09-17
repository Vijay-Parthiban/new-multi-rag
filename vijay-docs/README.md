# new-multi-rag — Documentation Index

**Last updated:** 2026-09-17

This folder is the canonical documentation set for the `new-multi-rag` platform. Service-level READMEs point here rather than duplicating architecture content at the repo root.

## Platform

| Document | Description |
|---|---|
| [overall-detailed.md](./overall-detailed.md) | End-to-end architecture, data lifecycle, ports, and operational runbook |

## RAG Ingestion Manager

| Document | Description |
|---|---|
| [overall-rag-ingestion-manager.md](./rag-ingestion-manager-docs/overall-rag-ingestion-manager.md) | Backend/frontend topology, fanout engine, codebase map |
| [01 — Overview Dashboard](./rag-ingestion-manager-docs/01_overview_dashboard_page.md) | Home page metrics and quick links |
| [02 — Folders & File Browser](./rag-ingestion-manager-docs/02_folders_and_file_browser_page.md) | Directory workspace and file preview |
| [03 — Data Sources](./rag-ingestion-manager-docs/03_data_sources_page.md) | MinIO buckets, connectors, sync |
| [04 — Knowledge Store Fanout](./rag-ingestion-manager-docs/04_knowledge_store_page.md) | 5-sink profiles, sync, purge, visualizers |
| [05 — Document Upload](./rag-ingestion-manager-docs/05_document_upload_page.md) | Chunked upload and multi-format parsing |

## RAG Retrieval & Chat Manager

| Document | Description |
|---|---|
| [overall-rag-retrieval-chat-manager.md](./rag-retrieval-chat-manager-docs/overall-rag-retrieval-chat-manager.md) | Retrieval, generation, guardrails, evaluation stack |
| [01–11 — UI pages](./rag-retrieval-chat-manager-docs/) | Per-page docs for dashboard, pipelines, chat, eval, guardrails |
| [12 — Evaluation Metrics Reference](./rag-retrieval-chat-manager-docs/12_evaluation_metrics_reference.md) | Retrieval, rerank, and generation metric definitions |
| [13 — Golden Dataset Requirements](./rag-retrieval-chat-manager-docs/13_golden_dataset_requirements.md) | Golden dataset schema and evaluation API contract |

## Shared Libraries

- `shared-libs/platform-common/` — API key auth (`X-API-Key` header or `api_key` query param), Qdrant store helpers, and retrieval payload contracts used by both ingestion fanout and retrieval search.

## Verification

- Knowledge fanout E2E script: `rag-ingestion-manager/backend/scripts/e2e_knowledge_fanout.py`
- Unit tests: `rag-ingestion-manager/backend/tests/test_page_yielder.py`, `test_fanout_payload.py`
