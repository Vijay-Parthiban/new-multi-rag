# Running the complete platform — `two_project_run.md`

**Last updated:** 2026-09-24

This document is the single run guide for the whole `new-multi-rag` workspace: both backends, both
frontends, and every dependency. Follow it top to bottom on a new machine. Sections 2 to 4 are
mandatory. Section 5 gives the fastest path for a machine that already ran the platform.

**Section 5b is the recommended way to run the platform.** It starts each project as one container
stack, with one command per project and nothing installed on the host. Sections 4 and 5 remain for
running the nine processes by hand, which is useful when you are changing their code and want a fast
restart.

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
| Web scraper API | 8000 | 8000 | `rag-ingestion-manager/docker-compose.yaml` | `scrape_embeddings`, the ingestion scraper path |
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

The guardrails image needs network access the first time it is built. It installs 13 real Guardrails
Hub validators from public PyPI and downloads the `en_core_web_sm` spaCy model from GitHub releases.
The build takes about 13 minutes from cold; later builds reuse the pip layer and take seconds. Rebuild
it whenever `guardrails-service/pyproject.toml`, `config.py` or `server.py` changes:

```bash
docker compose build guardrails-service && docker compose up -d guardrails-service
```

The service imports 13 validator modules at start, so give it about 15 seconds before the first
request. The three LLM-backed validators also need LiteLLM on port 4000; the compose entry sets
`extra_hosts: host.docker.internal:host-gateway` so the container can reach it.

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

## 5b. Run each project as one container stack

Sections 4 and 5 start nine processes by hand. The container path is shorter and is the one to prefer:
**one command per project**, with no shell profile, no `uv` and no Node on the host.

### One-time setup, per machine

Do this once. Nothing here repeats on a normal start.

```bash
# 1. The network both projects join. It is declared `external: true` in both compose
#    files, so compose will not create it. Two compose projects cannot share a network
#    they own: compose rejects a network that carries another project's label.
docker network create rag-shared

# 2. The four external containers, from their own directories (section 3.1).
#    qdrant:6335, litellm:4000, litellm_db:5433.
```

### Run the ingestion project

```bash
cd rag-ingestion-manager
docker compose up -d
```

That starts 15 services: `migrate`, `api`, `worker`, `pathway-worker`, `web`, the shared data tier
(`postgres`, `redis`, `qdrant`, `minio`, `opensearch`, `otel-collector`), and the scraper and guardrails
containers. `migrate` runs to completion and exits `0`; that is success, not a failure.

| Service | Port |
|---|---|
| `api` | 8007 |
| `web` | 5173 |
| `postgres` · `redis` · `qdrant` · `minio` · `opensearch` | 5432 · 6379 · 6333 · 9000 · 9200 |

Check it:

```bash
docker compose ps
docker compose logs migrate          # expect "Exited (0)"
```

### Run the retrieval project

Start it **after** the ingestion project. It reads that project's Postgres, Redis, Qdrant and
OpenSearch, and it resolves a pipeline by slug through that project's API.

```bash
cd rag-retrieval-chat-manager/backend
docker compose up -d
```

That starts four services: `migrate`, `rag-api`, `eval-worker`, `web`.

| Service | Port |
|---|---|
| `rag-api` | 8001 |
| `web` | 5174 |

`rag-api` can take a minute to answer its first request, because it imports the evaluation and
generation stacks on boot. A `connection closed` error in the first 60 seconds is that, not a fault.

Check it:

```bash
docker compose ps
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/chat/stats?limit=1
```

### Why the two compose files are not the same size

The ingestion compose declares **15 services** (18 with `extras`); the retrieval compose declares **4**.
That is not an oversight and not a half-finished migration. The two files answer different questions.

The ingestion project is **the producer and the owner of the data tier**. Its compose bundles four
separate responsibilities into one file:

