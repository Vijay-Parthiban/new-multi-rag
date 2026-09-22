# Overall Architecture — RAG Retrieval & Chat Manager

**Last updated:** 2026-09-20

## 1. System Overview
`rag-retrieval-chat-manager` is the query, retrieval, rerank, generation, guardrail, and evaluation service of the `new-multi-rag` ecosystem. It reads the shared Qdrant collection written by `web-scrapper-workspace` / `rag-ingestion-manager`, reranks hits with a LiteLLM-hosted cross-encoder, generates answers with LiteLLM chat/vision models, delegates safety checks to the external guardrails service, and runs Ragas-based evaluation both online (per chat message) and offline (golden datasets).

Repository layout:
- `backend/` — uv workspace, Python >= 3.12: `libs/*` (7 libraries) + `apps/rag-api` (HTTP API) + `apps/eval-worker` (RQ worker).
- `frontend/` — Vite 6 + React 19 single-page app (`frontend/package.json`).

---

## 2. Runtime Topology

```
+--------------------------------------------------------------------------+
|  Frontend: Vite / React — dev port 5174 (frontend/vite.config.ts)        |
|  api.ts API_URL      -> http://localhost:8007  (rag-ingestion-manager)   |
|  api.ts RAG_API_URL  -> http://localhost:8001  (this service)            |
|  api.ts SCRAPER_URL  -> http://localhost:8000  (web-scrapper API)        |
+---------------------------------+----------------------------------------+
                                  | HTTP  (X-API-Key header or ?api_key=)
                                  v
+--------------------------------------------------------------------------+
|  rag-api  (uvicorn rag_api.main:app) — port 8001                         |
|  FastAPI "RAG Platform API" 0.1.0, app-level verify_api_key dependency    |
|  app.state: settings, pipeline, retriever, generator, queue               |
|  routers: health, search, retrieve, rerank, generate, chat, evaluate,     |
|           prompts, guardrails, guardrails_evaluate, knowledge (proxy)     |
+----+----------------------+-----------------------+-----------------+-----+
     |                      |                       |                 |
     v                      v                       v                 v
 Qdrant :6333        LiteLLM proxy :4000      guardrails-service   Redis :6379/0
 scrape_embeddings   embeddings / rerank /    POST /validate       RQ queue "eval"
 dense + sparse      chat / vision models     (compose maps 18000)
 named vectors, RRF                                              |
     ^                      ^                                    v
     |                      |                       +----------------------------+
+----+----------------------+--------------------+  | eval-worker: rq worker     |
| Postgres :5432 database "rag" (SQLAlchemy)      |  | "eval" (run-worker.sh)     |
| chat, evaluation, guardrails tables (rag_db)    |  | tasks.compute_chat_metrics |
+-------------------------------------------------+  | tasks.run_evaluation       |
                                                     +----------------------------+
```

## 3. Processes, Ports, Entrypoints

| Process | Entrypoint | Port | Notes |
|---|---|---|---|
| rag-api | `rag_api.main:run` → `uvicorn rag_api.main:app` | 8001 (`API_PORT`) | compose maps `8001:8001` |
| eval-worker | `eval_worker.main:run` → `rq worker eval` | none | Consumes RQ queue `eval`; `rq_eval_queue` default `redis://…/0` |
| migrate | `rag-db-migrate` (`rag_db.migrate:main`) | none | Runs Alembic to head before api/worker start. Resolves `libs/database` via `/app/libs/database` in Docker, else `parents[2]` of `migrate.py` |
| frontend (dev) | `vite --force` | 5174 | `frontend/vite.config.ts`. No dev proxy: the browser calls 8001 and 8007 directly, so those APIs must send CORS headers |
| Postgres (rag DB) | container `postgres` | 5432 | database `rag`, role `crawler` |
| Redis | container `redis` | 6379 | RQ queue `eval` only; db 0 |
| Qdrant | container | 6333 | `qdrant_url`; holds `scrape_embeddings`, written by the scraper |
| Qdrant (knowledge products) | container | **6335** | `qdrant_kp_url`; holds every `kp_*` collection the assistants and the KP readers use. A separate server from the 6333 instance. |
| LiteLLM proxy | host process | 4000 | `litellm_base_url` — embeddings, rerank, chat, vision |
| guardrails-service | `guardrails-service/server.py` | 18000 → 8000 | compose maps `18000:8000`. `settings.guardrails_url` defaults to `http://localhost:18000`, so a host run needs no override |
| web-scrapper API | `web-scrapper-workspace` | 8000 | `SCRAPER_URL`; source of the crawl/scrape jobs the Tracking page lists |
| rag-ingestion-manager | external | 8007 | Knowledge Products proxy target |
| otel-collector | container `otel` | 4317 / 4318 | OTLP; absent from a native run, so set `OTEL_TRACING_ENABLED=false` |

