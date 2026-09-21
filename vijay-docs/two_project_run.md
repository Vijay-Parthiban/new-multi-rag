# Running the complete platform — `two_project_run.md`

**Last updated:** 2026-09-21

This document is the single run guide for the whole `new-multi-rag` workspace: both backends, both
frontends, and every dependency. Follow it top to bottom on a new machine. Sections 2 to 4 are
mandatory. Section 5 gives the fastest path for a machine that already ran the platform.

The two projects are:

| Project | Directory | Role |
|---|---|---|
| RAG Ingestion Manager | `rag-ingestion-manager/` | Brings documents in from MinIO, extracts them, chunks them, and fans the chunks out to four stores. Owns knowledge products and pipelines. |
| RAG Retrieval & Chat Manager | `rag-retrieval-chat-manager/` | Reads those stores, reranks, answers, streams, applies guardrails, and scores quality. |

They share nothing at runtime except data. The ingestion side writes the knowledge product stores; the
retrieval side reads them. The retrieval side also calls the ingestion API on `8007` to resolve a
pipeline by slug.

---

## 1. Port and service map

Know this table before you start. Two rows surprise people: the knowledge product Qdrant is on **6335**
and not on the scraping Qdrant at 6333, and LiteLLM is **not** in this repository.

| Service | Host port | Inside compose | Source | Needed for |
|---|---|---|---|---|
| Ingestion API | 8007 | 8000 | this repo | Everything on the ingestion side |
| Ingestion web UI | 5173 | 5173 | this repo | Ingestion pages |
| Ingestion worker | — | — | this repo | Sync jobs, connector polling |
| Ingestion pathway worker | — | — | this repo | Pathway and knowledge pollers |
| Retrieval API | 8001 | 8001 | this repo | Chat, assistants, guardrails, evaluation |
| Retrieval web UI | 5174 | 5174 | this repo | Retrieval pages |
| Retrieval evaluation worker | — | — | this repo | RAGAS metrics jobs |
| PostgreSQL | 5432 | 5432 | `rag-ingestion-manager/docker-compose.yaml` | `rag`, `ingestion` and `crawler` databases |
| Redis | 6379 | 6379 | `rag-ingestion-manager/docker-compose.yaml` | Ingestion queue, RQ evaluation queue |
| Qdrant (scraper) | 6333 | 6333 | `rag-ingestion-manager/docker-compose.yaml` | `scrape_embeddings`, written by the web scraper |
| Qdrant (knowledge products) | **6335** | 6333 | **external** container | Every `kp_*` collection the assistants read |
| MinIO | 9000, 9001 | 9000, 9001 | `rag-ingestion-manager/docker-compose.yaml` | Source document buckets |
| OpenSearch | 9200, 9600 | 9200, 9600 | `rag-ingestion-manager/docker-compose.yaml` | `kp_*` lexical indexes, BM25 |
| Web scraper API | 8000 | 8000 | `rag-ingestion-manager/docker-compose.yaml` | Tracking page, `scrape_embeddings` |
| Guardrails service | 18000 | 8000 | `rag-ingestion-manager/docker-compose.yaml` | Guard checks, guard traces |
| LiteLLM proxy | 4000 | 4000 | **external** container | Every chat, embedding, rerank and caption call. It requires a key: `OPENAI_API_KEY`, `sk-bot` by default |
| LiteLLM database | 5433 | 5432 | **external** container | LiteLLM's own keys and spend |

Confirm what is already up before you start anything:

```bash
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

---

## 2. Prerequisites

Install these first. The versions are the ones the platform runs on today.

| Tool | Version used | Check | Notes |
|---|---|---|---|
| Docker Desktop | any current release | `docker --version` | Runs the eight infrastructure containers |
| Python | 3.12 or 3.13 | `python --version` | Both backends and every backend library. Prefer 3.12 or 3.13, not 3.14: `scikit-network`, a dependency of the RAGAS evaluation library, publishes no wheel for 3.14 and then needs the Microsoft C++ build tools. |
| `uv` | current | `uv --version` | Both backends use `uv` for dependencies and scripts |
| Node.js | 20 or newer | `node --version` | Both frontends |
| `npm` | ships with Node | `npm --version` | Installs frontend dependencies |
| `git` | any current release | `git --version` | Clones the repository |

One more thing that is not a tool: **a reachable LiteLLM proxy with at least one embedding model and one
chat model**. Without it the ingestion fanout cannot embed a chunk and no assistant can answer. Section 3
lists the model names the platform expects.

---

## 3. Infrastructure

Run this section once per machine. It does not change when the application code changes.

### 3.1 The four external containers

Three services the platform calls are **not declared in this repository**. Start them first, from their
own directories, or provide equivalents and update the environment variables in section 4.

| Container | Host port | Why it is external |
|---|---|---|
| `qdrant` | 6335 | Holds every `kp_*` knowledge product collection. The compose Qdrant on 6333 is a different server. |
| `litellm` | 4000 | The model gateway for chat, embeddings, rerank and image captions |
| `litellm_db` | 5433 | LiteLLM's PostgreSQL |

If you keep them in a separate services repository, start that stack before the one below. If you do not
have them, run one Qdrant and one LiteLLM yourself and set `QDRANT_KP_URL` and `LITELLM_BASE_URL`
accordingly.

### 3.2 The repository stack

The ingestion compose file is the only one in this repository that declares the shared infrastructure:
PostgreSQL, Redis, Qdrant on 6333, MinIO, OpenSearch, the web scraper, the guardrails service and an
OpenTelemetry collector. A Neo4j service is still declared there and **no destination uses it**; you can
ignore it.

The build contexts are the monorepo root, so run compose from its own directory:

```bash
cd rag-ingestion-manager
docker compose up -d postgres redis qdrant minio opensearch otel-collector
```

Wait for the health checks, then start the two services that separate containers provide:

```bash
# The web scraper. It needs its tables, which the migrate service creates.
docker compose up -d --no-recreate scraper-migrate scraper-api

# The guardrails service. It is published on host port 18000.
docker compose up -d --no-recreate guardrails-service
```

`--no-recreate` matters. Without it compose rebuilds the shared PostgreSQL, Redis and Qdrant containers
that the running stack already uses.

OpenSearch takes the longest to become healthy. Check all of them:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
curl -s http://localhost:9200/_cluster/health
curl -s http://localhost:18000/health-check
curl -s http://localhost:8000/health
```

### 3.3 Databases and roles

The Postgres image creates the `ingestion` database from its own `POSTGRES_DB` setting. The other two
come from `docker/postgres/init-crawler-db.sql`, which Docker runs **once, on the first start of an empty
data volume**:

| Database | Owner | Used by |
|---|---|---|
| `rag` | `crawler` | Retrieval manager: chat, sessions, guardrails, evaluation, prompt templates |
| `ingestion` | `ingestion` | The `kp_*` pgvector schemas a relational destination writes |
| `crawler` | `crawler` | The web scraper |

Two roles exist: `crawler` and `ingestion`, both with password equal to the role name. `ingestion` is a
superuser and `crawler` is not.

Check them:

```bash
docker exec rag-ingestion-manager-postgres-1 psql -U ingestion -d postgres -c "\l"
docker exec rag-ingestion-manager-postgres-1 psql -U ingestion -d postgres -c "\du"
```

If the volume already existed before that script was added, the script does not re-run. Create the two
databases by hand, once:

```bash
docker exec -i rag-ingestion-manager-postgres-1 psql -U ingestion -d postgres \
  < rag-ingestion-manager/docker/postgres/init-crawler-db.sql
```

The same statements, if you prefer to type them:

```bash
docker exec rag-ingestion-manager-postgres-1 psql -U ingestion -d postgres \
  -c "CREATE ROLE crawler LOGIN PASSWORD 'crawler';"
docker exec rag-ingestion-manager-postgres-1 psql -U ingestion -d postgres \
  -c "CREATE DATABASE crawler OWNER crawler;"
docker exec rag-ingestion-manager-postgres-1 psql -U ingestion -d postgres \
  -c "CREATE DATABASE rag OWNER crawler;"
```

