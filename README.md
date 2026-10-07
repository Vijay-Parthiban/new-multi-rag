# new-multi-rag

Enterprise RAG platform with two applications. They share one data tier and one contract, and no code at runtime.

| Application | Role | Frontend | API |
|---|---|---|---|
| **rag-ingestion-manager** | Document ingestion, source connectors, 4-sink Knowledge Fanout. Owns the data tier, the Knowledge Products and the pipelines. | `5173` | `8007` |
| **rag-retrieval-chat-manager** | Hybrid retrieval, reranking, chat, guardrails, evaluation. Reads the stores ingestion writes. | `5174` | `8001` |

## Documentation

All architecture, page-level and operational documentation lives in **[vijay-docs/](./vijay-docs/README.md)**.

| Document | Use it for |
|---|---|
| [vijay-docs/two_project_run.md](./vijay-docs/two_project_run.md) | The run guide. Sections 2 to 4 on a new machine, then section 5b. |
| [vijay-docs/overall-detailed.md](./vijay-docs/overall-detailed.md) | Architecture, data lifecycle, port and storage matrix, shared contracts. |
| `vijay-docs/*-docs/overall-*.md` | One document per application. |

## Quick start

Run each project as one container stack. Run the ingestion project first, because the retrieval project reads its stores and resolves a pipeline through its API.

```bash
docker network create rag-shared          # once per machine
cd rag-ingestion-manager && docker compose up -d
cd ../rag-retrieval-chat-manager/backend && docker compose up -d
```

The web scraper is not part of that. It sits behind the `scraper` profile and normally runs on the host from `web-scrapper-workspace`, so its code hot-reloads:

```bash
sh scripts/dev.sh scraper-api             # :8000
sh scripts/dev.sh scraper-worker
```

For a container-only machine, start it inside compose instead:

```bash
cd rag-ingestion-manager && docker compose --profile scraper up -d scraper-api scraper-worker
```

Open <http://127.0.0.1:5173> and <http://127.0.0.1:5174>. Use `127.0.0.1`, not `localhost`. On Windows `localhost` resolves to IPv6 first and each API call then waits about 2 seconds.

Two containers live outside this repository and must run first. Without them nothing embeds and nothing answers.

| Container | Port |
|---|---|
| LiteLLM proxy | `4000` |
| LiteLLM database | `5433` |

To change application code, run the app processes on the host with their dependencies in Docker. See section 4 of [two_project_run.md](./vijay-docs/two_project_run.md), or use `scripts/dev.sh`.