### 3.1 Local (non-Docker) run

The Docker images need `rag-app-workspace/`, which no longer exists, so the services run natively. `backend/.env` holds Docker service hostnames (`postgres`, `redis`, `qdrant`), so pass host overrides as process environment — a real env var beats the `.env` file in pydantic-settings.

```bash
cd rag-retrieval-chat-manager/backend
uv sync --all-packages                      # required: uv sync alone installs only the root

# Prerequisites, once: a `rag` database and a `crawler` role in the running Postgres.
DATABASE_URL="postgresql+psycopg://crawler:crawler@localhost:5432/rag" uv run rag-db-migrate

DATABASE_URL="postgresql+psycopg://crawler:crawler@localhost:5432/rag" \
REDIS_URL="redis://localhost:6379/0" \
QDRANT_URL="http://localhost:6333" \
QDRANT_KP_URL="http://localhost:6335" \
OPENSEARCH_URL="http://localhost:9200" \
INGESTION_SERVICE_URL="http://localhost:8007" \
INGESTION_DATABASE_URL="postgresql://ingestion:ingestion@localhost:5432/ingestion" \
GUARDRAILS_URL="http://localhost:18000" \
LITELLM_BASE_URL="http://localhost:4000" \
EMBEDDING_MODEL="nvidia-embed-textonly" \
OTEL_TRACING_ENABLED=false \
  uv run uvicorn rag_api.main:app --host 0.0.0.0 --port 8001

# eval worker, same env. SimpleWorker is required on Windows: the default worker
# calls os.fork, which Windows does not have, and dies when a metrics job arrives.
uv run rq worker eval --url redis://localhost:6379/0 --worker-class rq.worker.SimpleWorker

# frontend — no .env needed; api.ts defaults to 8007 and 8001
cd ../frontend && node node_modules/vite/bin/vite.js --force --host 0.0.0.0 --port 5174
```

`QDRANT_KP_URL` is the one omission that reads as a code bug. The knowledge product collections live on
6335, not on `qdrant_url` (6333). Leave it unset and the readers fall back to 6333, find zero points, and
every assistant answers "I could not find any relevant sources".

`npx vite` cannot spawn on Windows (`os error 193`), so call the vite entry script through `node` directly.

Auth: the app registers `dependencies=[Depends(verify_api_key)]` (`apps/rag-api/src/rag_api/main.py:62`); `verify_api_key` comes from `platform_common.auth` and accepts `X-API-Key` or the `api_key` query parameter, and is a no-op when `api_key` is empty (`rag_shared/config.py:51`).

## 4. Modular Library Decomposition (`backend/libs/`)