The `ingestion` role owns the `kp_*` schemas and is a superuser. The relational reader connects as
`ingestion`, not as `crawler`, because `crawler` has no privileges on those schemas. The `crawler` role
needs no superuser rights: it owns `rag`, and the `rag` schema needs no Postgres extension. Only the
`ingestion` database carries the `vector` extension, and the fanout creates it itself.

Confirm the extension is in place:

```bash
docker exec rag-ingestion-manager-postgres-1 psql -U ingestion -d ingestion \
  -tAc "select extname from pg_extension"
```

A relational destination needs `vector` in that list. The fanout runs `CREATE EXTENSION IF NOT EXISTS
vector` before its first table, so the list fills in on the first fanout.

### 3.4 Models the platform calls

List what the proxy actually serves before you set anything:

```bash
curl -s -H 'Authorization: Bearer sk-bot' http://localhost:4000/v1/models | head -60
```

The proxy requires the key. It is the same value the backends send as `OPENAI_API_KEY`.

| Purpose | Setting | Value used today |
|---|---|---|
| Dense embeddings | `EMBEDDING_MODEL` | `nvidia-embed-textonly` — returns 2048 dimensions, the size the fanout writes |
| Image captions | `caption_model` | `groq-vision` |
| Rerank | `RERANKER_MODEL` | `nvidia-rerank` |
| Chat | the pipeline's `chat_model` | `Gpt-oss-120b` or `Gpt-oss-20b` |

Do not set `EMBEDDING_MODEL` to `nvidia-embed-passage`. The proxy does not serve it, and the fanout then
falls back to a local model whose vector size does not match the collection.

---

## 4. The four application processes and their dependencies

Install dependencies once per project. Run the migration before the backend that owns it. Then start the
processes. Every command block below is complete; none of them depends on a shell profile.

### 4.1 Ingestion Manager backend

```bash
cd rag-ingestion-manager/backend
uv sync --all-packages
```

`uv sync --all-packages` is required. A plain `uv sync` installs only the root project and not the
workspace members.

The backend reads `backend/.env`:

```ini
DATABASE_URL=sqlite+aiosqlite:///storage/ingestion.db
STORAGE_PATH=storage
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6335
MINIO_ENDPOINT=localhost:9000
OPENSEARCH_URL=http://localhost:9200
```

Two notes on `DATABASE_URL`:

- **SQLite**, as above, keeps the ingestion metadata in `backend/storage/ingestion.db`. The service
  creates the file, adds missing columns and renames legacy tables on start. This is the setting the
  platform runs on today.
- **PostgreSQL** is the other option, for example
  `postgresql://ingestion:ingestion@localhost:5432/ingestion`. The service then creates its tables in
  that database. If PostgreSQL is unreachable it falls back to the SQLite file, so set this value
  deliberately rather than by accident.

`QDRANT_URL` points at **6335** on purpose. The ingestion fanout writes the knowledge product
collections to that server.

Run the migration, then the API:

```bash
cd rag-ingestion-manager/backend
uv run ingestion-db-migrate
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8007
```

Check: `curl -s http://localhost:8007/api/pipelines` returns a JSON array.

### 4.2 Ingestion Manager workers

Two background processes. Start both. Without them, a source sync never runs and a knowledge product
never fans out.

```bash
cd rag-ingestion-manager/backend
uv run python -m apps.worker.main
```

```bash
cd rag-ingestion-manager/backend
uv run python -m apps.pathway_worker.main
```

They read the same `backend/.env` and use Redis on 6379.

### 4.3 Ingestion Manager frontend

```bash
cd rag-ingestion-manager/frontend
npm install
node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173
```

Open <http://127.0.0.1:5173>. Use `127.0.0.1`, not `localhost`, for the reason in section 8.

On Windows `npx vite` can fail to spawn. Calling the entry script through `node`, as above, avoids that.
`npm run dev` also works on Linux and macOS.

### 4.4 Retrieval & Chat Manager backend

