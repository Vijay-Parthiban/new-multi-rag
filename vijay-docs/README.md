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
| [02 — RAG Pipelines (the assistant builder)](./rag-retrieval-chat-manager-docs/02_rag_pipelines_page.md) | Creating a chat assistant: seven fields in a create dialog, the Knowledge Product and its destinations, the RAG strategy list, the pipeline card grid, the view dialog with its copyable endpoints, edit and the delete warning |
| [03 — RAG Chat](./rag-retrieval-chat-manager-docs/03_rag_chat_page.md) | Conversational interface with citations, streaming, multimodal input and guardrails. The page streams from the selected assistant's endpoint |
| [04 — Prompts](./rag-retrieval-chat-manager-docs/04_prompts_management_page.md) | Prompt templates: the system message a pipeline attaches, with create, edit and delete |
| [05 — Real Time Monitoring](./rag-retrieval-chat-manager-docs/05_realtime_monitoring_page.md) | Live latency, token, and quality metrics for running pipelines |
| [06 — Offline Evaluation](./rag-retrieval-chat-manager-docs/06_offline_evaluation_page.md) | Golden dataset runs scored per retrieval, rerank, and generation stage |
| [07 — Tracking & Traces](./rag-retrieval-chat-manager-docs/07_tracking_and_traces_page.md) | Per-message span timelines exported through OpenTelemetry |
| [08 — Guard Config](./rag-retrieval-chat-manager-docs/08_ai_guardrails_config_page.md) | Guardrails policy definitions: a validator picker beside per-validator settings, the ban list, PII entities and toxic language, and the config card grid |
| [09 — Guard Traces](./rag-retrieval-chat-manager-docs/09_ai_guardrails_traces_page.md) | Audit trail of guardrail evaluations: ranked block breakdown, per-validator failures, the trace table and its detail drawer |
| [10 — Guard Evaluation](./rag-retrieval-chat-manager-docs/10_ai_guardrails_eval_page.md) | Golden-dataset evaluation runs against guardrails configurations, with per-run missed and false counts |
| [11 — Knowledge Store (view only)](./rag-retrieval-chat-manager-docs/11_knowledge_store_page.md) | Read-only mirror of the ingestion manager's Knowledge Products: live fanout, ingested-file ledger, destination inspection, manual and automatic refresh |
| [12 — Evaluation Metrics Reference](./rag-retrieval-chat-manager-docs/12_evaluation_metrics_reference.md) | Retrieval, rerank, and generation metric definitions |
| [13 — Golden Dataset Requirements](./rag-retrieval-chat-manager-docs/13_golden_dataset_requirements.md) | Golden dataset schema and evaluation API contract |
| [14 — Assistant Pipelines & Endpoints](./rag-retrieval-chat-manager-docs/14_assistant_pipelines_and_endpoints.md) | The integrator reference: what an assistant is, how a slug resolves to stores, all four endpoints with `curl` examples, the OpenAI SDK snippets, and the strategy table |
| [15 — Assistant Session Memory](./rag-retrieval-chat-manager-docs/15_assistant_session_memory.md) | Session memory gated on the product's Redis destination: the six-step turn, the query rewrite, the `GET` and `DELETE` session endpoints, SDK snippets for another project, and the failure behaviour |
| [16 — Observability and Tracing](./rag-retrieval-chat-manager-docs/16_observability_tracing.md) | The OTEL collector fan-out to Phoenix and Langfuse, the `test` and `prod` trace modes, the individual turn trace, the session trace derived from the session UUID, and how to add a platform |

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
- **Guardrails UI pass on 2026-09-21**: the three guardrails pages were reworked for usability, and the work was verified in a live browser rather than by reading the code. All 14 retrieval routes (the 11 navigation entries plus `/browse`, `/sources`, `/upload` and `/knowledge-store`) render with no console error, nothing stuck loading, and no horizontal overflow at 1440, 1024, 900 or 375 px. Light mode was checked on the densest page (bars, guard chips, verdict badges and the detail drawer stay legible) because the new rules use the existing semantic tokens. Keyboard focus on a picker chip draws the 2 px accent ring, and a trace row opens from Enter or Space. Bar proportions were measured in the DOM: 86.7% / 13.3% blocked, and 32% / 25% / 0% failures. The commit is `b1b8b6d`
- **Pipelines page rework on 2026-09-21**: the create form moved off the page into a dialog, the saved list became a card grid, and a read-only view dialog took over the endpoint display. Verified in a live browser: every dialog opens, the delete warning appears from both the card and the view, and a full create-then-delete cycle was run with a throwaway pipeline and cleaned up. No console error on any of the 14 retrieval routes, no horizontal overflow at 1600, 1280, 1024, 900, 640 or 375 px, and the card grid collapses from three columns to two to one. Light mode was checked and its stat-card contrast defect fixed
- **Assistant session memory on 2026-09-22**: an assistant now keeps a conversation when its Knowledge Product has the Redis destination enabled, and ends it on `DELETE /api/assistants/{slug}/sessions/{session_id}`. Unit tests: `tests/unit/test_session_memory.py` (14 tests against a live Redis) and the history cases in `tests/unit/test_prompt_builder.py`, 19 passing. Live check: `scripts/e2e_session_memory.py`. **The live run and the browser pass are outstanding**: the Docker daemon stopped answering part way through (`docker ps` returns empty), so LiteLLM on 4000 hangs every model call and both the legacy `/chat` and the assistant chat timed out at 45 s. That is an environment failure, not a code defect, and it pre-dates this change: the legacy route carries none of this work and times out identically. Re-run the script and the browser pass once Docker Desktop is restarted
- **Observability and tracing on 2026-09-22**: the collector now fans out to Phoenix and Langfuse from one traces pipeline, every turn is tagged `test` or `prod` from the `X-RAG-Trace-Mode` header (absent means production), and a pipeline with Redis memory also files its turn into a session trace derived from the session UUID. The metrics span no longer opens a second trace. Migration `004` added `trace_mode`, `otel_trace_id` and `otel_span_id` to `chat_pipeline_traces`; it applied cleanly and the 85 existing rows read back as `prod`. Verified by `tests/unit/test_tracing.py`, 16 tests against an in-memory span exporter that assert what reaches the collector: the mode tag, two turns of one session sharing a trace id, separate traces without a session, two sessions not colliding, the metrics span joining the turn, and the non-UUID fallback. 35 unit tests pass in total. The collector config was validated statically: YAML parses, all 14 `${env:…}` references resolve against `otel/.env`, every named exporter is configured, and `batch` is last in every pipeline. **Two live checks are outstanding**: the collector was not restarted onto the new config, and the model call still hangs at 90 s, so no span has been observed arriving at either backend. Both are blocked by the Docker daemon and the LiteLLM proxy being unreliable in this environment
- Retrieval schema head: `004_trace_mode` (`uv run rag-db-migrate` from `rag-retrieval-chat-manager/backend`). Ingestion schema head: `011_assistant_pipeline`.

## Running the stack

[`two_project_run.md`](./two_project_run.md) is the complete run guide. `overall-detailed.md` §4 holds the shorter reference. Four things trip people up:

- **Three containers live outside this repository**: the knowledge product Qdrant on `6335`, the LiteLLM proxy on `4000`, and LiteLLM's own PostgreSQL on `5433`. Start them first, or the platform will not embed, answer, or find a single chunk.
- The retrieval `backend/.env` uses Docker service hostnames, so a host run needs `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `QDRANT_KP_URL`, `OPENSEARCH_URL`, `INGESTION_SERVICE_URL`, `INGESTION_DATABASE_URL`, `GUARDRAILS_URL` and `LITELLM_BASE_URL` passed as process environment. `uv sync --all-packages` is required; plain `uv sync` installs only the root project.
- **Two Qdrant instances can be running**: host `6333` (compose-declared, holds the scraper's `scrape_embeddings`) and host `6335` (holds the ingestion fanout `kp_*` collections). `qdrant_url` points at the first and `qdrant_kp_url` at the second. A reader pointed at the wrong one returns zero points and no error, which looks like a broken assistant.
- On Windows the RQ evaluation worker needs `--worker-class rq.worker.SimpleWorker`, because the default worker calls `os.fork()`.
