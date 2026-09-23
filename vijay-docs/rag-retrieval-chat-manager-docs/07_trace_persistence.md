# 07 — Trace Persistence and OTLP Export

**Last updated:** 2026-09-23

## 1. What this document covers

Traces are stored in Postgres as rows, not as an OpenTelemetry span tree, and the OpenTelemetry
side is export-only. Those two halves are what this document describes.

> **The Tracking page was removed on 2026-09-23.** It was a read-only operational monitor that
> listed ingestion pipeline runs, scraper crawl jobs and scraper scrape jobs, and its route was
> `/tracking`. It is gone from the retrieval frontend: the nav item, the route, the page
> component, its icon, its styles and the scraper API client it was the only user of. The
> ingestion frontend keeps its own unused copy of `TrackingPage.tsx`; nothing mounts it.
>
> What the page read is unchanged and still reachable elsewhere: pipeline runs come from
> `GET /api/pipelines/runs` on the ingestion manager, and the crawl and scrape jobs come from the
> web-scraper API on port 8000. Neither is rendered anywhere in the retrieval frontend now.

---

## 2. Trace Persistence & Retrieval (chat path)

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

## 3. OpenTelemetry Export Configuration

Traces are emitted by the backend process and shipped over OTLP/HTTP to the collector; the collector fans out to **Phoenix and Langfuse**. The application picks no backend: it exports once and the collector copies the span to each. Configuration is env-driven in `libs/shared/src/rag_shared/tracing.py:77-137`:

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

Backend credentials for a backend are **not** read here. They live in `otel/.env`, which the collector reads. See Section 4.

- Exporter: `OTLPSpanExporter` from `opentelemetry.exporter.otlp.proto.http.trace_exporter`, batched via `BatchSpanProcessor` (`tracing.py:106-116`).
- Outbound HTTP is auto-instrumented with `HTTPXClientInstrumentor().instrument()` when the package is installed, so LiteLLM/Qdrant calls appear as child spans only when a parent span is active (`tracing.py:126-127`).
- `force_flush(timeout_millis=10_000)` is called at the end of chat turns and by `emit_rag_pipeline_trace(..., flush=True)` so RQ workers push spans before moving on (`tracing.py:142-151, 206-266`).
- **No sampler is configured**: there is no `OTEL_TRACES_SAMPLER` handling in `tracing.py`, so the SDK default parent-based always-on sampler applies and every created span is exported.

**Spans actually emitted by application code:**

| Span name | Where | Notes |
|---|---|---|
| `rag.chat` | `rag_api/routes/chat.py:425` | wraps retrieve → rerank → generate for `POST /chat` and for the assistant routes that delegate to it |
| `rag.chat.stream` | `chat.py:602` region (greeting shortcut and the main stream path) | wraps the SSE generation path |
| `rag.pipeline.metrics` | `tracing.py:382` via `emit_rag_pipeline_trace` | emitted by the eval worker after metrics. It is **parented under the turn's own span**, so one question stays one trace |

### Session traces

A pipeline whose product has the Redis destination enabled files each turn into a **second** trace holding every Q/A of the session. The trace id is derived from the session UUID, so it is stable across processes without shared state (`session_trace_ids`, `tracing.py:91`). A turn that joins a session trace also carries `rag.session_trace: true`. A pipeline without Redis gets one trace per turn. Full detail: [16 — Observability and Tracing](./16_observability_tracing.md).

### Test and production turns

Every turn is tagged `test` or `prod` from the `X-RAG-Trace-Mode` request header (`TRACE_MODE_HEADER`, `tracing.py:81`). Only the exact value `test`, ignoring case and surrounding space, sets a test turn; **a request without the header is production**, which is the safe default. The mode is written to the span as `deployment.environment` and `rag.trace_mode`, and to the `chat_pipeline_traces.trace_mode` column that the Real Time Monitoring page tags each log with.

Attributes set on these spans (`tracing.py:218-258, 393-413`): Langfuse-recognized keys `langfuse.observation.type`, `langfuse.session.id`, `langfuse.observation.metadata.message_id`, `langfuse.trace.input` / `langfuse.observation.input` / `input.value`, `langfuse.trace.output` / `langfuse.observation.output` / `output.value`, `langfuse.observation.model.name`, `gen_ai.request.model`, `langfuse.observation.metadata.<key>`; the OpenInference keys Phoenix reads, `openinference.span.kind` (`CHAIN`) and `input.value` / `output.value`; plus `deployment.environment`, `rag.trace_mode`, `rag.session_trace`, `session.id`, `rag.message_id`, `rag.query_length`, `rag.output_length`, `rag.chunks_used`, `rag.retrieval_mode`, `rag.rerank_enabled`, `rag.generation_model`, `latency.<key>` and `eval.<metric>`. There are no application spans for individual retrieval, rerank, prompt-assembly, guardrail or token-streaming stages. Outbound HTTP calls to LiteLLM, Qdrant and OpenSearch do nest under the turn automatically, through the httpx instrumentation.

---

## 4. Collector Configuration (`otel/`)

`otel/otel-collector-config.yaml`:

- **Receivers**: `otlp` on gRPC `0.0.0.0:4317` and HTTP `0.0.0.0:4318`.
- **Processors**: `memory_limiter` (512 MiB limit, 128 MiB spike), `resource` (upserts `deployment.environment` and `service.namespace`), `batch` (256 spans, 5 s timeout).
- **Exporters**: `debug`, `otlp_http/langfuse` (OTLP/HTTP with `Authorization` and `x-langfuse-ingestion-version: "4"`), `otlp_http/phoenix` (OTLP/HTTP with `Authorization` and `x-project-name`).
- **Pipelines**: `traces` → `debug`, Langfuse, Phoenix. `metrics` and `logs` go to `debug` only, because neither backend accepts them and a failing export would otherwise trip the collector.
- All exporter credentials come from `otel/.env` (`OTEL_LOG_LEVEL`, `OTEL_DEBUG_VERBOSITY`, `OTEL_DEPLOYMENT_ENVIRONMENT`, `OTEL_SERVICE_NAMESPACE`, `LANGFUSE_OTLP_ENDPOINT`, `LANGFUSE_AUTH_HEADER`, `PHOENIX_OTLP_ENDPOINT`, `PHOENIX_API_KEY`, `PHOENIX_PROJECT_NAME`). `otel/.env.example` documents the same keys with placeholders, and `otel/.env` itself is gitignored.
- Arize AX and Grafana Cloud are kept as **commented worked examples** in the file. Arize is a different product from Phoenix: gRPC, authenticated with `api_key` and `space_id` rather than a bearer token. Adding a platform is a collector change and nothing else.

The collector exposes no query API back to the UI; the operator reads traces in Phoenix or Langfuse. The Real Time Monitoring page links out to both.
