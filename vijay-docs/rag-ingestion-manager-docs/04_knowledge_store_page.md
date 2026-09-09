# 04. Knowledge Store & Profiles Page (`/knowledge-store`)

## 1. Page Purpose & Summary

The **Knowledge Store** (`/knowledge-store`) page manages the **Universal Multi-Sink Fanout Engine**. It enables administrators to group multiple MinIO document source buckets into unified **Knowledge Profiles** and fan out ingested documents across 5 enterprise destination categories.

---

## 2. Supported Destination Categories

1. **Vector Search**: Qdrant Vector Database (Dense embeddings + BM25 sparse vectors).
2. **Relational Database**: PostgreSQL structured data extraction.
3. **Document Store**: Elasticsearch / MongoDB document collection.
4. **Graph Database**: Neo4j knowledge graphs.
5. **Data Lake**: Snowflake / Parquet files in S3.

---

## 3. Key UI Modules & Features

1. **Knowledge Profiles Grid**: Displays profiles with associated source buckets, destination sinks, and sync statuses (`operational`, `syncing`, `error`).
2. **Create Knowledge Profile Wizard**:
   - Step 1: Set Profile Name & Description.
   - Step 2: Select MinIO Source Buckets to include.
   - Step 3: Configure Destination Sinks & parameters (e.g. Qdrant collection name, vector dimension).
3. **Profile Sync Actions**:
   - `Sync All Sinks`: Triggers full fanout execution across all attached destinations.
   - `Delete Profile`: Removes profile configuration without deleting underlying source buckets.

---

## 4. Data Fetching & API Interactions

- **`listKnowledgeProfiles()`**: `GET /api/knowledge/profiles`
  - Retrieves all knowledge profiles with source bucket mappings and destination configs.
- **`getKnowledgeDestinationOptions()`**: `GET /api/knowledge/destinations/options`
  - Fetches configuration schemas for supported destination types.
- **`createKnowledgeProfile(payload)`**: `POST /api/knowledge/profiles`
  - Registers a new multi-sink fanout profile.
- **`triggerKnowledgeProfileSync(profileId)`**: `POST /api/knowledge/profiles/{id}/sync`
  - Dispatches multi-destination fanout worker jobs.