```bash
cd rag-retrieval-chat-manager/backend
uv sync --all-packages --python 3.12
```

Again, `--all-packages` is required. The project is a workspace of eight packages: `rag-api`,
`rag-core`, `vector-core`, `retrieval-core`, `generation-core`, `reranker-core`, `eval-core`, and the
`shared`, `database` and `shared-contracts` libraries.

`--python 3.12` is required too. Without it `uv` picks the newest interpreter on the machine, and on
3.14 the sync fails: `scikit-network`, which `ragas` needs, publishes wheels only up to 3.13 and then
falls back to a source build that needs the Microsoft C++ build tools. The lockfile pins `ragas` 0.4.3,
and that version needs `ragas.metrics.collections`, which does not exist in the 0.3 line.

Its `backend/.env` holds **Docker service hostnames** such as `postgres`, `redis` and `qdrant`. Those do
not resolve from the host. Two ways to run it:

**Option A — pass the host values as process environment.** A real environment variable wins over the
`.env` file, so this overrides cleanly. This is the recommended host path:

```bash
cd rag-retrieval-chat-manager/backend
uv run rag-db-migrate    # with DATABASE_URL below set
```

```bash
cd rag-retrieval-chat-manager/backend
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
```

**Option B — run it inside the compose network.** Then the `.env` hostnames resolve, and
`scripts/run-api.sh` works unchanged. Use the ingestion compose file, which declares a `rag-api` service.

The variables, and why each one matters:

| Variable | What it points at | Consequence if wrong |
|---|---|---|
| `DATABASE_URL` | The `rag` database, through `psycopg` | Chat sessions, guardrails and prompt templates fail |
| `REDIS_URL` | Redis on 6379 | Metrics jobs never queue |
| `QDRANT_URL` | The scraping Qdrant on 6333 | The legacy `scrape_embeddings` chat path fails |
| `QDRANT_KP_URL` | The knowledge product Qdrant on 6335 | **Every assistant returns no chunks** |
| `OPENSEARCH_URL` | OpenSearch on 9200 | The `lexical` strategy and `hybrid` fail |
| `INGESTION_SERVICE_URL` | The ingestion API on 8007 | Assistant resolution returns 503 |
| `INGESTION_DATABASE_URL` | The `ingestion` database as the `ingestion` role | The `relational` strategy fails |
| `GUARDRAILS_URL` | The guardrails service on 18000 | Guardrails silently pass every request |
| `LITELLM_BASE_URL` | The LiteLLM proxy on 4000 | No answer, no embedding |
| `EMBEDDING_MODEL` | A model the proxy serves | Vector search returns nothing, or the fanout fails |
| `OTEL_TRACING_ENABLED` | `false` on a host run | Export errors when no collector answers on 4318 |

`QDRANT_KP_URL` is the one omission that looks like a code bug. An assistant reads the product's
collection, and those collections live on 6335. Leave the variable unset and the reader falls back to
`QDRANT_URL` on 6333, finds zero points, and answers "I could not find any relevant sources".

Run the migration first, then the API:

```bash
cd rag-retrieval-chat-manager/backend
DATABASE_URL="postgresql+psycopg://crawler:crawler@localhost:5432/rag" uv run rag-db-migrate
```

Check with the same environment: `curl -s http://localhost:8001/prompt-templates`.

### 4.5 Retrieval evaluation worker

One RQ worker. It computes RAGAS metrics for a chat turn, which is why a chat response reports
`metrics_status: "pending"` first.

```bash
cd rag-retrieval-chat-manager/backend
uv run rq worker eval --url redis://localhost:6379/0 --worker-class rq.worker.SimpleWorker
```

`--worker-class rq.worker.SimpleWorker` is required on Windows. The default worker calls `os.fork()`,
which Windows does not have, and the process dies with `AttributeError: module 'os' has no attribute
'fork'` the moment a job arrives. On Linux and macOS either worker class works.

### 4.6 Retrieval & Chat Manager frontend

```bash
cd rag-retrieval-chat-manager/frontend
npm install
node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5174
```

