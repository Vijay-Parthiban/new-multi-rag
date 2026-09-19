# 07 — Tracking Page & Trace Persistence

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **Tracking** page (`frontend/src/pages/TrackingPage.tsx`, route `/tracking`, nav label "Tracking") is a **read-only operational monitor**. Its own header describes the scope exactly: title "Pipeline Tracking", description "Monitor document ingestion status and web scraper job history." (`TrackingPage.tsx:94-95`). It lists ingestion pipeline runs, scraper crawl jobs and scraper scrape jobs, and it polls every 5 minutes while it is the active route.

It is **not** a distributed-trace / span-waterfall inspector. The RAG API has no `/tracking/*` routes at all: `create_app()` registers only health, search, retrieve, rerank, generate, chat, evaluate, prompts, guardrails, guardrails-evaluate and knowledge routers (`rag_api/main.py:71-81`). Message-level pipeline trace data is persisted in Postgres and read back through the chat endpoints (section 4); the OpenTelemetry side is export-only to the collector (section 5).

---

## 2. Data Sources & Endpoints

| UI area | Endpoint called | Client function | Base URL |
|---|---|---|---|
| Summary cards, "File Ingestion Runs" tab | `GET /api/pipelines/runs?limit=100` | `listAllPipelineRuns(100)` (`frontend/src/api.ts:453-455`) | `VITE_API_URL`, default `http://localhost:8007` (`api.ts:3`) — the ingestion manager |
| "Crawl Jobs" tab | `GET /crawls?limit=50` | `listScraperCrawls(50)` (`api.ts:503-505`) | `VITE_SCRAPER_URL`, default `http://localhost:8000` (`api.ts:4`) |
| "Scrape Jobs" tab | `GET /scrapes?limit=50` | `listScraperScrapes(50)` (`api.ts:507-509`) | `VITE_SCRAPER_URL`, default `http://localhost:8000` |

Scraper calls use the `X-API-Key` header with `VITE_SCRAPER_API_KEY` (`api.ts:5-8, 459-470`); ingestion calls use `VITE_API_KEY` (`api.ts:12-13, 51-58`). The page never touches the RAG API (`VITE_RAG_API_URL`, default `http://localhost:8001`, `api.ts:5`) — the trace data described in section 4 is served by that API but is not rendered here.

Load behaviour (`TrackingPage.tsx:41-89`):

- `loadRuns`, `loadCrawls`, `loadScrapes` each run on mount and on a `setInterval` of 300000 ms, but only while `location.pathname === "/tracking"` (persistent-mount pages stay mounted behind other routes).
- Each loader keeps its own error state: a pipeline-run failure renders an error alert, a crawl/scrape failure renders the warning `Scraper API: <message>. Make sure the scraper service is running at <VITE_SCRAPER_URL>` (`TrackingPage.tsx:266-268, 352-355`).

---

## 3. What the Page Displays

```
+-----------------------------------------------------------------------------------------------+
|  Pipeline Tracking                                            [ Refresh ]                      |
|  Monitor document ingestion status and web scraper job history.                               |
+-----------------------------------------------------------------------------------------------+
|  Total runs | Active | Completed | Failed | Crawl jobs | Scrape jobs                           |
+-----------------------------------------------------------------------------------------------+
|  [ File Ingestion Runs (n) ] [ Crawl Jobs ] [ Scrape Jobs ]                                   |
|  Pipeline            | Status    | Files | Pages | Points | Scraper job | Started | Completed |
|  name / description  | pending   | 8/10  | 142   | 980    | job id ab…   | 5m ago  | —         |
|  collection          | processing|       |       |        |              |         |           |
|  ...failure rows are tinted red, per-run error_message printed as alert blocks...              |
+-----------------------------------------------------------------------------------------------+
|  Crawl Jobs: ID | Seed URL | Status | Mode | Pages crawled | Total links | Markdown | Image |   |
|              Error                                                                            |
|  Scrape Jobs: same panel pattern                                                              |
+-----------------------------------------------------------------------------------------------+
```

- Summary card counters (`TrackingPage.tsx:110-136`): `runs.length`, active = `status === "pending" || status === "processing"`, completed = `status === "completed" || status === "success"`, failed = `status === "failed"`, plus `crawls.length` and `scrapes.length`.
- Tab badges: the "File Ingestion Runs" tab shows the active-run count (`TrackingPage.tsx:139-161`).
- Ingestion table columns (`TrackingPage.tsx:192-235`): Pipeline (name, description, `qdrant_collection`), Status badge, Files `files_processed/files_total`, Pages (`pages_indexed`), Points (`points_upserted`), Scraper job (`scraper_crawl_job_id`, truncated), Started / Completed relative timestamps. Rows are tinted for `failed` and `processing`.
- Crawl table columns (`TrackingPage.tsx:278-345`): ID, Seed URL (link), Status, Mode, Pages crawled (`result.pages_crawled`), Total links (`result.total_links`), Markdown ingested, Image ingested, Error message.
- Empty states: "No pipeline runs yet. Go to Pipelines to start one." (`:187`), "No crawl jobs found in the scraper service." (`:272`), "No scrape jobs found. Start a pipeline with web scraping enabled." (`:359`).
- Nothing on this page renders spans, trace trees, TTFT, token counts or retrieved-chunk payloads.

