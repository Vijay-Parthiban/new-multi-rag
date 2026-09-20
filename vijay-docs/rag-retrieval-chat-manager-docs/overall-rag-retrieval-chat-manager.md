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
 scrape_embeddings   embeddings / rerank /    POST /parse/{guard}  RQ queue "eval"
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
| LiteLLM proxy | host process | 4000 | `litellm_base_url` — embeddings, rerank, chat, vision |
| guardrails-service | `guardrails-service/server.py` | 18000 → 8000 | compose maps `18000:8000`; `rag_shared/guardrails_client.py` default is `http://localhost:8002`, so the client default and the compose port disagree |
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
LITELLM_BASE_URL="http://localhost:4000" \
OTEL_TRACING_ENABLED=false \
  uv run uvicorn rag_api.main:app --host 0.0.0.0 --port 8001

# eval worker, same env
uv run rq worker eval --url redis://localhost:6379/0

# frontend — no .env needed; api.ts defaults to 8007 and 8001
cd ../frontend && node node_modules/vite/bin/vite.js --force --host 0.0.0.0 --port 5174
```

`npx vite` cannot spawn on Windows (`os error 193`), so call the vite entry script through `node` directly.

Auth: the app registers `dependencies=[Depends(verify_api_key)]` (`apps/rag-api/src/rag_api/main.py:62`); `verify_api_key` comes from `platform_common.auth` and accepts `X-API-Key` or the `api_key` query parameter, and is a no-op when `api_key` is empty (`rag_shared/config.py:51`).

## 4. Modular Library Decomposition (`backend/libs/`)

| Library | Package | Contents |
|---|---|---|
| `libs/rag-core` | `rag_core` | `RAGPipeline` orchestrator (`pipeline.py`: retrieve / rerank / chat / generate / from_request), request + result schemas (`schemas.py`), pipeline prompts (`prompts.py`) |
| `libs/vector-core` | `vector_core` | Qdrant dense+sparse access (`qdrant_store.py`, `search.py`), LiteLLM embeddings (`embedding_client.py`), sparse BM25 encoder (`sparse_client.py`), vision payload client (`vision_client.py`), payload filters and hit mapping |
| `libs/retrieval-core` | `retrieval_core` | `Retriever` mode/limit resolution (`retriever.py`), `chunk_from_search_hit` (`hit_mapper.py`) |
| `libs/reranker-core` | `reranker_core` | `Reranker` protocol, `LiteLLMReranker` (LiteLLM `POST /v1/rerank`), `NoopReranker` pass-through, `build_reranker` factory |
| `libs/generation-core` | `generation_core` | `Generator` (text) + `VisionGenerator` + fusion, prompt assembly (`prompt_builder.py`), prompt loading with overrides (`prompts.py`), `GenerationResult` |
| `libs/eval-core` | `eval_core` | `GoldenItemEvaluator` (`runner.py`), Ragas client (`ragas_client.py`), chat/retrieval/rerank/generation metrics, guardrail eval runner, golden + guardrails dataset schemas |
| `libs/database` | `rag_db` | SQLAlchemy models (`models/chat.py`, `models/evaluation.py`, `models/guardrails.py`), repositories, session factory (`services/database.py`), Alembic runner (`migrate.py`) |
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

## 6. Guardrails Integration Point

Guardrails are **not** implemented in-process: `routes/chat.py` `_run_guardrails()` (`routes/chat.py:295`) reads a `guardrails_configs` row through `GuardrailsRepository`, then calls `run_guardrails_check(text, cfg.guards, …, timeout_s, settings)` from `rag_shared/guardrails_client.py:11`, which POSTs to `{guardrails_url}/parse/{guard}` per guard and treats a failed `validation_passed` as blocked.

- Input phase runs before `pipeline.chat()` (`routes/chat.py:380`); output phase runs after (`routes/chat.py:432`); config `mode` (`input` / `output`) selects which phase executes.
- A blocked turn returns canned copy from `GUARD_BLOCK_COPY` (ban list, PII, toxic language) with span attributes `guardrails.{phase}.blocked` / `blocked_by`, and a `guardrails_traces` row is recorded.
- Note: `rag_shared/config.py` defines no `guardrails_url` / `guardrails_timeout_s` fields, so the chat guardrail path relies on attributes that the current `Settings` class does not declare.
- Guardrail golden-dataset evaluation (`routes/guardrails_evaluate.py`) reuses the same client against the same service.

## 7. Persistence (`rag_db`)

Postgres, SQLAlchemy 2.x via `get_session_factory()` (`libs/database/src/rag_db/services/database.py:14`), `database_url` default `postgresql+psycopg://crawler:crawler@postgres:5432/rag` (`rag_shared/config.py:15`). Tables:

| Area | Tables | Model |
|---|---|---|
| Chat | `chat_sessions`, `chat_messages`, `chat_pipeline_traces`, `chat_message_metrics` | `libs/database/src/rag_db/models/chat.py:14,26,40,61` |
| Online/offline eval | `golden_datasets`, `golden_dataset_items`, `evaluation_runs`, `evaluation_run_items` | `.../models/evaluation.py:14,26,41,57` |
| Guardrails | `guardrails_configs`, `guardrails_traces`, `guardrails_golden_datasets`, `guardrails_golden_dataset_items`, `guardrails_eval_runs`, `guardrails_eval_run_items` | `.../models/guardrails.py:14,30,47,59,75,93` |

Repositories: `chat_repository.py`, `evaluation_repository.py`, `guardrails_repository.py`, `guardrails_evaluation_repository.py`. Schema is versioned with Alembic (`rag_db.migrate:main`, CLI `rag-db-migrate`); head is `002_guardrails_tables`. Redis holds only the RQ queue (`redis_url` default `redis://redis:6379/0`); there is no semantic cache layer.

Two points to know before you touch this layer:

- **`get_engine()` caches one engine per URL** (`libs/database/src/rag_db/services/database.py`). It used to call `create_engine()` on every request, which opened a fresh pool and abandoned the old one; the app drained Postgres `max_connections` (97 idle `crawler` connections) and every DB-backed endpoint then answered `500`. `@lru_cache` on the engine, plus `pool_size=5, max_overflow=10`.
- **The guardrails tables come from migration `002`, not `001`.** `001_initial_schema` predates the guardrails models, and `alembic/env.py` imported only `chat` and `evaluation`, so the six guardrails tables were never created and every guardrails page failed with "relation does not exist". `002` creates them from `Base.metadata`, so the columns cannot drift from `rag_db/models/guardrails.py`. Any new model module must be added to the `env.py` import list or it will be invisible to autogenerate.

## 8. Tracing & Observability

`init_tracing()` runs at process startup for both apps (`apps/rag-api/src/rag_api/main.py:44`, `apps/eval-worker/src/eval_worker/main.py:10`) and configures an OTLP HTTP exporter (`rag_shared/tracing.py`). Chat spans are created with `rag_pipeline_span()` — `rag.chat` for `POST /chat` (`routes/chat.py:367`), `rag.chat.stream` for `POST /chat/stream` — and carry Langfuse-compatible attributes (`langfuse.trace.input/output`, `langfuse.session.id`, `langfuse.observation.metadata.*`) plus `latency.*` and `rag.chunks_used`. `emit_rag_pipeline_trace()` is used by the eval worker to emit synthetic traces for background metric runs, and `force_flush()` drains spans before worker exit.

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
| GET | `/guardrails/guards` | `routes/guardrails.py:209` |
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

### Knowledge Products proxy (present, unused)
`routes/knowledge.py` contains no storage of its own: every handler forwards over `httpx` to the ingestion manager under prefix `/api/knowledge-products`. The base URL is read from `settings.ingestion_service_url` with a fallback of `http://localhost:8007`; every call uses a 15 s timeout, the update route uses `PATCH`, and upstream connection errors surface as HTTP 503 "Ingestion service unavailable". The proxy has no sync route, because manual sync was removed upstream.

