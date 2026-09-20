import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import ConfirmDialog from "../components/ConfirmDialog";
import FileBrowser from "../components/Sources/FileBrowser";
import ConnectorConfigForm, {
  defaultConfigFor,
} from "../components/Sources/ConnectorConfigForm";
import {
  IconBucket,
  IconFile,
  IconFolder,
  IconPause,
  IconPlay,
  IconPlus,
  IconServer,
  IconSources,
  IconSync,
  IconTrash,
  IconZap,
} from "../components/Icons";
import type {
  SourceConnectorRecord,
  SourceFileEntry,
  SourceRecord,
} from "../api";
import {
  ApiError,
  addSourceConnector,
  deleteSourceConnector,
  getSource,
  listSourceFiles,
  updateSourceConnector,
} from "../api";

function toApiError(err: unknown, code = "UNKNOWN"): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(500, {
    error: { code, message: err instanceof Error ? err.message : String(err) },
  });
}

type TabId = "connectors" | "files";

interface ConnectorCatalogItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  description: string;
}

/**
 * Apache NiFi connector catalogue. Every entry has a matching sync path in
 * src/ingestion_service/core/nifi_sync.py that writes into the source bucket.
 */
const EXTENDED_CATALOG: ConnectorCatalogItem[] = [
  {
    id: "google_drive",
    label: "Google Drive",
    icon: <IconFolder size={22} />,
    description: "Pull documents and folders from a Google Drive folder into this MinIO bucket.",
  },
  {
    id: "s3",
    label: "Amazon S3",
    icon: <IconBucket size={22} />,
    description: "Copy objects from an Amazon S3 bucket into this MinIO bucket.",
  },
  {
    id: "azure_blob",
    label: "Azure Blob Storage",
    icon: <IconServer size={22} />,
    description: "Copy blobs from an Azure storage container into this MinIO bucket.",
  },
];

function catalogItemFor(connectorType: string): ConnectorCatalogItem | undefined {
  return EXTENDED_CATALOG.find((item) => item.id === connectorType);
}

interface SourceDetailPageProps {
  routeSourceId?: string;
}