Open <http://127.0.0.1:5174>. Use `127.0.0.1`, not `localhost`, for the reason in section 8.

The Vite config sets no dev proxy, so the browser calls `8001` and `8007` directly. `src/api.ts` supplies
those defaults, and no frontend `.env` is needed. To point the UI at other hosts, set `VITE_API_URL`,
`VITE_RAG_API_URL` and `VITE_SCRAPER_URL`.

---

## 5. Start order, and the short version

Start in this order. Each step depends on the one before it.

1. The external Qdrant on 6335, LiteLLM on 4000, and the LiteLLM database on 5433.
2. The repository infrastructure: PostgreSQL, Redis, Qdrant on 6333, MinIO, OpenSearch, the OTel
   collector.
3. The web scraper and the guardrails service.
4. The databases and roles, then the migrations for both backends.
5. The ingestion API, then its two workers, then its frontend.
6. The retrieval API, then its evaluation worker, then its frontend.

The whole sequence, for a machine that already has the images and the dependencies installed:

```bash
# 1. External containers, from their own directories.
cd <external-services-dir> && docker compose up -d    # qdrant:6335, litellm:4000, postgres:5433

# 2. Repository infrastructure.
cd rag-ingestion-manager && docker compose up -d postgres redis qdrant minio opensearch otel-collector
cd rag-ingestion-manager && docker compose up -d --no-recreate scraper-migrate scraper-api guardrails-service

# 3. Ingestion backend.
cd rag-ingestion-manager/backend && uv run ingestion-db-migrate
cd rag-ingestion-manager/backend && uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8007
cd rag-ingestion-manager/backend && uv run python -m apps.worker.main
cd rag-ingestion-manager/backend && uv run python -m apps.pathway_worker.main
cd rag-ingestion-manager/frontend && node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173

# 4. Retrieval backend. Prefix each command with the environment block from section 4.4.
export DATABASE_URL="postgresql+psycopg://crawler:crawler@localhost:5432/rag"
export REDIS_URL="redis://localhost:6379/0"
export QDRANT_URL="http://localhost:6333"
export QDRANT_KP_URL="http://localhost:6335"
export OPENSEARCH_URL="http://localhost:9200"
export INGESTION_SERVICE_URL="http://localhost:8007"
export INGESTION_DATABASE_URL="postgresql://ingestion:ingestion@localhost:5432/ingestion"
export GUARDRAILS_URL="http://localhost:18000"
export LITELLM_BASE_URL="http://localhost:4000"
export EMBEDDING_MODEL="nvidia-embed-textonly"
export OTEL_TRACING_ENABLED=false

cd rag-retrieval-chat-manager/backend && uv sync --all-packages --python 3.12
cd rag-retrieval-chat-manager/backend && uv run rag-db-migrate
cd rag-retrieval-chat-manager/backend && uv run uvicorn rag_api.main:app --host 0.0.0.0 --port 8001
cd rag-retrieval-chat-manager/backend && uv run rq worker eval --url redis://localhost:6379/0 --worker-class rq.worker.SimpleWorker
cd rag-retrieval-chat-manager/frontend && node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5174
```

---

## 6. First run: get from nothing to a working assistant

This section is the shortest path to a chat answer. Follow it once. After that, section 7 verifies the
whole platform.

1. **Open the ingestion UI** at <http://localhost:5173>.
2. **Create a source.** Go to `Sources`, add a source with a MinIO bucket, and let it sync. The `Folders`
   and `Sources` pages show the files as they arrive.
3. **Create a Knowledge Product.** Go to `Knowledge Store` and press `Create Knowledge Product`. Give it a
   name. Enable the destinations you want to read later: `Qdrant` for vector search, `OpenSearch` for
   keyword search, `PostgreSQL` for SQL search. Enable `Qdrant` and `OpenSearch` together if you want the
   `Hybrid` strategy.
4. **Attach sources and wait for the fanout.** Add the source to the product. The fanout writes one row
   per chunk to every enabled destination. The Knowledge Store page shows a live timeline and, per
   destination, the store inspector. Confirm the record count is larger than zero in each store you
   enabled.
