# new-multi-rag — Documentation Index

**Last updated:** 2026-09-21

This folder is the canonical documentation set for the `new-multi-rag` platform. Service-level READMEs point here rather than duplicating architecture content at the repo root.

## Start here

| Document | Description |
|---|---|
| [two_project_run.md](./two_project_run.md) | **The run guide.** How to run both projects end to end in any environment: prerequisites, the six containers this repository declares, the three containers that live outside it, every port, the environment block for each backend, the start order, a first-run walkthrough, verification commands and a troubleshooting table |

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
| [06 — Ingestion Profiles](./rag-ingestion-manager-docs/06_ingestion_profiles_page.md) | Saved destination and chunking profiles: env-only connections, text or text-with-images modality, copy-on-create semantics, apply-profile purge and re-sync |

## RAG Retrieval & Chat Manager (`rag-retrieval-chat-manager-docs/`)

| Document | Description |
|---|---|
| [overall-rag-retrieval-chat-manager.md](./rag-retrieval-chat-manager-docs/overall-rag-retrieval-chat-manager.md) | Retrieval, rerank, generation, guardrails, and evaluation service architecture |
| [01 — Overview Dashboard](./rag-retrieval-chat-manager-docs/01_overview_dashboard_page.md) | Landing page with headline stats and quick links to the other pages |
| [02 — RAG Pipelines (the assistant builder)](./rag-retrieval-chat-manager-docs/02_rag_pipelines_page.md) | Creating a chat assistant: seven fields, the Knowledge Product and its destinations, the RAG strategy list, the copyable endpoint, the saved list, the edit modal |
| [03 — RAG Chat](./rag-retrieval-chat-manager-docs/03_rag_chat_page.md) | Conversational interface with citations, streaming, multimodal input and guardrails. The page streams from the selected assistant's endpoint |
| [04 — Prompts](./rag-retrieval-chat-manager-docs/04_prompts_management_page.md) | Prompt templates: the system message a pipeline attaches, with create, edit and delete |
| [05 — Real Time Monitoring](./rag-retrieval-chat-manager-docs/05_realtime_monitoring_page.md) | Live latency, token, and quality metrics for running pipelines |
| [06 — Offline Evaluation](./rag-retrieval-chat-manager-docs/06_offline_evaluation_page.md) | Golden dataset runs scored per retrieval, rerank, and generation stage |
| [07 — Tracking & Traces](./rag-retrieval-chat-manager-docs/07_tracking_and_traces_page.md) | Per-message span timelines exported through OpenTelemetry |
| [08 — Guard Config](./rag-retrieval-chat-manager-docs/08_ai_guardrails_config_page.md) | Guardrails policy definitions: ban list, PII entities, toxic language |
| [09 — Guard Traces](./rag-retrieval-chat-manager-docs/09_ai_guardrails_traces_page.md) | Audit trail of guardrail evaluations and their outcomes |
| [10 — Guard Evaluation](./rag-retrieval-chat-manager-docs/10_ai_guardrails_eval_page.md) | Golden-dataset evaluation runs against guardrails configurations |
| [11 — Knowledge Store (view only)](./rag-retrieval-chat-manager-docs/11_knowledge_store_page.md) | Read-only mirror of the ingestion manager's Knowledge Products: live fanout, ingested-file ledger, destination inspection, manual and automatic refresh |
| [12 — Evaluation Metrics Reference](./rag-retrieval-chat-manager-docs/12_evaluation_metrics_reference.md) | Retrieval, rerank, and generation metric definitions |
| [13 — Golden Dataset Requirements](./rag-retrieval-chat-manager-docs/13_golden_dataset_requirements.md) | Golden dataset schema and evaluation API contract |
| [14 — Assistant Pipelines & Endpoints](./rag-retrieval-chat-manager-docs/14_assistant_pipelines_and_endpoints.md) | The integrator reference: what an assistant is, how a slug resolves to stores, all four endpoints with `curl` examples, the OpenAI SDK snippets, and the strategy table |

## Shared Libraries

- `shared-libs/platform-common/` — API key auth (`X-API-Key` header or `api_key` query param), dense/sparse embedding clients, SSRF URL validation, Qdrant store helpers, and the retrieval hit/payload contract used by both ingestion fanout and retrieval search.
- `shared-contracts/` — Pydantic cross-service schemas (`shared_contracts.knowledge`, `.sources`, `.search`, `.pipelines`) consumed by the ingestion backend and the retrieval knowledge-product proxy.

