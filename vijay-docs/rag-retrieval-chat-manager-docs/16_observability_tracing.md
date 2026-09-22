# 16 — Observability and Tracing

**Last updated:** 2026-09-22

**Covers:** the OTEL collector fan-out, the `test` and `prod` trace modes, the individual
turn trace, the session trace, and how to add a platform.
**Files:** `otel/otel-collector-config.yaml`, `otel/.env`, `libs/shared/src/rag_shared/tracing.py`,
`apps/rag-api/src/rag_api/routes/chat.py`, `apps/eval-worker/src/eval_worker/tasks.py`.

## 1. The shape

```
                 ┌──────────────────────┐
  Chat page ────▶│ rag-api :8001        │
                 │  X-RAG-Trace-Mode:   │
                 │  test                │
                 └──────────┬───────────┘
                            │ OTLP/HTTP :4318
  External  ────────────────┤
  caller                     ▼
  (no header)       ┌──────────────────────┐
                    │ otel-collector :4318 │
                    │  one traces pipeline │
                    │  two exporters       │
                    └────┬────────────┬────┘
                         │            │
                    Phoenix      Langfuse
```

The application never talks to Phoenix or Langfuse. It exports once, to the collector, and the
collector fans out. That is what makes a new platform a collector change and nothing else.

| Setting | Value | Where |
|---|---|---|
| Collector OTLP receiver | `:4317` gRPC, `:4318` HTTP | `otel-collector-config.yaml` |
| Application exporter target | `http://otel:4318` | `OTEL_EXPORTER_OTLP_ENDPOINT` in `backend/.env` |
| Credentials | `otel/.env` (gitignored) | `otel/.env.example` is the template |

## 2. Two trace modes

Every turn is tagged `test` or `prod`. The tag is a span attribute
(`deployment.environment` and `rag.trace_mode`) and a stored column
(`chat_pipeline_traces.trace_mode`).

| Mode | Set by | What it means |
|---|---|---|
| `test` | The Chat page sends `X-RAG-Trace-Mode: test` | A turn sent from the UI while trying a pipeline |
| `prod` | Anything without that header | A real caller hitting the callable endpoint |

The Chat page and an external caller hit **the same route**
(`POST /api/assistants/{slug}/chat/stream`), so the header is the only thing that separates
them. A request without it is production, which is the safe default: an integrator who has
never heard of the header cannot accidentally label real traffic as a test.

`normalize_trace_mode()` accepts `test` in any case, with surrounding whitespace, and maps
everything else to `prod`.

## 3. The individual turn trace

Every pipeline gets one trace per Q/A turn, with no configuration. The root span is
`rag.chat` or `rag.chat.stream`, and it carries:

| Attribute | Value |
|---|---|
| `input.value` / `output.value` | The question and the answer. OpenInference keys, read by Phoenix |
| `langfuse.trace.input` / `.output` | The same two, for Langfuse |
| `langfuse.observation.type` | `generation` |
| `openinference.span.kind` | `CHAIN` |
| `deployment.environment`, `rag.trace_mode` | `test` or `prod` |
| `session.id`, `langfuse.session.id` | The session, when one exists |
| `rag.message_id` | The stored assistant message id |
| `gen_ai.request.model` | The chat model |

Child spans come free: `opentelemetry-instrumentation-httpx` is installed, so every outbound
call to LiteLLM, Qdrant and OpenSearch nests under the turn automatically.

### The metrics span is a child, not a second trace

The metrics worker runs later, in a different process, once the RAGAS scores are computed. It
used to open its own root span, which made **one question appear twice** in both backends.

The turn now stores its own `otel_trace_id` and `otel_span_id`, and the worker parents its
`rag.pipeline.metrics` span under them. One turn stays one trace, and the scores sit inside
the turn they belong to.

The columns were added in migration `004`. A turn stored before that migration has no ids, and
the worker falls back to opening its own trace, because there is nothing to join.

## 4. The session trace

A pipeline whose Knowledge Product has the Redis destination enabled gets a **second** trace
holding every Q/A of the session.

A session runs across many HTTP requests, so its trace cannot be one open span. Instead the
trace id is **derived from the session UUID**:

```
trace_id = session_uuid.bytes          (16 bytes, printed as 32 hex chars)
root_id  = session_uuid.bytes[:8]      (8 bytes, printed as 16 hex chars)
```

