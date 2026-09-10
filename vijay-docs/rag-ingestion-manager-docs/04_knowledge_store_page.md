# 04. Knowledge Store & Profiles Page (`/knowledge-store`)

## 1. Page Purpose & Summary

The **Knowledge Store** (`/knowledge-store`) page manages the **Universal Multi-Sink Fanout Engine**. It enables administrators to group multiple MinIO document source buckets into unified **Knowledge Profiles** and fan out ingested documents across 5 enterprise destination categories.

---

## 2. Supported Destination Categories

1. **Vector Engine**: Qdrant Vector Database (Dense embeddings + BM25 sparse vectors).
2. **Lexical Engine**: OpenSearch (BM25 + Sparse SPLADE lexical search).
3. **Knowledge Graph Store**: Neo4j (Entities, Triplets & GraphRAG summaries).
4. **Multi-Model Relational Database**: PostgreSQL (`pgvector` / `pgvectorscale`).
5. **Semantic Cache & Summary Stores**: RedisVL (RAPTOR summary trees & parent-child document maps).

---

## 3. Key UI Modules & Features

1. **Knowledge Profiles Grid**: Displays profiles with associated source buckets, active destination sinks, enabled toggle statuses, and fanout sync statuses (`idle`, `syncing`, `error`).
2. **Create / Edit Knowledge Profile Modal**:
   - Set Profile Name & Description.
   - Select linked MinIO Data Source Buckets.
   - Configure Destination Sinks & parameters (Qdrant collection, OpenSearch index, Neo4j graph URI, PostgreSQL vector table, RedisVL cache index).
3. **Profile Sync Actions**:
   - `Trigger Fanout Sync`: Runs `execute_universal_fanout_sync` across all enabled destination sinks.
   - `Toggle Status`: Enables or disables fanout indexing for target profiles.
   - `Delete Profile`: Removes profile configuration without deleting underlying source buckets.

---

## 4. Data Fetching & API Interactions

- **`listKnowledgeProfiles()`**: `GET /api/knowledge/profiles`
  - Retrieves all knowledge profiles with source bucket mappings and destination configs.
- **`getKnowledgeDestinationOptions()`**: `GET /api/knowledge/destinations/options`
  - Fetches configuration schemas for supported destination types.
- **`createKnowledgeProfile(payload)`**: `POST /api/knowledge/profiles`
  - Persists new profile definition and links associated sources.
- **`triggerKnowledgeProfileSync(profileId)`**: `POST /api/knowledge/profiles/{id}/sync`
  - Dispatches multi-sink fanout pipeline execution (`universal_fanout.py`).
- **`deleteKnowledgeProfile(profileId)`**: `DELETE /api/knowledge/profiles/{id}`
  - Deletes knowledge profile record.