## Verification

- Knowledge E2E scripts, all green against the live four stores on 2026-09-21: `rag-ingestion-manager/backend/scripts/e2e_knowledge_fanout.py` (21 checks — CRUD propagation, store isolation, a supplied store name overwritten by the derived one), `e2e_knowledge_pause.py` (14 checks — pause and resume), `e2e_ingestion_profiles.py` (50 checks — profile store isolation, per-page chunking, `apply-profile` re-sync and `409 PROFILE_IN_USE`) and `e2e_ingestion_modality.py` (29 checks — env-only field surface, derived dimension, `text` versus `text_images`, `422 CAPTION_MODEL_REQUIRED`), plus `e2e_chunk_strategies.py` (19 checks — one product moved through `section`, `parent_child`, `fixed` and `context_aware`, with the record count and the `parent_ref` checked in all four stores after each move)
- Legacy Neo4j purge script: `rag-ingestion-manager/backend/scripts/purge_neo4j_legacy.py`
- Ingestion unit tests (`uv run pytest tests -q` from `rag-ingestion-manager/backend`, 59 passing): `tests/test_page_yielder.py`, `tests/test_page_yielder_figures.py`, `tests/test_fanout_payload.py`, `tests/test_knowledge_destination_schemas.py`, `tests/test_knowledge_product_files.py`, `tests/test_connector_config_validation.py`, `tests/test_ingestion_profile_chunking.py` and `tests/test_ingestion_modality_resolvers.py`
- Retrieval unit tests: `rag-retrieval-chat-manager/backend/tests/unit/` — 52 tests, **20 failing** as of 2026-09-20 and the failures pre-date that day's fixes. `test_dataset_upload.py` asserts a 20-item golden dataset while the committed file holds 5; `test_stats.py` fails only when the suite runs as a whole, because each test passes alone
- Retrieval integration test: `rag-retrieval-chat-manager/backend/tests/integration/test_qdrant_retrieve.py` (requires a reachable Qdrant)
- **Assistant pipeline E2E**: `rag-retrieval-chat-manager/backend/scripts/e2e_assistant_pipelines.py` — **30 checks, all green on 2026-09-21** against the live stack. It creates its own prompt template, guardrails config and pipeline, then deletes every fixture. Coverage: prompt-template CRUD and a duplicate-name `409`, a guardrails config, pipeline create with a slug and four destinations, assistant resolution, native chat with sources, the OpenAI non-stream and stream shapes, the native stream frames, a guardrails block with a recorded trace, one chat per strategy (`vector`, `lexical`, `relational`, `hybrid`), a prompt template in force (a one-word template produced a one-word answer), an edit of the chat model, and fixture deletion
- Frontend checks on 2026-09-21: `npx tsc --noEmit` reports no error, `npx vite build` succeeds, and a browser pass over all 14 retrieval routes and all 6 ingestion routes reports zero console errors
- Retrieval schema head: `003_prompt_templates` (`uv run rag-db-migrate` from `rag-retrieval-chat-manager/backend`). Ingestion schema head: `011_assistant_pipeline`.

## Running the stack

[`two_project_run.md`](./two_project_run.md) is the complete run guide. `overall-detailed.md` §4 holds the shorter reference. Four things trip people up:

- **Three containers live outside this repository**: the knowledge product Qdrant on `6335`, the LiteLLM proxy on `4000`, and LiteLLM's own PostgreSQL on `5433`. Start them first, or the platform will not embed, answer, or find a single chunk.
- The retrieval `backend/.env` uses Docker service hostnames, so a host run needs `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `QDRANT_KP_URL`, `OPENSEARCH_URL`, `INGESTION_SERVICE_URL`, `INGESTION_DATABASE_URL`, `GUARDRAILS_URL` and `LITELLM_BASE_URL` passed as process environment. `uv sync --all-packages` is required; plain `uv sync` installs only the root project.
- **Two Qdrant instances can be running**: host `6333` (compose-declared, holds the scraper's `scrape_embeddings`) and host `6335` (holds the ingestion fanout `kp_*` collections). `qdrant_url` points at the first and `qdrant_kp_url` at the second. A reader pointed at the wrong one returns zero points and no error, which looks like a broken assistant.
- On Windows the RQ evaluation worker needs `--worker-class rq.worker.SimpleWorker`, because the default worker calls `os.fork()`.