5. **Optional: an ingestion profile.** `Ingestion Profiles` sets the chunking and the modality once, then
   a product applies it. Apply a profile, then let the product re-sync. A change to the chunk strategy
   requires `Apply Profile`; chunking is part of the pipeline fingerprint.
6. **Open the retrieval UI** at <http://localhost:5174>.
7. **Create a prompt template.** Go to `Prompts`, press `Create prompt template`, and write the system
   message, for example:
   `You are an assistant for insurance questions. Answer only from the passages and cite the passage number.`
8. **Optional: a guardrails config.** Go to `Guard Config`, create a config, and pick `Ban List` with at
   least one keyword, or `PII Detection` with at least one entity. A guard list with no item is rejected.
9. **Create the assistant.** Go to `Pipelines`, choose the Knowledge Product, choose a `RAG Strategy`
   from the ones its destinations allow, choose the prompt template, choose the guardrails config, and
   choose a `Chat Model`.
10. **Copy the endpoint.** The `Assistant ready` panel shows the OpenAI base URL and the native chat URL.
    Press the copy button.
11. **Test it.** Paste this into a terminal, replacing the slug:

```bash
curl -s -X POST http://localhost:8001/api/assistants/<slug>/chat \
  -H 'Content-Type: application/json' \
  -d '{"query": "What award did Rohan receive at Amazon?"}' | python -m json.tool
```

Or use the OpenAI shape:

```bash
curl -s -X POST http://localhost:8001/v1/assistants/<slug>/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "assistant", "messages": [{"role": "user", "content": "What award did Rohan receive at Amazon?"}]}' \
  | python -m json.tool
```

12. **Or test it in the Chat page.** Open `Chat`, select the pipeline, and ask the same question. The
    answer streams, and the source list below it is not empty.

If step 11 returns an answer but the source list is empty, the reader is looking at the wrong Qdrant.
Read section 8.

---

## 7. Verification

Run these after the platform is up. Each one proves a layer.

| Layer | Command | Expected |
|---|---|---|
| Infrastructure | `docker ps --format "table {{.Names}}\t{{.Status}}"` | All containers `Up` |
| Qdrant 6335 | `curl -s -H 'api-key: qdrant' http://localhost:6335/collections` | A JSON list of `kp_*` collections. Without the header the answer is `401` |
| Qdrant 6333 | `curl -s -H 'api-key: qdrant' http://localhost:6333/collections` | The scraper's collections, or empty. Without the header the answer is `401` |
| OpenSearch | `curl -s "http://localhost:9200/_cat/indices?h=index"` | The `kp_*` indexes |
| Guardrails | `curl -s http://localhost:18000/health-check` | `{"status":200,"message":"Ok"}`. The service has no `/health` route; `/health-check` is the one |
| LiteLLM | `curl -s -H 'Authorization: Bearer sk-bot' http://localhost:4000/v1/models` | The served models, 18 of them. The key is `OPENAI_API_KEY`, `sk-bot` by default |
| Ingestion API | `curl -s http://localhost:8007/api/pipelines` | A JSON array |
| Retrieval API | `curl -s http://localhost:8001/prompt-templates` | `{"count": N, "items": [...]}` |

Then run the two check suites.

**Ingestion suites** (from `rag-ingestion-manager/backend`):

```bash
cd rag-ingestion-manager/backend
uv run pytest tests -q                       # 59 unit tests
uv run python scripts/e2e_knowledge_fanout.py       # 21 checks
uv run python scripts/e2e_knowledge_pause.py        # 14 checks
uv run python scripts/e2e_ingestion_profiles.py     # 50 checks
uv run python scripts/e2e_ingestion_modality.py     # 29 checks
uv run python scripts/e2e_chunk_strategies.py       # 19 checks
```

**Retrieval assistant suite** (from `rag-retrieval-chat-manager/backend`, with the environment block from
section 4.4 exported). It creates its own prompt template, guardrails config and pipeline, checks thirty
things, then deletes every fixture:

```bash
cd rag-retrieval-chat-manager/backend
uv run python scripts/e2e_assistant_pipelines.py    # 30 checks
```

It needs one Knowledge Product with the Qdrant, OpenSearch and PostgreSQL destinations all enabled. It
picks the product with the most enabled retrieval destinations and stops with a clear message if none has
all three.

**Frontend checks** (from either frontend directory):

```bash
npx tsc --noEmit
npx vite build
```

**Schema heads.** Ingestion: `011_assistant_pipeline`. Retrieval: `003_prompt_templates`. Confirm with
`uv run alembic current` from the matching `backend` directory, or read the `alembic_version` table.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| An assistant answers, but the source list is empty | The reader used `QDRANT_URL` on 6333 instead of 6335 | Set `QDRANT_KP_URL=http://localhost:6335` |
| Every assistant request returns 503 | The retrieval API cannot reach the ingestion API | Check `INGESTION_SERVICE_URL` and that `8007` answers |
| `POST /api/assistants/{slug}/chat` returns 422 `NOT_AN_ASSISTANT` | The pipeline's strategy is a legacy one such as `naive` | Create the pipeline from the `Pipelines` page, or set `rag_strategy` to `vector`, `lexical`, `relational` or `hybrid` |
| 422 `RAG_STRATEGY_UNAVAILABLE` | The product does not have the destination the strategy needs enabled | Enable the destination in the ingestion `Knowledge Store` page, then re-create or patch the pipeline |
| 422 `CHAT_MODEL_REQUIRED` | No `chat_model` on the pipeline | Set it in the `Pipelines` page or through `PATCH /api/pipelines/{id}` |
| The `Hybrid` option is missing from the strategy list | Only one of the Qdrant and OpenSearch destinations is enabled | Enable both on the product |
| The relational strategy fails with a permission error | The reader connected as `crawler`, which cannot see the `kp_*` schemas | Set `INGESTION_DATABASE_URL` to the `ingestion` role |
| Guardrails never block | `GUARDRAILS_URL` is wrong, or the guard name does not match | Check `GUARDRAILS_URL` on 18000 and `curl -s http://localhost:18000/guards` |
| A guard returns 404 `Unknown guard` | The config stores `ban_list`, the service names its guard `ban-list` | The client maps the underscore to a hyphen. A 404 means the config holds a name the service does not have. |
| `metrics_status` stays `pending` | The RQ worker is not running, or it died on `os.fork()` | Start it, and add `--worker-class rq.worker.SimpleWorker` on Windows |
| Every metrics job fails, and the reason mentions `ragas.metrics.collections` or `llm_factory(client=…)` | The venv was built on a Python newer than 3.13, so `uv` fell back to `ragas` 0.3.x. The evaluation code needs the 0.4 API | Rebuild with `uv sync --all-packages --python 3.12`. Section 4.4 explains it |
| A metrics job fails with `unknown async library, or not in async context` | Same cause as the row above: `ragas` 0.3.x drives its own event loop and rejects the driver in `compute_chat_pipeline_metrics` | See the row above |
| Every retrieval page logs a CORS error, and `/guardrails/traces` answers 500 | A trace row has no `config_id` (the chat turn ran without a guardrails config), and the response model declared that field as required | Fixed: `TraceResponse.config_id` is optional and the name reads `No config`. A 500 escapes the CORS middleware, which is why the browser reports CORS rather than the real error |
| Every embedding fails with `Invalid model name` | `EMBEDDING_MODEL` names a model the proxy does not serve | Use `nvidia-embed-textonly`, or any model from `GET /v1/models` |
| `/v1/models` answers `401` | The LiteLLM key is missing | Add `-H 'Authorization: Bearer <OPENAI_API_KEY>'` |
| A Qdrant call answers `401` | The API key header is missing | Add `-H 'api-key: qdrant'` |
| The fanout rejects a Qdrant write over the vector size | The embedding model changed after the collection was created | Use one model per product, or re-sync the product into a new collection |
| The ingestion migration fails on `ALTER TYPE` | It ran against SQLite | Migration `011` skips the enum change on SQLite. If you see this, the database is PostgreSQL and the type is missing. |
| A port is already in use | Another stack holds it | `docker ps`, then stop the container or change the host port |
| `npx vite` does nothing on Windows | Spawn problem in `npx` | Call `node node_modules/vite/bin/vite.js` |
| Every page sits on its loading state for a few seconds, and one API call takes about 2 seconds | In the browser, `localhost` resolves to `::1` before `127.0.0.1`, and uvicorn bound to `0.0.0.0` answers IPv4 only, so the first connection attempt times out. `127.0.0.1:8007/api/sources` answers in 20 ms while `localhost:8007/api/sources` takes 2 s, on every call | Open both UIs on `127.0.0.1`, not `localhost`. The retrieval frontend already defaults to `127.0.0.1` in `src/api.ts`. To serve IPv6 as well, start uvicorn on `--host ::` instead of `--host 0.0.0.0` |
| A page shows an empty list and no error, and the request log shows no failure | Vite answers an unknown path with `index.html` and status `200`, so a missing API route looks like an empty result rather than an error | Check the Network tab for a `200` whose body is HTML. Confirm the proxy target in `vite.config.ts` |

