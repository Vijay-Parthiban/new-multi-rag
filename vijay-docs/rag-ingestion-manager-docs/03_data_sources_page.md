# 03 — Data Sources & Connectors Page

**Last updated:** 2026-09-20 (pause/resume revision)

## 1. Executive Summary & Page Purpose
The **Data Sources Page** manages the ingestion perimeter. Two files implement it:

- `SourcesPage.tsx` (route `/sources`) — source list, creation, sync, delete, file management drawer.
- `SourceDetailPage.tsx` (route `/sources/:id`) — one source: connectors, NiFi connector catalogue, files.

A **Source** is a per-source MinIO bucket that connectors write into. Connectors are attached separately (`SourceConnector` rows); the source bucket is the destination. Terminology note: the module names `core/airbyte_connector.py` and `core/pathway_sync.py` still say "Airbyte / Pathway", but there is no Airbyte runtime call on this path. Connector sync is dispatched by the NiFi connector engine (`core/nifi_sync.py`, `sync_connector_via_nifi`), and the Airbyte-named module is only a config mapper. `_run_airbyte_connector` in `core/pathway_sync.py` is dead code that references a `settings.airbyte_url` field that does not exist in `settings.py`.

There are exactly **two bucket source types** and the UI offers both:

| Source type | `source_type` | Written by | How files land in the bucket |
|---|---|---|---|
| Apache NiFi Connector Source | `minio` | NiFi connectors | `sync_connector_via_nifi` copies remote objects under `connectors/<connector_id>/` |
| Manual Upload Source | `minio_manual` | The browser | `POST /api/sources/{id}/files` (file picker or drag-and-drop) |

A legacy `local_filesystem` source type still exists in the backend so old rows keep working, and the UI renders it (badge "Legacy Local File System", files under `storage/local_sources/<folder>`). Neither the UI nor `create_source` can create one any more.

Two monitoring modes exist at two independent points:
- **Connector → Source**: how connectors pull remote data into the bucket (per connector, fallback source default). Each connector chooses **live** or **scheduled**, and a scheduled interval is given in **seconds or minutes**.
- **Source → Pipeline**: how bucket changes trigger pipeline re-indexing (per link, fallback source default).

---

## 2. UI Layout & Visual Components

```
+--------------------------------------------------------------------------------+
|  Data Sources                                             [ + New Source ]      |
|  Create a NiFi connector source or a manual upload source. Each source gets    |
|  its own isolated MinIO bucket.                                                |
+--------------------------------------------------------------------------------+
|  Stats cards: Total Sources | Attached Connectors | Syncing | Buckets (filter)  |
+--------------------------------------------------------------------------------+
|  [ search sources or buckets ]        [ grid | table ]                          |
+--------------------------------------------------------------------------------+
|  +--------------------------------------+  +--------------------------------------+
|  | <name>                  [Synced]  -> |  | <name>                  [Synced]  -> |
|  | <status dot> synced                  |  | <status dot> synced                  |
|  | 2 connectors | source-v-res-1a2b3c4d |  | MinIO | MANUAL UPLOAD                |
|  | <connector badges, max 4, +N more>   |  | Manual upload source — files land    |
|  | [Pause All] [Files] [Trash] [Manage] |  | [Upload Files] [Trash] [Manage]      |
|  +--------------------------------------+  +--------------------------------------+
+--------------------------------------------------------------------------------+
|  Detail page: Back to Sources | Pause All Connectors                           |
|  Stats: Source Status | Attached Connectors | Total Synced Files (+ size)        |
|  Tabs: Connectors Catalogue | Source Files  (tabs hidden for manual/local)      |
|  Active Attached Connectors + NiFi Connector Catalogue grid (3 tiles)            |
+--------------------------------------------------------------------------------+
```

List page behaviour:
- Grid view cards and table view columns: Source Name, Storage Location, Status, Connectors, Last Updated, Actions.
- Cards show the connector count (manual sources show a `MinIO / MANUAL UPLOAD` stat and local sources a filesystem marker instead), the bucket name with a copy-to-clipboard button, and up to 4 connector type badges with a vector icon per connector type. Cards do **not** show a file count or last-sync time.
- The source list re-fetches every 30 s while `/sources` is the active route (`SourcesPage.tsx:527`); the detail page re-fetches source + files every 20 s (`SourceDetailPage.tsx:154-157`).
- Actions: grid cards and table rows both offer a pause toggle, a file action and `Manage` (navigates to `/sources/:id`), plus a delete button. The file action reads **Upload Files** for manual sources and **Files** for connector sources; both open the same file drawer modal.
- **There is no manual sync trigger.** Polling is automatic: it starts the moment a connector is saved and stops only when every connector is paused. The pause toggle reads **Pause All** / **Resume All** on a card and **Pause** / **Resume** in a table row, and it is only shown when the source has connector rows. A manual-upload bucket has nothing to poll, so it shows no pause button. The card subtitle switches to "Paused — polling stopped" when every connector is disabled.
- Pausing flips `SourceConnector.enabled` for every connector of the source, one sequential `PATCH /api/sources/{id}/connectors/{cid}` at a time. The calls are sequential on purpose: each one re-registers the source poller, and parallel calls would race on the poller task registry.
- **New Source** modal: name input, two mutually exclusive radio tiles, a live bucket-name preview and a submit button whose label depends on the choice (`SourcesPage.tsx:913-1013`):
  - **Apache NiFi Connector Source** (`source_type: minio`) — "Pull files in through NiFi connectors: Google Drive, Amazon S3, Azure Blob Storage." Submitting navigates to the detail page so connectors can be attached.
  - **Manual Upload Source** (`source_type: minio_manual`) — "Pick files in the browser. Files are stored straight in the MinIO bucket." Submitting opens the file drawer immediately.
  - There is no local-filesystem option.
