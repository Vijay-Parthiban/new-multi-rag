# 01. Ingestion Overview Dashboard Page (`/`)

## 1. Page Purpose & Summary

The **Ingestion Overview Dashboard** (`/`) is the landing screen of the `rag-ingestion-manager` application. It presents a comprehensive overview of document ingestion performance, active data sources, virtual directory folder counts, knowledge store profile counts, and backend service health.

---

## 2. Key UI Modules & Widgets

1. **System Operational Banner**: Reflects live API connection status (`http://localhost:8007/health`), database connection state, and storage service readiness.
2. **Key Metric Summary Cards**:
   - **Total Sources**: Count of configured external data source buckets.
   - **Active Directory Folders**: Total virtual directory root folders created in storage.
   - **Knowledge Store Profiles**: Count of active multi-sink knowledge fanout profiles.
   - **Background Ingestion Workers**: Active polling tasks and background sync status.
3. **Recent Data Sources List**: Recent storage buckets, showing connector types, monitoring modes (`live` / `scheduled`), and sync status indicators (`synced`, `syncing`, `failed`, `idle`).
4. **Quick Actions Bar**: Direct shortcuts to `/upload`, `/sources`, `/browse`, and `/knowledge-store`.

---

## 3. Data Fetching & API Interactions

- **`GET /api/sources`**: Retrieves source records, attached connectors, `total_files`, `total_size_bytes`, and monitoring modes.
- **`GET /api/directories`**: Fetches directory summaries for folder count metrics.
- **`GET /api/knowledge/profiles`**: Fetches configured multi-sink knowledge profiles.
- **`GET /health`**: Health check polling endpoint confirming backend operational status.

---

## 4. State Management & Interaction Patterns

- **State Hooks**: Component-level React state tracking `sources`, `directories`, `profiles`, `loading`, and `error`.
- **Navigation Shortcuts**: Direct routing to `/sources`, `/browse`, and `/upload`.