| Library | Package | Contents |
|---|---|---|
| `libs/rag-core` | `rag_core` | `RAGPipeline` orchestrator (`pipeline.py`: retrieve / rerank / chat / generate / stream_chat / from_request), request + result schemas plus `StreamEvent` (`schemas.py`), knowledge product strategy resolution (`assistant.py`), pipeline prompts (`prompts.py`) |
| `libs/vector-core` | `vector_core` | Qdrant dense+sparse access (`qdrant_store.py`, `search.py`), LiteLLM embeddings (`embedding_client.py`), sparse BM25 encoder (`sparse_client.py`), vision payload client (`vision_client.py`), payload filters and hit mapping, OpenSearch BM25 reader (`lexical.py`), pgvector reader and reciprocal rank fusion (`relational.py`) |
| `libs/retrieval-core` | `retrieval_core` | `Retriever` mode/limit resolution and strategy dispatch (`retriever.py`), knowledge product strategy readers (`kp_retriever.py`), `chunk_from_search_hit` (`hit_mapper.py`) |
| `libs/reranker-core` | `reranker_core` | `Reranker` protocol, `LiteLLMReranker` (LiteLLM `POST /v1/rerank`), `NoopReranker` pass-through, `build_reranker` factory |
| `libs/generation-core` | `generation_core` | `Generator` (text) + `VisionGenerator` + fusion, token streaming (`generate_stream`), prompt assembly with an optional system-message override (`prompt_builder.py`), prompt loading with overrides (`prompts.py`), `GenerationResult` |
| `libs/eval-core` | `eval_core` | `GoldenItemEvaluator` (`runner.py`), Ragas client (`ragas_client.py`), chat/retrieval/rerank/generation metrics, guardrail eval runner, golden + guardrails dataset schemas |
| `libs/database` | `rag_db` | SQLAlchemy models (`models/chat.py`, `models/evaluation.py`, `models/guardrails.py`, `models/prompt.py`), repositories (including `prompt_repository.py`), session factory (`services/database.py`), Alembic runner (`migrate.py`) |
| `libs/shared` | `rag_shared` | Settings, API-key auth, OpenTelemetry tracing, guardrails HTTP client, prompt override store, logging |

Two shared packages are consumed from sibling workspaces: `platform_common` (auth, vector names) and `shared_contracts.knowledge` (Knowledge Product models used by the proxy).

## 5. Retrieval → Generation Pipeline (as implemented)

`routes/chat.py` → `RAGPipeline.chat()` → `RAGPipeline.rerank()` → `RAGPipeline.retrieve()`:

1. **Retrieve** — `RAGPipeline.retrieve()` (`libs/rag-core/src/rag_core/pipeline.py:27`) resolves the request config and calls `Retriever.retrieve()` (`libs/retrieval-core/src/retrieval_core/retriever.py:14`), which runs `search_scrape_chunks()` (`libs/vector-core/src/vector_core/search.py:17`).
   - `mode=dense` → LiteLLM dense embedding only; `mode=sparse` → sparse BM25 embedding only; `mode=hybrid` (default, `settings.default_retrieval_mode`) → both named vectors in one Qdrant query with RRF fusion.
   - Source filters: `source_type` (`all` / `web_scrape` / `file_ingest`) and `source_id`.
2. **Rerank** — `RAGPipeline.rerank()` (`pipeline.py:47`) builds a reranker via `build_reranker(settings, enabled=cfg.rerank_enabled, model=cfg.rerank_model)` and truncates to `cfg.top_k` (default 5). Disabled → `NoopReranker`. Latency captured as `retrieve`, `rerank`, `total` ms.
3. **Generate** — `RAGPipeline.chat()` (`pipeline.py:83`) calls `Generator.generate(query, reranked, model=…, vision_model=…, fusion_model=…)`, which builds the RAG prompt from reranked chunks, generates the text answer, generates a vision answer for image chunks (when present), and optionally fuses both. Result: `ChatResult` with `answer`, `text_answer`, `vision_answer`, chunk counts, and per-stage latency.
4. **Persist + enqueue** — `_persist_chat_turn()` (`routes/chat.py:231`) writes session/message/trace to Postgres and, when `ragas_enabled and chat_metrics_async`, creates a pending metrics row and enqueues `eval_worker.tasks.compute_chat_metrics` on the RQ `eval` queue (`routes/chat.py:285`).
5. **Offline evaluation** — `POST /evaluate/runs` persists a run and enqueues `eval_worker.tasks.run_evaluation` (`routes/evaluate.py:337`); the worker scores golden items with `GoldenItemEvaluator` and stores per-item metrics.

`POST /generate`, `POST /rerank`, `POST /retrieve` expose individual stages on the same pipeline.

### 5.1 The knowledge product path (assistants)

When the request carries a `strategy`, retrieval does not touch the scrape collection. `Retriever.retrieve()`
hands off to `KpRetriever` (`libs/retrieval-core/src/retrieval_core/kp_retriever.py`), which reads the store
the strategy names:

| Strategy | Reader | Store |
|---|---|---|
| `vector` | `search_scrape_chunks(mode="dense")` | Qdrant collection `config.collection_name` on `settings.qdrant_kp_url` |
| `lexical` | `search_lexical_index()` (`vector_core/lexical.py`) | OpenSearch index `config.index_name`, a `multi_match` on `content` and `text` |
| `relational` | `search_pgvector_chunks()` (`vector_core/relational.py`) | `<config.schema_name>.config.table_name` in `settings.ingestion_database_url`, cosine distance on `embedding` |
| `hybrid` | both `vector` and `lexical` | `reciprocal_rank_fusion()`, `k = 60`, fused on `(source_id, file_key, page_index, chunk_index)` |

Every reader returns the dict shape `chunk_from_search_hit` expects, so the rest of the pipeline —
rerank, generate, persist — is unchanged. Store resolution lives in
`libs/rag-core/src/rag_core/assistant.py`: `strategies_for_product()` reports what a product's enabled
destinations can serve, `stores_for_product()` reads the store names, and `resolve_strategy()` fails when a
store the strategy needs is absent. `cache_redisvl` serves no strategy, because it caches answers rather
than holding a searchable copy of the chunks.

The fanout writes Qdrant **dense only** (`enable_sparse=False` in `universal_fanout.py`), so no product
collection has sparse vectors and the Qdrant reader always runs `mode="dense"`. BM25 for a product lives
only in OpenSearch. That is also why `hybrid` means "Qdrant dense fused with OpenSearch BM25" on this
path, not the named-vector fusion the scrape path uses.

`RAGPipeline.stream_chat()` (`libs/rag-core/src/rag_core/pipeline.py`) yields `StreamEvent` objects for the
same retrieve → rerank → generate sequence, and `Generator.generate_stream()` yields the answer deltas.

## 6. Guardrails Integration Point

Guardrails are **not** implemented in-process: `routes/chat.py` `_run_guardrails()` (`routes/chat.py:295`) reads a `guardrails_configs` row through `GuardrailsRepository`, then calls `run_guardrails_check(text, cfg.guards, …, timeout_s, settings)` from `rag_shared/guardrails_client.py:11`, which POSTs the whole validator list to `{guardrails_url}/validate` in one call and treats a failed `validation_passed` as blocked.

- Input phase runs before `pipeline.chat()` (`routes/chat.py:380`); output phase runs after (`routes/chat.py:432`); config `mode` (`input` / `output`) selects which phase executes.
- A blocked turn returns canned copy from `GUARD_BLOCK_COPY` (ban list, PII, toxic language) with span attributes `guardrails.{phase}.blocked` / `blocked_by`, and a `guardrails_traces` row is recorded.
- `rag_shared/config.py` declares `guardrails_url` (default `http://localhost:18000`) and `guardrails_timeout_s`, so the client and the chat path read the same values. The client maps a config guard id such as `ban_list` to the service name `ban-list`; without that mapping every check returned 404 and the client read a non-200 as "passed", so no guard ever blocked a turn.
- Guardrail golden-dataset evaluation (`routes/guardrails_evaluate.py`) reuses the same client against the same service.

## 7. Persistence (`rag_db`)

Postgres, SQLAlchemy 2.x via `get_session_factory()` (`libs/database/src/rag_db/services/database.py:14`), `database_url` default `postgresql+psycopg://crawler:crawler@postgres:5432/rag` (`rag_shared/config.py:15`). Tables:

| Area | Tables | Model |
|---|---|---|
| Chat | `chat_sessions`, `chat_messages`, `chat_pipeline_traces`, `chat_message_metrics` | `libs/database/src/rag_db/models/chat.py:14,26,40,61` |
| Online/offline eval | `golden_datasets`, `golden_dataset_items`, `evaluation_runs`, `evaluation_run_items` | `.../models/evaluation.py:14,26,41,57` |
| Guardrails | `guardrails_configs`, `guardrails_traces`, `guardrails_golden_datasets`, `guardrails_golden_dataset_items`, `guardrails_eval_runs`, `guardrails_eval_run_items` | `.../models/guardrails.py:14,30,47,59,75,93` |
| Prompt templates | `prompt_templates` | `.../models/prompt.py` — the system message a pipeline can attach |

