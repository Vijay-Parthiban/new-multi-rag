import { FormEvent, useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import {
  ApiError,
  ConnectorOption,
  SourceRecord,
  SourceCreateRequest,
  SourceUpdateRequest,
  SourceFileEntry,
  PipelineRecord,
  createSource,
  deleteSource,
  getSource,
  listConnectors,
  listSourceFiles,
  listSources,
  listPipelines,
  updateSource,
  triggerSourceSync,
  linkSourceToPipeline,
  unlinkSourceFromPipeline,
} from "../api";

/* ── Connector-specific config field definitions ── */

const CONNECTOR_CONFIG_FIELDS: Record<string, { key: string; label: string; placeholder: string; type?: string; multiline?: boolean; required?: boolean }[]> = {
  google_drive: [
    { key: "folder_id", label: "Folder ID", placeholder: "1ABCxyz...", required: true },
    { key: "drive_id", label: "Shared Drive ID", placeholder: "0A... (optional)" },
    { key: "client_id", label: "Client ID", placeholder: "123456-xxx.apps.googleusercontent.com", required: true },
    { key: "client_secret", label: "Client Secret", placeholder: "GOCSPX-...", type: "password", required: true },
    { key: "refresh_token", label: "Refresh Token", placeholder: "1//0g...", type: "password", required: true },
    { key: "file_types", label: "File Types", placeholder: "pdf,docx,txt (comma-separated, leave empty for all)" },
  ],
  gcs: [
    { key: "bucket_name", label: "GCS Bucket Name", placeholder: "my-data-bucket", required: true },
    { key: "project_id", label: "Project ID", placeholder: "my-gcp-project", required: true },
    { key: "service_account_json", label: "Service Account JSON", placeholder: '{"type": "service_account", ...}', multiline: true, required: true },
    { key: "prefix", label: "Prefix Filter", placeholder: "folder/subfolder/ (optional)" },
  ],
  s3: [
    { key: "bucket_name", label: "S3 Bucket Name", placeholder: "my-s3-bucket", required: true },
    { key: "aws_access_key_id", label: "AWS Access Key ID", placeholder: "AKIA...", required: true },
    { key: "aws_secret_access_key", label: "AWS Secret Access Key", placeholder: "wJalr...", type: "password", required: true },
    { key: "region", label: "AWS Region", placeholder: "us-east-1", required: true },
    { key: "prefix", label: "Prefix Filter", placeholder: "path/to/files (optional)" },
  ],
  azure_blob: [
    { key: "container_name", label: "Container Name", placeholder: "my-container", required: true },
    { key: "connection_string", label: "Connection String", placeholder: "DefaultEndpointsProtocol=...", multiline: true, required: true },
    { key: "prefix", label: "Prefix Filter", placeholder: "folder/ (optional)" },
  ],
  sharepoint: [
    { key: "site_url", label: "SharePoint Site URL", placeholder: "https://yourorg.sharepoint.com/sites/MySite", required: true },
    { key: "drive_id", label: "Drive ID", placeholder: "b!...", required: true },
    { key: "client_id", label: "Client ID", placeholder: "xxx-xxx", required: true },
    { key: "client_secret", label: "Client Secret", placeholder: "...", type: "password", required: true },
    { key: "tenant_id", label: "Tenant ID", placeholder: "xxx-xxx-xxx", required: true },
  ],
};

/* ── Component ── */

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [connectors, setConnectors] = useState<ConnectorOption[]>([]);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<SourceRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [sourceFiles, setSourceFiles] = useState<SourceFileEntry[]>([]);
  const [currentPrefix, setCurrentPrefix] = useState<string>("");

  // Create modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createStep, setCreateStep] = useState<"select" | "configure">("select");
  const [newName, setNewName] = useState("");
  const [newConnectorType, setNewConnectorType] = useState<string>("");
  const [newMonitorMode, setNewMonitorMode] = useState<"live" | "scheduled">("scheduled");
  const [newSyncInterval, setNewSyncInterval] = useState<number>(10);
  const [newConfig, setNewConfig] = useState<Record<string, unknown>>({});

  // Edit source state
  const [editName, setEditName] = useState("");
  const [editConnectorType, setEditConnectorType] = useState<string>("");
  const [editMonitorMode, setEditMonitorMode] = useState<"live" | "scheduled">("scheduled");
  const [editSyncInterval, setEditSyncInterval] = useState<number | null>(null);
  const [editEnabled, setEditEnabled] = useState(true);
  const [editConfig, setEditConfig] = useState<Record<string, unknown>>({});

  // Pipeline linking
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkPipelineId, setLinkPipelineId] = useState<string>("");
  const [linkedPipelineIds, setLinkedPipelineIds] = useState<string[]>([]);

  // No auto-refresh needed — user triggers sync manually

  /* ── Loaders ── */

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [srcs, conns, pipes] = await Promise.all([
        listSources(),
        listConnectors(),
        listPipelines(),
      ]);
      setSources(srcs);
      setConnectors(conns);
      setPipelines(pipes);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSourceDetails = useCallback(async (sourceId: string) => {
    try {
      const source = await getSource(sourceId);
      setSelectedSource(source);
      setSelectedSourceId(sourceId);
      setEditName(source.name);
      setEditConnectorType(source.connector_type);
      setEditMonitorMode(source.monitor_mode);
      setEditSyncInterval(source.sync_interval_minutes ?? null);
      setEditEnabled(source.enabled);
      setEditConfig(source.config ?? {});
      setLinkedPipelineIds(source.pipeline_ids || []);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  }, []);

  const loadSourceFiles = useCallback(async (sourceId: string, prefix?: string) => {
    try {
      const res = await listSourceFiles(sourceId, prefix ?? currentPrefix);
      setSourceFiles(res.files);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  }, [currentPrefix]);

  /* ── Initial load ── */

  useEffect(() => {
    load();
  }, [load]);

  /* ── Select source handler ── */

  const handleSelectSource = useCallback(async (sourceId: string) => {
    setSelectedSourceId(sourceId);
    await Promise.all([
      loadSourceDetails(sourceId),
      loadSourceFiles(sourceId),
    ]);
  }, [loadSourceDetails, loadSourceFiles]);

  /* ── Create source flow ── */

  const openCreateModal = () => {
    setShowCreateModal(true);
    setCreateStep("select");
    setNewName("");
    setNewConnectorType("");
    setNewMonitorMode("scheduled");
    setNewSyncInterval(10);
    setNewConfig({});
    setError(null);
  };

  const closeCreateModal = () => {
    setShowCreateModal(false);
    setCreateStep("select");
  };

  const selectConnectorForCreate = (connectorId: string) => {
    setNewConnectorType(connectorId);
    setNewConfig({});
    setCreateStep("configure");
  };

  const handleNewConfigField = (key: string, value: string) => {
    setNewConfig((prev) => ({ ...prev, [key]: value }));
  };

  const handleCreateSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const body: SourceCreateRequest = {
      name: newName.trim(),
      connector_type: newConnectorType,
      monitor_mode: newMonitorMode,
      sync_interval_minutes: newMonitorMode === "scheduled" ? newSyncInterval : undefined,
      config: newConfig,
    };

    try {
      const created = await createSource(body);
      setInfo(`Source "${created.name}" created successfully.`);
      closeCreateModal();
      await load();
      setSelectedSourceId(created.id);
      await loadSourceDetails(created.id);
      await loadSourceFiles(created.id);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setSubmitting(false);
    }
  };

  /* ── Update source ── */

  const handleUpdate = async () => {
    if (!selectedSourceId) return;
    setSubmitting(true);
    setError(null);

    const body: SourceUpdateRequest = {
      name: editName.trim() || undefined,
      monitor_mode: editMonitorMode,
      sync_interval_minutes: editMonitorMode === "scheduled" ? editSyncInterval : undefined,
      enabled: editEnabled,
      config: Object.keys(editConfig).length > 0 ? editConfig : undefined,
    };

    try {
      await updateSource(selectedSourceId, body);
      setInfo("Source updated.");
      await load();
      await loadSourceDetails(selectedSourceId);
      await loadSourceFiles(selectedSourceId);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setSubmitting(false);
    }
  };

  /* ── Delete source ── */

  const handleDelete = async () => {
    if (!selectedSourceId) return;
    if (!window.confirm("Delete this source? This action cannot be undone.")) return;

    try {
      await deleteSource(selectedSourceId);
      setInfo("Source deleted.");
      setSelectedSourceId(null);
      setSelectedSource(null);
      setSourceFiles([]);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  };

  /* ── Sync ── */

  const handleTriggerSync = async () => {
    if (!selectedSourceId) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await triggerSourceSync(selectedSourceId);
      setInfo(`Sync triggered (${res.status}).`);
      await load();
      await loadSourceDetails(selectedSourceId);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setSubmitting(false);
    }
  };

  /* ── Pipeline linking ── */

  const openLinkModal = () => {
    setShowLinkModal(true);
    setLinkPipelineId("");
  };

  const handleLinkPipeline = async () => {
    if (!selectedSourceId || !linkPipelineId) return;
    try {
      await linkSourceToPipeline(selectedSourceId, linkPipelineId);
      setInfo("Pipeline linked to source.");
      setShowLinkModal(false);
      await loadSourceDetails(selectedSourceId);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  };

  const handleUnlinkPipeline = async (pipelineId: string) => {
    if (!selectedSourceId) return;
    if (!window.confirm("Unlink this pipeline from the source?")) return;
    try {
      await unlinkSourceFromPipeline(selectedSourceId, pipelineId);
      setInfo("Pipeline unlinked.");
      await loadSourceDetails(selectedSourceId);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  };

  /* ── File browsing ── */

  const handlePrefixChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const prefix = e.target.value;
    setCurrentPrefix(prefix);
    if (selectedSourceId) {
      await loadSourceFiles(selectedSourceId, prefix);
    }
  };

  const handleClearPrefix = async () => {
    setCurrentPrefix("");
    if (selectedSourceId) {
      await loadSourceFiles(selectedSourceId, "");
    }
  };

  /* ── Config field helpers ── */

  const handleEditConfigField = (key: string, value: string) => {
    setEditConfig((prev) => ({ ...prev, [key]: value }));
  };

  /* ── Find pipeline name helper ── */

  const getPipelineName = (pipelineId: string): string => {
    const p = pipelines.find((p) => p.id === pipelineId);
    return p ? p.name : pipelineId.slice(0, 8);
  };

  const getConnectorLabel = (type: string): string => {
    const c = connectors.find((c) => c.id === type);
    return c ? c.label : type;
  };

  /* ── Unlinked pipelines (for link modal) ── */
  const unlinkedPipelines = pipelines.filter(
    (p) => !linkedPipelineIds.includes(p.id)
  );

  /* ── Render ── */
  return (
    <div className="page">
      <PageHeader
        title="Sources"
        description="Connect external data sources via Airbyte connectors to ingest files into your RAG pipelines"
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Sources" },
        ]}
        actions={
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={openCreateModal}
            >
              + Create New Source
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => load()}
              disabled={loading}
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}
      {info && <div className="alert alert-info">{info}</div>}

      <div className="sources-layout">
        {/* ── Sources list (left panel) ── */}
        <section className="panel sources-list-panel">
          <div className="panel-header">
            <h2 className="panel-title">All Sources</h2>
            <span className="panel-toolbar-label">{sources.length} source{sources.length !== 1 ? "s" : ""}</span>
          </div>

          {loading && sources.length === 0 ? (
            <p className="muted" style={{ padding: "1rem" }}>Loading sources…</p>
          ) : sources.length === 0 ? (
            <div className="panel-empty">
              <div className="empty-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                  <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                </svg>
              </div>
              <p className="muted">No sources configured yet.</p>
              <button
                type="button"
                className="btn btn-primary"
                onClick={openCreateModal}
              >
                + Create Your First Source
              </button>
            </div>
          ) : (
            <ul className="sources-list">
              {sources.map((source) => (
                <li
                  key={source.id}
                  className={selectedSourceId === source.id ? "active" : ""}
                >
                  <button
                    type="button"
                    className="sources-list-item"
                    onClick={() => handleSelectSource(source.id)}
                  >
                    <div className="sources-list-item-info">
                      <strong>{source.name}</strong>
                      <span className="muted">
                        {getConnectorLabel(source.connector_type)} · {source.monitor_mode === "live" ? "Live" : "Scheduled"}
                      </span>
                      <span className="muted mono" style={{ fontSize: "0.7rem" }}>
                        {source.minio_bucket}
                      </span>
                    </div>
                    <div className="sources-list-item-actions">
                      <StatusBadge
                        status={
                          !source.enabled
                            ? "disabled"
                            : source.status === "connected"
                            ? "synced"
                            : source.status === "syncing"
                            ? "running"
                            : source.status === "error"
                            ? "failed"
                            : "pending"
                        }
                      />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* ── Source detail / editor (right panel) ── */}
        {selectedSource && selectedSourceId ? (
          <section className="panel source-detail-panel">
            <div className="panel-header">
              <h2 className="panel-title">{selectedSource.name}</h2>
              <div className="source-header-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={handleTriggerSync}
                  disabled={submitting || !editEnabled}
                  title="Trigger sync now"
                >
                  Sync Now
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger-ghost"
                  onClick={handleDelete}
                  disabled={submitting}
                  title="Delete source"
                >
                  Delete
                </button>
              </div>
            </div>

            <div className="form-body">
              {/* ── Basic info ── */}
              <div className="form-row">
                <div>
                  <label className="field-label" htmlFor="source-name">Name</label>
                  <input
                    id="source-name"
                    className="input"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    disabled={submitting}
                  />
                </div>
                <div>
                  <label className="field-label">Connector Type</label>
                  <div className="input" style={{ opacity: 0.7, cursor: "default" }}>
                    {getConnectorLabel(editConnectorType)}
                  </div>
                </div>
              </div>

              {/* ── Enabled toggle + Monitor Mode ── */}
              <div className="form-row">
                <div>
                  <label className="field-label">Status</label>
                  <label className="check-row" style={{ marginTop: "0.375rem" }}>
                    <input
                      type="checkbox"
                      checked={editEnabled}
                      onChange={(e) => setEditEnabled(e.target.checked)}
                      disabled={submitting}
                    />
                    <span>Source enabled (syncs active)</span>
                  </label>
                </div>
                <div>
                  <label className="field-label" htmlFor="source-monitor-mode">
                    Monitoring Mode
                  </label>
                  <select
                    id="source-monitor-mode"
                    className="input"
                    value={editMonitorMode}
                    onChange={(e) => setEditMonitorMode(e.target.value as "live" | "scheduled")}
                    disabled={submitting}
                  >
                    <option value="live">Live (Continuous — poll for changes)</option>
                    <option value="scheduled">Scheduled (cron-based interval)</option>
                  </select>
                </div>
              </div>

              {/* ── Sync interval (scheduled only) ── */}
              {editMonitorMode === "scheduled" && (
                <div className="form-row">
                  <div>
                    <label className="field-label" htmlFor="source-sync-interval">
                      Sync Interval (minutes)
                    </label>
                    <input
                      id="source-sync-interval"
                      type="number"
                      className="input"
                      value={editSyncInterval ?? ""}
                      onChange={(e) => setEditSyncInterval(e.target.value ? Number(e.target.value) : null)}
                      disabled={submitting || editMonitorMode !== "scheduled"}
                      min={1}
                      placeholder="Required for scheduled"
                    />
                    <p className="field-hint">How often to poll the connector for new/changed files</p>
                  </div>
                  <div>
                    <label className="field-label">MinIO Bucket</label>
                    <div className="input mono" style={{ opacity: 0.7, cursor: "default", fontSize: "0.8rem" }}>
                      {selectedSource.minio_bucket}
                    </div>
                    <p className="field-hint">Auto-created per-source storage bucket</p>
                  </div>
                </div>
              )}

              {/* ── Connector-specific config ── */}
              {CONNECTOR_CONFIG_FIELDS[editConnectorType] && (
                <div className="source-config-section">
                  <h3 className="source-config-title">Connector Configuration</h3>
                  {CONNECTOR_CONFIG_FIELDS[editConnectorType].map((field) => (
                    <div key={field.key} style={{ marginBottom: "0.5rem" }}>
                      <label className="field-label" htmlFor={`edit-cfg-${field.key}`}>
                        {field.label}
                      </label>
                      {field.multiline ? (
                        <textarea
                          id={`edit-cfg-${field.key}`}
                          className="input"
                          rows={3}
                          value={(editConfig[field.key] as string) ?? ""}
                          onChange={(e) => handleEditConfigField(field.key, e.target.value)}
                          placeholder={field.placeholder}
                          disabled={submitting}
                        />
                      ) : (
                        <input
                          id={`edit-cfg-${field.key}`}
                          className="input"
                          type={field.type ?? "text"}
                          value={(editConfig[field.key] as string) ?? ""}
                          onChange={(e) => handleEditConfigField(field.key, e.target.value)}
                          placeholder={field.placeholder}
                          disabled={submitting}
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* ── General JSON fallback for unsupported connectors ── */}
              {!CONNECTOR_CONFIG_FIELDS[editConnectorType] && (
                <div className="form-row">
                  <div>
                    <label className="field-label" htmlFor="edit-source-config">
                      Configuration (JSON)
                    </label>
                    <textarea
                      id="edit-source-config"
                      className="input"
                      rows={4}
                      value={JSON.stringify(editConfig, null, 2)}
                      onChange={(e) => {
                        try { setEditConfig(JSON.parse(e.target.value)); }
                        catch { /* ignore */ }
                      }}
                      disabled={submitting}
                      placeholder='{"key": "value"}'
                    />
                  </div>
                </div>
              )}

              {/* ── Linked pipelines ── */}
              <div className="source-config-section">
                <div className="source-pipelines-header">
                  <h3 className="source-config-title">Linked Pipelines</h3>
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    onClick={openLinkModal}
                    disabled={unlinkedPipelines.length === 0}
                  >
                    + Link Pipeline
                  </button>
                </div>
                {linkedPipelineIds.length === 0 ? (
                  <p className="field-hint">
                    No pipelines linked. Link a pipeline to trigger RAG indexing when files change in this source.
                  </p>
                ) : (
                  <ul className="source-pipeline-links">
                    {linkedPipelineIds.map((pid) => (
                      <li key={pid}>
                        <div className="source-pipeline-link-info">
                          <span className="mono">{getPipelineName(pid)}</span>
                          <span className="muted" style={{ fontSize: "0.75rem" }}>{pid.slice(0, 8)}</span>
                        </div>
                        <button
                          type="button"
                          className="btn btn-sm btn-danger-ghost"
                          onClick={() => handleUnlinkPipeline(pid)}
                        >
                          Unlink
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* ── Save / Cancel ── */}
              <div className="form-row actions" style={{ marginTop: "1rem" }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleUpdate}
                  disabled={submitting || !editName.trim()}
                >
                  {submitting ? "Saving…" : "Save Changes"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    if (selectedSource) {
                      loadSourceDetails(selectedSource.id);
                    }
                  }}
                  disabled={submitting}
                >
                  Reset
                </button>
              </div>
            </div>
          </section>
        ) : !loading ? (
          <section className="panel source-detail-panel">
            <div className="panel-empty">
              <p className="muted">Select a source from the list to view and edit its configuration.</p>
            </div>
          </section>
        ) : null}
      </div>

      {/* ── Source files panel ── */}
      {selectedSource && (
        <section className="panel source-files-panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Files in <span className="mono">{selectedSource.minio_bucket}</span></h2>
              <p className="field-hint" style={{ margin: "0.2rem 0 0" }}>
                Files synced from the {getConnectorLabel(selectedSource.connector_type)} connector
              </p>
            </div>
            <div className="source-files-toolbar">
              <input
                type="text"
                className="input input-sm"
                placeholder="Filter by prefix..."
                value={currentPrefix}
                onChange={handlePrefixChange}
                disabled={submitting}
              />
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={handleClearPrefix}
                disabled={currentPrefix === ""}
              >
                Clear
              </button>
            </div>
          </div>
          {sourceFiles.length === 0 ? (
            <div className="panel-empty">
              <p className="muted">No files found in this source's MinIO bucket.</p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleTriggerSync}
                disabled={submitting || !editEnabled}
              >
                Trigger Sync to Fetch Files
              </button>
            </div>
          ) : (
            <div className="repo-table-wrap">
              <table className="repo-table">
                <thead>
                  <tr>
                    <th>File Key</th>
                    <th>Size</th>
                    <th>Last Modified</th>
                  </tr>
                </thead>
                <tbody>
                  {sourceFiles.map((file) => (
                    <tr key={file.key}>
                      <td>
                        <span className="mono" style={{ fontSize: "0.8rem" }}>{file.key}</span>
                      </td>
                      <td className="muted mono">
                        {file.size >= 1024 * 1024
                          ? (file.size / (1024 * 1024)).toFixed(2) + " MB"
                          : file.size >= 1024
                          ? (file.size / 1024).toFixed(2) + " KB"
                          : file.size + " B"}
                      </td>
                      <td className="muted mono">
                        {new Date(file.last_modified).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* ════════════════════════════════════════
          CREATE SOURCE MODAL
         ════════════════════════════════════════ */}
      {showCreateModal && (
        <div className="modal-overlay" onClick={closeCreateModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">
                {createStep === "select" ? "Select Connector Type" : "Configure Source"}
              </h2>
              <button
                type="button"
                className="modal-close"
                onClick={closeCreateModal}
                aria-label="Close"
              >
                &times;
              </button>
            </div>

            {createStep === "select" ? (
              <div className="modal-body">
                <p className="muted" style={{ marginBottom: "1rem" }}>
                  Choose an Airbyte connector to use as your data source. Each source gets its own MinIO bucket.
                </p>
                <div className="connector-grid">
                  {connectors.map((conn) => {
                    const configFields = CONNECTOR_CONFIG_FIELDS[conn.id];
                    const isAvailable = !!configFields || conn.id === "http_api";
                    return (
                      <button
                        key={conn.id}
                        type="button"
                        className={`connector-card${!isAvailable ? " connector-card--disabled" : ""}`}
                        onClick={() => isAvailable && selectConnectorForCreate(conn.id)}
                        disabled={!isAvailable}
                        title={!isAvailable ? "Configuration form not yet implemented" : conn.description}
                      >
                        <span className="connector-card-name">{conn.label}</span>
                        <span className="connector-card-desc">{conn.description}</span>
                        {!isAvailable && (
                          <span className="connector-card-badge">Coming Soon</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              <form onSubmit={handleCreateSubmit}>
                <div className="modal-body">
                  <p className="muted" style={{ marginBottom: "1rem" }}>
                    Configure your {getConnectorLabel(newConnectorType)} source
                  </p>

                  {/* Source Name */}
                  <label className="field-label" htmlFor="new-source-name">Source Name</label>
                  <input
                    id="new-source-name"
                    className="input"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="e.g., legal-google-drive"
                    required
                    disabled={submitting}
                    autoFocus
                  />
                  <p className="field-hint">A unique name for this source. Used to create the MinIO bucket.</p>

                  {/* Connector config fields */}
                  {CONNECTOR_CONFIG_FIELDS[newConnectorType] && (
                    <div className="source-config-section">
                      <h3 className="source-config-title">{getConnectorLabel(newConnectorType)} Settings</h3>
                      {CONNECTOR_CONFIG_FIELDS[newConnectorType].filter(f => f.required).length > 0 && (
                        <p className="field-hint">All required fields must be filled</p>
                      )}
                      {CONNECTOR_CONFIG_FIELDS[newConnectorType].map((field) => (
                        <div key={field.key} style={{ marginBottom: "0.5rem" }}>
                          <label className="field-label" htmlFor={`new-cfg-${field.key}`}>
                            {field.label}
                            {field.required && <span className="required-mark">*</span>}
                          </label>
                          {field.multiline ? (
                            <textarea
                              id={`new-cfg-${field.key}`}
                              className="input"
                              rows={3}
                              value={(newConfig[field.key] as string) ?? ""}
                              onChange={(e) => handleNewConfigField(field.key, e.target.value)}
                              placeholder={field.placeholder}
                              required={field.required}
                              disabled={submitting}
                            />
                          ) : (
                            <input
                              id={`new-cfg-${field.key}`}
                              className="input"
                              type={field.type ?? "text"}
                              value={(newConfig[field.key] as string) ?? ""}
                              onChange={(e) => handleNewConfigField(field.key, e.target.value)}
                              placeholder={field.placeholder}
                              required={field.required}
                              disabled={submitting}
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* General JSON fallback */}
                  {!CONNECTOR_CONFIG_FIELDS[newConnectorType] && (
                    <div className="form-row">
                      <div>
                        <label className="field-label" htmlFor="new-source-config">Configuration (JSON)</label>
                        <textarea
                          id="new-source-config"
                          className="input"
                          rows={4}
                          value={JSON.stringify(newConfig, null, 2)}
                          onChange={(e) => {
                            try { setNewConfig(JSON.parse(e.target.value)); }
                            catch { /* ignore */ }
                          }}
                          disabled={submitting}
                          placeholder='{"key": "value"}'
                        />
                        <p className="field-hint">Connector-specific config as JSON</p>
                      </div>
                    </div>
                  )}

                  {/* Monitor Mode */}
                  <div className="form-row" style={{ marginTop: "1rem" }}>
                    <div>
                      <label className="field-label" htmlFor="new-monitor-mode">Monitoring Mode</label>
                      <select
                        id="new-monitor-mode"
                        className="input"
                        value={newMonitorMode}
                        onChange={(e) => setNewMonitorMode(e.target.value as "live" | "scheduled")}
                        disabled={submitting}
                      >
                        <option value="live">Live (Continuous)</option>
                        <option value="scheduled">Scheduled (Interval)</option>
                      </select>
                    </div>
                    {newMonitorMode === "scheduled" && (
                      <div>
                        <label className="field-label" htmlFor="new-sync-interval">Sync Interval (minutes)</label>
                        <input
                          id="new-sync-interval"
                          type="number"
                          className="input"
                          value={newSyncInterval}
                          onChange={(e) => setNewSyncInterval(Number(e.target.value))}
                          min={1}
                          required
                          disabled={submitting}
                        />
                      </div>
                    )}
                  </div>
                </div>

                <div className="modal-footer">
                  <button type="button" className="btn btn-secondary" onClick={() => setCreateStep("select")} disabled={submitting}>
                    Back
                  </button>
                  <div>
                    <button type="button" className="btn btn-secondary" onClick={closeCreateModal} disabled={submitting} style={{ marginRight: "0.5rem" }}>
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="btn btn-primary"
                      disabled={
                        submitting ||
                        !newName.trim() ||
                        !newConnectorType
                      }
                    >
                      {submitting ? "Creating…" : "Create Source"}
                    </button>
                  </div>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════
          LINK PIPELINE MODAL
         ════════════════════════════════════════ */}
      {showLinkModal && (
        <div className="modal-overlay" onClick={() => setShowLinkModal(false)}>
          <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Link Pipeline to Source</h2>
              <button
                type="button"
                className="modal-close"
                onClick={() => setShowLinkModal(false)}
                aria-label="Close"
              >
                &times;
              </button>
            </div>
            <div className="modal-body">
              <p className="muted" style={{ marginBottom: "1rem" }}>
                When files change in this source, linked pipelines will automatically re-index the affected files.
              </p>
              {unlinkedPipelines.length === 0 ? (
                <p className="field-hint">All pipelines are already linked to this source.</p>
              ) : (
                <>
                  <label className="field-label" htmlFor="link-pipeline-select">Select Pipeline</label>
                  <select
                    id="link-pipeline-select"
                    className="input"
                    value={linkPipelineId}
                    onChange={(e) => setLinkPipelineId(e.target.value)}
                  >
                    <option value="">Choose a pipeline…</option>
                    {unlinkedPipelines.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} — {p.description}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => setShowLinkModal(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleLinkPipeline}
                disabled={!linkPipelineId}
              >
                Link Pipeline
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