- **Delete** uses an in-app `ConfirmDialog` (`components/ConfirmDialog.tsx`), not `window.confirm`. The dialog names the bucket, the current object count, and warns that the bucket and every object inside it are deleted, plus that pipeline and knowledge-profile links are removed. The confirm button is red and the cancel button takes focus on open; Escape and a backdrop click cancel. The card is removed from the list as soon as the API returns.
- Status labels come from `StatusBadge.tsx`: `processing`→"Syncing", `synced`→"Synced", `failed`→"Failed", `pending`→"Pending", `running`→"Running", `completed`/`success`→"Complete"; unknown values are printed verbatim.

Detail page behaviour:
- Header pill: bucket name (manual and connector sources) or `storage/local_sources/<folder>` (local sources), plus `StatusBadge`.
- Stat cards: Source Status, Attached Connectors (count), Total Synced Files (`total_files`) with subtext derived from `total_size_bytes` formatted as KB.
- Banner for `minio_manual` sources ("Files are stored directly in MinIO S3 bucket …") and for legacy local sources.
- Tab 1 "Connectors Catalogue": a card per attached connector showing the catalogue label and vector icon, the mode ("Live polling", "Scheduled every `<n>s`" / "`<n>m`", or "Paused"), a status badge (`Paused` when disabled), the last sync timestamp, and `Pause` / `Resume` plus `Configure` and delete buttons. The manual sync button is gone; the header button is `Pause All Connectors` / `Resume All Connectors` and appears only when the source has connectors. Below the cards is the "NiFi Connector Catalogue" grid of exactly three tiles — Google Drive, Amazon S3, Azure Blob Storage — each marked "Live and scheduled polling". The category filter pills are gone because only one category remains.
- Tab 2 "Source Files": `FileBrowser` renders the read-only view unless the source is a manual or legacy local bucket. `allowUpload` and `allowDelete` are both `true` for those two kinds only, and `allowPreview` is `false` everywhere, so:
  - Connector bucket → the file table has **no** Actions column at all: no "Open & Visualize" and no "Delete".
  - Manual / legacy local bucket → Delete stays, "Open & Visualize" is gone.
  - The drawer on `/sources` follows the same rule through `canManageFiles`, which is `isManualSource(x) || isLocalSource(x)`.
- Tab navigation is hidden entirely for manual and local sources; the source-files view is shown directly for them (`SourceDetailPage.tsx:141`, `:515`).
- The connector modal hosts `ConnectorConfigForm`, a monitor-mode radio pair ("Immediate live polling" / "Scheduled polling"), and — when Scheduled is selected — a numeric interval input plus a unit `<select>` with `Seconds (minimum 5)` and `Minutes`. A helper line under the pair states the unit semantics. On edit, a connector stores only one of the two interval columns, and the modal picks the unit from whichever is set (seconds win).
- Deleting a connector uses the same in-app `ConfirmDialog` and notes that files the connector already copied stay in the bucket.

---

## 3. Connector Types Actually Available

`GET /api/sources/connectors` returns the static `CONNECTOR_OPTIONS` list (`routes/sources.py:35-41`). Any create/attach request whose `connector_type` is not in this list is rejected with `INVALID_CONNECTOR` (422) (`routes/sources.py:43`, `:333`, `:513`).

The catalogue is deliberately NiFi-only — three connectors, each with a working sync path into the source bucket:

| id | Label | NiFi sync path | Config validator |
|---|---|---|---|
| `google_drive` | Google Drive | `sync_google_drive_to_minio` (`gdrive_sync.py`) | needs `folder_url` or `folder_id`; credentials fall back to the server service-account file |
| `s3` | Amazon S3 | `NiFiConnectorManager._sync_s3_to_minio` | needs `bucket`, `access_key_id` (or `aws_access_key_id`), `secret_access_key` (or `aws_secret_access_key`) |
| `azure_blob` | Azure Blob Storage | `NiFiConnectorManager._sync_azure_to_minio` | needs `container_name` plus `connection_string` or (`account_name` + `account_key`) |

