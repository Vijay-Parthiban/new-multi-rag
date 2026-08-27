import { FormEvent, useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import ConnectorConfigForm, {
  defaultConfigFor,
  getConnectorSchema,
} from "../components/Sources/ConnectorConfigForm";
import {
  IconCheckCircle,
  IconFile,
  IconPipeline,
  IconPlus,
  IconRadio,
  IconSources,
  IconSync,
  IconZap,
} from "../components/Icons";
import { formatRelativeTime, formatSize } from "../utils/format";
import type {
  ConnectorOption,
  PipelineLinkInfo,
  PipelineRecord,
  SourceConnectorRecord,
  SourceRecord,
} from "../api";
import {
  ApiError,
  addSourceConnector,
  deleteSourceConnector,
  deleteSourceFile,
  getSource,
  linkSourceToPipeline,
  listConnectors,
  listPipelines,
  listSourceFiles,
  triggerConnectorSync,
  triggerSourceSync,
  unlinkSourceFromPipeline,
  updateSource,
  updateSourceConnector,
} from "../api";

function toApiError(err: unknown, code = "UNKNOWN"): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(500, {
    error: { code, message: err instanceof Error ? err.message : String(err) },
  });
}

type TabId = "connectors" | "files" | "pipeline";


const CORE_CONNECTOR_CATALOG = [
  { id: "google_drive", label: "Google Drive", icon: "📁", description: "Sync documents, PDFs & folders directly from Google Drive" },
  { id: "azure_blob", label: "Azure Blob Storage", icon: "☁️", description: "Stream files from Microsoft Azure Blob Storage containers" },
  { id: "s3", label: "Amazon S3", icon: "🪣", description: "Pull objects from AWS S3 buckets into MinIO" },
  { id: "google_sheets", label: "Google Sheets", icon: "📊", description: "Import tabular data directly from Google Sheets" },
  { id: "onedrive", label: "Microsoft OneDrive", icon: "💾", description: "Ingest document libraries from Microsoft OneDrive" },
  { id: "sharepoint", label: "Microsoft SharePoint", icon: "🌐", description: "Ingest document libraries & lists from SharePoint sites" },
];

function MonitorBadge({ mode }: { mode: "live" | "scheduled" }) {
  return (
    <span className={`status-badge ${mode === "live" ? "status-running" : "status-synced"}`}>
      {mode === "live" ? "Live" : "Scheduled"}
    </span>
  );
}

interface ConnectorFormState {
  connectorType: string;
  config: Record<string, unknown>;
  monitorMode: "live" | "scheduled";
  syncIntervalMinutes: string;
}

const EMPTY_CONNECTOR_FORM: ConnectorFormState = {
  connectorType: "",
  config: {},
  monitorMode: "live",
  syncIntervalMinutes: "",
};

interface LinkFormState {
  pipelineId: string;
  monitorMode: "live" | "scheduled";
  syncIntervalMinutes: string;
}

const EMPTY_LINK_FORM: LinkFormState = {
  pipelineId: "",
  monitorMode: "live",
  syncIntervalMinutes: "",
};

interface SourceMonitorForm {
  connectorMonitorMode: "live" | "scheduled";
  connectorSyncInterval: string;
  pipelineMonitorMode: "live" | "scheduled";
  pipelineSyncInterval: string;
}