| What | Services | Why it is here |
|---|---|---|
| The ingestion application | `api`, `worker`, `pathway-worker`, `web`, `migrate` | It is the project's own code |
| The shared data tier | `postgres`, `redis`, `qdrant`, `minio`, `opensearch`, `otel-collector` | The data is **born** here: MinIO holds the bytes, Qdrant the dense vectors, OpenSearch the BM25 index, Postgres the metadata, Redis the job queues and session memory |
| The web scraper, a separate application | `scraper-api`, `scraper-worker`, `scraper-migrate` | It fetches pages **into** the ingestion pipeline, so it sits on the producer side. Its own image, its own `.env.scraper`, its own `crawler-db-migrate` |
| The guardrails service, a second separate application | `guardrails-service` | Built from `../guardrails-service`, a different folder. Both projects call it over HTTP on 18000 |

The retrieval project is **a pure consumer**. Its compose declares only its own four services and owns
no infrastructure at all. Its header says so: *"This project has no data tier of its own. It reads the
stores the ingestion project writes."* It resolves `postgres`, `redis` and `qdrant` by name over the
`rag-shared` network, and reaches everything else through `host.docker.internal`.

**One owner for the data tier is required, not preferred.** There is one Postgres, one Redis and one
Qdrant on 6333. If both composes declared them, two servers would race for port 5432 and the data would
split into two copies that silently disagree. Exactly one project must own them, and the ingestion
project is the one that writes to them.

The port counts show the same asymmetry:

| | Ingestion | Retrieval |
|---|---|---|
| Published host ports | **10** — 8007, 5173, 5432, 6379, 6333, 9000, 9001, 9200, 9600, 4317, 4318, 8000, 18000 | **2** — 8001, 5174 |
| Docker images built | 3 Dockerfiles (`backend`, `frontend`, `../guardrails-service`) plus 1 pulled (`tharun0511/web-scrapper-wokspace`) | 2 Dockerfiles (`backend`, `frontend`), nothing pulled |
| Exit-on-complete jobs | `migrate`, `scraper-migrate` | `migrate` |

One line each: the ingestion project is the kitchen and the building's utility room. The retrieval
project is a dining room that plugs into the utilities.

The whole topology, as declared:

```mermaid
graph TB
  subgraph SHARED["rag-shared network"]
    subgraph ING["project: rag-ingestion-manager"]
      IAPI["api :8007"]
      IWK["worker"]
      IPW["pathway-worker"]
      IWEB["web :5173"]
      IMIG["migrate (exits 0)"]
      SAPI["scraper-api :8000"]
      SWK["scraper-worker"]
      SMIG["scraper-migrate (exits 0)"]
      GRD["guardrails-service :18000"]
      subgraph TIER["data tier — owned here"]
        PG["postgres :5432"]
        RD["redis :6379"]
        QD["qdrant :6333"]
        MN["minio :9000"]
        OS["opensearch :9200"]
        OT["otel-collector :4318"]
      end
    end
    subgraph RET["project: backend"]
      RMIG["migrate (exits 0)"]
      RAPI["rag-api :8001"]
      EWK["eval-worker"]
      RWEB["web :5174"]
    end
  end
  subgraph OUT["outside both projects, on the host"]
    LL["litellm :4000"]
    LDB["litellm_db :5433"]
    KQ["qdrant :6335 (knowledge products)"]
  end
  RAPI -->|"reads by name"| PG
  RAPI -->|"reads by name"| RD
  RAPI -->|"reads by name"| QD
  RAPI -->|"HTTP, pipeline by slug"| IAPI
  RAPI -->|"host.docker.internal"| LL
  RAPI -->|"host.docker.internal"| KQ
  RAPI -->|"host.docker.internal"| GRD
  IAPI --> PG
  IWK --> PG
  IWK --> QD
  IWK --> OS
  IWK --> MN
  IWK --> RD
```

Note the one asymmetry in the diagram: **the retrieval API reads the Qdrant on 6335, not the 6333 one
that the ingestion compose declares.** Two separate Qdrant instances are in play and they are not
interchangeable:

| Variable | Value | Holds |
|---|---|---|
| `QDRANT_URL` | `http://qdrant:6333` | The ingestion project's own store, on the `rag-shared` network |
| `QDRANT_KP_URL` | `http://host.docker.internal:6335` | The **knowledge-product** vectors, on the host. This is what chat search reads |

`libs/retrieval-core/src/retrieval_core/kp_retriever.py` resolves this as
`qdrant_kp_url or qdrant_url`. So if `QDRANT_KP_URL` is **empty**, search silently falls back to the
6333 instance, finds nothing, and the assistant answers with no context and no error. The retrieval
`.env` sets `QDRANT_KP_URL` correctly, so the fallback never fires — but that is the one variable to
check first if retrieval returns nothing.

### Verify the cross-project contract

The retrieval service proxies the ingestion service's knowledge-product API, and FastAPI filters that
response through `shared_contracts.knowledge.KnowledgeProductRead`. **Any field the model does not
declare is dropped before the frontend sees it, with no warning.** This has already happened once: the
model declared 19 of the 29 fields the ingestion serializer writes, so the Knowledge Store page showed
`Linked RAG Pipelines (0)` for every product.

```bash
cd rag-retrieval-chat-manager/backend
uv run python scripts/e2e_kp_contract.py
```

It compares the direct ingestion payload with the proxied one **recursively**, at every nesting level,
and names every lost field. It asserts nothing by hand, so a field added to either side later is caught
here instead of in the browser. Run it after any change to the knowledge-product serializer.

### Verify both projects

```bash
# Ingestion API, serving the knowledge products and pipelines
curl -s http://localhost:8007/api/knowledge-products | head -c 300
curl -s http://localhost:8007/api/pipelines | head -c 300

# Ingestion and retrieval frontends
curl -s -o /dev/null -w 'ingestion web %{http_code}\n' http://localhost:5173/
curl -s -o /dev/null -w 'retrieval web %{http_code}\n' http://localhost:5174/

# Retrieval API resolving a pipeline through the ingestion API.
# This single call proves the cross-project path: the slug, the `rag` database,
# and the memory gate all have to work for it to answer.
curl -s http://localhost:8001/api/assistants/<slug>
```

### Stop them

```bash
cd rag-retrieval-chat-manager/backend && docker compose down
cd rag-ingestion-manager && docker compose down
```

`down` removes the containers and keeps the named volumes, so your data survives. Add `-v` only when
you intend to erase it.

### The optional services

Three services in the ingestion compose sit behind the **`extras`** profile, because nothing needs them
today: `neo4j` (no destination uses it), `opensearch-dashboards` (a UI; the product reads the index
directly) and `nifi` (the connector sync reaches Google Drive itself). Start them with:

```bash
cd rag-ingestion-manager
docker compose --profile extras up -d
```

### How the two projects share a data tier

They join one Docker network named **`rag-shared`**, which is why the retrieval compose can name
`postgres`, `redis` and `qdrant` directly. The network is `external: true` in both compose files, so it
must exist first (see the one-time setup) and neither project claims ownership of it.

The retrieval project has one hard dependency on the ingestion project at runtime: it resolves a
pipeline by slug through the ingestion API. With that API down, the assistant routes return an error.

Anything outside both projects is reached through `host.docker.internal`: the LiteLLM proxy on 4000,
the knowledge-product Qdrant on **6335**, the guardrails service, and the ingestion API. Both composes
set `extra_hosts: host.docker.internal:host-gateway` for that.

### Frontend variables, and why they are not interchangeable

Both frontends read `VITE_*` from the **process environment** when the Vite dev server starts, so the
compose `environment:` block is the right place for them, not a build argument. The retrieval frontend
reads two variables and they point at different projects:

| Variable | Points at | Used for |
|---|---|---|
| `VITE_API_URL` | the **ingestion** API, `http://localhost:8007` | Sources, knowledge products, pipelines |
| `VITE_RAG_API_URL` | the **retrieval** API, `http://localhost:8001` | Chat, assistants, guardrails, evaluation |