---

## 9. Where the pieces live

| Concern | Path |
|---|---|
| Ingestion backend | `rag-ingestion-manager/backend/` |
| Ingestion API routes | `rag-ingestion-manager/backend/apps/api/routes/` |
| Ingestion fanout engine | `rag-ingestion-manager/backend/src/ingestion_service/core/universal_fanout.py` |
| Ingestion database models | `rag-ingestion-manager/backend/src/shared/db/models.py` |
| Ingestion migrations | `rag-ingestion-manager/backend/alembic/versions/` |
| Ingestion frontend | `rag-ingestion-manager/frontend/src/` |
| Ingestion compose file | `rag-ingestion-manager/docker-compose.yaml` |
| Retrieval backend | `rag-retrieval-chat-manager/backend/` |
| Retrieval API routes | `rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/` |
| Assistant endpoints | `.../routes/assistants.py` |
| Prompt template routes | `.../routes/prompt_templates.py` |
| Chat and streaming | `.../routes/chat.py` |
| Strategy resolution | `libs/rag-core/src/rag_core/assistant.py` |
| Store readers | `libs/vector-core/src/vector_core/lexical.py`, `.../relational.py` |
| Strategy dispatch | `libs/retrieval-core/src/retrieval_core/kp_retriever.py` |
| Retrieval settings | `libs/shared/src/rag_shared/config.py` |
| Retrieval migrations | `libs/database/alembic/versions/` |
| Retrieval frontend | `rag-retrieval-chat-manager/frontend/src/` |
| Shared libraries | `shared-libs/platform-common/`, `shared-contracts/` |
| Platform documentation | `vijay-docs/` |

---

## 10. Reference

Deeper documentation for each area:

- `vijay-docs/overall-detailed.md` — architecture, data lifecycle, storage matrix, shared contracts
- `vijay-docs/rag-ingestion-manager-docs/overall-rag-ingestion-manager.md` — connector sync and fanout
- `vijay-docs/rag-ingestion-manager-docs/04_knowledge_store_page.md` — products and destinations
- `vijay-docs/rag-ingestion-manager-docs/06_ingestion_profiles_page.md` — chunking and modality
- `vijay-docs/rag-retrieval-chat-manager-docs/overall-rag-retrieval-chat-manager.md` — retrieval services
- `vijay-docs/rag-retrieval-chat-manager-docs/02_rag_pipelines_page.md` — the assistant builder
- `vijay-docs/rag-retrieval-chat-manager-docs/03_rag_chat_page.md` — the chat page
- `vijay-docs/rag-retrieval-chat-manager-docs/04_prompts_management_page.md` — prompt templates
- `vijay-docs/rag-retrieval-chat-manager-docs/14_assistant_pipelines_and_endpoints.md` — the assistant
  endpoint reference for integrators