`manual_upload` is **not** a connector id and is **not** in `CONNECTOR_OPTIONS`. It is only a source-level marker written by `create_source` for a Manual Upload Source; no `SourceConnector` row is ever created for it.

The connector dispatch switch is `nifi_sync.py:61-112`. The engine still carries branches for `amazon_s3`, `azure`, `sftp`/`ftp`, `web_scraper`/`web`, `confluence`, `local_folder`/`local_dir`, plus `web_scraper`, and `pathway_sync.sync_local_dir_to_minio` remains. None of them can be selected any more because `VALID_CONNECTOR_IDS` gates every create/attach request. `ConnectorConfigForm` also keeps its typed forms for those legacy ids so a connector row created before the catalogue was narrowed can still be edited.

Notes:
- There is no `minio` connector id. `connector_type: "minio"` is accepted by `create_source` only as the sentinel that means "no auto-created connector", and it is never written as a `SourceConnector`. `sync_source_from_pathway` explicitly skips synthesising a connector from the marker types `minio`, `minio_manual`, `manual_upload` and `local_filesystem`.
- There is no `POST /api/sources/{id}/test` endpoint; connectivity is not validated from the sources API.
- Field mismatches between the form and the sync engine were the reason S3 and Azure connectors never synced before 2026-09-20. `validate_airbyte_connector_config` (`core/airbyte_connector.py`) now accepts exactly the keys the UI writes; `backend/tests/test_connector_config_validation.py` guards the contract.

---

## 4. Connector Configuration Fields

Defaults come from `defaultConfigFor()` (`ConnectorConfigForm.tsx:9-46`); "read by engine" lists the keys the NiFi sync functions actually consume.

Only three ids can be attached to a new source:

| Connector | Default config (created by the form) | Keys read by the sync engine |
|---|---|---|
| `google_drive` | `folder_url: ""`, `service_account_json: null` | `folder_url` \| `folder_id`, else a hardcoded demo folder id; `service_account_json` \| `credentials_json` \| `credentials` \| `service_account_file`, else a bundled default key path (`gdrive_sync.py:168-174`, `:208-209`) |
| `s3` | `bucket`, `access_key_id`, `secret_access_key`, `region: "us-east-1"`, `prefix: ""` | `bucket_name`\|`s3_bucket`\|`bucket`, `aws_access_key_id`\|`access_key_id`, `aws_secret_access_key`\|`secret_access_key`, `region_name`\|`region` (`us-east-1`), `prefix` (`nifi_sync.py:125-129`) |
| `azure_blob` | `container_name`, `connection_string`, `prefix: ""` | `container_name`\|`azure_container`\|`container`, `connection_string`, `account_name`, `account_key`, `prefix` (`nifi_sync.py:247-251`) |

`defaultConfigFor` still returns defaults for the legacy ids (`google_sheets`, `onedrive`, `sharepoint`, `postgres`/`postgres_db`, `mysql`/`mysql_db`, `mongodb`/`mongodb_db`, `web_scraper`/`web_crawler`, `confluence`, `sftp`, `http_api`), and `ConnectorConfigForm` still renders their typed forms. That is intentional: connector rows created before the catalogue was narrowed can still be opened, edited and deleted from the detail page, even though they return `{"files_synced": 0, "status": "unsupported"}` from the sync engine. The backend rejects any *new* attach request for those ids.

Form coverage (`ConnectorConfigForm.tsx`):
- GUI forms exist for `google_drive`/`google_sheets`, `s3`, `azure_blob`, `postgres`/`postgres_db`, `mysql`/`mysql_db`, `mongodb`/`mongodb_db`, `web_scraper`/`web_crawler`.
- Every other legacy id falls back to a raw JSON textarea seeded with its defaults.
- Any connector can also be edited as raw JSON via the "Advanced: Edit Raw JSON" toggle, with a Prettify button.
- Secret fields (`AWS Secret Access Key`, Azure connection string, DB password) have a text `Show`/`Hide` toggle with `aria-label` and `aria-pressed`; there are no emoji icons in the form.
- For `google_drive` a service-account JSON can be uploaded or drag-dropped; it is stored in the config as both `service_account_json` and `credentials_json`, with `_filename` kept for display only.
- `defaultConfigFor` seeds the modal when a catalogue tile is clicked; when editing an existing connector the stored `config` is used as-is (`SourceDetailPage.tsx:207`, `:217`).
- `getConnectorSchema()` in the same module returns `{}`; it is not used for validation.

Server-side validation runs before every sync, not at attach time: `validate_airbyte_connector_config(connector_type, config)` (`core/airbyte_connector.py:413`) returns `(is_valid, error_message)` and the failure text is stored on the connector row as `error_message`, leaving the connector in `status: "error"`. The `s3` and `azure_blob` checks accept the same key names the form writes. `backend/tests/test_connector_config_validation.py` pins this contract.

