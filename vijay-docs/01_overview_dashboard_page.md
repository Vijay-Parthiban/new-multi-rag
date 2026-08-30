# Page Documentation: Overview / System Summary Dashboard (`HomePage.tsx`)

## 1. Overview & Purpose

The **Overview / System Summary Dashboard** serves as the central command center for the Multi-RAG platform. Located at the root route (`/`), it provides a high-level operational overview of system metrics, container health statuses, active data pipelines, storage utilization, and recent execution events across the entire RAG pipeline ecosystem.

---

## 2. UI Layout & Component Architecture

### 2.1 Visual Layout Structure
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: System Overview | 2026 Engine Badge | Quick Launch Actions          │
├─────────────────────────────────────────────────────────────────────────────┤
│ Top Metric Bento Grid:                                                      │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────┐ │
│  │ Total Sources  │ │ Active Streams │ │ Vector Buckets │ │ Query Latency │ │
│  │      12        │ │       8        │ │      12        │ │    145 ms     │ │
│  └────────────────┘ └────────────────┘ └────────────────┘ └───────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Infrastructure Health Indicator Bar:                                         │
│  [● Postgres: UP]  [● Redis: UP]  [● MinIO: UP]  [● Qdrant: UP] [● RAG API]  │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ Quick Action Shortcuts               │ Recent System Activity Feed          │
│  - 📤 Ingest Documents               │  - [10:14] Google Drive Sync Done    │
│  - ⚡ Connect Data Source             │  - [10:12] Chunking 45 pages to S3   │
│  - 🔮 Open RAG Chat Playground       │  - [10:05] Qdrant Collection Upsert  │
│  - ⚙️ Configure Vector Pipeline      │  - [09:50] Evaluation Test Passed    │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

### 2.2 Key UI Components
- **Header Banner**: Dynamic greeting, current system environment badge (`2026 Engine`), and quick action buttons.
- **5-Card Metric Bento Grid**: High-contrast dark glass cards displaying:
  1. *Total Data Sources* (Total count of registered local & external sources).
  2. *Active Connector Streams* (Number of active polling/webhook streams).
  3. *Isolated MinIO Buckets* (Total storage namespaces created).
  4. *Average Query Latency* (P95 search + generation response time).
  5. *Total Vector Embeddings* (Total chunk points stored in Qdrant).
- **Service Health Bar**: Status indicators showing real-time ping results for backend APIs and storage layers.
- **Quick Shortcuts Panel**: Instant navigation links to Ingestion, Sources, Chat, and Pipelines.
- **Recent System Activity Stream**: Chronological audit feed of document processing jobs, sync events, and evaluation runs.

---

## 3. Data Flow & Sequence Diagram

```
[User Browser] ───────► GET /api/sources ─────────────► [Ingestion API :8007]
[User Browser] ───────► GET /api/pipelines ───────────► [Ingestion API :8007]
[User Browser] ───────► GET /api/v1/health ───────────► [RAG Query API :8001]
[User Browser] ───────► GET /health ──────────────────► [Web Scraper API :8000]
```

---

## 4. API Endpoints & Schemas

### 4.1 `GET /api/sources`
- **Description**: Fetches all registered data sources and attached connectors.
- **Response Schema (`SourceRecord[]`)**:
```json
[
  {
    "id": "a8541818-bb30-44b5-8956-75e0e5ca7d88",
    "name": "engineering-knowledge",
    "minio_bucket": "source-engineering-knowledge-a8541818",
    "enabled": true,
    "status": "connected",
    "connectors": [
      {
        "id": "c-101",
        "connector_type": "google_drive",
        "status": "active",
        "monitor_mode": "live"
      }
    ],
    "updated_at": "2026-08-30T10:15:00Z"
  }
]
```

### 4.2 `GET /api/pipelines`
- **Description**: Retrieves configured RAG vector pipelines.
- **Response Schema (`PipelineRecord[]`)**:
```json
[
  {
    "id": "pipe-001",
    "name": "Default Vector Pipeline",
    "qdrant_collection": "rag-documents",
    "chunk_size": 512,
    "chunk_overlap": 64,
    "embedding_model": "text-embedding-3-small"
  }
]
```

---

## 5. State Management & Hooks

- `useHomePage`: Local state hook managing `sources`, `pipelines`, `systemMetrics`, `loading`, and `error`.
- `useEffect` Polling Loop: Auto-refreshes system health and activity metrics every 30 seconds.

---

## 6. How to Run & Verify

1. **Start Backend & Infrastructure**: Ensure Docker Compose services and FastAPI backends are active.
2. **Launch Dev Server**:
   ```bash
   cd ingestion-workspace/ingestion-frontend
   npm run dev
   ```
3. **Verify View**: Open `http://localhost:5173/` in your browser.
4. **Expected Result**: Metric summary cards render with live data, green service health badges display, and action buttons navigate smoothly.