export default function SourceDetailPage({
  routeSourceId,
}: {
  routeSourceId: string;
}) {
  const navigate = useNavigate();

  const [source, setSource] = useState<SourceRecord | null>(null);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [catalog, setCatalog] = useState<ConnectorOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [tab, setTab] = useState<TabId>("connectors");
  const connectorModalTitleId = useId();
  const linkModalTitleId = useId();

  // Connector management modal
  const [connectorModalOpen, setConnectorModalOpen] = useState(false);
  const [editingConnector, setEditingConnector] = useState<SourceConnectorRecord | null>(null);
  const [connectorForm, setConnectorForm] = useState<ConnectorFormState>(EMPTY_CONNECTOR_FORM);
  const [connectorSubmitting, setConnectorSubmitting] = useState(false);

  // Files
  const [files, setFiles] = useState<{ key: string; size: number; last_modified: string }[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);

  // Pipeline linking
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [linkForm, setLinkForm] = useState<LinkFormState>(EMPTY_LINK_FORM);

  // Source RAG Polling Mode
  const [monitorForm, setMonitorForm] = useState<SourceMonitorForm | null>(null);
  const [monitorSaving, setMonitorSaving] = useState(false);

  const reloadSource = async (initial = false) => {
    if (initial && !source) setLoading(true);
    try {
      const [sourceData, pipelinesData, connectorsData] = await Promise.all([
        getSource(routeSourceId),
        listPipelines(),
        listConnectors(),
      ]);
      setSource(sourceData);
      setPipelines(pipelinesData);
      setCatalog(connectorsData);
    } catch (err) {
      setError(toApiError(err, "LOAD_FAILED"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reloadSource(true);
  }, [routeSourceId]);
  useEffect(() => {
    if (source) {
      setMonitorForm({
        connectorMonitorMode: source.connector_monitor_mode ?? "live",
        connectorSyncInterval: source.connector_sync_interval_minutes?.toString() ?? "",
        pipelineMonitorMode: source.pipeline_monitor_mode ?? "live",
        pipelineSyncInterval: source.pipeline_sync_interval_minutes?.toString() ?? "",
      });
    }
  }, [source]);

  const loadFiles = async () => {
    setFilesLoading(true);
    try {
      const res = await listSourceFiles(routeSourceId);
      setFiles(res.files);
    } catch (err) {
      setError(toApiError(err, "LIST_FILES_FAILED"));
    } finally {
      setFilesLoading(false);
    }
  };

  useEffect(() => {
    loadFiles();
  }, [tab, routeSourceId]);

  if (loading && !source) {
    return (
      <div className="page" style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p className="muted">Loading source details...</p>
      </div>
    );
  }

  if (error && !source) {
    return (
      <div className="page">
        <div className="alert alert-error" role="alert">
          <strong>{error.code}</strong>: {error.message}
        </div>
        <button type="button" className="btn btn-secondary" onClick={() => navigate("/sources")}>
          Back to sources
        </button>
      </div>
    );
  }

  if (!source) return null;

  const connectorLabel = (id: string) =>
    catalog.find((c) => c.id === id)?.label ??
    CORE_CONNECTOR_CATALOG.find((c) => c.id === id)?.label ??
    id;

  const getPipelineName = (pipelineId: string) =>
    pipelines.find((p) => p.id === pipelineId)?.name ?? pipelineId;

  const handleSelectCatalogueConnector = (typeId: string) => {
    setEditingConnector(null);
    setConnectorForm({
      connectorType: typeId,
      config: defaultConfigFor(typeId),
      monitorMode: "live",
      syncIntervalMinutes: "",
    });
    setError(null);
    setConnectorModalOpen(true);
  };

  const handleAddConnector = () => {
    const firstType = CORE_CONNECTOR_CATALOG[0]?.id ?? "google_drive";
    handleSelectCatalogueConnector(firstType);
  };

  const handleEditConnector = (connector: SourceConnectorRecord) => {
    setEditingConnector(connector);
    setConnectorForm({
      connectorType: connector.connector_type,
      config: connector.config ?? {},
      monitorMode: connector.monitor_mode ?? "live",
      syncIntervalMinutes: connector.sync_interval_minutes?.toString() ?? "",
    });
    setError(null);
    setConnectorModalOpen(true);
  };

  const handleSubmitConnector = async (e: FormEvent) => {
    e.preventDefault();
    if (!source) return;
    const config = connectorForm.config;
    const syncInterval = connectorForm.syncIntervalMinutes
      ? Number(connectorForm.syncIntervalMinutes)
      : null;
    setConnectorSubmitting(true);
    setError(null);
    try {
      if (editingConnector) {
        await updateSourceConnector(source.id, editingConnector.id, {
          config,
          monitor_mode: connectorForm.monitorMode,
          sync_interval_minutes: syncInterval,
        });
        setInfo(`Connector updated.`);
      } else {
        await addSourceConnector(source.id, {
          connector_type: connectorForm.connectorType,
          config,
          monitor_mode: connectorForm.monitorMode,
          sync_interval_minutes: syncInterval,
        });
        setInfo(`Connector added.`);
      }
      setConnectorModalOpen(false);
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "CONNECTOR_SAVE_FAILED"));
    } finally {
      setConnectorSubmitting(false);
    }
  };

  const handleDeleteConnector = async (connector: SourceConnectorRecord) => {
    if (!source) return;
    if (!window.confirm(`Delete connector "${connectorLabel(connector.connector_type)}"?`)) return;
    try {
      await deleteSourceConnector(source.id, connector.id);
      setInfo("Connector removed.");
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "DELETE_CONNECTOR_FAILED"));
    }
  };

  const handleConnectorSync = async (connector: SourceConnectorRecord) => {
    if (!source) return;
    try {
      await triggerConnectorSync(source.id, connector.id);
      setInfo(`Sync triggered for connector ${connectorLabel(connector.connector_type)}.`);
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "CONNECTOR_SYNC_FAILED"));
    }
  };

  const handleSourceSync = async () => {
    if (!source) return;
    try {
      await triggerSourceSync(source.id);
      setInfo("Sync triggered for all connectors on this MinIO bucket.");
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "SOURCE_SYNC_FAILED"));
    }
  };

  const handleDeleteFile = async (key: string) => {
    if (!source) return;
    if (!window.confirm(`Delete file "${key}" from MinIO bucket?`)) return;
    try {
      await deleteSourceFile(source.id, key);
      setInfo(`File deleted.`);
      await loadFiles();
    } catch (err) {
      setError(toApiError(err, "DELETE_FILE_FAILED"));
    }
  };

  const handleLinkPipeline = async (e: FormEvent) => {
    e.preventDefault();
    if (!source || !linkForm.pipelineId) return;
    try {
      await linkSourceToPipeline(source.id, linkForm.pipelineId, {
        monitor_mode: linkForm.monitorMode,
        sync_interval_minutes: linkForm.syncIntervalMinutes
          ? Number(linkForm.syncIntervalMinutes)
          : null,
      });
      setInfo("Linked to pipeline.");
      setLinkModalOpen(false);
      setLinkForm(EMPTY_LINK_FORM);
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "LINK_PIPELINE_FAILED"));
    }
  };

  const handleUnlinkPipeline = async (link: PipelineLinkInfo) => {
    if (!source) return;
    const name = getPipelineName(link.pipeline_id);
    if (!window.confirm(`Unlink from pipeline "${name}"?`)) return;
    try {
      await unlinkSourceFromPipeline(source.id, link.pipeline_id);
      setInfo("Pipeline unlinked.");
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "UNLINK_PIPELINE_FAILED"));
    }
  };

  const handleSaveMonitor = async (e: FormEvent) => {
    e.preventDefault();
    if (!source || !monitorForm) return;
    setMonitorSaving(true);
    try {
      await updateSource(source.id, {
        connector_monitor_mode: monitorForm.connectorMonitorMode,
        connector_sync_interval_minutes: monitorForm.connectorSyncInterval
          ? Number(monitorForm.connectorSyncInterval)
          : null,
        pipeline_monitor_mode: monitorForm.pipelineMonitorMode,
        pipeline_sync_interval_minutes: monitorForm.pipelineSyncInterval
          ? Number(monitorForm.pipelineSyncInterval)
          : null,
      });
      setInfo("Source & RAG polling modes updated.");
      await reloadSource();
    } catch (err) {
      setError(toApiError(err, "UPDATE_MONITOR_FAILED"));
    } finally {
      setMonitorSaving(false);
    }
  };

  const renderConnectors = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Configured connectors list */}
      <div className="panel">
        <div className="panel-toolbar">
          <span className="panel-toolbar-label">
            Configured Connectors ({source.connectors.length})
          </span>
          <button type="button" className="btn btn-sm btn-primary" onClick={handleAddConnector}>
            + Add Custom Connector
          </button>
        </div>
        {source.connectors.length === 0 ? (
          <div className="panel-empty">
            <IconSources className="empty-icon" size={40} />
            <p>No connectors linked to this MinIO bucket yet</p>
            <p className="muted">
              Select a connector from the catalogue below to configure file polling into{" "}
              <span className="mono">{source.minio_bucket}</span>.
            </p>
          </div>
        ) : (
          <div className="repo-table-wrap">
            <table className="repo-table">
              <thead>
                <tr>
                  <th>Connector</th>
                  <th>File Polling Mode</th>
                  <th>Status</th>
                  <th>Last Sync</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {source.connectors.map((connector) => (
                  <tr key={connector.id}>
                    <td>
                      <span className="file-name-cell" style={{ fontWeight: 600 }}>
                        {connectorLabel(connector.connector_type)}
                      </span>
                      {!connector.enabled && (
                        <span className="status-badge status-deleted" style={{ marginLeft: "0.5rem" }}>
                          disabled
                        </span>
                      )}
                      {connector.error_message && (
                        <div className="file-meta muted">{connector.error_message.slice(0, 120)}</div>
                      )}
                    </td>
                    <td>
                      <MonitorBadge mode={connector.monitor_mode ?? "live"} />
                      {connector.sync_interval_minutes && (
                        <span className="file-meta" style={{ display: "block" }}>
                          every {connector.sync_interval_minutes} min
                        </span>
                      )}
                    </td>
                    <td>
                      <StatusBadge status={connector.status} />
                    </td>
                    <td className="muted">
                      {connector.last_sync_at ? formatRelativeTime(connector.last_sync_at) : "never"}
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          type="button"
                          className="btn btn-sm btn-secondary"
                          onClick={() => handleConnectorSync(connector)}
                        >
                          Sync Now
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => handleEditConnector(connector)}
                        >
                          Configure Polling
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-danger-ghost"
                          onClick={() => handleDeleteConnector(connector)}
                        >
                          Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Interactive Connector Catalogue Grid */}
      {/* Interactive Connector Catalogue Grid */}
      <div className="panel">
        <div className="panel-toolbar">
          <span className="panel-toolbar-label" style={{ fontWeight: 600 }}>
            Connector Catalogue — Attach to MinIO Bucket <code className="mono">{source.minio_bucket}</code>
          </span>
        </div>
        <div className="form-body">
          <p className="muted" style={{ marginBottom: "1.25rem" }}>
            Select an integration connector below to configure automated sync schedules from external storage or SaaS applications.
          </p>
          <div className="catalog-grid">
            {CORE_CONNECTOR_CATALOG.map((cat) => (
              <div key={cat.id} className="catalog-card">
                <div>
                  <div className="catalog-card-header">
                    <div className="catalog-card-icon">{cat.icon}</div>
                    <h3 className="catalog-card-title">{cat.label}</h3>
                  </div>
                  <p className="catalog-card-desc">{cat.description}</p>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  style={{ width: "100%", justifyContent: "center", display: "inline-flex", alignItems: "center", gap: "0.375rem" }}
                  onClick={() => handleSelectCatalogueConnector(cat.id)}
                >
                  <IconPlus size={14} />
                  Configure & Attach
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  const renderFiles = () => (
    <div className="panel">
      <div className="panel-toolbar">
        <span className="panel-toolbar-label">
          {filesLoading ? "Loading…" : `${files.length} file${files.length === 1 ? "" : "s"} in bucket ${source.minio_bucket}`}
        </span>
        <button type="button" className="btn btn-sm btn-secondary" onClick={loadFiles}>
          Refresh Files
        </button>
      </div>
      {filesLoading ? (
        <p className="panel-empty muted">Loading files from MinIO…</p>
      ) : files.length === 0 ? (
        <div className="panel-empty">
          <p>No files in MinIO bucket <span className="mono">{source.minio_bucket}</span></p>
          <p className="muted">
            Configure a connector from the Catalogue to automatically poll files into this bucket.
          </p>
        </div>
      ) : (
        <div className="repo-table-wrap">
          <table className="repo-table">
            <thead>
              <tr>
                <th>File Key</th>
                <th>Size</th>
                <th>Last Modified</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.key}>
                  <td>
                    <span className="mono">{file.key}</span>
                  </td>
                  <td>{formatSize(file.size)}</td>
                  <td className="muted">{formatRelativeTime(file.last_modified)}</td>
                  <td>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-danger-ghost"
                        onClick={() => handleDeleteFile(file.key)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  const renderPipeline = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Linked Pipelines */}
      <div className="panel">
        <div className="panel-toolbar">
          <span className="panel-toolbar-label">Linked RAG Pipelines</span>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => {
              const available = pipelines.filter(
                (p) => !source.pipeline_links.some((l) => l.pipeline_id === p.id),
              );
              setLinkForm({
                pipelineId: available[0]?.id ?? "",
                monitorMode: "live",
                syncIntervalMinutes: "",
              });
              setLinkModalOpen(true);
            }}
          >
            + Link to Pipeline
          </button>
        </div>
        {source.pipeline_links.length === 0 ? (
          <div className="panel-empty">
            <p>Not linked to any pipeline</p>
            <p className="muted">
              Link this MinIO bucket to a RAG pipeline to automatically ingest files into vector search.
            </p>
          </div>
        ) : (
          <div className="repo-table-wrap">
            <table className="repo-table">
              <thead>
                <tr>
                  <th>Pipeline</th>
                  <th>RAG File Polling Mode</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {source.pipeline_links.map((link) => (
                  <tr key={link.pipeline_id}>
                    <td>
                      <span className="file-name-cell" style={{ fontWeight: 600 }}>
                        {getPipelineName(link.pipeline_id)}
                      </span>
                    </td>
                    <td>
                      <MonitorBadge mode={link.monitor_mode ?? "live"} />
                      {link.sync_interval_minutes && (
                        <span className="file-meta" style={{ display: "block" }}>
                          every {link.sync_interval_minutes} min
                        </span>
                      )}
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          type="button"
                          className="btn btn-sm btn-danger-ghost"
                          onClick={() => handleUnlinkPipeline(link)}
                        >
                          Unlink
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Bucket RAG Polling Mode Config */}
      <div className="panel">
        <div className="panel-toolbar">
          <span className="panel-toolbar-label">MinIO Bucket RAG Polling Mode</span>
        </div>
        {monitorForm && (
          <form className="form-body" onSubmit={handleSaveMonitor}>
            <p className="muted" style={{ marginBottom: "1rem" }}>
              Configure how this MinIO bucket delivers contents and CRUD updates to linked RAG pipelines.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
              <div>
                <label className="field-label" htmlFor="src-pipeline-mode">
                  RAG Delivery Polling Mode
                </label>
                <select
                  id="src-pipeline-mode"
                  value={monitorForm.pipelineMonitorMode}
                  onChange={(e) =>
                    setMonitorForm((prev) =>
                      prev ? { ...prev, pipelineMonitorMode: e.target.value as "live" | "scheduled" } : prev,
                    )
                  }
                >
                  <option value="live">Live Polling (Push on CRUD events)</option>
                  <option value="scheduled">Scheduled Polling (Interval batch)</option>
                </select>
              </div>
              {monitorForm.pipelineMonitorMode === "scheduled" && (
                <div>
                  <label className="field-label" htmlFor="src-pipeline-interval">
                    Poll Interval (minutes)
                  </label>
                  <input
                    id="src-pipeline-interval"
                    type="number"
                    min={1}
                    value={monitorForm.pipelineSyncInterval}
                    placeholder="15"
                    onChange={(e) =>
                      setMonitorForm((prev) =>
                        prev ? { ...prev, pipelineSyncInterval: e.target.value } : prev,
                      )
                    }
                  />
                </div>
              )}
            </div>
            <div className="form-actions" style={{ marginTop: "1rem" }}>
              <button type="submit" className="btn btn-secondary" disabled={monitorSaving}>
                {monitorSaving ? "Saving…" : "Save MinIO Bucket RAG Polling Mode"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );

  return (
    <div className="page">
      <PageHeader
        title={source.name}
        description={`MinIO bucket: ${source.minio_bucket}`}
        breadcrumbs={[
          { label: "Sources", to: "/sources" },
          { label: source.name, to: `/sources/${source.id}` },
        ]}
        actions={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleSourceSync}
              style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}
            >
              <IconSync size={15} />
              Sync All Connectors
            </button>
            <button type="button" className="btn btn-primary" onClick={() => navigate("/sources")}>
              Back to Sources
            </button>
          </>
        }
      />

      {error && (
        <div className="alert alert-error" role="alert">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}
      {info && <div className="alert alert-info" role="status">{info}</div>}

      {/* Overview Stat Cards Row */}
      <div className="stats-overview-grid">
        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Source Status</div>
            <div style={{ marginTop: "0.25rem" }}>
              <StatusBadge status={source.status} />
            </div>
            {source.error_message ? (
              <div className="stats-overview-subtext" style={{ color: "var(--danger)" }}>
                {source.error_message}
              </div>
            ) : (
              <div className="stats-overview-subtext">
                {source.last_sync_at ? `Last sync: ${formatRelativeTime(source.last_sync_at)}` : "Ready"}
              </div>
            )}
          </div>
          <div className="stats-overview-icon stats-icon--blue">
            <IconCheckCircle size={20} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Connectors Attached</div>
            <div className="stats-overview-value">{source.connectors.length}</div>
            <div className="stats-overview-subtext">
              {source.connectors.map((c) => connectorLabel(c.connector_type)).join(", ") || "None attached"}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--purple">
            <IconZap size={20} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">RAG Delivery Polling</div>
            <div style={{ marginTop: "0.25rem" }}>
              <MonitorBadge mode={source.pipeline_monitor_mode ?? "live"} />
            </div>
            <div className="stats-overview-subtext">
              {source.pipeline_sync_interval_minutes
                ? `Every ${source.pipeline_sync_interval_minutes}m batch`
                : "Real-time CRUD push"}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--amber">
            <IconRadio size={20} />
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
      <nav className="sources-tabs-nav" aria-label="Source sections">
        <button
          type="button"
          className={`sources-tab-btn${tab === "connectors" ? " active" : ""}`}
          onClick={() => setTab("connectors")}
        >
          <IconZap size={16} />
          Connectors Catalogue
          <span className="sources-tab-badge">{source.connectors.length}</span>
        </button>
        <button
          type="button"
          className={`sources-tab-btn${tab === "files" ? " active" : ""}`}
          onClick={() => setTab("files")}
        >
          <IconFile size={16} />
          Bucket Files
          <span className="sources-tab-badge">{files.length}</span>
        </button>
        <button
          type="button"
          className={`sources-tab-btn${tab === "pipeline" ? " active" : ""}`}
          onClick={() => setTab("pipeline")}
        >
          <IconPipeline size={16} />
          RAG Pipelines
          <span className="sources-tab-badge">{source.pipeline_links.length}</span>
        </button>
      </nav>

      {tab === "connectors" && renderConnectors()}
      {tab === "files" && renderFiles()}
      {tab === "pipeline" && renderPipeline()}

      {/* Connector add/edit modal */}
      {connectorModalOpen && (
        <div className="modal-overlay" onClick={() => setConnectorModalOpen(false)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={connectorModalTitleId}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 className="modal-title" id={connectorModalTitleId}>
                {editingConnector ? "Configure Connector" : "Add Connector from Catalogue"}
              </h2>
              <button
                type="button"
                className="modal-close"
                onClick={() => setConnectorModalOpen(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <form className="modal-body" onSubmit={handleSubmitConnector}>
              {!editingConnector && (
                <div>
                  <label className="field-label" htmlFor="connector-type">
                    Selected Connector Type
                  </label>
                  <select
                    id="connector-type"
                    value={connectorForm.connectorType}
                    onChange={(e) =>
                      setConnectorForm((prev) => ({
                        ...prev,
                        connectorType: e.target.value,
                        config: defaultConfigFor(e.target.value),
                      }))
                    }
                  >
                    {CORE_CONNECTOR_CATALOG.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.icon} {c.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div style={{ marginTop: "0.75rem" }}>
                <label className="field-label">Connector Configuration</label>
                <ConnectorConfigForm
                  connectorType={connectorForm.connectorType}
                  config={connectorForm.config}
                  onConfigChange={(newConfig) =>
                    setConnectorForm((prev) => ({ ...prev, config: newConfig }))
                  }
                />
              </div>

              <div style={{ marginTop: "1rem", paddingTop: "1rem", borderTop: "1px solid var(--border)" }}>
                <label className="field-label" htmlFor="connector-monitor-mode">
                  File Polling Mode (Connector → MinIO Bucket)
                </label>
                <select
                  id="connector-monitor-mode"
                  value={connectorForm.monitorMode}
                  onChange={(e) =>
                    setConnectorForm((prev) => ({
                      ...prev,
                      monitorMode: e.target.value as "live" | "scheduled",
                    }))
                  }
                >
                  <option value="live">Live Polling (Continuous / Real-time)</option>
                  <option value="scheduled">Scheduled Polling (Interval batch)</option>
                </select>

                {connectorForm.monitorMode === "scheduled" && (
                  <div style={{ marginTop: "0.5rem" }}>
                    <label className="field-label" htmlFor="connector-poll-interval">
                      Poll Interval (minutes)
                    </label>
                    <input
                      id="connector-poll-interval"
                      type="number"
                      min={1}
                      className="form-input"
                      placeholder="15"
                      value={connectorForm.syncIntervalMinutes}
                      onChange={(e) =>
                        setConnectorForm((prev) => ({
                          ...prev,
                          syncIntervalMinutes: e.target.value,
                        }))
                      }
                    />
                  </div>
                )}
              </div>

              <div className="modal-footer" style={{ marginTop: "1.5rem" }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setConnectorModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={connectorSubmitting}>
                  {connectorSubmitting ? "Saving…" : editingConnector ? "Save Connector" : "Add Connector"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Link to pipeline modal */}
      {linkModalOpen && (
        <div className="modal-overlay" onClick={() => setLinkModalOpen(false)}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={linkModalTitleId}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 className="modal-title" id={linkModalTitleId}>
                Link MinIO Bucket to Pipeline
              </h2>
              <button
                type="button"
                className="modal-close"
                onClick={() => setLinkModalOpen(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <form className="modal-body" onSubmit={handleLinkPipeline}>
              <div>
                <label className="field-label" htmlFor="link-pipeline-id">
                  Target Pipeline
                </label>
                <select
                  id="link-pipeline-id"
                  value={linkForm.pipelineId}
                  onChange={(e) =>
                    setLinkForm((prev) => ({ ...prev, pipelineId: e.target.value }))
                  }
                  required
                >
                  <option value="" disabled>
                    Select a pipeline
                  </option>
                  {pipelines
                    .filter((p) => !source.pipeline_links.some((l) => l.pipeline_id === p.id))
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.qdrant_collection})
                      </option>
                    ))}
                </select>
              </div>

              <div style={{ marginTop: "0.75rem" }}>
                <label className="field-label" htmlFor="link-monitor-mode">
                  RAG Polling Mode for this Pipeline Link
                </label>
                <select
                  id="link-monitor-mode"
                  value={linkForm.monitorMode}
                  onChange={(e) =>
                    setLinkForm((prev) => ({
                      ...prev,
                      monitorMode: e.target.value as "live" | "scheduled",
                    }))
                  }
                >
                  <option value="live">Live Polling (Push CRUD events immediately)</option>
                  <option value="scheduled">Scheduled Polling (Interval batch)</option>
                </select>
              </div>

              {linkForm.monitorMode === "scheduled" && (
                <div style={{ marginTop: "0.5rem" }}>
                  <label className="field-label" htmlFor="link-sync-interval">
                    Poll Interval (minutes)
                  </label>
                  <input
                    id="link-sync-interval"
                    type="number"
                    min={1}
                    placeholder="15"
                    value={linkForm.syncIntervalMinutes}
                    onChange={(e) =>
                      setLinkForm((prev) => ({
                        ...prev,
                        syncIntervalMinutes: e.target.value,
                      }))
                    }
                  />
                </div>
              )}

              <div className="modal-footer" style={{ marginTop: "1.5rem" }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setLinkModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={!linkForm.pipelineId}>
                  Link Pipeline
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