Monitoring fields travel beside the config:

| Field | Applies to | Notes |
|---|---|---|
| `monitor_mode` | connector, and source default | `live` or `scheduled` |
| `sync_interval_minutes` | connector, and source default | integer ≥ 1 |
| `sync_interval_seconds` | connector, and source default | integer 5–86400; takes priority over minutes when set |

The frontend sends exactly one of the two interval fields: minutes when the unit select is `Minutes`, seconds when it is `Seconds`.

---

## 5. Backend APIs & Data Contracts

All routes are under `APIRouter(prefix="/api/sources")` (`routes/sources.py:32`) and require the app-level `verify_api_key` dependency (`X-API-Key` header or `api_key` query parameter, `apps/api/main.py:36`). Error bodies come from `AppError` handlers: 404 `NotFoundError`, 409 `ConflictError`, 422 `ValidationError` (`file_manager/core/errors.py:16-28`).

| Method | Endpoint | Status | Description | Request / Response |
|---|---|---|---|---|
| `GET` | `/api/sources/connectors` | 200 | Static connector catalogue | `{"connectors": [{id,label,description}]}` |
| `GET` | `/api/sources` | 200 | List all sources, newest first; first runs orphan local-source cleanup | `list[SourceRecord]` (bare array) |
| `POST` | `/api/sources` | 201 | Create a source (manual bucket or connector bucket) | `SourceCreateRequest` → `SourceRecord`; 409 `SOURCE_EXISTS` on duplicate name |
| `GET` | `/api/sources/{id}` | 200 | Source with connectors and pipeline links | `SourceRecord` |
| `PATCH` | `/api/sources/{id}` | 200 | Update name/config/monitor modes/intervals/enabled | `SourceUpdateRequest` → `SourceRecord`; 409 `NAME_IN_USE` |
| `DELETE` | `/api/sources/{id}` | 200 | Delete source, empty and remove its bucket (or local folder), and drop all links | `{"status":"deleted","id":str}` |
| `POST` | `/api/sources/{id}/connectors` | 201 | Attach a connector | `ConnectorCreateRequest` → connector record; 422 `CONNECTORS_NOT_SUPPORTED` for local sources, 422 `INVALID_CONNECTOR` for unknown ids |
| `GET` | `/api/sources/{id}/connectors/{connector_id}` | 200 | Read one connector | connector record |
| `PATCH` | `/api/sources/{id}/connectors/{connector_id}` | 200 | Update connector config/mode/interval/enabled (pause and resume) | `ConnectorUpdateRequest` → connector record |
| `DELETE` | `/api/sources/{id}/connectors/{connector_id}` | 200 | Detach a connector | `{"status":"deleted","connector_id":…,"source_id":…}` |
| `POST` | `/api/sources/{id}/connectors/{connector_id}/sync` | 200 | Sync a single connector | `{"status":"triggered",…}`; `{"status":"error","message":"Connector is disabled"}` if disabled; 404 if not attached to this source |
| `POST` | `/api/sources/{id}/pipeline/{pipeline_id}` | 200 | Link source to pipeline | optional `{monitor_mode, sync_interval_minutes}`; 409 `LINK_EXISTS`, 404 `SOURCE_NOT_FOUND`/`PIPELINE_NOT_FOUND` |
| `DELETE` | `/api/sources/{id}/pipeline/{pipeline_id}` | 200 | Unlink | `{"status":"unlinked",…}`; 404 `LINK_NOT_FOUND` |
| `GET` | `/api/sources/{id}/files` | 200 | List objects/keys | query `prefix`; `{"source_id","bucket","files":[{key,size,last_modified}]}` |
| `POST` | `/api/sources/{id}/files` | 201 | Upload one or many files | multipart `file` and/or `files`; 422 `FILE_REQUIRED` / `EMPTY_FILE`; returns `{status,bucket,key,size,files[]}` |
| `DELETE` | `/api/sources/{id}/files` | 200 | Delete one object | query `key` (required) |
| `GET` | `/api/sources/{id}/files/content` | 200 | Download raw content | query `key` (required); media type guessed from the key, else `application/octet-stream`; 404 `FILE_NOT_FOUND` |
| `POST` | `/api/sources/{id}/sync` | 200 | Trigger sync for all connectors of the source | `{"status":"triggered","source_id","connector_type","minio_bucket"}`, or `{"status":"error","message":"Source is disabled"}` / "not found" |
| `POST` | `/api/sources/{id}/events` | 200 | MinIO bucket-notification webhook | See §6.7 |