Repositories: `chat_repository.py`, `evaluation_repository.py`, `guardrails_repository.py`, `guardrails_evaluation_repository.py`, `prompt_repository.py`. Schema is versioned with Alembic (`rag_db.migrate:main`, CLI `rag-db-migrate`); head is `003_prompt_templates`. Redis holds only the RQ queue (`redis_url` default `redis://redis:6379/0`); there is no semantic cache layer.

Two points to know before you touch this layer:

- **`get_engine()` caches one engine per URL** (`libs/database/src/rag_db/services/database.py`). It used to call `create_engine()` on every request, which opened a fresh pool and abandoned the old one; the app drained Postgres `max_connections` (97 idle `crawler` connections) and every DB-backed endpoint then answered `500`. `@lru_cache` on the engine, plus `pool_size=5, max_overflow=10`.
- **The guardrails tables come from migration `002`, not `001`.** `001_initial_schema` predates the guardrails models, and `alembic/env.py` imported only `chat` and `evaluation`, so the six guardrails tables were never created and every guardrails page failed with "relation does not exist". `002` creates them from `Base.metadata`, so the columns cannot drift from `rag_db/models/guardrails.py`. Any new model module must be added to the `env.py` import list or it will be invisible to autogenerate.

## 8. Tracing & Observability

`init_tracing()` runs at process startup for both apps (`apps/rag-api/src/rag_api/main.py:44`, `apps/eval-worker/src/eval_worker/main.py:10`) and configures an OTLP HTTP exporter (`rag_shared/tracing.py`). The collector fans the traces out to Phoenix and Langfuse; the application names neither.

Chat spans are created with `rag_pipeline_span()` — `rag.chat` for `POST /chat` and for the assistant routes that delegate to it (`routes/chat.py:425`), `rag.chat.stream` for the streaming path (`chat.py:602` region) — and carry Langfuse-compatible attributes (`langfuse.trace.input/output`, `langfuse.session.id`, `langfuse.observation.metadata.*`), the OpenInference keys Phoenix reads (`openinference.span.kind`, `input.value`/`output.value`), plus `deployment.environment`, `rag.trace_mode`, `latency.*` and `rag.chunks_used`.

Every turn is tagged `test` or `prod` from the `X-RAG-Trace-Mode` request header, and **a request without the header is production**. The Chat page sets it, so a turn sent from the UI while trying a pipeline is a test turn; an integrator's caller never sets it. The mode is stored on the trace row and the Real Time Monitoring page tags each log with it.

A pipeline whose product has the Redis destination enabled also files each turn into a session trace whose id is derived from the session UUID, so every Q/A of a conversation sits in one trace. `emit_rag_pipeline_trace()` is used by the eval worker to emit the `rag.pipeline.metrics` span for background metric runs, **parented under the turn's own span** so one question produces one trace, and `force_flush()` drains spans before worker exit. Full detail: [16 — Observability and Tracing](./16_observability_tracing.md).

## 9. HTTP Endpoint Inventory

