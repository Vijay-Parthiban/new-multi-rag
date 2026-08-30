# Page Documentation: Tracking, Observability & Telemetry Tracing (`TrackingPage.tsx`)

## 1. Overview & Purpose

The **Tracking, Observability & Telemetry Tracing Page** (`/tracking`) provides end-to-end execution visibility across document ingestion pipelines, Web Scraper Crawl4AI jobs, single-page scrapes, and vector upsert operations. It displays real-time execution statuses, duration breakdowns, error diagnostics, and OpenTelemetry/Langfuse trace spans.

---

## 2. Page Architecture & Tabbed Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Tracking & Observability | [🔄 Refresh]                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Top Metric Summary Cards:                                                   │
│ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌───────────────┐ │
│ │ Total Runs     │ │ Active / Sync  │ │ Completed Runs │ │ Failed Runs   │ │
│ │      45        │ │       2        │ │       42       │ │       1       │ │
│ └────────────────┘ └────────────────┘ └────────────────┘ └───────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Tab Navigation:                                                             │
│ [⚡ File Ingestion Runs (45)] [🕷️ Crawl Jobs (12)] [📄 Scrape Jobs (28)]    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Ingestion Runs Audit Table:                                                 │
│ ┌── Run ID ────┬── Pipeline Name ──────┬── Trigger ──┬── Status ──┬── Duration ┐│
│ │ run-9901    │ Production Hybrid RAG │ Scheduled   │ ● DONE   │ 42.1s    ││
│ │ run-9884    │ S3 Customer Support   │ Webhook     │ ● DONE   │ 12.4s    ││
│ │ run-9871    │ Web Scraper Index     │ Manual      │ 🔴 FAILED│ 2.1s     ││
│ └─────────────┴───────────────────────┴─────────────┴──────────┴──────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│ Expanded Telemetry Trace Span (On Row Click):                               │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Trace ID: trace-sf89-9912 | Target Qdrant Collection: production-docs  │ │
│ │ Span 1: MinIO Fetch document "annual_report.pdf" (12 ms)               │ │
│ │ Span 2: PyMuPDF Text Extraction & OCR Parsing (340 ms)                  │ │
│ │ Span 3: Recursive Character Chunking [1000 tokens, 120 overlap] (18 ms)  │ │
│ │ Span 4: OpenAI API "text-embedding-3-small" (85 vectors) (1,240 ms)     │ │
│ │ Span 5: Qdrant Batch Points Upsert (45 ms)                              │ │
│ │ [↗ View Full Span in Langfuse Console]                                  │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Supported Tracking Categories

1. **File Ingestion Runs**: Tracks Celery background tasks reading files from MinIO buckets, parsing document layouts, splitting chunks, and writing vector embeddings into Qdrant collections.
2. **Web Scraper Crawl Jobs**: Tracks multi-page Crawl4AI web crawling operations (`start_url`, `max_depth`, `max_pages`, total crawled links, active depth level).
3. **Web Scraper Scrape Jobs**: Tracks single-page targeted markdown/text extractions and raw HTML cleanups.

---

## 4. API Endpoints & Request Schemas

### 4.1 `GET /api/pipelines/runs?limit=100`
- **Description**: Returns execution records for document ingestion pipeline runs.
- **Response Schema (`PipelineRunWithPipeline[]`)**:
```json
[
  {
    "id": "run-9901",
    "pipeline_id": "pipe-001",
    "pipeline_name": "Production Hybrid RAG",
    "status": "completed",
    "trigger_type": "scheduled",
    "documents_processed": 142,
    "chunks_created": 850,
    "duration_seconds": 42.1,
    "error_message": null,
    "created_at": "2026-08-30T10:15:00Z"
  }
]
```

### 4.2 `GET /api/scraper/crawls`
- **Description**: Returns all Crawl4AI multi-page crawling jobs.
- **Response Schema (`ScraperCrawlJob[]`)**:
```json
[
  {
    "job_id": "crawl-8810",
    "seed_url": "https://docs.example.com",
    "status": "completed",
    "pages_crawled": 48,
    "max_depth": 2,
    "duration_seconds": 38.5,
    "created_at": "2026-08-30T09:45:00Z"
  }
]
```

### 4.3 `GET /api/scraper/scrapes`
- **Description**: Returns single-page targeted scraping jobs.

---

## 5. How to Run & Verify

1. **Open Tracking View**: Navigate to `http://localhost:5173/tracking`.
2. **Inspect Summary Cards**: Confirm total run count, active count, and completion ratios render correctly.
3. **Switch Tabs**: Click between `File Ingestion Runs`, `Crawl Jobs`, and `Scrape Jobs`.
4. **Expand Trace Spans**: Click any completed or failed ingestion run to view step-by-step telemetry spans and error tracebacks.
5. **Test Manual Refresh**: Click `Refresh` button to poll latest worker execution updates.