`SourceRecord` fields (`_source_to_dict`, `routes/sources.py:205-252`): `id`, `name`, `source_type` (`local_filesystem` \| `minio_manual` \| `minio`), `is_manual`, `is_local`, `local_path`, `connector_type`, `config`, `connector_monitor_mode`, `connector_sync_interval_minutes`, `connector_sync_interval_seconds`, `pipeline_monitor_mode`, `pipeline_sync_interval_minutes`, `minio_bucket`, `sync_interval_minutes`, `enabled`, `last_sync_at`, `status`, `total_files`, `total_size_bytes`, `error_message`, `pipeline_ids`, `pipeline_links[{pipeline_id,monitor_mode,sync_interval_minutes}]`, `connectors[]`, `connector_count`, `created_at`, `updated_at`. The frontend `SourceRecord` type also declares `pipelines`, which the API never returns.

Connector record fields (`_connector_to_dict`, `routes/sources.py:117-134`): `id`, `source_id`, `connector_type`, `config`, `monitor_mode`, `sync_interval_minutes`, `sync_interval_seconds`, `enabled`, `last_sync_at`, `status`, `error_message`, `created_at`, `updated_at`.

`SourceCreateRequest` also accepts the legacy single-connector fields `connector_type` + `config` and the legacy `monitor_mode` / `sync_interval_minutes` pair. `source_type` is typed as a loose union, so values such as `"connector"` are accepted, but only `minio` and `minio_manual` change creation behaviour — the `local_filesystem` creation branch was removed on 2026-09-20.

### Sample creation payload — connector source (`POST /api/sources`)
```json
{
  "name": "v-res",
  "source_type": "minio",
  "connectors": [
    {
      "connector_type": "s3",
      "config": {
        "bucket": "my-company-documents",
        "access_key_id": "AKIA...",
        "secret_access_key": "...",
        "region": "us-east-1",
        "prefix": "documents/2026/"
      },
      "monitor_mode": "live"
    }
  ],
  "connector_monitor_mode": "live",
  "pipeline_monitor_mode": "live"
}
```
Response `minio_bucket` is `<MINIO_BUCKET_PREFIX>-<name>-<id[:8]>` (default prefix `source`, `settings.py:44`; `routes/sources.py:255-259`).

---

## 6. Key Workflows

### 6.1 Source creation
`create_source` (`routes/sources.py:277-382`) branches two ways:
1. **Manual Upload Source** (`source_type == "minio_manual"` or `connector_type` in `manual_upload`/`minio_manual`): the bucket name is generated, `config` is stamped with `source_type: "minio_manual"` and `mode: "manual_upload"`, `connector_type` is stored as `manual_upload`, `status` starts as `synced`, and the bucket is provisioned with `ensure_bucket`. No connector row is created. The response returns before any connector handling.
2. **NiFi Connector Source**: sources with `connectors: [...]` (or a legacy `connector_type` other than `minio`) get a bucket plus one `SourceConnector` row per entry; each `connector_type` is validated against `VALID_CONNECTOR_IDS`. Source `status` is left at the model default (`disconnected`); `minio_bucket` is always auto-generated, never supplied by the client. After the commit the source poller is registered.

The `local_filesystem` creation branch that used to sit between these two was unreachable (the manual branch returned first) and was deleted on 2026-09-20. Legacy local rows still work through `_is_local_source`.

Name uniqueness is enforced case-sensitively on the trimmed name (409 `SOURCE_EXISTS`).

### 6.1a Source deletion
`DELETE /api/sources/{id}` (`routes/sources.py:502-532`):
1. Deletes `KnowledgeProfileSource` and `PipelineSource` rows for the source.
2. For a local source, recursively deletes `storage/local_sources/<folder_name>` through `_force_rmtree`.
3. Otherwise calls `src.shared.storage.delete_bucket(minio_bucket)`. `_sync_delete_bucket` (`s3_client.py:138-155`) pages `list_objects_v2`, deletes every object individually (logging a warning per object that fails), then deletes the bucket itself. Failures are logged at warning level and do not fail the request.
4. Deletes the `Source` row (connectors cascade via `cascade="all, delete-orphan"`), runs the orphaned local-source cleanup, and stops the poller.

Verified on 2026-09-20 against a live MinIO: create → upload → delete leaves no bucket and no leftover objects.

### 6.2 Manual upload flow
- In the New Source modal choose **Manual Upload Source**; submitting creates the bucket and opens the file drawer immediately, so the first upload needs no navigation.
- Upload via the drawer's dropzone (click, drag-and-drop, or Enter/Space) or by picking files in the browser file dialog → `POST /api/sources/{id}/files` with multipart `file`/`files`; file names are sanitized, then written to the bucket with `put_object`.
- After a successful upload the backend recalculates metrics and triggers a background pipeline sync without blocking the response.
- Downloads use `GET /files/content?key=…`; deletes use `DELETE /files?key=…` and also refresh metrics plus trigger a background sync.
- Manual sources can carry connectors too (the API allows it and the detail page would render them), but the Connectors tab is hidden for them, so in practice a Manual Upload Source stays upload-only.