| Method | Path | Router |
|---|---|---|
| GET | `/health` | `routes/health.py:6` — returns only `{"status": "ok"}` |
| GET | `/search` | `routes/search.py:103` |
| POST | `/scrapes/query` | `routes/search.py:128` |
| POST | `/retrieve` | `routes/retrieve.py:37` (marked deprecated) |
| POST | `/rerank` | `routes/rerank.py:17` |
| POST | `/generate` | `routes/generate.py:22` |
| POST | `/chat` | `routes/chat.py:356` |
| POST | `/chat/stream` | `routes/chat.py:493` — SSE (`status` / `token` / `session` / `done` / `blocked` events) |
| GET | `/chat/messages/{message_id}/metrics` | `routes/chat.py:764` |
| GET | `/chat/stats` | `routes/chat.py:802` |
| GET | `/chat/sessions` | `routes/chat.py:822` |
| GET | `/chat/sessions/{session_id}/messages` | `routes/chat.py:848` |
| DELETE | `/chat/sessions/{session_id}` | `routes/chat.py:889` |
| DELETE | `/chat/messages/{message_id}` | `routes/chat.py:902` |
| POST | `/evaluate/datasets`, `/evaluate/datasets/upload` | `routes/evaluate.py:134,144` |
| GET | `/evaluate/datasets`, `/evaluate/datasets/{id}`, `/evaluate/datasets/{id}/runs` | `routes/evaluate.py:166,195,256` |
| DELETE | `/evaluate/datasets/{id}` | `routes/evaluate.py:215` |
| POST | `/evaluate/runs` | `routes/evaluate.py:319` |
| GET | `/evaluate/runs/{id}`, `/evaluate/runs/{id}/items` | `routes/evaluate.py:341,281` |
| GET | `/evaluate/stats` | `routes/evaluate.py:398` |
| GET | `/prompts` | `routes/prompts.py:163` |
| PUT | `/prompts` | `routes/prompts.py:187` |
| POST | `/prompts/reset` | `routes/prompts.py:196` |
| GET | `/prompts/{prompt_id}` | `routes/prompts.py:204` |
| PUT | `/prompts/{prompt_id}` | `routes/prompts.py:221` |
| POST | `/prompts/{prompt_id}/reset` | `routes/prompts.py:229` |
| GET | `/guardrails/guards` (proxies the service catalog) | `routes/guardrails.py:231` |
| GET | `/guardrails/on-fail-options` | `routes/guardrails.py:257` |
| POST | `/guardrails/configs` | `routes/guardrails.py:215` |
| GET | `/guardrails/configs`, `/guardrails/configs/{id}` | `routes/guardrails.py:244,257` |
| PUT / DELETE | `/guardrails/configs/{id}` | `routes/guardrails.py:271,306` |
| GET | `/guardrails/traces`, `/guardrails/stats` | `routes/guardrails.py:321,349` |
| POST | `/guardrails-evaluate/datasets`, `/guardrails-evaluate/datasets/upload` | `routes/guardrails_evaluate.py:153,139` |
| GET | `/guardrails-evaluate/datasets`, `/guardrails-evaluate/datasets/{id}/runs` | `routes/guardrails_evaluate.py:162,332` |
| DELETE | `/guardrails-evaluate/datasets/{id}` | `routes/guardrails_evaluate.py:184` |
| POST | `/guardrails-evaluate/runs` | `routes/guardrails_evaluate.py:197` |
| GET | `/guardrails-evaluate/runs/{id}`, `/guardrails-evaluate/runs/{id}/items` | `routes/guardrails_evaluate.py:307,365` |
| GET/POST | `/api/knowledge-products` | `routes/knowledge.py` |
| GET/PATCH/DELETE | `/api/knowledge-products/{product_id}` | `routes/knowledge.py` |
| POST | `/api/knowledge-products/{product_id}/test-connection` | `routes/knowledge.py` |
| GET / POST | `/prompt-templates` | `routes/prompt_templates.py` — list and create |
| GET / PUT / DELETE | `/prompt-templates/{id}` | `routes/prompt_templates.py` |
| GET | `/api/assistants/{slug}` | `routes/assistants.py` — resolved configuration, no secrets |
| POST | `/api/assistants/{slug}/chat` | `routes/assistants.py` — delegates to the `POST /chat` handler |
| POST | `/api/assistants/{slug}/chat/stream` | `routes/assistants.py` — delegates to the `POST /chat/stream` handler |
| POST | `/v1/assistants/{slug}/chat/completions` | `routes/assistants.py` — the OpenAI chat-completions shape |

### Assistant endpoints
A pipeline whose `rag_strategy` is `vector`, `lexical`, `relational` or `hybrid` reads one Knowledge
Product's stores. These four routes address it by `slug` instead of by UUID, so an external project can
call it without knowing the pipeline id. The two chat routes resolve the pipeline and the stores, then
delegate to the existing chat handlers, so guardrails, retrieval, rerank, generation, persistence and
metrics are not duplicated.

The copyable base URL is `{RAG_API_URL}/v1/assistants/{slug}`. An OpenAI SDK client sets `base_url` to it
and the SDK appends `/chat/completions`. The OpenAI route is single-turn: it reads the last `role=user`
message and ignores the earlier turns. Multi-turn memory needs a `session_id` extension field, not
`messages` parsing.

See `14_assistant_pipelines_and_endpoints.md` for the request and response bodies, the error codes and
client snippets.

### Knowledge Products proxy (present, unused)
`routes/knowledge.py` contains no storage of its own: every handler forwards over `httpx` to the ingestion manager under prefix `/api/knowledge-products`. The base URL is read from `settings.ingestion_service_url` with a fallback of `http://localhost:8007`; every call uses a 15 s timeout, the update route uses `PATCH`, and upstream connection errors surface as HTTP 503 "Ingestion service unavailable". The proxy has no sync route, because manual sync was removed upstream.

