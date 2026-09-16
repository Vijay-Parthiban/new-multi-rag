# 11 — Knowledge Store Proxy & Sink Verification Page

## 1. Executive Summary & Page Purpose
The **Knowledge Store Proxy Page** (`KnowledgeStorePage.tsx`, route: `/knowledge-store` in `rag-retrieval-chat-manager`) acts as the cross-service integration bridge. It proxies requests to the ingestion backend (Port 8007) and provides the retrieval manager with real-time visibility into configured routing profiles, connected MinIO source buckets, and active destination sinks (Qdrant, OpenSearch, Neo4j, PostgreSQL, RedisVL).

---

## 2. Cross-Service Routing & Proxy Architecture

```
+-----------------------------------------------------------------------------------------------+
|  RAG Retrieval & Chat Manager (Port 5174 / Backend Port 8000)                                |
|  - Route: /knowledge-store                                                                    |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v (FastAPI Reverse Proxy / Client-side Fetch)
+-----------------------------------------------------------------------------------------------+
|  RAG Ingestion Manager (Port 5173 / Backend Port 8007)                                       |
|  - /api/knowledge-profiles                                                                    |
|  - /api/knowledge-profiles/{id}/sync                                                          |
|  - /api/knowledge-profiles/{id}/inspect/{destination_type}                                    |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  5 Enterprise Destination Sinks                                                               |
|  [ Qdrant Vector ] [ OpenSearch BM25 ] [ Neo4j Graph ] [ PostgreSQL ] [ RedisVL Cache ]       |
+-----------------------------------------------------------------------------------------------+
```

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  Knowledge Store Integration                                                                  |
|  Proxy link to Ingestion Manager — View live sink health, vector counts, and sync status.     |
+-----------------------------------------------------------------------------------------------+
|  Active Profiles:                                                                             |
|  - Enterprise Multi-RAG Fanout Profile (Status: SYNCED)                                       |
|    - Sources: v-res (10 files), manual-vj (1 file)                                            |
|    - Sinks: Qdrant (73 points), OpenSearch (955 docs), Neo4j (10 nodes), Postgres (25 rows)   |
|                                                                                               |
|  Actions Available:                                                                           |
|  [ ⚡ Trigger Fanout Sync ]  [ 🔗 Open Ingestion Visualizer ]  [ 📋 Copy Profile ID ]          |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/knowledge/profiles` | Proxies list of knowledge profiles from Ingestion Manager | `list[KnowledgeProfile]` |
| `POST` | `/knowledge/profiles/{id}/sync` | Proxies fanout sync trigger | `{"status": "sync_triggered"}` |
| `GET` | `/knowledge/health` | Validates connectivity between Retrieval and Ingestion services | `{"status": "connected"}` |