### 6.3 Connector add / edit / delete / sync
- **Add**: `POST /{id}/connectors` stores the config verbatim together with `monitor_mode` and the chosen interval column, and if `enabled` is true enqueues an initial Pathway sync (`enqueue_pathway_sync`) before re-registering the source poller. Unknown `connector_type` values are rejected with 422 `INVALID_CONNECTOR`. Polling starts from this call — no manual trigger is needed or offered.
- **Edit**: `PATCH /{id}/connectors/{connector_id}` replaces `config`, `monitor_mode`, `sync_interval_minutes`, `sync_interval_seconds` or `enabled` when present (partial update; omitted fields are untouched). A `PATCH` that changes nothing emits no UPDATE and is a no-op.
- **Delete**: `DELETE /{id}/connectors/{connector_id}` removes the row and re-registers the poller. The UI asks for confirmation first and notes that already-copied files stay in the bucket.
- **Pause / resume**: the same `PATCH` with `{"enabled": false|true}`. See §6.5a.
- **Sync**: `POST /{id}/connectors/{connector_id}/sync` sets the connector to `syncing`, clears its error, and enqueues a Pathway sync. It has no UI caller any more; the endpoint stays for scripts.
- **Source-level sync**: `POST /{id}/sync` delegates to `clients/source_sync.py:trigger_source_sync`, which sets `status = "syncing"`, clears the error, and enqueues the Pathway job. It refuses disabled sources.
- **Serialisation caveat**: `updated_at` carries `onupdate=func.now()`, so SQLAlchemy expires it after an emitted UPDATE. Both `PATCH` handlers call `await db.refresh(obj)` before serialising, otherwise reading `updated_at` triggers a lazy load outside the greenlet and the request fails with `MissingGreenlet` (500). A no-op PATCH never hit this, which is why it went unnoticed.

### 6.4 Sync execution and duplicate detection
`sync_source_from_pathway` (`core/pathway_sync.py:27-181`) iterates the source's **enabled** connectors and calls `sync_connector_via_nifi` for each; per-connector results set `connector.status` to `synced` (with `last_sync_at`) or `error` (with `error_message`). Afterwards the source's `total_files`/`total_size_bytes` are recomputed from the bucket, `status` becomes `idle`, `last_sync_at` is stamped, pipeline syncs are triggered, and the MinIO watcher is started. Poller registration is **not** re-done here; see §6.5.

Change detection in the connector engines is metadata-based: S3 and Azure compare the stored `remote-etag` plus object size, the web scraper and SFTP compare sizes, and the local-directory sync compares mtime + size (`pathway_sync.py:376-391`). Connector output is written under the key prefix `connectors/<connector_id>/` inside the source bucket (`nifi_sync.py:167`, `:287`), so connector files show up in the file browser under that folder. Content-level SHA-256 hashing exists further downstream in the knowledge-profile fanout (`core/universal_fanout.py:255-256`), not in the connector sync path.

### 6.5 Automatic background polling
- `register_source_poller(source_id)` (`pathway_sync.py:449-528`) stops any existing poller and starts a new one:
  - The **enabled connector rows decide the schedule**. A source with connector rows but none enabled stops the poller and returns (`source_poller_skipped`). A bucket-only source (marker `connector_type`, no connector rows) is also skipped — there is nothing to poll.
  - Mode: `live` when **any enabled connector** is `live` → continuous loop with a fixed 3-second interval. Otherwise scheduled.
  - Scheduled interval, in order: the smallest `sync_interval_seconds` among enabled connectors (floored at 5 s), else the smallest `sync_interval_minutes × 60`, else **5 minutes**.
  - Only a source with **no connector rows at all** falls back to the source-level `connector_monitor_mode` / interval fields (legacy sources).
  - Disabled sources or unknown ids stop the poller instead.
  - After registering, an immediate initial sync runs in the background so a newly configured connector does not wait for the first sleep.
- Before 2026-09-20 the mode was `source.connector_monitor_mode == "live" or any(connector is live)`. Because every new source defaulted to `live`, a connector configured as scheduled was still polled every 3 seconds and the UI's "Scheduled every 30s" was a lie. The enabled connectors now win.
- One loop serves the whole source, so when connectors in one source have different intervals the **shortest** one applies to all of them. Splitting into per-connector pollers is the next step if a source ever mixes a 5-second and an hour-long schedule.
- The `sync_interval_seconds` column was added on 2026-09-20 to `sources` (`connector_sync_interval_seconds`) and `source_connectors` (`sync_interval_seconds`). Both are nullable; seconds always win over minutes when set.
- Who starts it: source create, source update, connector add/update/delete, and server startup. `apps/api/main.py:23-26` schedules `init_all_source_pollers()` in the lifespan, which registers pollers for every enabled source.
- `_do_sync_source_from_pathway` no longer re-registers the poller at the end of every sync. It used to, which tore the poller down and rebuilt it on each tick; registration belongs to the mutation paths and to startup.
- Additional per-source watchers: `start_minio_monitor` (bucket notification watch stream, triggers pipeline syncs on create/upload events) and `start_local_fs_monitor` (2-second mtime snapshot loop over `storage/local_sources/<folder>`, triggers pipeline syncs on change).
- `stop_source_poller` cancels and forgets the task; it is called on source delete, on any connector pause/resume, and whenever a source is found disabled.