**No frontend code calls it.** Both the Knowledge Store pages use `apiFetch`, whose base is `API_URL = VITE_API_URL ?? "http://localhost:8007"`, so the browser reaches the ingestion backend directly and this router is a parallel path that nothing takes. It answers 200 when called by hand. Removing the router, or repointing the pages at it, is an open choice — see `11_knowledge_store_page.md` §6.

## 10. Key Invariants & Operational Guarantees
1. **Safety before generation**: when a `guardrails_config_id` is supplied, input validation runs before retrieval/generation; output validation runs on the generated answer before it is persisted and returned. Guardrail checks execute only via the external guardrails service.
2. **Deterministic offline evaluation**: golden-dataset runs use the pipeline with fixed configs and default `router_enabled=False`, so metric baselines are reproducible.
3. **Single source of retrieval truth**: this service holds read-only Qdrant access to the shared collection; ingestion writes the vectors (embedding/sparse model names must match `web-scrapper-workspace`).
4. **End-to-end tracing**: every `/chat` request produces one `rag.chat` span tree covering retrieve → rerank → generate (and guardrails when configured), with latency attributes per stage.
5. **Async quality scoring**: chat-level Ragas metrics are computed by the `eval-worker` process, not in the request path; the response carries `metrics_status` (`pending` when a metrics job was enqueued, `skipped` when metrics are disabled or the turn was blocked) for the client to poll.
6. **A Knowledge Product is the only retrieval source for an assistant**: an assistant owns no collection and no documents. It reads the stores of the product it names, and only the strategies that product's enabled destinations can serve.
7. **The store names come from the fanout**: `kp_<product-slug>_<id8>`. A caller never supplies them by hand, and the fanout rejects a clash on a store name.
8. **One store server per purpose**: `qdrant_url` points at the scraper's Qdrant (6333) and `qdrant_kp_url` at the knowledge product Qdrant (6335). A reader that uses the wrong one returns zero points without an error.

## 11. Known Gaps in the Working Tree

Open:

- `uv run pytest tests -q` → **7 failed, 45 passed, 1 skipped** on the Python 3.12 venv, and every failure predates the 2026-09-21 work. They are test-side problems rather than product defects: two dataset tests assert the committed golden file holds ≥20 items while it holds 5, one asserts `200` where the route correctly answers `422`, one expects a `recall_at_3` key the metrics helper does not return, one mocks a sparse client that is no longer constructed on that path, and two `test_stats.py` cases hand a `MagicMock` to a Pydantic model. Each passes alone; the last pair fails only in a full run.
- The OpenAI-compatible route ignores conversation history. It reads the last `role=user` message. Multi-turn memory through that route needs a `session_id` extension field.
- `generate_stream()` cannot stream a vision answer. With image chunks present it makes one blocking call and yields the whole answer as one token event, because the vision and fusion passes report no progress.
- `Settings.chat_model` is still `llama-3.3-70b-versatile`, which the LiteLLM proxy does not serve. An assistant always carries an explicit `chat_model`, so the assistant path never reaches that default; a hand-made legacy `POST /chat` with no `generation_model` gets a 400.
- The LLM query router and self-corrective RAG are **not** implemented. The module `rag_core.query_router` never existed, so both are out of scope until someone writes them. The Chat page no longer offers the controls.
- The knowledge-products proxy router (`routes/knowledge.py`) is still unreachable from the frontend, which calls the ingestion API directly. Removing the router, or repointing the pages at it, is an open choice — see `11_knowledge_store_page.md` §6.

Fixed on 2026-09-21 and no longer open:

