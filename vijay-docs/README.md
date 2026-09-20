# new-multi-rag — Documentation Index

**Last updated:** 2026-09-20

This folder is the canonical documentation set for the `new-multi-rag` platform. Service-level READMEs point here rather than duplicating architecture content at the repo root.

## Platform

| Document | Description |
|---|---|
| [overall-detailed.md](./overall-detailed.md) | End-to-end architecture, data lifecycle, port/storage matrix, shared contracts, and operational runbook |

## RAG Ingestion Manager (`rag-ingestion-manager-docs/`)

| Document | Description |
|---|---|
| [overall-rag-ingestion-manager.md](./rag-ingestion-manager-docs/overall-rag-ingestion-manager.md) | Backend/frontend topology, connector sync, fanout engine, codebase map |
| [01 — Overview Dashboard](./rag-ingestion-manager-docs/01_overview_dashboard_page.md) | Home page metrics, source summary, and quick links |
| [02 — Folders & File Browser](./rag-ingestion-manager-docs/02_folders_and_file_browser_page.md) | Directory workspace, file listing, and document inspector |
| [03 — Data Sources](./rag-ingestion-manager-docs/03_data_sources_page.md) | Source buckets, NiFi connector catalogue, live/scheduled polling, sync, delete, file management |
| [04 — Knowledge Store Fanout](./rag-ingestion-manager-docs/04_knowledge_store_page.md) | Knowledge products, 4 destination sinks, automatic sync, pause/resume, live fanout timeline, visualizers |
| [05 — Document Upload (removed)](./rag-ingestion-manager-docs/05_document_upload_page.md) | Why the `/upload` page was removed, where uploads live now, and the file-format support matrix |

## RAG Retrieval & Chat Manager (`rag-retrieval-chat-manager-docs/`)

| Document | Description |
|---|---|
| [overall-rag-retrieval-chat-manager.md](./rag-retrieval-chat-manager-docs/overall-rag-retrieval-chat-manager.md) | Retrieval, rerank, generation, guardrails, and evaluation service architecture |
| [01 — Overview Dashboard](./rag-retrieval-chat-manager-docs/01_overview_dashboard_page.md) | Landing page with headline stats and quick links to the other pages |
| [02 — RAG Pipelines](./rag-retrieval-chat-manager-docs/02_rag_pipelines_page.md) | Pipeline configuration: retrieval mode, models, rerank and generation settings |
| [03 — RAG Chat](./rag-retrieval-chat-manager-docs/03_rag_chat_page.md) | Conversational interface with citations, streaming, multimodal input, guardrails |
| [04 — Prompts](./rag-retrieval-chat-manager-docs/04_prompts_management_page.md) | Prompt studio: authoring, versioning, and prompt overrides |
| [05 — Real Time Monitoring](./rag-retrieval-chat-manager-docs/05_realtime_monitoring_page.md) | Live latency, token, and quality metrics for running pipelines |
| [06 — Offline Evaluation](./rag-retrieval-chat-manager-docs/06_offline_evaluation_page.md) | Golden dataset runs scored per retrieval, rerank, and generation stage |
| [07 — Tracking & Traces](./rag-retrieval-chat-manager-docs/07_tracking_and_traces_page.md) | Per-message span timelines exported through OpenTelemetry |
| [08 — Guard Config](./rag-retrieval-chat-manager-docs/08_ai_guardrails_config_page.md) | Guardrails policy definitions: ban list, PII entities, toxic language |
| [09 — Guard Traces](./rag-retrieval-chat-manager-docs/09_ai_guardrails_traces_page.md) | Audit trail of guardrail evaluations and their outcomes |
| [10 — Guard Evaluation](./rag-retrieval-chat-manager-docs/10_ai_guardrails_eval_page.md) | Golden-dataset evaluation runs against guardrails configurations |
| [11 — Knowledge Store (view only)](./rag-retrieval-chat-manager-docs/11_knowledge_store_page.md) | Read-only mirror of the ingestion manager's Knowledge Products: live fanout, ingested-file ledger, destination inspection, manual and automatic refresh |
| [12 — Evaluation Metrics Reference](./rag-retrieval-chat-manager-docs/12_evaluation_metrics_reference.md) | Retrieval, rerank, and generation metric definitions |
| [13 — Golden Dataset Requirements](./rag-retrieval-chat-manager-docs/13_golden_dataset_requirements.md) | Golden dataset schema and evaluation API contract |

## Shared Libraries

- `shared-libs/platform-common/` — API key auth (`X-API-Key` header or `api_key` query param), dense/sparse embedding clients, SSRF URL validation, Qdrant store helpers, and the retrieval hit/payload contract used by both ingestion fanout and retrieval search.
- `shared-contracts/` — Pydantic cross-service schemas (`shared_contracts.knowledge`, `.sources`, `.search`, `.pipelines`) consumed by the ingestion backend and the retrieval knowledge-product proxy.

## Verification

- Knowledge fanout E2E scripts: `rag-ingestion-manager/backend/scripts/e2e_knowledge_fanout.py` (20 checks — CRUD propagation and store isolation) and `rag-ingestion-manager/backend/scripts/e2e_knowledge_pause.py` (14 checks — pause and resume)
- Legacy Neo4j purge script: `rag-ingestion-manager/backend/scripts/purge_neo4j_legacy.py`
- Ingestion unit tests (`uv run pytest tests -q` from `rag-ingestion-manager/backend`, 23 passing): `tests/test_page_yielder.py`, `tests/test_fanout_payload.py`, `tests/test_knowledge_destination_schemas.py`, `tests/test_knowledge_product_files.py`, `tests/test_connector_config_validation.py`
- Retrieval unit tests: `rag-retrieval-chat-manager/backend/tests/unit/` — 52 tests, **20 failing** as of 2026-09-20 and the failures pre-date that day's fixes. `test_dataset_upload.py` asserts a 20-item golden dataset while the committed file holds 5; `test_stats.py` fails only when the suite runs as a whole, because each test passes alone
- Retrieval integration test: `rag-retrieval-chat-manager/backend/tests/integration/test_qdrant_retrieve.py` (requires a reachable Qdrant)
- Retrieval schema head: `002_guardrails_tables` (`uv run rag-db-migrate` from `rag-retrieval-chat-manager/backend`)

## Running the stack

`overall-detailed.md` §4 holds the commands. Two things trip people up:

- The retrieval `backend/.env` uses Docker service hostnames, so a host run needs `DATABASE_URL`, `REDIS_URL` and `QDRANT_URL` passed as process environment. `uv sync --all-packages` is required; plain `uv sync` installs only the root project.
- Two Qdrant instances can be running: host `6333` (compose-declared, holds the scraper's `scrape_embeddings`) and host `6335` (holds the ingestion fanout `kp_*` collections). Point a reader at whichever one holds the data it needs.