### 6.5a Pause and resume
`enabled` on the connector row is the pause switch, and it is the only one — `Source.enabled` keeps its original meaning ("is this source row active") and is not used by the pause buttons.

| Action | Request | Effect |
|---|---|---|
| Pause one connector | `PATCH /api/sources/{id}/connectors/{cid}` `{"enabled": false}` | Row leaves the enabled set; the poller is re-registered and stops if none remain |
| Resume one connector | same with `{"enabled": true}` | Poller re-registers and runs an immediate initial sync |
| Pause / resume all | the same call, once per connector, sequential | Same as above applied to every connector |

Because `_do_sync_source_from_pathway` already filters `c.enabled`, a paused connector is skipped by the poller, by `POST /{id}/sync`, by the MinIO event webhook and by the cron sweep — not just by the UI.

**Do not fire the per-connector PATCHes in parallel.** Each one calls `register_source_poller`, which pops and cancels the previous task and stores a new one; concurrent calls race on `_SOURCE_POLLER_TASKS` and can leave a stray task. The UI sends them sequentially.

### 6.5b Selecting the connector for a sync
`_do_sync_source_from_pathway` (`pathway_sync.py:35-181`) prefers enabled `SourceConnector` rows. Only when there are none does it fall back to the legacy single-connector fields, and since 2026-09-20 that fallback skips the marker values `minio`, `minio_manual`, `manual_upload` and `local_filesystem`. Without that guard a freshly created NiFi source (which stores `connector_type: "minio"`) synthesised a fake connector on every 3-second tick, logged `nifi_unsupported_connector_type type=minio`, and did nothing. A source with no connectors now exits early with `pathway_sync_no_connectors`.

### 6.5c SQLite column backfill
`_ensure_sqlite_columns` (`src/shared/db/session.py`) adds columns that `Base.metadata.create_all` cannot add to an existing table. It covers `sources.total_files`, `sources.total_size_bytes`, `sources.error_message`, `sources.connector_sync_interval_seconds` and `source_connectors.sync_interval_seconds`.

Until 2026-09-20 the helper only ran on the Postgres→SQLite fallback path, so a deployment configured with `DATABASE_URL=sqlite+aiosqlite:///storage/ingestion.db` (the value in `backend/.env`) never received new columns and every `Source` query failed with `no such column`. `init_db` now calls it on the configured-SQLite path too.

### 6.6 Source ↔ pipeline linking
- `POST /{id}/pipeline/{pipeline_id}` inserts a `PipelineSource` row with optional per-link `monitor_mode` and `sync_interval_minutes` (both may be null, meaning "inherit the source default"), then starts the MinIO monitor for the source and enqueues a sync run for the pipeline. Duplicate links raise 409 `LINK_EXISTS`.
- `DELETE /{id}/pipeline/{pipeline_id}` removes the link and enqueues a sync run.
- Effective pipeline mode for a link = link `monitor_mode` if set, else `source.pipeline_monitor_mode`.
- `pipeline_ids` and `pipeline_links` are exposed on `SourceRecord`; per-link values are `None` when unset.
- Changing the source-level `pipeline_monitor_mode` to `live` attempts to install a MinIO bucket notification pointing at `getattr(settings, "internal_api_url", "http://localhost:8000")` + `/api/sources/{id}/events` (`routes/sources.py:488-489`). `internal_api_url` is not a field on `Settings`, so the fallback `http://localhost:8000` is always used. Failures are logged and do not fail the request.

### 6.7 MinIO event ingestion (`POST /api/sources/{id}/events`)
Webhook for MinIO/S3 bucket notifications.
- 404 if the source does not exist.
- `{"status":"ignored","reason":"source disabled"}` if the source is disabled.
- `{"status":"ignored","reason":"no live pipeline links"}` if no linked pipeline resolves to `live` mode.
- `{"status":"error","reason":"invalid json"}` when the body is not JSON.
- `{"status":"ok","records":0}` when `Records` is empty.
- Otherwise it collects the `s3.object.key` of every record, logs a summary, and enqueues a sync run for each live pipeline: `{"status":"ok","records":n,"affected_keys":[…],"pipelines_triggered":[ids]}`. The affected keys are reported but not passed to the sync job.

### 6.8 Per-source file operations and metrics
- `GET /{id}/files` lists local folder contents (recursive, `size` + `last_modified` from the filesystem) for local sources, or MinIO objects with a 5-second timeout for bucket sources; a listing failure logs a warning and returns an empty `files` array rather than an error. `prefix` is applied client-side for local sources.
- `total_files` and `total_size_bytes` are column-backed metrics recalculated by `_update_source_metrics` after every upload/delete file call and at the end of every source sync, then returned in `SourceRecord` and rendered on the detail page.

