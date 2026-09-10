# 04. Knowledge Store & Profiles Page (`/knowledge-store`)

## 1. Page Purpose & Summary

The **Knowledge Store** (`/knowledge-store`) page manages the **Universal Multi-Sink Fanout Engine**. It enables administrators to aggregate multiple MinIO data source buckets into unified **Knowledge Profiles** and fan out ingested documents across 5 enterprise destination categories.

---

## 2. Supported Multi-Destination Sinks

1. **Vector Engine**: Qdrant Vector Database (Dense embeddings + BM25 sparse vectors).
2. **Lexical Engine**: OpenSearch (BM25 + SPLADE lexical search).
3. **Knowledge Graph Store**: Neo4j (Entity extraction & relation triplets).
4. **Relational Database**: PostgreSQL (`pgvector` / `pgvectorscale`).
5. **Semantic Cache & Summary Store**: RedisVL (RAPTOR summary trees & parent-child document maps).

---

## 3. Key UI Modules & Features

1. **Knowledge Profiles Grid**: Displays configured profiles with linked source buckets, enabled destination sinks, toggle state, and fanout status (`idle`, `syncing`, `failed`).
2. **Create / Edit Profile Modal**:
   - Profile Name & Description.
   - Select linked MinIO Data Source Buckets.
   - Configure Destination Sinks & Connection Parameters (Qdrant collection name, OpenSearch index, Neo4j graph URI, PostgreSQL vector table, RedisVL cache index).
3. **Profile Actions**:
   - `Trigger Fanout Sync`: Runs `execute_universal_fanout_sync` across enabled destination sinks.
   - `Toggle Enabled State`: Enables or disables fanout indexing for the profile.
   - `Delete Profile`: Removes profile configuration without deleting underlying source buckets.

---

## 4. Data Fetching & API Interactions

- **`listKnowledgeProfiles()`**: `GET /api/knowledge/profiles` — Retrieves all knowledge profiles with embedded source bucket details and destination sink configurations.
- **`createKnowledgeProfile(body)`**: `POST /api/knowledge/profiles` — Creates a new knowledge profile with selected source buckets and destination sinks.
- **`updateKnowledgeProfile(id, body)`**: `PUT /api/knowledge/profiles/{id}` — Updates profile settings, destination sinks, or linked sources.
- **`deleteKnowledgeProfile(id)`**: `DELETE /api/knowledge/profiles/{id}` — Removes knowledge profile configuration.
- **`triggerFanoutSync(id)`**: `POST /api/knowledge/profiles/{id}/sync` — Executes universal fanout synchronization across all enabled destination sinks.