- **RAGAS metrics had never computed.** `eval-core` targets the ragas 0.4 API (`ragas.metrics.collections`, `ascore(**fields)`, `llm_factory(client=…)`), while `uv.lock` pinned 0.3.1, where that module does not exist. Every metrics job died and every chat turn stayed unresolved. The dependency specifier is now `ragas>=0.4`, and the backend venv is built with `--python 3.12`, because ragas 0.4 needs `scikit-network` and that package publishes no wheel for 3.14. The first successful job returned context_precision 1.0, context_recall 1.0, faithfulness 1.0, answer_relevancy 0.957, kendall_tau 1.0 and mrr 1.0.
- `GET /guardrails/traces` answered 500 and every retrieval page reported it as a CORS error. Trace rows written without a guardrails config carry a `NULL` `config_id`, and the column is nullable, but `TraceResponse` declared the field as required. Six of forty-two rows were enough to break the list, and the exception escaped the CORS middleware, which is why the browser blamed CORS. The field is optional now and its name reads `No config`.
- The metrics worker failed every job with `compute_chat_pipeline_metrics() got an unexpected keyword argument 'sc_iterations'` — a caller left behind when self-corrective RAG was removed.
- The three stat cards on the Overview showed the literals `4`, `42 ms` and `96.8%`. They read `GET :8007/api/pipelines` and the recent turns from `GET /chat/stats`, and show `—` when the data is absent. The second card's label lost the word "Hybrid", because the average covers every retrieval mode.
- `POST /chat/stream` imported `rag_core.query_router` at module scope inside the handler, so every request answered `500 ModuleNotFoundError` before the stream began. The dead router branch, the dead `config.rag_mode` read and the call to the missing `RAGPipeline.stream_chat_self_corrective` are gone. `StreamEvent`, `RAGPipeline.stream_chat` and `Generator.generate_stream` now exist.
- Guardrails never blocked a turn. The config stores `ban_list`, the guardrails service names its guard `ban-list`, so every check returned 404 and the client read a non-200 as "passed". `guardrails_client.py` maps `_` to `-`.
- The three guardrails pages were functional but hard to use, and one showed a wrong validator name. The Guard Config create form rendered all sixteen validators with every parameter open, a 2,589 px wall of controls; it now splits into a validator picker and a settings pane for the selected validators only. Guard Traces drew its block split as a donut, which renders a 13-versus-2 split as a circle with a sliver, and repeated the same numbers three times; the donut and its component are gone, replaced by ranked bars with direct labels and one labelled proportion bar in the Charts view. Guard Evaluation carried three competing primary buttons and printed `id=… · mode=both · guards=…` on the page; it has one primary action and renders the config as tags. The validator label map moved to `frontend/src/utils/guardLabels.ts` with a readable fallback — it had keyed the retired `pii_check` id, so a real PII block displayed the raw id `detect_pii`.
- `Settings` declares `guardrails_url`, `guardrails_timeout_s`, `ingestion_service_url`, `ingestion_database_url`, `qdrant_kp_url`, `opensearch_url`, `opensearch_username` and `opensearch_password`, so none of them relies on an undeclared attribute.
- `Settings.embedding_model` defaulted to `nvidia-embed-passage`, which the proxy does not serve. It is now `nvidia-embed-textonly`, which returns 2048 dimensions, the size the fanout writes.

Fixed on 2026-09-20 and no longer open:

- The four `DELETE` routes that annotate `-> Response` now import it. Without the import `/openapi.json` returned 500 with a Pydantic `class-not-fully-defined` error.
- `routes/prompts.py` calls `has_override` / `write_override` / `clear_override` with the current `(package, name)` signature. It previously passed a filename alone, so `GET /prompts` returned 500.
- `libs/vector-core/pyproject.toml` resolves `platform-common` four levels up. It said three, which made `uv sync` fail outside Docker.
- `rag_db.migrate` finds `libs/database` via `parents[2]`. It said `parents[1]`, which is `libs/database/src` and holds no `alembic.ini`.

## 12. Related Documentation
- [02 — RAG Pipelines (the assistant builder)](./02_rag_pipelines_page.md)
- [03 — RAG Chat](./03_rag_chat_page.md)
- [04 — Prompts (prompt templates)](./04_prompts_management_page.md)
- [12 — Evaluation Metrics Reference](./12_evaluation_metrics_reference.md)
- [13 — Golden Dataset Requirements](./13_golden_dataset_requirements.md)
- [14 — Assistant Pipelines & Endpoints](./14_assistant_pipelines_and_endpoints.md)
- [06 — Offline Evaluation Page](./06_offline_evaluation_page.md)
- [Running the complete platform](../two_project_run.md)