**No frontend code calls it.** Both the Knowledge Store pages use `apiFetch`, whose base is `API_URL = VITE_API_URL ?? "http://localhost:8007"`, so the browser reaches the ingestion backend directly and this router is a parallel path that nothing takes. It answers 200 when called by hand. Removing the router, or repointing the pages at it, is an open choice — see `11_knowledge_store_page.md` §6.

## 10. Key Invariants & Operational Guarantees
1. **Safety before generation**: when a `guardrails_config_id` is supplied, input validation runs before retrieval/generation; output validation runs on the generated answer before it is persisted and returned. Guardrail checks execute only via the external guardrails service.
2. **Deterministic offline evaluation**: golden-dataset runs use the pipeline with fixed configs and default `router_enabled=False`, so metric baselines are reproducible.
3. **Single source of retrieval truth**: this service holds read-only Qdrant access to the shared collection; ingestion writes the vectors (embedding/sparse model names must match `web-scrapper-workspace`).
4. **End-to-end tracing**: every `/chat` request produces one `rag.chat` span tree covering retrieve → rerank → generate (and guardrails when configured), with latency attributes per stage.
5. **Async quality scoring**: chat-level Ragas metrics are computed by the `eval-worker` process, not in the request path; the response carries `metrics_status` (`pending` when a metrics job was enqueued, `skipped` when metrics are disabled or the turn was blocked) for the client to poll.

## 11. Known Gaps in the Working Tree

Open:

- `POST /chat/stream` (`routes/chat.py:493`) lazily imports a query-routing module (`routes/chat.py:506`) and calls `RAGPipeline.stream_chat` / `stream_chat_self_corrective`; neither the routing module nor those pipeline methods exist in this repository (`libs/rag-core/src/rag_core/pipeline.py` implements only retrieve/rerank/chat/generate), and `PipelineConfig` has no `rag_mode` field. Streaming chat therefore cannot execute as written. The Chat page does not call it, so the page loads.
- `Settings` (`rag_shared/config.py`) declares no guardrails URL/timeout and no `ingestion_service_url` field; the guardrails client default (`http://localhost:8002`) and the proxy default (`http://localhost:8007`) are the effective values. The guardrails client default does not match the compose mapping (`18000:8000`), so a guard actually evaluated in chat needs `GUARDRAILS_URL` set by hand.
- The guardrails service is not part of the native run. The three Guardrails pages read and write through `rag-api`, so they load and work; only live guard evaluation during a chat needs the separate service on 18000.
- `uv run pytest tests/unit -q` → **20 failed, 32 passed**, and this predates the 2026-09-20 fixes. Two causes: `test_dataset_upload.py` asserts the golden dataset holds ≥20 items while the committed file holds 5, and `test_stats.py` fails only when the whole suite runs together (each test passes alone).

Fixed on 2026-09-20 and no longer open:

- The four `DELETE` routes that annotate `-> Response` now import it. Without the import `/openapi.json` returned 500 with a Pydantic `class-not-fully-defined` error.
- `routes/prompts.py` calls `has_override` / `write_override` / `clear_override` with the current `(package, name)` signature. It previously passed a filename alone, so `GET /prompts` returned 500.
- `libs/vector-core/pyproject.toml` resolves `platform-common` four levels up. It said three, which made `uv sync` fail outside Docker.
- `rag_db.migrate` finds `libs/database` via `parents[2]`. It said `parents[1]`, which is `libs/database/src` and holds no `alembic.ini`.

## 12. Related Documentation
- [12 — Evaluation Metrics Reference](./12_evaluation_metrics_reference.md)
- [13 — Golden Dataset Requirements](./13_golden_dataset_requirements.md)
- [06 — Offline Evaluation Page](./06_offline_evaluation_page.md)