Every turn parents its span under that fixed `root_id`, so all of them land in one trace. The
derivation is pure arithmetic, so the same session id yields the same two numbers in every
process, with no shared state anywhere.

**No span is emitted for `root_id`.** It would have to be emitted on every turn, because no
process knows whether it is the first, and the same span id would then be written repeatedly.
Both Langfuse and Phoenix group by trace id and treat a missing parent as a root, so the turns
appear as the roots of the session trace.

A turn that joins a session trace also carries `rag.session_trace: true`, so a reader can tell
the two traces of a session turn apart without knowing the session id.

| Pipeline | Traces per turn |
|---|---|
| No Redis destination | 1 — the individual turn |
| Redis destination enabled | 2 — the individual turn, and the turn inside its session trace |

A session id that is not a UUID cannot produce a stable trace id, so it gets no session trace.
That is the only case where the feature silently does nothing.

## 5. Adding a platform

Three steps, all in `otel/otel-collector-config.yaml`.

1. Add an exporter. Worked examples for Arize AX (gRPC, `api_key` + `space_id`) and Grafana
   Cloud (OTLP/HTTP, Basic auth) sit commented in the file.
2. Add its credentials to `otel/.env`, and to `otel/.env.example` with a placeholder.
3. Name it in the `traces` pipeline's `exporters` list.

One pipeline with several exporters is enough: each exporter receives its own copy of the
span, so no backend can affect what another sees. Separate pipelines are only needed when one
of them must **modify** spans, because a processor mutation is visible to every pipeline
sharing that span.

### Reference: the two active backends

| | Phoenix | Langfuse |
|---|---|---|
| Transport | OTLP/HTTP | OTLP/HTTP (no gRPC support) |
| Endpoint | `https://app.phoenix.arize.com/v1/traces` | `https://jp.cloud.langfuse.com/api/public/otel` |
| Auth header | `Authorization: Bearer <api key>` | `Authorization: Basic base64(public:secret)` |
| Extra | `x-project-name` routes to a project (HTTP only) | `x-langfuse-ingestion-version: 4` |
| Self-hosted | `http://localhost:6006/v1/traces`, no auth | n/a |

The Langfuse region must match `LANGFUSE_BASE_URL` in the backend's `.env.langfuse`. The wrong
region sends traces to a different project, and nothing reports an error.

## 6. Real Time Monitoring

The page at `/evaluations` reads `GET /chat/stats` and lists one row per Q/A turn.

- Each row carries a `test` or `prod` tag next to its message id. The tag is two-toned as well
  as two-worded, so the modes are distinguishable at a glance. A row written before migration
  `004` has no mode and shows no tag, rather than a guess.
- `Open Langfuse` and `Open Phoenix` sit in the page header. They read
  `VITE_LANGFUSE_TRACES_URL` and `VITE_PHOENIX_URL`, and fall back to the public cloud
  landing pages when unset.

Set them to a deep link to be taken straight to the traces:

```
VITE_LANGFUSE_TRACES_URL=https://jp.cloud.langfuse.com/project/<project-id>/traces
VITE_PHOENIX_URL=https://app.phoenix.arize.com/s/<space>/projects/<project-id>
```

## 7. Failure behaviour

Tracing never fails a turn. A missing collector, a rejected credential or a full queue costs
traces, not answers.

| Failure | Behaviour |
|---|---|
| `OTEL_TRACING_ENABLED=false` | Spans are created but never exported |
| The collector is down | The batch processor retries, then drops. The answer is unaffected |
| A backend rejects the auth | The collector logs it and retries that exporter alone. The other backend still receives the span |
| A turn has no OTEL ids | The metrics worker opens its own trace, as before migration `004` |
| A session id is not a UUID | No session trace. The individual turn trace is unaffected |

## 8. Verification

- `tests/unit/test_tracing.py` — 16 tests against an in-memory span exporter, so they assert
  what actually reaches the collector: the mode tag, the two-turn session sharing one trace id,
  separate traces when there is no session, two sessions not colliding, the metrics span joining
  the turn, and the non-UUID fallback.
- `tests/unit/test_session_memory.py` — 14 tests against a live Redis.
- `tests/unit/test_prompt_builder.py` — 5 tests, including the history placement the session
  replay depends on.
- The collector's own log is the check that fan-out works. Set `OTEL_DEBUG_VERBOSITY=detailed`
  in `otel/.env` to log every span and attribute it exports.