Setting `VITE_API_URL` to 8001 looks plausible and is wrong: every ingestion-backed call then 404s, and
the whole frontend fills with console errors while still rendering. `src/api.ts` already falls back to
the correct values, so the safest thing is to set both explicitly.

### The two Dockerfiles must mirror the repository layout

This is the least obvious requirement, and breaking it fails the build with a confusing message.

`libs/*/pyproject.toml` in the retrieval backend declare their path dependencies as
`../../../../shared-libs` and `../../../../shared-contracts` — four levels up from `libs/shared`. Four
levels only land somewhere real if the application sits at the same depth inside the image that it does
in the repo. So the retrieval image keeps `/app/rag-retrieval-chat-manager/backend/...` and puts the
shared packages at `/app/shared-libs` and `/app/shared-contracts`.

Flattening it to `/app` makes uv refuse:

```
cannot normalize a relative path beyond the base directory:
/app/libs/shared/../../../../shared-libs/platform-common
```

The compose `command:` entries are therefore **relative** (`sh scripts/run-migrate.sh`), because the
workdir is the application directory in both layouts.

The ingestion Dockerfile uses pip rather than uv, and pip does not read `[tool.uv.sources]` at all —
that is a uv-only extension. So it installs `platform-common` and `shared-contracts` from source
**before** the editable install, which then finds both requirements already satisfied.

### The repository root needs a `.dockerignore`

Both backend builds use the repository root as their context (`context: ..` and `context: ../..`).
Docker sends the **whole context to the daemon before it runs a single `COPY`**, and this repository is
**1.6 GB** — three `node_modules` trees, several virtualenvs, the whole `.git` history and 168 MB of
`otel` data. Without an ignore file every build transfers all of it, the build appears to hang, and the
image never appears.

```
1.6G   .                        <- the context, before .dockerignore
 712M  rag-retrieval-chat-manager
 616M  rag-ingestion-manager
 168M  otel
```

The root `.dockerignore` cuts that to the source the two Dockerfiles actually copy. If a build seems to
hang with no output, check that the file is still present. It excludes `node_modules`, `.venv`, `.git`,
`__pycache__`, `dist`, caches and `vijay-docs` — and nothing else. It deliberately does **not** exclude
either backend or anything named `build` or `env`, because one context serves both images and a source
directory with either name would silently vanish from the build.

### Check the runtime dependencies from inside the container

Settings can look right in the compose file and still be wrong inside the container, because
`host.docker.internal` resolves differently from the host and a service name is only valid on the shared
network. This probe reads every URL from the **resolved settings** and connects for real:

```bash
cd rag-retrieval-chat-manager/backend
docker cp scripts/check_deps.py backend-rag-api-1:/tmp/check_deps.py
docker exec backend-rag-api-1 python /tmp/check_deps.py
```

Expect 8 checks and 0 failures: the ingestion API, the LiteLLM proxy, the guardrails service, OpenSearch
over HTTP, and a TCP connect to Postgres, Redis, the knowledge-product Qdrant on 6335 and the OTel
collector. A `401` from LiteLLM is a pass — it proves the proxy is reachable and only wants a key.

### Which env file is authoritative

More than one file exists and they disagree. Know which one your compose reads.

| File | Used by | Values |
|---|---|---|
| `rag-ingestion-manager/.env` | The ingestion compose's app services | **Postgres**, container hostnames |
| `rag-ingestion-manager/backend/.env` | The host run in section 4.1 | **SQLite**, localhost |
| `rag-retrieval-chat-manager/backend/.env` | The retrieval compose | The `rag` database, container hostnames, `host.docker.internal` for the rest |

Two things to know:

- **`rag-ingestion-manager/.env.rag` is dead.** The retrieval services that used it moved to the
  retrieval project's own compose, which reads `rag-retrieval-chat-manager/backend/.env`. Delete
  `.env.rag` when convenient.
