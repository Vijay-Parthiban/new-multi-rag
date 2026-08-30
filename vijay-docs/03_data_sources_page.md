# Page Documentation: Data Sources & Connector Configuration (`SourcesPage.tsx`, `SourceDetailPage.tsx`, `ConnectorConfigForm.tsx`)

## 1. Overview & Purpose

The **Data Sources Management System** allows enterprise teams to connect, isolate, and synchronize external data repositories (Google Drive, Amazon S3, Azure Blob, Google Sheets, Databases, Web Scrapers, Confluence, SFTP) into dedicated MinIO object namespaces and RAG vector indexes using Apache NiFi for connector ingestion and Pathway for live event monitoring.
---

## 2. Page & Component Architecture

1. **`SourcesPage.tsx` (`/sources`)**: Overview grid of registered data sources, storage buckets, operational statuses, and search/filter tools.
2. **`SourceDetailPage.tsx` (`/sources/:id`)**: Detail management dashboard for a single source, featuring connector configuration, storage file browser, and linked RAG pipelines.
3. **`ConnectorConfigForm.tsx`**: Dynamic GUI form component with raw JSON editor toggle, password visibility toggles, and drag-and-drop key upload zones.

---

## 3. Visual Layout & UI Controls

### 3.1 Sources Page Layout (`SourcesPage.tsx`)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Data Sources | 2026 Engine Badge                  [+ New Source]   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4-Card Bento Stats Overview:                                                │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌───────────┐ │
│  │ Total Sources    │ │ Attached         │ │ Syncing          │ │ Isolated  │ │
│  │     12           │ │ Connectors: 18   │ │ Sources: 3       │ │ Buckets:12│ │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘ └───────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Search & Filters Toolbar:                                                   │
│  [🔍 Search sources...  ] [All 12] [Active 10] [Syncing 3] [View: 🔲 | ☰]    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Sources Bento Cards Grid:                                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 📁 engineering-knowledge                        ● CONNECTED [Manage ➔]│  │
│  │ 🪣 Bucket: source-engineering-knowledge-a8541818 [📋]                │  │
│  │ Connectors: [📁 Google Drive] [🪣 AWS S3] [🐘 PostgreSQL]             │  │
│  │ Actions: [🔄 Sync Now] [⚙️ Configure] [🗑️ Delete]                     │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Source Detail Page & Connector Catalogue (`SourceDetailPage.tsx`)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Overview > Sources > engineering-knowledge                          │
│ Title: engineering-knowledge | Status: ● CONNECTED | Bucket: source-... [📋] │
│ Actions: [← Back to Sources] [🔄 Sync All Connectors]                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3 Summary Cards: [Source Status: Live] [Attached Connectors: 3] [RAG: Linked]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Tab Navigation: [⚡ Connectors Catalogue (3)] [📁 Storage Files (142)] [🔮 RAG]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Integration Catalogue Grid:                                                 │
│ Category Filters: [All Connectors] [Cloud Storage] [Databases] [Files & Web]│
│ ┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐ │
│ │ 📁 Google Drive      │ │ 🪣 Amazon S3         │ │ ☁️ Azure Blob        │ │
│ │ Sync docs & folders  │ │ Stream AWS S3 buckets│ │ Microsoft Azure Sync │ │
│ │ ✓ CDC Supported      │ │ ✓ CDC Supported      │ │ ✓ CDC Supported      │ │
│ │ [+ Attach Connector] │ │ [+ Attach Connector] │ │ [+ Attach Connector] │ │
│ └──────────────────────┘ └──────────────────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Supported Connector Types & Schemas

| Connector ID | Name | Category | Primary Configuration Parameters |
|---|---|---|---|
| `google_drive` | Google Drive | Cloud | `folder_url`, `service_account_json` |
| `s3` | Amazon S3 | Cloud | `bucket`, `access_key_id`, `secret_access_key`, `region`, `prefix` |
| `azure_blob` | Azure Blob | Cloud | `container_name`, `connection_string`, `prefix` |
| `google_sheets` | Google Sheets | Files | `spreadsheet_url`, `service_account_json` |
| `onedrive` | OneDrive | Cloud | `folder_path`, `client_id`, `client_secret`, `tenant_id` |
| `sharepoint` | SharePoint | Workspace | `site_url`, `folder_path`, `client_id`, `client_secret` |
| `postgres` | PostgreSQL | Database | `host`, `port`, `database`, `username`, `password`, `schema` |
| `mysql` | MySQL | Database | `host`, `port`, `database`, `username`, `password` |
| `mongodb` | MongoDB | Database | `connection_uri`, `database`, `collection` |
| `web_scraper` | Web Scraper | Files | `start_urls`, `max_depth`, `max_pages` |
| `confluence` | Confluence | Workspace | `domain_url`, `space_key`, `email`, `api_token` |
| `sftp` | SFTP Server | Files | `host`, `port`, `username`, `password`, `remote_path` |

---

## 5. API Endpoints & Request Payloads

### 5.1 `POST /api/sources`
- **Description**: Creates a new isolated data source and generates its MinIO bucket.
- **Request Body**:
```json
{
  "name": "engineering-knowledge"
}
```
- **Response**:
```json
{
  "id": "a8541818-bb30-44b5-8956-75e0e5ca7d88",
  "name": "engineering-knowledge",
  "minio_bucket": "source-engineering-knowledge-a8541818",
  "enabled": true,
  "status": "idle",
  "created_at": "2026-08-30T10:15:00Z"
}
```

### 5.2 `POST /api/sources/:id/connectors`
- **Description**: Attaches a connector configuration to the data source.
- **Request Body**:
```json
{
  "connector_type": "google_drive",
  "config": {
    "folder_url": "https://drive.google.com/drive/folders/14IXHBDpExTdBd...",
    "service_account_json": { "type": "service_account", "client_email": "rag-bot@app.iam.gserviceaccount.com" }
  },
  "monitor_mode": "live",
  "sync_interval_minutes": 15
}
```

### 5.3 `POST /api/sources/:id/sync`
- **Description**: Triggers immediate synchronization of all connectors under the source into its isolated MinIO bucket via Apache NiFi.

### 5.4 `POST /api/sources/:source_id/pipeline/:pipeline_id`
- **Description**: Links a data source to a RAG pipeline. Automatically initializes the Pathway live MinIO monitor (`start_minio_monitor`) and enqueues a full reconciliation sync job (`enqueue_sync_run`).

### 5.5 `DELETE /api/sources/:source_id/pipeline/:pipeline_id`
- **Description**: Unlinks a data source from a RAG pipeline and enqueues a reconciliation sync job to remove the source's vector embeddings from Qdrant.
---

## 6. How to Run & Test

1. **Open Sources Page**: Navigate to `http://localhost:5173/sources`.
2. **Create New Data Source**:
   - Click `+ New Source`.
   - Type `customer-support` into the modal input.
   - Observe live bucket preview: `source-customer-support-...`.
   - Click `Create Source`.
3. **Configure Connector**:
   - On the Source Detail page (`/sources/:id`), locate Google Drive or Amazon S3 in the Integration Catalogue.
   - Click `+ Attach`.
   - Fill in configuration credentials or drop a `.json` key file.
   - Click `Attach Connector`.
4. **Trigger Sync**: Click `Sync Now` or `Sync All Connectors` to verify background indexing.