---

## 4. Trace Persistence & Retrieval (chat path)

Traces are stored as rows, not as an OpenTelemetry span tree.

**Model** — `ChatPipelineTrace`, table `chat_pipeline_traces` (`libs/database/src/rag_db/models/chat.py:39-61`). One row per assistant message (`chat_message_id` is unique):

| Column | Type | Meaning |
|---|---|---|
| `query` | Text | user question |
| `retrieval_mode` | String | e.g. `hybrid` |
| `retrieve_limit` | Integer | candidate count requested |
| `rerank_enabled` | Boolean | reranker on/off |
| `rerank_model` | String, nullable | reranker model id |
| `generation_model` | String, nullable | generation model id |
| `retrieved_chunks` | JSONB list | pre-rerank chunks |
| `reranked_chunks` | JSONB list | post-rerank chunks |
| `latency_ms` | JSONB dict | per-stage timings and route flags |
| `created_at` | timestamp | row creation |

**Write path** — `ChatRepository.save_pipeline_trace` (`libs/database/src/rag_db/repositories/chat_repository.py:42-70`), called from `_persist_chat_turn` (`rag_api/routes/chat.py:231-290`, call site `:270`) for both `/chat` and `/chat/stream`. Normal turns and guardrail-blocked turns (persisted with a `route: "blocked"` latency payload, `chat.py:403-404, 554-555`) both get a trace row; the streaming greeting shortcut passes `save_trace=False` and therefore stores no trace (`chat.py:611`).

**Read path** — `get_trace_for_message`, `list_session_messages` (outer-joins trace and metrics), `list_recent_metrics_stats` (`chat_repository.py:110-115, 157-179`).

**HTTP exposure** (read-only, no span hierarchy, no raw payload dump):

| Method | Endpoint | Returns | Evidence |
|---|---|---|---|
| `GET` | `/chat/sessions/{session_id}/messages` | per message: `trace {retrieval_mode, rerank_enabled, generation_model, route}`, `sources [{source_locator, chunk_index, rerank_score}]` derived from `reranked_chunks`, `metrics_status`, `blocked` / `blocked_by_guard` / `blocked_on` | `chat.py:848-886` |
| `GET` | `/chat/messages/{message_id}/metrics` | staged metrics (`retrieval` / `reranker` / `generation`) plus flat `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall`, `kendall_tau`, `mrr`, `ndcg` | `chat.py:764-800` |
| `GET` | `/chat/stats` | recent assistant messages with metrics and trace config (incl. `latency_ms`) | `chat.py:802-820` |
| `GET` | `/chat/sessions` | session list with message counts and preview | `chat.py:822-846` |

`route` is read out of `latency_ms["route"]` (`chat.py:680, 862-864`); its documented values are `normal`, `self_corrective`, `self_corrective_auto`, `greeting`, `blocked` (`chat.py:102`).

**`latency_ms` keys actually written**: `retrieve`, `rerank` (`libs/rag-core/src/rag_core/pipeline.py:66-72, 102-107`), `generate_text` / `generate_vision` / `generate_fusion`, `generate_total` (`libs/generation-core/src/generation_core/generator.py:112-143`), `generate` and `total` (`pipeline.py:118-119`), plus `route` (`chat.py:680`) and `blocked`, `blocked_by_guard`, `blocked_on` (`chat.py:142-150`). No first-token / TTFT key and no per-stage span hierarchy are recorded anywhere.

---

## 5. OpenTelemetry Export Configuration

Traces are emitted by the backend process and shipped over OTLP/HTTP to the collector; the collector fans out to Langfuse, Arize AX and Grafana Cloud. Configuration is env-driven in `libs/shared/src/rag_shared/tracing.py:77-137`:

| Env var | Default | Effect |
|---|---|---|
| `OTEL_TRACING_ENABLED` | `"true"` | `"false"` disables the provider; a plain tracer is still returned |
| `OTEL_SERVICE_NAME` | `"rag-platform"` | tracer name and `service.name` resource attribute |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `"http://otel:4318"` | OTLP HTTP base; `/v1/traces` is appended unless already present (`tracing.py:69-74`) |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | unset | overrides the base endpoint verbatim |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | comma-separated `key=value` pairs; values are URL-decoded (`tracing.py:57-66`) |
| `OTEL_CONSOLE_EXPORT` | `"false"` | adds a `SimpleSpanProcessor(ConsoleSpanExporter())` |
| `OTEL_RESOURCE_ATTRIBUTES` | unset | comma-separated resource attributes; when empty, `deployment.environment` and `service.namespace` defaults are applied |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | `"production"` | resource attribute default |
| `OTEL_SERVICE_NAMESPACE` | `"rag-platform"` | resource attribute default |
| `ARIZE_MODEL_ID`, `ARIZE_PROJECT_NAME` | service name / unset | Arize requires `model_id` or `arize.project.name` on the resource; both are injected (`tracing.py:39-48`) |

- Exporter: `OTLPSpanExporter` from `opentelemetry.exporter.otlp.proto.http.trace_exporter`, batched via `BatchSpanProcessor` (`tracing.py:106-116`).
- Outbound HTTP is auto-instrumented with `HTTPXClientInstrumentor().instrument()` when the package is installed, so LiteLLM/Qdrant calls appear as child spans only when a parent span is active (`tracing.py:126-127`).
- `force_flush(timeout_millis=10_000)` is called at the end of chat turns and by `emit_rag_pipeline_trace(..., flush=True)` so RQ workers push spans before moving on (`tracing.py:142-151, 206-266`).
- **No sampler is configured**: there is no `OTEL_TRACES_SAMPLER` handling in `tracing.py`, so the SDK default parent-based always-on sampler applies and every created span is exported.

**Spans actually emitted by application code:**

| Span name | Where | Notes |
|---|---|---|
| `rag.chat` | `rag_api/routes/chat.py:367` | wraps retrieve → rerank → generate for `POST /chat` |
| `rag.chat.stream` | `chat.py:579` (greeting shortcut), `chat.py:636` (main stream path) | wraps the SSE generation path |
| `rag.pipeline` | `tracing.py:234` via `emit_rag_pipeline_trace` | synthetic post-hoc span emitted by the eval worker after metrics |

Attributes set on these spans (`tracing.py:164-204, 236-262`): Langfuse-recognized keys `langfuse.observation.type`, `langfuse.session.id`, `langfuse.observation.metadata.message_id`, `langfuse.trace.input` / `langfuse.observation.input` / `input.value`, `langfuse.trace.output` / `langfuse.observation.output` / `output.value`, `langfuse.observation.model.name`, `gen_ai.request.model`, `langfuse.observation.metadata.<key>`; plus `rag.query_length`, `rag.output_length`, `rag.chunks_used`, `rag.retrieval_mode`, `rag.rerank_enabled`, `rag.generation_model`, `latency.<key>` and `eval.<metric>`. There are no application spans for individual retrieval, rerank, prompt-assembly, guardrail or token-streaming stages.

---

## 6. Collector Configuration (`otel/`)

`otel/otel-collector-config.yaml`:

- **Receivers**: `otlp` on gRPC `0.0.0.0:4317` and HTTP `0.0.0.0:4318`.
- **Processors**: `memory_limiter` (512 MiB limit, 128 MiB spike), `resource` (upserts `model_id`, `arize.project.name`, `deployment.environment`, `service.namespace`), `batch` (256 spans, 5 s timeout).
- **Exporters**: `debug`, `otlp_http/langfuse` (OTLP/HTTP with `Authorization` and `x-langfuse-ingestion-version: "4"`), `otlp_grpc/arize` (OTLP/gRPC with `api_key` and `space_id`), `otlp_http/grafana` (OTLP/HTTP gateway).
- **Pipelines**: `traces` → `debug`, Langfuse, Arize, Grafana; `metrics` and `logs` → `debug` and Grafana only (Langfuse/Arize accept traces only).
- All exporter credentials come from environment variables; the template values live in `otel/.env` (`OTEL_LOG_LEVEL`, `OTEL_DEBUG_VERBOSITY`, `OTEL_DEPLOYMENT_ENVIRONMENT`, `OTEL_SERVICE_NAMESPACE`, `LANGFUSE_OTLP_ENDPOINT`, `LANGFUSE_AUTH_HEADER`, `ARIZE_OTLP_ENDPOINT` = `otlp.arize.com:443`, `ARIZE_API_KEY`, `ARIZE_SPACE_ID`, `ARIZE_MODEL_ID`, `ARIZE_PROJECT_NAME`, `GRAFANA_OTLP_ENDPOINT`, `GRAFANA_AUTH_HEADER`). `otel/.env.example` documents the same keys.

The collector exposes no query API back to the UI; the operator reads traces in Langfuse / Arize / Grafana, not in the Tracking page.