- **The retrieval app's tables live in the `rag` database, not `ingestion`.** `DATABASE_URL` must be
  `postgresql+psycopg://crawler:crawler@postgres:5432/rag`. Pointing it at `ingestion` makes
  `rag-db-migrate` create a second copy of the schema inside the ingestion database, silently split
  from the host run's data.

### The database question: SQLite or Postgres

The host run uses a SQLite file; the container uses Postgres. **They are not the same data.** Moving a
host setup to containers therefore needs a one-time metadata copy:

1. `DATABASE_URL="postgresql://ingestion:ingestion@localhost:5432/ingestion" uv run ingestion-db-migrate`
   from `rag-ingestion-manager/backend`, to create the schema in Postgres.
2. Start the API once against Postgres, then stop it. That creates the two tables alembic does not:
   `ingestion_profiles` and `ingestion_profile_destinations`, which the app makes at startup.
3. Copy the rows, parents before children:
   `sources` → `source_connectors` → `ingestion_profiles` → `ingestion_profile_destinations` →
   `knowledge_products` → `knowledge_product_destinations` → `knowledge_product_sources` →
   `knowledge_product_files` → `pipelines`.

Only metadata moves. The document bytes live in MinIO and the four stores, and the Knowledge Product
keeps its id, so every derived store name (`kp_<slug>_<id8>`) stays valid and **nothing needs
re-ingesting**.

Do this on 2026-09-24: 18 rows across 9 tables. Row counts matched exactly afterwards, every apparent
difference was formatting (UUID hyphenation, `1` versus `True`, JSON text versus jsonb), and the four
store names were identical.

### Two known gaps in the container path

- **The alembic chain is behind the models.** Six columns exist in the models and in no migration:
  `knowledge_products.ingestion_profile_id`, `knowledge_products.pipeline_fingerprint`,
  `sources.total_files`, `sources.total_size_bytes`, `sources.connector_sync_interval_seconds` and
  `source_connectors.sync_interval_seconds`. `Base.metadata.create_all` never alters an existing table,
  and the patch routine in `src/shared/db/session.py` (`_ensure_sqlite_columns`) runs **only for
  SQLite**. So a Postgres database created from the migrations alone **lacks those six columns** and the
  app fails on any query that selects them. Add them by hand, or write the missing migration. This is
  also why the platform has been running on SQLite.
- **`nifi`, `neo4j` and `opensearch-dashboards` are declared but unused.** They sit behind `extras`.

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
| Guardrails | `curl -s http://localhost:18000/health-check` | `{"status":"ok"}`. `curl -s http://localhost:18000/catalog` lists the 16 installed validators |
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

**Guardrails suite** (same directory). It creates a guardrails config, seeds
`golden/guardrails-dataset.json`, runs the evaluation over it, and deletes its config:

```bash
uv run pytest tests/unit/test_guardrails_runner.py -q  # 15 tests
uv run python scripts/e2e_guardrails.py                # 34 checks
```

The guardrails service must be rebuilt and running first. It needs about 20 seconds per run, because
three of the twelve rows call the LLM judge.

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
| Guardrails never block | `GUARDRAILS_URL` is wrong, or the config selects no validator that can block | Check `GUARDRAILS_URL` on 18000 and `curl -s http://localhost:18000/health-check` |
| An LLM-backed guard reports `timed out` or `Judge returned no JSON` | Those guards call LiteLLM on the host and need about a second each | Check `LITELLM_BASE_URL`, `LLM_API_KEY` and `GUARDRAIL_LLM_MODEL` in `.env.guardrails`. `Gpt-oss-20b` needs `GUARDRAIL_LLM_MAX_TOKENS=512`: with a smaller budget the reasoning model returns an empty body |
| A guard is reported as `is not installed` | The service image is older than `guardrails-service/pyproject.toml` | Rebuild it with `docker compose build guardrails-service`, then `up -d` |
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
