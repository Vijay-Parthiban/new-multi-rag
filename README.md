# new-multi-rag

Enterprise RAG platform with two main applications:

| Application | Role | Default ports |
|---|---|---|
| **rag-ingestion-manager** | Document ingestion, source connectors, 5-sink Knowledge Fanout | Frontend `5173`, API `8007` |
| **rag-retrieval-chat-manager** | Hybrid retrieval, reranking, chat, guardrails, evaluation | Frontend `5174`, API `8000` |

## Documentation

All architecture, page-level, and operational documentation lives in **[vijay-docs/](./vijay-docs/README.md)**.

## Quick start

```bash
cd rag-ingestion-manager
docker compose up --build
```

See [vijay-docs/overall-detailed.md](./vijay-docs/overall-detailed.md) for full service inventory, ports, and local development commands.