### 6.9 Orphaned local-source cleanup
`_cleanup_orphaned_local_sources` (`routes/sources.py:168-190`) scans `storage/local_sources/` and deletes any child directory whose folder name does not match an active local source (folder name taken from `config.folder_name`, else `minio_bucket` with the `local-` prefix stripped). Deletion uses `_force_rmtree`, which clears the read-only bit and retries on Windows/POSIX. It runs on every `GET /api/sources` and again after a source delete; all failures are caught and logged (`logger.warning`) without failing the request.

---

## 7. Verification (2026-09-20)

Two checks cover this page.

**1. Live API walkthrough.** A throwaway script drove the running API end to end (create source → bucket in MinIO → upload → list → delete → confirm the bucket is gone from MinIO, then a NiFi source with an `s3` connector on a 30-second schedule). All 18 assertions passed. The script was deleted after use; the flow is reproducible from the `curl`/HTTP examples above.

**2. Unit tests.** `backend/tests/test_connector_config_validation.py` (7 cases) pins the validator contract that decides whether a connector ever syncs:

```
cd rag-ingestion-manager/backend && uv run pytest tests -q
# 23 passed
```

Frontend: `npx tsc --noEmit` reports no errors and `npx vite build` succeeds.

Browser checks performed: nav has no Upload item; New Source shows both source types; a Manual Upload Source opens the file drawer and a picked file appears in the bucket listing (30 B, "just now"); the delete dialog shows the bucket name and object count and closes on Escape; deleting removes the card at once; a NiFi source shows the three-tile catalogue; attaching Amazon S3 with "Scheduled / 30 / Seconds" renders as "Mode: Scheduled every 30s"; and reopening Configure prefills `45` with unit `seconds` for a 45-second connector.

### 7.1 Automatic polling and pause (2026-09-20)

Measured against the running API on a connector created with `monitor_mode: "scheduled"`, `sync_interval_seconds: 30` on a source whose `connector_monitor_mode` defaulted to `live`:

| Check | Method | Result |
|---|---|---|
| Syncs without any manual trigger | Connector created → sync ran immediately | pass (`nifi_s3_sync_failed` appeared with no `POST /sync` call) |
| The 30 s schedule wins over the source-level `live` default | `last_sync_at` unchanged at t=0 s and t=10 s, advanced at t=36 s | pass |
| Pause stops polling | `PATCH {enabled:false}` → `last_sync_at` unchanged over 40 s while it had been moving every ~30 s | pass |
| Resume restarts polling at once | `PATCH {enabled:true}` → `last_sync_at` advanced within 6 s | pass |
| `PATCH` returns 200 for a real change | both the connector and the source PATCH return 200 with the persisted `enabled` | pass (this is the fix in §6.3) |
| Connector bucket shows no file actions | detail page → Source Files: table headers are Name / Size / Modified only, no "Open & Visualize", no Delete | pass |
| Manual bucket keeps Delete only | detail page → Source Files: Actions column present with Delete, no "Open & Visualize" | pass |
| Sources page pause toggle | card button flips Pause All ⇄ Resume All, subtitle flips to "Paused — polling stopped", banner names the connector count | pass |
| Detail page pause | header `Pause All Connectors`, per-connector `Pause` → `Resume`, mode line shows "Paused", badge shows `Paused` | pass |

`uv run pytest tests -q` → 23 passed (14 at the time of this run; the Knowledge Products work added `test_knowledge_product_files.py`). `npx tsc --noEmit` → no errors. `npx vite build` → succeeds.

## 8. Known limitations

- One poller loop serves a whole source, so connectors with different intervals in the same source all follow the **shortest** interval. Per-connector pollers are the fix if that ever matters.
- Pausing every connector takes one sequential `PATCH` per connector and each `PATCH` runs an immediate initial sync on the ones that stay enabled. With three connectors that is three round trips; a bulk endpoint would collapse it.
- `POST /{id}/connectors/{cid}/sync` and `POST /{id}/sync` still exist and still work, but nothing in the UI calls them.
- `GET /api/sources` takes roughly 2.6 s under load while the background pollers run their sync cycles; the UI polls every 30 s and updates optimistically after a create or delete, so this only shows up as latency on the first paint.
- The detail page stat "Attached Connectors" counts `source.connectors`, which excludes marker types by construction; a NiFi source with no connectors correctly shows 0.
- `_run_airbyte_connector` in `core/pathway_sync.py` remains dead code. It references `settings.airbyte_url`, which `Settings` does not define. Left in place rather than deleted because it is pre-existing and outside the Sources-page scope.
- `init_all_live_sync_pollers()` in `core/pathway_sync.py` is also pre-existing dead code (a two-line alias with no callers). Its sibling `start_live_sync_poller` was removed on 2026-09-20 because the poller rewrite orphaned it.