// 2026 Engine Source Detail Component
export default function SourceDetailPage({ routeSourceId }: SourceDetailPageProps) {
  const { id: paramId } = useParams<{ id: string }>();
  const id = routeSourceId ?? paramId;
  const navigate = useNavigate();

  const [source, setSource] = useState<SourceRecord | null>(null);
  const [files, setFiles] = useState<SourceFileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("connectors");

  const [togglingAll, setTogglingAll] = useState(false);
  const [togglingConnectorId, setTogglingConnectorId] = useState<string | null>(null);
  const [copiedBucket, setCopiedBucket] = useState(false);
  // Connector Modal State
  const [connectorModalOpen, setConnectorModalOpen] = useState(false);
  const [editingConnector, setEditingConnector] = useState<SourceConnectorRecord | null>(null);
  const [connectorToDelete, setConnectorToDelete] = useState<SourceConnectorRecord | null>(null);
  const [deletingConnector, setDeletingConnector] = useState(false);
  const [connectorForm, setConnectorForm] = useState<{
    connectorType: string;
    config: Record<string, unknown>;
    monitorMode: "live" | "scheduled";
    intervalValue: string;
    intervalUnit: "seconds" | "minutes";
  }>({
    connectorType: "google_drive",
    config: defaultConfigFor("google_drive"),
    monitorMode: "live",
    intervalValue: "",
    intervalUnit: "seconds",
  });
  const [savingConnector, setSavingConnector] = useState(false);

  const fetchSource = async () => {
    if (!id) return;
    try {
      const data = await getSource(id);
      setSource(data);
      setError(null);
    } catch (err) {
      setError(toApiError(err, "SOURCE_FETCH_FAILED"));
    }
  };

  const fetchFiles = async () => {
    if (!id) return;
    try {
      const res = await listSourceFiles(id);
      setFiles(res.files ?? []);
    } catch {
      // non-fatal
    }
  };

  useEffect(() => {
    if (!id) return;
    let mounted = true;

    async function init() {
      setLoading(true);
      try {
        const srcData = await getSource(id!);
        if (!mounted) return;
        setSource(srcData);
        if (srcData.connector_type === "local_filesystem" || srcData.source_type === "local_filesystem" || srcData.minio_bucket?.startsWith("local-") || srcData.source_type === "minio_manual" || srcData.connector_type === "manual_upload") {
          setActiveTab("files");
        }

        const fileRes = await listSourceFiles(id!).catch(() => ({ files: [] }));
        if (mounted) setFiles(fileRes.files ?? []);
      } catch (err) {
        if (mounted) setError(toApiError(err, "LOAD_FAILED"));
      } finally {
        if (mounted) setLoading(false);
      }
    }

    init();
    const interval = setInterval(() => {
      fetchSource();
      fetchFiles();
    }, 20000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [id]);

  const handleCopyBucket = () => {
    if (!source?.minio_bucket) return;
    navigator.clipboard.writeText(source.minio_bucket);
    setCopiedBucket(true);
    setTimeout(() => setCopiedBucket(false), 2000);
  };

  const handleToggleAllConnectors = async () => {
    if (!source) return;
    const connectors = source.connectors ?? [];
    if (connectors.length === 0) return;
    const resume = connectors.every((c) => c.enabled === false);
    setTogglingAll(true);
    try {
      // ponytail: one PATCH per connector, sequential. Each PATCH re-registers
      // the source poller, so parallel calls would race on the task registry.
      for (const c of connectors) {
        await updateSourceConnector(source.id, c.id, { enabled: resume });
      }
      setInfo(
        resume
          ? "All connectors resumed. Polling restarts now."
          : "All connectors paused. Polling stops until you resume.",
      );
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "TOGGLE_CONNECTORS_FAILED"));
    } finally {
      setTogglingAll(false);
    }
  };

  const handleOpenCatalogueConnector = (item: ConnectorCatalogItem) => {
    setEditingConnector(null);
    setConnectorForm({
      connectorType: item.id,
      config: defaultConfigFor(item.id),
      monitorMode: "live",
      intervalValue: "",
      intervalUnit: "seconds",
    });
    setConnectorModalOpen(true);
  };

  const handleEditConnector = (conn: SourceConnectorRecord) => {
    setEditingConnector(conn);
    const seconds = conn.sync_interval_seconds;
    const minutes = conn.sync_interval_minutes;
    setConnectorForm({
      connectorType: conn.connector_type,
      config: conn.config ?? {},
      monitorMode: (conn.monitor_mode as "live" | "scheduled") ?? "live",
      intervalValue: seconds ? String(seconds) : minutes ? String(minutes) : "",
      intervalUnit: seconds ? "seconds" : "minutes",
    });
    setConnectorModalOpen(true);
  };

  const handleSaveConnector = async (e: FormEvent) => {
    e.preventDefault();
    if (!source) return;
    setSavingConnector(true);

    try {
      const isScheduled = connectorForm.monitorMode === "scheduled";
      const parsed = isScheduled ? parseInt(connectorForm.intervalValue, 10) : NaN;
      const hasInterval = Number.isFinite(parsed) && parsed > 0;
      const useSeconds = connectorForm.intervalUnit === "seconds" && hasInterval;

      const body = {
        config: connectorForm.config,
        monitor_mode: connectorForm.monitorMode,
        sync_interval_seconds: useSeconds ? parsed : undefined,
        sync_interval_minutes:
          hasInterval && connectorForm.intervalUnit === "minutes" ? parsed : undefined,
      };

      if (editingConnector) {
        await updateSourceConnector(source.id, editingConnector.id, body);
        setInfo("Connector configuration updated.");
      } else {
        await addSourceConnector(source.id, {
          connector_type: connectorForm.connectorType,
          ...body,
        });
        setInfo("Connector attached. The first sync starts now.");
      }
      setConnectorModalOpen(false);
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "SAVE_CONNECTOR_FAILED"));
    } finally {
      setSavingConnector(false);
    }
  };

  const handleDeleteConnector = (conn: SourceConnectorRecord) => {
    setConnectorToDelete(conn);
  };

  const confirmDeleteConnector = async () => {
    if (!source || !connectorToDelete) return;
    setDeletingConnector(true);
    try {
      await deleteSourceConnector(source.id, connectorToDelete.id);
      setInfo("Connector removed. Files it already copied stay in the bucket.");
      setConnectorToDelete(null);
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "DELETE_CONNECTOR_FAILED"));
    } finally {
      setDeletingConnector(false);
    }
  };

  const handleToggleConnector = async (conn: SourceConnectorRecord) => {
    if (!source) return;
    setTogglingConnectorId(conn.id);
    try {
      await updateSourceConnector(source.id, conn.id, { enabled: !conn.enabled });
      setInfo(conn.enabled ? "Connector paused." : "Connector resumed. Polling restarts now.");
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "TOGGLE_CONNECTOR_FAILED"));
    } finally {
      setTogglingConnectorId(null);
    }
  };


  if (loading) {
    return (
      <div className="page" style={{ textAlign: "center", padding: "5rem 2rem" }}>
        <IconSync size={32} className="spin" style={{ color: "#58a6ff", marginBottom: "1rem" }} />
        <div style={{ color: "#e6edf3", fontWeight: 600 }}>Loading Data Source details...</div>
      </div>
    );
  }

  if (error && !source) {
    return (
      <div className="page">
        <div className="alert alert-error" style={{ marginBottom: "1.5rem" }}>
          <strong>{error.code}</strong>: {error.message}
        </div>
        <button type="button" className="btn btn-secondary" onClick={() => navigate("/sources")}>
          ← Back to Data Sources
        </button>
      </div>
    );
  }

  if (!source) return null;

  const connectorCount = source.connectors?.length ?? 0;
  const isLocalSource = source.connector_type === "local_filesystem" || source.source_type === "local_filesystem" || source.minio_bucket?.startsWith("local-") || source.is_local;
  const isManualMinioSource = source.connector_type === "manual_upload" || source.connector_type === "minio_manual" || source.source_type === "minio_manual" || source.is_manual;
  const allConnectorsPaused =
    connectorCount > 0 && (source.connectors ?? []).every((c) => c.enabled === false);
  return (
    <div className="page">
      {/* Top Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <div style={{ fontSize: "0.8rem", color: "#8b949e", marginBottom: "0.25rem" }}>
            Overview &gt; Sources &gt; <span style={{ color: "#c9d1d9" }}>{source.name}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
            <h1 style={{ fontSize: "1.75rem", fontWeight: 800, color: "#e6edf3", margin: 0, display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(56, 139, 253, 0.15)", color: "#58a6ff", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <IconSources size={22} />
              </div>
              <span>{source.name}</span>
            </h1>
            <StatusBadge status={source.status || "idle"} />

            {/* Bucket / Local Storage Pill */}
            {isManualMinioSource ? (
              <div
                onClick={handleCopyBucket}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  padding: "0.25rem 0.65rem",
                  borderRadius: "999px",
                  background: "rgba(56, 189, 248, 0.15)",
                  border: "1px solid rgba(56, 189, 248, 0.3)",
                  color: "#38bdf8",
                  fontSize: "0.8rem",
                  cursor: "pointer",
                }}
                title="MinIO Bucket (Manual Uploads)"
              >
                <IconBucket size={14} />
                <code style={{ fontWeight: 600 }}>{source.minio_bucket}</code>
                <span style={{ fontSize: "0.7rem", opacity: 0.8 }}>{copiedBucket ? "Copied" : "Copy"}</span>
              </div>
            ) : isLocalSource ? (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  padding: "0.25rem 0.65rem",
                  borderRadius: "999px",
                  background: "rgba(46, 160, 67, 0.15)",
                  border: "1px solid rgba(46, 160, 67, 0.3)",
                  color: "#7ee787",
                  fontSize: "0.8rem",
                }}
                title="Local Storage Path"
              >
                <IconFolder size={14} />
                <code style={{ fontWeight: 600 }}>storage/local_sources/{(source.config?.folder_name as string) || source.minio_bucket.replace("local-", "")}</code>
              </div>
            ) : (
              <div
                onClick={handleCopyBucket}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  padding: "0.25rem 0.65rem",
                  borderRadius: "999px",
                  background: "rgba(56, 139, 253, 0.1)",
                  border: "1px solid rgba(56, 139, 253, 0.25)",
                  color: "#58a6ff",
                  fontSize: "0.8rem",
                  cursor: "pointer",
                }}
                title="Click to copy MinIO bucket name"
              >
                <IconBucket size={13} />
                <code style={{ fontWeight: 600 }}>{source.minio_bucket}</code>
                <span>{copiedBucket ? "Copied" : "Copy"}</span>
              </div>
            )}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => navigate("/sources")}
          >
            ← Back to Sources
          </button>
          {connectorCount > 0 && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleToggleAllConnectors}
              disabled={togglingAll}
              title={
                allConnectorsPaused
                  ? "Resume polling for every connector of this bucket"
                  : "Pause polling for every connector of this bucket"
              }
              style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
            >
              {allConnectorsPaused ? (
                <IconPlay size={15} />
              ) : (
                <IconPause size={15} className={togglingAll ? "spin" : ""} />
              )}
              <span>
                {togglingAll
                  ? "Working..."
                  : allConnectorsPaused
                    ? "Resume All Connectors"
                    : "Pause All Connectors"}
              </span>
            </button>
          )}
        </div>
      </div>

      {/* Info / Error Alerts */}
      {info && (
        <div className="alert alert-info" style={{ marginBottom: "1.25rem" }}>
          <span>ℹ️ {info}</span>
          <button type="button" className="btn-close" onClick={() => setInfo(null)}>×</button>
        </div>
      )}
      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1.25rem" }}>
          <strong>{error.code}</strong>: {error.message}
          <button type="button" className="btn-close" onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Top Source Summary Metric Cards */}
      <div className="stats-overview-grid" style={{ marginBottom: "1.5rem" }}>
        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Source Status</div>
            <div className="stats-overview-value" style={{ textTransform: "capitalize", fontSize: "1.35rem" }}>
              {source.status || "Idle / Ready"}
            </div>
            <div className="stats-overview-subtext">
              Last updated: {source.updated_at ? new Date(source.updated_at).toLocaleTimeString() : "Recently"}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--blue">
            <IconSources size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Attached Connectors</div>
            <div className="stats-overview-value">{connectorCount}</div>
            <div className="stats-overview-subtext">
              {connectorCount === 0 ? "No active streams" : `${connectorCount} active ingestion streams`}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--green">
            <IconZap size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Total Synced Files</div>
            <div className="stats-overview-value">{source.total_files ?? 0}</div>
            <div className="stats-overview-subtext">
              {source.total_size_bytes ? `${(source.total_size_bytes / 1024).toFixed(1)} KB total size` : "In MinIO storage"}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--blue">
            <IconFile size={22} />
          </div>
        </div>

      </div>
      {/* MinIO Manual Source Information Banner */}
      {isManualMinioSource && (
        <div
          style={{
            padding: "1rem 1.25rem",
            borderRadius: "10px",
            background: "rgba(56, 189, 248, 0.1)",
            border: "1px solid rgba(56, 189, 248, 0.25)",
            color: "#38bdf8",
            marginBottom: "1.5rem",
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
          }}
        >
          <span style={{ fontSize: "1.4rem" }}>🪣</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>
              MinIO Manual File Upload Manager (Direct S3 Bucket)
            </div>
            <div style={{ fontSize: "0.82rem", color: "#7dd3fc", marginTop: "0.15rem" }}>
              Files are stored directly in MinIO S3 bucket <code>{source.minio_bucket}</code>. Upload, list and delete them below.
            </div>
          </div>
        </div>
      )}

      {/* Local File System Information Banner */}
      {isLocalSource && (
        <div
          style={{
            padding: "1rem 1.25rem",
            borderRadius: "10px",
            background: "rgba(46, 160, 67, 0.1)",
            border: "1px solid rgba(46, 160, 67, 0.25)",
            color: "#7ee787",
            marginBottom: "1.5rem",
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
          }}
        >
          <IconFolder size={22} />
          <div>
            <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>
              Legacy Local File System Source
            </div>
            <div style={{ fontSize: "0.82rem", color: "#a5d6a7", marginTop: "0.15rem" }}>
              Files are stored locally in <code>storage/local_sources/{(source.config?.folder_name as string) || source.minio_bucket.replace("local-", "")}</code>.
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation (Hidden for Local FS & MinIO Manual sources) */}
      {!isLocalSource && !isManualMinioSource && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.35rem",
            background: "rgba(11, 14, 20, 0.6)",
            border: "1px solid rgba(56, 68, 100, 0.45)",
            borderRadius: "10px",
            marginBottom: "1.75rem",
            width: "fit-content",
            backdropFilter: "blur(8px)",
          }}
        >
          <button
            type="button"
            onClick={() => setActiveTab("connectors")}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.55rem 1.1rem",
              borderRadius: "7px",
              border: "none",
              background: activeTab === "connectors" ? "linear-gradient(135deg, #388bfd 0%, #1f6feb 100%)" : "transparent",
              color: activeTab === "connectors" ? "#ffffff" : "#94a3b8",
              fontSize: "0.875rem",
              fontWeight: activeTab === "connectors" ? 600 : 500,
              cursor: "pointer",
              transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
              boxShadow: activeTab === "connectors" ? "0 2px 10px rgba(56, 139, 253, 0.35)" : "none",
            }}
          >
            <IconZap size={15} />
            <span>Connectors Catalogue</span>
            <span
              style={{
                fontSize: "0.72rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "999px",
                background: activeTab === "connectors" ? "rgba(255, 255, 255, 0.25)" : "rgba(255, 255, 255, 0.08)",
                color: activeTab === "connectors" ? "#ffffff" : "#8b949e",
                fontWeight: 600,
              }}
            >
              {connectorCount}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("files")}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.55rem 1.1rem",
              borderRadius: "7px",
              border: "none",
              background: activeTab === "files" ? "linear-gradient(135deg, #388bfd 0%, #1f6feb 100%)" : "transparent",
              color: activeTab === "files" ? "#ffffff" : "#94a3b8",
              fontSize: "0.875rem",
              fontWeight: activeTab === "files" ? 600 : 500,
              cursor: "pointer",
              transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
              boxShadow: activeTab === "files" ? "0 2px 10px rgba(56, 139, 253, 0.35)" : "none",
            }}
          >
            <IconFile size={15} />
            <span>Source Files</span>
            <span
              style={{
                fontSize: "0.72rem",
                padding: "0.15rem 0.5rem",
                borderRadius: "999px",
                background: activeTab === "files" ? "rgba(255, 255, 255, 0.25)" : "rgba(255, 255, 255, 0.08)",
                color: activeTab === "files" ? "#ffffff" : "#8b949e",
                fontWeight: 600,
              }}
            >
              {files.length}
            </span>
          </button>
        </div>
      )}

      {/* TAB 1: CONNECTORS CATALOGUE & ACTIVE CONNECTORS */}
      {!isLocalSource && !isManualMinioSource && activeTab === "connectors" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
          {/* Active Attached Connectors Section */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                Active Attached Connectors ({connectorCount})
              </h2>
            </div>

            {connectorCount === 0 ? (
              <div style={{ padding: "2.5rem 1.5rem", textAlign: "center", background: "rgba(17, 21, 30, 0.4)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                <IconZap size={32} style={{ color: "#58a6ff", marginBottom: "0.5rem" }} />
                <div style={{ fontSize: "0.95rem", fontWeight: 600, color: "#e6edf3", marginBottom: "0.25rem" }}>
                  No connectors attached to this source yet
                </div>
                <div style={{ fontSize: "0.8125rem", color: "#8b949e", marginBottom: "1rem" }}>
                  Select any integration from the catalogue below to begin streaming documents into MinIO bucket <code>{source.minio_bucket}</code>.
                </div>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "1rem" }}>
                {source.connectors?.map((conn) => (
                  <div
                    key={conn.id}
                    style={{
                      background: "rgba(17, 21, 30, 0.6)",
                      border: "1px solid rgba(88, 166, 253, 0.2)",
                      borderRadius: "12px",
                      padding: "1.15rem",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                    }}
                  >
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                          <span style={{ color: "#58a6ff", display: "inline-flex" }}>
                            {catalogItemFor(conn.connector_type)?.icon ?? <IconZap size={22} />}
                          </span>
                          <div>
                            <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#e6edf3" }}>
                              {catalogItemFor(conn.connector_type)?.label ??
                                conn.connector_type.replace(/_/g, " ")}
                            </div>
                            <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>
                              {conn.enabled === false ? (
                                <>
                                  Mode: <span style={{ color: "#d29922", fontWeight: 600 }}>Paused</span>
                                </>
                              ) : conn.monitor_mode === "scheduled" ? (
                                <>
                                  Mode:{" "}
                                  <span style={{ color: "#58a6ff", fontWeight: 600 }}>
                                    Scheduled every{" "}
                                    {conn.sync_interval_seconds
                                      ? `${conn.sync_interval_seconds}s`
                                      : `${conn.sync_interval_minutes || 5}m`}
                                  </span>
                                </>
                              ) : (
                                <>
                                  Mode: <span style={{ color: "#3fb950", fontWeight: 600 }}>Live polling</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                        <StatusBadge status={conn.enabled === false ? "paused" : conn.status || "idle"} />
                      </div>

                      <div style={{ fontSize: "0.78rem", color: "#8b949e", marginBottom: "1rem", background: "rgba(0, 0, 0, 0.2)", padding: "0.5rem 0.75rem", borderRadius: "6px" }}>
                        Last sync: {conn.last_sync_at ? new Date(conn.last_sync_at).toLocaleString() : "Never synced"}
                      </div>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: "0.75rem", borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleToggleConnector(conn)}
                        disabled={togglingConnectorId === conn.id}
                        title={conn.enabled === false ? "Resume scheduled polling for this connector" : "Stop polling this connector"}
                        style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
                      >
                        {conn.enabled === false ? <IconPlay size={12} /> : <IconPause size={12} />}
                        <span>
                          {togglingConnectorId === conn.id
                            ? "Working..."
                            : conn.enabled === false
                              ? "Resume"
                              : "Pause"}
                        </span>
                      </button>

                      <div style={{ display: "flex", gap: "0.4rem" }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleEditConnector(conn)}
                        >
                          Configure
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => handleDeleteConnector(conn)}
                          style={{ color: "#f85149" }}
                        >
                          <IconTrash size={13} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Connector Catalogue Grid */}
          <div>
            <div style={{ marginBottom: "1rem" }}>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                NiFi Connector Catalogue
              </h2>
              <div style={{ fontSize: "0.8rem", color: "#8b949e" }}>
                Attach one or more connectors to MinIO bucket <code>{source.minio_bucket}</code>
              </div>
            </div>

            {/* Grid of Catalogue Connectors */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "1rem" }}>
              {EXTENDED_CATALOG.map((item) => (
                <div
                  key={item.id}
                  onClick={() => handleOpenCatalogueConnector(item)}
                  style={{
                    background: "rgba(17, 21, 30, 0.5)",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                    borderRadius: "12px",
                    padding: "1.25rem",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                  }}
                  className="connector-cat-card"
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.6rem" }}>
                      <span style={{ color: "#58a6ff", display: "inline-flex" }}>{item.icon}</span>
                      <div>
                        <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#e6edf3" }}>
                          {item.label}
                        </div>
                      </div>
                    </div>
                    <p style={{ fontSize: "0.8125rem", color: "#8b949e", lineHeight: 1.4, margin: "0 0 1rem 0" }}>
                      {item.description}
                    </p>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: "0.75rem", borderTop: "1px solid rgba(255, 255, 255, 0.06)" }}>
                    <span style={{ fontSize: "0.75rem", color: "#3fb950", fontWeight: 600 }}>
                      Live and scheduled polling
                    </span>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: "0.75rem" }}
                    >
                      + Attach
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: BUCKET STORAGE FILES */}
      {(isLocalSource || isManualMinioSource || activeTab === "files") && (
        <FileBrowser
          sourceId={source?.id ?? id ?? ""}
          bucketName={source?.minio_bucket ?? ""}
          files={files}
          allowUpload={isLocalSource || isManualMinioSource}
          allowDelete={isLocalSource || isManualMinioSource}
          onError={(err) => setError(err)}
          onInfo={(msg) => console.log(msg)}
        />
      )}


      {/* CONNECTOR CONFIGURATION MODAL */}
      {connectorModalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            background: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(12px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1.5rem",
          }}
          onClick={() => setConnectorModalOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label={editingConnector ? "Configure connector" : "Attach connector"}
          onKeyDown={(e) => {
            if (e.key === "Escape") setConnectorModalOpen(false);
          }}
        >
          <div
            style={{
              width: "100%",
              maxWidth: "640px",
              maxHeight: "90vh",
              overflowY: "auto",
              background: "#111622",
              border: "1px solid rgba(88, 166, 253, 0.3)",
              borderRadius: "16px",
              padding: "1.75rem",
              boxShadow: "0 20px 50px rgba(0, 0, 0, 0.5), 0 0 30px rgba(56, 139, 253, 0.15)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <div>
                <h2 style={{ fontSize: "1.25rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                  {editingConnector
                    ? `Configure ${catalogItemFor(editingConnector.connector_type)?.label ?? editingConnector.connector_type}`
                    : `Attach ${catalogItemFor(connectorForm.connectorType)?.label ?? connectorForm.connectorType.replace(/_/g, " ")}`}
                </h2>
                <div style={{ fontSize: "0.78rem", color: "#8b949e" }}>
                  Destination MinIO Bucket: <code>{source.minio_bucket}</code>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setConnectorModalOpen(false)}
                aria-label="Close connector dialog"
                style={{ background: "none", border: "none", color: "#8b949e", fontSize: "1.25rem", cursor: "pointer", minWidth: "44px", minHeight: "44px" }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveConnector} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
              {/* Connector Type Form */}
              <ConnectorConfigForm
                connectorType={connectorForm.connectorType}
                config={connectorForm.config}
                onConfigChange={(newConfig) =>
                  setConnectorForm((prev) => ({ ...prev, config: newConfig }))
                }
              />

              {/* Polling Strategy */}
              <div style={{ paddingTop: "1rem", borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
                <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "#c9d1d9", marginBottom: "0.5rem" }}>
                  Sync Monitoring Strategy
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                  <label
                    style={{
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: `1px solid ${connectorForm.monitorMode === "live" ? "#58a6ff" : "rgba(255, 255, 255, 0.1)"}`,
                      background: connectorForm.monitorMode === "live" ? "rgba(56, 139, 253, 0.1)" : "rgba(0, 0, 0, 0.2)",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "0.5rem",
                    }}
                  >
                    <input
                      type="radio"
                      name="monitorMode"
                      value="live"
                      checked={connectorForm.monitorMode === "live"}
                      onChange={() => setConnectorForm((prev) => ({ ...prev, monitorMode: "live" }))}
                    />
                    <div>
                      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e6edf3" }}>Immediate live polling</div>
                      <div style={{ fontSize: "0.72rem", color: "#8b949e" }}>Short-interval background poll</div>
                    </div>
                  </label>

                  <label
                    style={{
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: `1px solid ${connectorForm.monitorMode === "scheduled" ? "#58a6ff" : "rgba(255, 255, 255, 0.1)"}`,
                      background: connectorForm.monitorMode === "scheduled" ? "rgba(56, 139, 253, 0.1)" : "rgba(0, 0, 0, 0.2)",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "0.5rem",
                    }}
                  >
                    <input
                      type="radio"
                      name="monitorMode"
                      value="scheduled"
                      checked={connectorForm.monitorMode === "scheduled"}
                      onChange={() => setConnectorForm((prev) => ({ ...prev, monitorMode: "scheduled" }))}
                    />
                    <div>
                      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e6edf3" }}>Scheduled polling</div>
                      <div style={{ fontSize: "0.72rem", color: "#8b949e" }}>Fixed interval in seconds or minutes</div>
                    </div>
                  </label>
                </div>
              </div>

              {connectorForm.monitorMode === "scheduled" && (
                <div>
                  <label
                    htmlFor="connector-interval"
                    style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "#c9d1d9", marginBottom: "0.4rem" }}
                  >
                    Polling interval *
                  </label>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                    <input
                      id="connector-interval"
                      type="number"
                      min={1}
                      max={connectorForm.intervalUnit === "seconds" ? 86400 : 1440}
                      value={connectorForm.intervalValue}
                      onChange={(e) => setConnectorForm((prev) => ({ ...prev, intervalValue: e.target.value }))}
                      placeholder={connectorForm.intervalUnit === "seconds" ? "30" : "15"}
                      required
                      style={{
                        width: "100%",
                        padding: "0.65rem 0.85rem",
                        borderRadius: "8px",
                        border: "1px solid rgba(56, 68, 100, 0.45)",
                        background: "rgba(11, 14, 20, 0.6)",
                        color: "#e6edf3",
                      }}
                    />
                    <select
                      aria-label="Polling interval unit"
                      value={connectorForm.intervalUnit}
                      onChange={(e) =>
                        setConnectorForm((prev) => ({
                          ...prev,
                          intervalUnit: e.target.value as "seconds" | "minutes",
                        }))
                      }
                      style={{
                        width: "100%",
                        padding: "0.65rem 0.85rem",
                        borderRadius: "8px",
                        border: "1px solid rgba(56, 68, 100, 0.45)",
                        background: "rgba(11, 14, 20, 0.6)",
                        color: "#e6edf3",
                        cursor: "pointer",
                      }}
                    >
                      <option value="seconds">Seconds (minimum 5)</option>
                      <option value="minutes">Minutes</option>
                    </select>
                  </div>
                  <p style={{ margin: "0.4rem 0 0", fontSize: "0.75rem", color: "#8b949e" }}>
                    {connectorForm.intervalUnit === "seconds"
                      ? "The connector polls the remote service every few seconds. Minimum 5 seconds."
                      : "The connector polls the remote service every few minutes."}
                  </p>
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1rem" }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setConnectorModalOpen(false)}
                  disabled={savingConnector}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={savingConnector}
                  style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
                >
                  {savingConnector ? <IconSync size={14} className="spin" /> : <IconPlus size={14} />}
                  <span>{savingConnector ? "Saving..." : editingConnector ? "Save Changes" : "Attach Connector"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* REMOVE CONNECTOR CONFIRMATION */}
      <ConfirmDialog
        open={connectorToDelete !== null}
        danger
        title="Remove this connector?"
        message={
          connectorToDelete
            ? `${catalogItemFor(connectorToDelete.connector_type)?.label ?? connectorToDelete.connector_type} stops polling for "${source.name}".`
            : ""
        }
        details={[
          "The connector and its polling schedule are deleted.",
          "Files it already copied stay in the MinIO bucket.",
        ]}
        confirmLabel="Remove connector"
        cancelLabel="Keep connector"
        busy={deletingConnector}
        onConfirm={confirmDeleteConnector}
        onCancel={() => setConnectorToDelete(null)}
      />
    </div>
  );
}
