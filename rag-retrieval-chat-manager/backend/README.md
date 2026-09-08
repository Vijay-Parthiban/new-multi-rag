# RAG Platform

Docker-only RAG service: **retrieve → rerank → generate** over Qdrant chunks indexed by [web-scrapper-workspace](../web-scrapper-workspace).

## Architecture

```
web-scrapper-workspace          rag-app-workspace (this repo)
──────────────────────          ─────────────────────────────
postgres, redis, qdrant  ←──→  migrate, rag-api (:8001), eval-worker
on network rag-shared
```

All containers talk over **`rag-shared`** using Docker DNS: `postgres`, `redis`, `qdrant`.

## Startup (Docker only)

### Step 1 — web-scrapper infra

```bash
cd ../web-scrapper-workspace
cp .env.example .env
docker compose up -d
```

### Step 2 — create RAG database (once, from web-scrapper)

Same Postgres user as scraper (`crawler`); only the **database name** differs.

```bash
cd ../web-scrapper-workspace

docker compose exec postgres psql -U crawler -d crawler -c "CREATE DATABASE rag;"
```

Verify:

```bash
docker compose exec postgres psql -U crawler -d rag -c "SELECT current_database(), current_user;"
```

### Step 3 — RAG app

```bash
cd ../rag-app-workspace
cp .env.example .env
docker compose up --build
```

- Migrations run via `migrate` service
- API: http://localhost:8001 (port mapped from container)

## Environment (all Docker hostnames)

| Variable | Value in `.env` |
|----------|-----------------|
| `DATABASE_URL` | `postgresql+psycopg://crawler:crawler@postgres:5432/rag` |
| `REDIS_URL` | `redis://redis:6379/0` |
| `QDRANT_URL` | `http://qdrant:6333` |
| `QDRANT_COLLECTION` | `scrape_embeddings` |
| `EMBEDDING_MODEL` | `nvidia-embed-passage` |
| `SPARSE_EMBEDDING_MODEL` | `Qdrant/bm25` |
| `LITELLM_BASE_URL` | `http://host.docker.internal:4000` |

LiteLLM runs on the **host**; containers reach it via `host.docker.internal` (same as web-scrapper).

## API examples

Call from your machine (host → published port 8001):

```bash
curl -X POST http://localhost:8001/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query":"What is attention?","source_type":"web_scrape","source_id":"<scrape-job-uuid>","retrieval_mode":"hybrid"}'
```

Or from another container on `rag-shared`:

```bash
curl -X POST http://rag-api:8001/retrieve ...
```

## docker-compose.yaml

This repo only runs **migrate**, **rag-api**, **eval-worker**. No local postgres/redis/qdrant.

```yaml
networks:
  rag-shared:
    external: true
    name: rag-shared
```

## Tests (optional, on host)

```bash
uv run pytest tests/unit -v
```
