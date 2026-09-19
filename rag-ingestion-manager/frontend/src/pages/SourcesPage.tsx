import { FormEvent, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import ConfirmDialog from "../components/ConfirmDialog";
import FileBrowser from "../components/Sources/FileBrowser";
import {
  IconArrowRight,
  IconBucket,
  IconCheckCircle,
  IconCopy,
  IconServer,
  IconFolder,
  IconGrid,
  IconList,
  IconPlus,
  IconRadio,
  IconSearch,
  IconSources,
  IconSync,
  IconTrash,
  IconUpload,
  IconZap,
} from "../components/Icons";
import {
  ApiError,
  SourceConnectorRecord,
  SourceRecord,
  createSource,
  deleteSource,
  listSources,
  triggerSourceSync,
} from "../api";

function toApiError(err: unknown, code = "UNKNOWN"): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(500, {
    error: { code, message: err instanceof Error ? err.message : String(err) },
  });
}

/* ── Connector glyph — one vector icon per NiFi connector ── */
function ConnectorGlyph({ type, size = 13 }: { type?: string; size?: number }) {
  const t = (type ?? "").toLowerCase();
  if (t.includes("drive")) return <IconFolder size={size} />;
  if (t.includes("s3")) return <IconBucket size={size} />;
  if (t.includes("azure")) return <IconServer size={size} />;
  return <IconZap size={size} />;
}

/* ── Connector status summary ── */
interface StatusSummary {
  connected: number;
  syncing: number;
  errored: number;
  disabled: number;
  other: number;
}

export function summarizeConnectors(connectors: SourceConnectorRecord[]): StatusSummary {
  const summary: StatusSummary = { connected: 0, syncing: 0, errored: 0, disabled: 0, other: 0 };
  if (!connectors) return summary;

  for (const c of connectors) {
    if (c.enabled === false) {
      summary.disabled += 1;
      continue;
    }
    const st = (c.status || "").toLowerCase();
    if (st === "connected" || st === "active" || st === "ready" || st === "idle") {
      summary.connected += 1;
    } else if (st === "syncing" || st === "processing" || st === "indexing") {
      summary.syncing += 1;
    } else if (st === "error" || st === "failed" || !!c.error_message) {
      summary.errored += 1;
    } else {
      summary.other += 1;
    }
  }
  return summary;
}

/* ── Source card ── */
function SourceCard({
  source,
  onNavigate,
  onSync,
  onDelete,
  onOpenFiles,
  syncing,
  deleting,
}: {
  source: SourceRecord;
  onNavigate: (id: string) => void;
  onSync: (id: string) => void;
  onDelete: (id: string, name: string) => void;
  onOpenFiles?: (source: SourceRecord) => void;
  syncing: boolean;
  deleting: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const connectorCount = source.connectors?.length ?? 0;
  const isLocal = source.connector_type === "local_filesystem" || source.source_type === "local_filesystem" || source.minio_bucket.startsWith("local-") || source.is_local;
  const isManual = source.connector_type === "manual_upload" || source.connector_type === "minio_manual" || source.source_type === "minio_manual" || source.is_manual;
  const folderName = (source.config?.folder_name as string) || source.minio_bucket.replace("local-", "");

  const handleCopyBucket = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(source.minio_bucket);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onNavigate(source.id);
    }
  };

  return (
    <article
      className="source-card"
      role="button"
      tabIndex={0}
      aria-label={`Open source ${source.name}`}
      onClick={() => onNavigate(source.id)}
      onKeyDown={handleKeyDown}
    >
      {/* Top Banner & Header */}
      <div className="source-card-header">
        <div className="source-card-title">
          <div className="source-card-icon">
            <IconSources size={20} />
          </div>
          <div>
            <h3 className="source-card-name">{source.name}</h3>
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.15rem" }}>
              <span className="source-status-dot" data-status={source.status || "idle"} />
              <span style={{ fontSize: "0.75rem", color: "#8b949e", textTransform: "capitalize" }}>
                {source.status || "Idle / Ready"}
              </span>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <StatusBadge status={source.status || "idle"} />
          <IconArrowRight className="source-card-arrow" size={16} />
        </div>
      </div>

      {/* Meta Stats & MinIO Bucket Tag */}
      {/* Meta Stats & MinIO Bucket / Local FS Tag */}
      <div className="source-card-meta">
        {isManual ? (
          <div className="source-card-stat">
            <span className="source-card-stat-value" style={{ color: "#38bdf8", fontSize: "0.85rem" }}>MinIO</span>
            <span className="source-card-stat-label">Manual Upload</span>
          </div>
        ) : isLocal ? (
          <div className="source-card-stat">
            <span className="source-card-stat-value" style={{ color: "#7ee787", display: "inline-flex" }}><IconFolder size={13} /></span>
            <span className="source-card-stat-label">Local System</span>
          </div>
        ) : (
          <div className="source-card-stat">
            <span className="source-card-stat-value">{connectorCount}</span>
            <span className="source-card-stat-label">{connectorCount === 1 ? "connector" : "connectors"}</span>
          </div>
        )}
        <div className="source-card-divider" />

        {isLocal ? (
          <div className="source-card-bucket" title={`Local Storage Path: storage/local_sources/${folderName}`}>
            <span style={{ color: "#3fb950", display: "inline-flex", fontSize: "0.85rem" }}>
              📁
            </span>
            <span className="source-card-bucket-code" style={{ color: "#7ee787" }}>storage/local_sources/{folderName}</span>
          </div>
        ) : (
          <div className="source-card-bucket" title={`MinIO Bucket: ${source.minio_bucket}`}>
            <span style={{ color: "#58a6ff", display: "inline-flex" }}>
              <IconBucket size={14} />
            </span>
            <span className="source-card-bucket-code">{source.minio_bucket}</span>
            <button
              type="button"
              onClick={handleCopyBucket}
              className="source-card-copy-btn"
              title="Copy bucket name"
              aria-label="Copy bucket name"
            >
              {copied ? <IconCheckCircle size={12} style={{ color: "#3fb950" }} /> : <IconCopy size={12} />}
            </button>
          </div>
        )}
      </div>

      {/* Attached Connectors Brand Badges Row */}
      <div style={{ marginTop: "0.85rem", marginBottom: "0.85rem" }}>
        {isManual ? (
          <div className="source-card-empty-connectors" style={{ borderColor: "rgba(56, 189, 248, 0.25)", background: "rgba(56, 189, 248, 0.08)" }}>
            <span style={{ color: "#38bdf8", fontWeight: 500, display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <IconUpload size={13} /> Manual upload source — files land in this MinIO bucket
            </span>
          </div>
        ) : isLocal ? (
          <div className="source-card-empty-connectors" style={{ borderColor: "rgba(46, 160, 67, 0.25)", background: "rgba(46, 160, 67, 0.08)" }}>
            <span style={{ color: "#7ee787", fontWeight: 500, display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
              <IconFolder size={13} /> Legacy local file system source
            </span>
          </div>
        ) : connectorCount === 0 ? (
          <div className="source-card-empty-connectors">
            <span>+ No connectors configured</span>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap" }}>
            {source.connectors?.slice(0, 4).map((c) => (
              <span
                key={c.id}
                style={{
                  fontSize: "0.75rem",
                  padding: "0.2rem 0.55rem",
                  borderRadius: "6px",
                  background: "rgba(255, 255, 255, 0.05)",
                  border: "1px solid rgba(255, 255, 255, 0.1)",
                  color: "#c9d1d9",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.3rem",
                }}
              >
                <ConnectorGlyph type={c.connector_type} />
                <span style={{ fontWeight: 500 }}>{c.connector_type.replace(/_/g, " ")}</span>
              </span>
            ))}
            {connectorCount > 4 && (
              <span style={{ fontSize: "0.75rem", color: "#8b949e" }}>+{connectorCount - 4} more</span>
            )}
          </div>
        )}
      </div>


      {/* Actions Toolbar */}
      <div className="source-card-actions" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => onSync(source.id)}
          disabled={syncing}
          style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}
        >
          <IconSync size={13} className={syncing ? "spin" : ""} />
          <span>{syncing ? "Syncing..." : "Sync Now"}</span>
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          {onOpenFiles && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                onOpenFiles(source);
              }}
              title={isManual ? "Upload files into this MinIO bucket" : "Browse files in this MinIO bucket"}
              aria-label={isManual ? `Upload files to ${source.name}` : `Browse files in ${source.name}`}
              style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
            >
              {isManual ? <IconUpload size={13} /> : <IconFolder size={13} />}
              <span>{isManual ? "Upload Files" : "Files"}</span>
            </button>
          )}

          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onDelete(source.id, source.name)}
            disabled={deleting}
            title="Delete source and its MinIO bucket"
            aria-label={`Delete source ${source.name}`}
            style={{ color: "#f85149" }}
          >
            <IconTrash size={14} />
          </button>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => onNavigate(source.id)}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem", color: "#58a6ff" }}
          >
            <span>Manage</span>
            <IconArrowRight size={13} />
          </button>
        </div>
      </div>
    </article>
  );
}

/* ── Source Table View ── */
function SourceTable({
  sources,
  onNavigate,
  onSync,
  onDelete,
  onOpenFiles,
  syncingId,
  deletingId,
}: {
  sources: SourceRecord[];
  onNavigate: (id: string) => void;
  onSync: (id: string) => void;
  onDelete: (id: string, name: string) => void;
  onOpenFiles?: (source: SourceRecord) => void;
  syncingId: string | null;
  deletingId: string | null;
}) {
  return (
    <div className="table-responsive" style={{ borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
      <table className="table" style={{ margin: 0 }}>
        <thead>
          <tr>
            <th>Source Name</th>
            <th>Storage Location</th>
            <th>Status</th>
            <th>Connectors</th>
            <th>Last Updated</th>
            <th style={{ textAlign: "right" }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => {
            const connectorCount = s.connectors?.length ?? 0;
            const isLocal = s.connector_type === "local_filesystem" || s.source_type === "local_filesystem" || s.minio_bucket.startsWith("local-");
            const isManualRow = s.connector_type === "manual_upload" || s.connector_type === "minio_manual" || s.source_type === "minio_manual" || s.is_manual;
            const folderName = (s.config?.folder_name as string) || s.minio_bucket.replace("local-", "");
            return (
              <tr
                key={s.id}
                style={{ cursor: "pointer" }}
                onClick={() => onNavigate(s.id)}
              >
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                    <div className="source-card-icon" style={{ width: "32px", height: "32px" }}>
                      {isLocal ? <IconFolder size={16} /> : <IconSources size={16} />}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600, color: "#e6edf3" }}>{s.name}</div>
                      <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>ID: {s.id.slice(0, 8)}...</div>
                    </div>
                  </div>
                </td>
                <td>
                  {isLocal ? (
                    <code style={{ fontSize: "0.8rem", color: "#7ee787", background: "rgba(46, 160, 67, 0.15)", padding: "0.2rem 0.5rem", borderRadius: "6px" }}>
                      storage/local_sources/{folderName}
                    </code>
                  ) : (
                    <code style={{ fontSize: "0.8rem", color: "#58a6ff", background: "rgba(56, 139, 253, 0.1)", padding: "0.2rem 0.5rem", borderRadius: "6px" }}>
                      {s.minio_bucket}
                    </code>
                  )}
                </td>
                <td>
                  <StatusBadge status={s.status || "idle"} />
                </td>
                <td>
                  <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e6edf3" }}>
                    {connectorCount}
                  </span>{" "}
                  <span style={{ fontSize: "0.75rem", color: "#8b949e" }}>connected</span>
                </td>
                <td>
                  <span style={{ fontSize: "0.8rem", color: "#8b949e" }}>
                    {s.updated_at ? new Date(s.updated_at).toLocaleString() : "Recently"}
                  </span>
                </td>
                <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                  <div style={{ display: "inline-flex", gap: "0.4rem" }}>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => onSync(s.id)}
                      disabled={syncingId === s.id}
                      title="Sync now"
                      aria-label={`Sync source ${s.name}`}
                    >
                      <IconSync size={12} className={syncingId === s.id ? "spin" : ""} />
                    </button>
                    {onOpenFiles && (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => onOpenFiles(s)}
                        title={isManualRow ? "Upload files into this MinIO bucket" : "Browse files in this MinIO bucket"}
                        aria-label={isManualRow ? `Upload files to ${s.name}` : `Browse files in ${s.name}`}
                        style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
                      >
                        {isManualRow ? <IconUpload size={12} /> : <IconFolder size={12} />}
                        <span>{isManualRow ? "Upload" : "Files"}</span>
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => onNavigate(s.id)}
                    >
                      Manage
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => onDelete(s.id, s.name)}
                      disabled={deletingId === s.id}
                      title="Delete source and its MinIO bucket"
                      aria-label={`Delete source ${s.name}`}
                      style={{ color: "#f85149" }}
                    >
                      <IconTrash size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── Stats overview dashboard ── */
function StatsOverview({
  sources,
  activeFilter,
  onSelectFilter,
}: {
  sources: SourceRecord[];
  activeFilter: string;
  onSelectFilter: (filter: "all" | "active" | "syncing" | "error") => void;
}) {
  const totalSources = sources.length;
  const activeSources = sources.filter((s) => s.enabled !== false).length;
  const syncingSources = sources.filter((s) => s.status === "syncing" || s.status === "processing").length;
  const totalConnectors = sources.reduce((acc, s) => acc + (s.connectors?.length ?? 0), 0);

  return (
    <div className="stats-overview-grid">
      <div
        className={`stats-overview-card${activeFilter === "all" ? " active" : ""}`}
        onClick={() => onSelectFilter("all")}
        style={{ cursor: "pointer" }}
      >
        <div>
          <div className="stats-overview-label">Total Data Sources</div>
          <div className="stats-overview-value">{totalSources}</div>
          <div className="stats-overview-subtext">{activeSources} enabled & operational</div>
        </div>
        <div className="stats-overview-icon stats-icon--blue">
          <IconSources size={22} />
        </div>
      </div>

      <div
        className={`stats-overview-card${activeFilter === "active" ? " active" : ""}`}
        onClick={() => onSelectFilter("active")}
        style={{ cursor: "pointer" }}
      >
        <div>
          <div className="stats-overview-label">Attached Connectors</div>
          <div className="stats-overview-value">{totalConnectors}</div>
          <div className="stats-overview-subtext">Active integration streams</div>
        </div>
        <div className="stats-overview-icon stats-icon--green">
          <IconCheckCircle size={22} />
        </div>
      </div>

      <div
        className={`stats-overview-card${activeFilter === "syncing" ? " active" : ""}`}
        onClick={() => onSelectFilter("syncing")}
        style={{ cursor: "pointer" }}
      >
        <div>
          <div className="stats-overview-label">Syncing Sources</div>
          <div className="stats-overview-value">{syncingSources}</div>
          <div className="stats-overview-subtext">Continuous CDC background poller</div>
        </div>
        <div className="stats-overview-icon stats-icon--purple">
          <IconRadio size={22} />
        </div>
      </div>

      <div className="stats-overview-card">
        <div>
          <div className="stats-overview-label">Isolated MinIO Buckets</div>
          <div className="stats-overview-value">{totalSources}</div>
          <div className="stats-overview-subtext">S3-compatible namespaces</div>
        </div>
        <div className="stats-overview-icon stats-icon--amber">
          <IconBucket size={22} />
        </div>
      </div>
    </div>
  );
}

/* ── Main SourcesPage component ── */
export default function SourcesPage() {
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newSourceName, setNewSourceName] = useState("");
  const [selectedSourceType, setSelectedSourceType] = useState<"minio" | "minio_manual">("minio");
  const [fileDrawerSource, setFileDrawerSource] = useState<SourceRecord | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    name: string;
    minio_bucket: string;
    total_files?: number | null;
  } | null>(null);
  const [creating, setCreating] = useState(false);
  // Search & Filter controls state
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "syncing" | "error">("all");
  const [viewMode, setViewMode] = useState<"grid" | "table">("grid");

  const navigate = useNavigate();
  const location = useLocation();
  const isVisible = location.pathname === "/sources";

  const load = useCallback(async () => {
    try {
      const data = await listSources();
      setSources(data);
      setError(null);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [isVisible, load]);

  const handleNavigate = useCallback(
    (sourceId: string) => {
      navigate(`/sources/${sourceId}`);
    },
    [navigate]
  );

  const handleSync = useCallback(
    async (sourceId: string) => {
      setSyncingId(sourceId);
      try {
        const res = await triggerSourceSync(sourceId);
        setInfo(res.message ?? "Sync triggered successfully.");
        await load();
      } catch (err) {
        setError(toApiError(err, "SYNC_FAILED"));
      } finally {
        setSyncingId(null);
      }
    },
    [load]
  );

  const handleDelete = useCallback((sourceId: string, name: string) => {
    const target = sources.find((s) => s.id === sourceId);
    setPendingDelete(
      target
        ? { id: target.id, name: target.name, minio_bucket: target.minio_bucket, total_files: target.total_files }
        : { id: sourceId, name, minio_bucket: "" },
    );
  }, [sources]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const { id, name } = pendingDelete;
    setDeletingId(id);
    try {
      await deleteSource(id);
      setInfo(`Source "${name}" deleted. Its MinIO bucket and all objects were removed.`);
      // Drop it locally so the card goes at once, then resync with the server.
      setSources((prev) => prev.filter((s) => s.id !== id));
      setPendingDelete(null);
      await load();
    } catch (err) {
      setError(toApiError(err, "DELETE_FAILED"));
    } finally {
      setDeletingId(null);
    }
  }, [pendingDelete, load]);

  const handleCreate = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (!newSourceName.trim()) return;
      const nameToCreate = newSourceName.trim();
      const typeToCreate = selectedSourceType;

      // Close modal immediately and reset inputs
      setShowCreateForm(false);
      setNewSourceName("");
      setSelectedSourceType("minio");
      setCreating(true);

      try {
        const created = await createSource({
          name: nameToCreate,
          source_type: typeToCreate,
          connector_type: typeToCreate === "minio_manual" ? "manual_upload" : "minio",
        });
        setSources((prev) => [created, ...prev.filter((s) => s.id !== created.id)]);
        if (typeToCreate === "minio_manual") {
          // Manual upload source: open the file picker straight away.
          setInfo(`Source "${created.name}" created. Add files to bucket ${created.minio_bucket}.`);
          setFileDrawerSource(created);
        } else {
          setInfo(`Source "${created.name}" created. Attach NiFi connectors next.`);
          navigate(`/sources/${created.id}`);
        }
      } catch (err) {
        setError(toApiError(err, "CREATE_FAILED"));
        setShowCreateForm(true);
      } finally {
        setCreating(false);
      }
    },
    [newSourceName, selectedSourceType, navigate]
  );
  // Filtered sources
  const filteredSources = sources.filter((s) => {
    const matchesSearch =
      !searchQuery.trim() ||
      s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.minio_bucket.toLowerCase().includes(searchQuery.toLowerCase());

    if (!matchesSearch) return false;

    if (statusFilter === "active") return s.enabled !== false;
    if (statusFilter === "syncing") return s.status === "syncing" || s.status === "processing";
    if (statusFilter === "error") return s.status === "error" || s.status === "failed" || !!s.error_message;

    return true;
  });

  const activeCount = sources.filter((s) => s.enabled !== false).length;
  const syncingCount = sources.filter((s) => s.status === "syncing" || s.status === "processing").length;
  const errorCount = sources.filter((s) => s.status === "error" || s.status === "failed" || !!s.error_message).length;

  return (
    <div className="page">
      {/* Top Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <div style={{ fontSize: "0.8rem", color: "#8b949e", marginBottom: "0.25rem" }}>
            Overview &gt; Sources
          </div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 800, color: "#e6edf3", margin: 0, display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <span>Data Sources</span>
            <span style={{ fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "999px", background: "rgba(88, 166, 253, 0.15)", color: "#58a6ff", border: "1px solid rgba(88, 166, 253, 0.3)" }}>
              2026 Engine
            </span>
          </h1>
          <p style={{ fontSize: "0.875rem", color: "#8b949e", marginTop: "0.35rem", margin: 0 }}>
            Create a NiFi connector source or a manual upload source. Each source gets its own isolated MinIO bucket.
          </p>
        </div>

        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setShowCreateForm(true)}
          style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", padding: "0.6rem 1.1rem" }}
        >
          <IconPlus size={16} />
          <span>New Source</span>
        </button>
      </div>

      {/* Info / Error Banners */}
      {info && (
        <div className="alert alert-info" role="status" style={{ marginBottom: "1.25rem" }}>
          <span role="status">{info}</span>
          <button type="button" className="btn-close" onClick={() => setInfo(null)}>×</button>
        </div>
      )}

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: "1.25rem" }}>
          <strong>{error.code}</strong>: {error.message}
          <button type="button" className="btn-close" onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Stats Overview Grid */}
      <StatsOverview
        sources={sources}
        activeFilter={statusFilter}
        onSelectFilter={(f) => setStatusFilter(f)}
      />

      {/* Toolbar & Search Bar */}
      <div className="sources-toolbar" style={{ marginTop: "1.5rem", marginBottom: "1.25rem" }}>
        <div className="sources-search-wrap">
          <IconSearch className="sources-search-icon" size={16} />
          <input
            type="text"
            className="sources-search-input"
            placeholder="Search sources or buckets..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              style={{
                position: "absolute",
                right: "0.75rem",
                top: "50%",
                transform: "translateY(-50%)",
                background: "none",
                border: "none",
                color: "#8b949e",
                cursor: "pointer",
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="sources-filters-group">
          <button
            type="button"
            className={`sources-filter-btn${statusFilter === "all" ? " active" : ""}`}
            onClick={() => setStatusFilter("all")}
          >
            All <span className="sources-filter-count">{sources.length}</span>
          </button>

          <button
            type="button"
            className={`sources-filter-btn${statusFilter === "active" ? " active" : ""}`}
            onClick={() => setStatusFilter("active")}
          >
            Active <span className="sources-filter-count">{activeCount}</span>
          </button>

          <button
            type="button"
            className={`sources-filter-btn${statusFilter === "syncing" ? " active" : ""}`}
            onClick={() => setStatusFilter("syncing")}
          >
            Syncing <span className="sources-filter-count">{syncingCount}</span>
          </button>

          {errorCount > 0 && (
            <button
              type="button"
              className={`sources-filter-btn${statusFilter === "error" ? " active" : ""}`}
              onClick={() => setStatusFilter("error")}
              style={{ color: "#f85149" }}
            >
              Error <span className="sources-filter-count">{errorCount}</span>
            </button>
          )}
        </div>

        {/* View Toggle */}
        <div className="sources-view-toggle">
          <button
            type="button"
            className={`sources-view-btn${viewMode === "grid" ? " active" : ""}`}
            onClick={() => setViewMode("grid")}
            title="Grid View"
          >
            <IconGrid size={16} />
          </button>
          <button
            type="button"
            className={`sources-view-btn${viewMode === "table" ? " active" : ""}`}
            onClick={() => setViewMode("table")}
            title="Table View"
          >
            <IconList size={16} />
          </button>
        </div>
      </div>

      {/* Content Rendering */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "4rem 2rem", background: "rgba(17, 21, 30, 0.4)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
          <IconSync size={28} className="spin" style={{ color: "#58a6ff", marginBottom: "0.75rem" }} />
          <div style={{ color: "#e6edf3", fontWeight: 600 }}>Loading data sources...</div>
        </div>
      ) : filteredSources.length === 0 ? (
        <div style={{ textAlign: "center", padding: "4rem 2rem", background: "rgba(17, 21, 30, 0.4)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
          <IconBucket size={38} style={{ color: "#58a6ff", marginBottom: "0.75rem" }} />
          <h3 style={{ color: "#e6edf3", margin: "0 0 0.5rem 0" }}>No data sources found</h3>
          <p style={{ color: "#8b949e", fontSize: "0.875rem", marginBottom: "1.25rem" }}>
            {searchQuery || statusFilter !== "all"
              ? "No sources match your current search criteria."
              : "Create your first MinIO bucket source to start."}
          </p>
          {!searchQuery && statusFilter === "all" && (
            <button type="button" className="btn btn-primary" onClick={() => setShowCreateForm(true)}>
              + Create data source
            </button>
          )}
        </div>
      ) : viewMode === "grid" ? (
        <div className="sources-grid">
          {filteredSources.map((s) => (
            <SourceCard
              key={s.id}
              source={s}
              onNavigate={handleNavigate}
              onSync={handleSync}
              onDelete={handleDelete}
              onOpenFiles={(src) => setFileDrawerSource(src)}
              syncing={syncingId === s.id}
              deleting={deletingId === s.id}
            />
          ))}
        </div>
      ) : (
        <SourceTable
          sources={filteredSources}
          onNavigate={handleNavigate}
          onSync={handleSync}
          onDelete={handleDelete}
          onOpenFiles={(src) => setFileDrawerSource(src)}
          syncingId={syncingId}
          deletingId={deletingId}
        />
      )}

      {/* CREATE NEW DATA SOURCE MODAL */}
      {showCreateForm && (
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
          onClick={() => setShowCreateForm(false)}
        >
          <div
            style={{
              width: "100%",
              maxWidth: "520px",
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "10px", background: "rgba(56, 139, 253, 0.15)", color: "#58a6ff", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <IconSources size={20} />
                </div>
                <div>
                  <h2 style={{ fontSize: "1.2rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                    New MinIO Bucket Source
                  </h2>
                  <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>
                    Each source gets its own isolated MinIO bucket
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#8b949e",
                  fontSize: "1.2rem",
                  cursor: "pointer",
                  padding: "0.25rem",
                }}
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreate}>
              <div style={{ marginBottom: "1.25rem" }}>
                <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "#c9d1d9", marginBottom: "0.4rem" }}>
                  Source Name *
                </label>
                <input
                  type="text"
                  value={newSourceName}
                  onChange={(e) => setNewSourceName(e.target.value)}
                  placeholder="e.g. engineering-docs, customer-support, hr-policy"
                  required
                  autoFocus
                  style={{
                    width: "100%",
                    padding: "0.75rem 1rem",
                    borderRadius: "8px",
                    border: "1px solid rgba(56, 68, 100, 0.5)",
                    background: "rgba(17, 21, 30, 0.8)",
                    color: "#e6edf3",
                    fontSize: "0.9rem",
                    outline: "none",
                  }}
                />
              </div>

              <div style={{ marginBottom: "1.25rem" }}>
                <label id="source-type-label" style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "#c9d1d9", marginBottom: "0.4rem" }}>
                  Bucket Source Type *
                </label>
                <div role="radiogroup" aria-labelledby="source-type-label" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selectedSourceType === "minio"}
                    onClick={() => setSelectedSourceType("minio")}
                    style={{
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: selectedSourceType === "minio" ? "1px solid #58a6ff" : "1px solid rgba(255,255,255,0.1)",
                      background: selectedSourceType === "minio" ? "rgba(56, 139, 253, 0.15)" : "rgba(17, 21, 30, 0.6)",
                      color: selectedSourceType === "minio" ? "#58a6ff" : "#8b949e",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: "0.2rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <IconZap size={14} /> Apache NiFi Connector Source
                    </div>
                    <div style={{ fontSize: "0.72rem", opacity: 0.8, lineHeight: 1.4 }}>
                      Pull files in through NiFi connectors: Google Drive, Amazon S3, Azure Blob Storage.
                    </div>
                  </button>

                  <button
                    type="button"
                    role="radio"
                    aria-checked={selectedSourceType === "minio_manual"}
                    onClick={() => setSelectedSourceType("minio_manual")}
                    style={{
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: selectedSourceType === "minio_manual" ? "1px solid #38bdf8" : "1px solid rgba(255,255,255,0.1)",
                      background: selectedSourceType === "minio_manual" ? "rgba(56, 189, 248, 0.15)" : "rgba(17, 21, 30, 0.6)",
                      color: selectedSourceType === "minio_manual" ? "#38bdf8" : "#8b949e",
                      textAlign: "left",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: "0.2rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <IconUpload size={14} /> Manual Upload Source
                    </div>
                    <div style={{ fontSize: "0.72rem", opacity: 0.8, lineHeight: 1.4 }}>
                      Pick files in the browser. Files are stored straight in the MinIO bucket.
                    </div>
                  </button>
                </div>
              </div>

              {/* Storage Location Preview Card */}
              {newSourceName.trim() && (
                <div
                  style={{
                    padding: "0.85rem 1rem",
                    borderRadius: "8px",
                    background: "rgba(56, 139, 253, 0.08)",
                    border: "1px solid rgba(56, 139, 253, 0.25)",
                    marginBottom: "1.25rem",
                  }}
                >
                  <div style={{ fontSize: "0.75rem", color: "#8b949e", marginBottom: "0.25rem" }}>
                    MinIO bucket name (assigned on create):
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <IconBucket size={14} style={{ color: "#58a6ff" }} />
                    <code style={{ fontSize: "0.85rem", color: "#58a6ff", fontWeight: 600 }}>
                      source-{newSourceName.toLowerCase().replace(/[^a-z0-9-]/g, "-")}-&lt;id&gt;
                    </code>
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "#8b949e", marginTop: "0.4rem" }}>
                    {selectedSourceType === "minio_manual"
                      ? "You can upload files as soon as the source exists."
                      : "Add one or more NiFi connectors after the source exists."}
                  </div>
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowCreateForm(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={creating}
                >
                  {creating
                    ? "Creating..."
                    : selectedSourceType === "minio_manual"
                      ? "Create source & upload files"
                      : "Create NiFi source"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* FILE MANAGEMENT MODAL */}
      {fileDrawerSource && (
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
          onClick={() => setFileDrawerSource(null)}
        >
          <div
            style={{
              width: "100%",
              maxWidth: "840px",
              maxHeight: "90vh",
              overflowY: "auto",
              background: "#111622",
              border: "1px solid rgba(88, 166, 253, 0.3)",
              borderRadius: "16px",
              padding: "1.75rem",
              boxShadow: "0 20px 50px rgba(0, 0, 0, 0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={`Files for source ${fileDrawerSource.name}`}
            onKeyDown={(e) => {
              if (e.key === "Escape") setFileDrawerSource(null);
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <div>
                <h2 style={{ fontSize: "1.2rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                  {fileDrawerSource.connector_type === "manual_upload"
                    ? `Upload Files — ${fileDrawerSource.name}`
                    : `Source Files — ${fileDrawerSource.name}`}
                </h2>
                <div style={{ fontSize: "0.78rem", color: "#8b949e", marginTop: "0.2rem" }}>
                  {fileDrawerSource.connector_type === "local_filesystem" || fileDrawerSource.minio_bucket.startsWith("local-")
                    ? `Local Storage: storage/local_sources/${(fileDrawerSource.config?.folder_name as string) || fileDrawerSource.minio_bucket.replace("local-", "")}`
                    : `MinIO Bucket: ${fileDrawerSource.minio_bucket}`}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setFileDrawerSource(null)}
                aria-label="Close file manager"
                style={{ background: "none", border: "none", color: "#8b949e", fontSize: "1.25rem", cursor: "pointer", minWidth: "44px", minHeight: "44px" }}
              >
                ✕
              </button>
            </div>

            <FileBrowser
              sourceId={fileDrawerSource.id}
              bucketName={fileDrawerSource.minio_bucket}
              allowUpload={true}
              allowDelete={true}
              onError={(err) => setError(err)}
              onInfo={(msg) => setInfo(msg)}
            />
          </div>
        </div>
      )}

      {/* DELETE SOURCE CONFIRMATION */}
      <ConfirmDialog
        open={pendingDelete !== null}
        danger
        title="Delete this source?"
        message={
          pendingDelete
            ? `Source "${pendingDelete.name}" and its MinIO bucket are removed for good. This cannot be undone.`
            : ""
        }
        details={
          pendingDelete
            ? [
                `MinIO bucket: ${pendingDelete.minio_bucket || "unknown"}`,
                `Objects in the bucket: ${pendingDelete.total_files ?? 0}`,
                "The bucket and every object inside it are deleted.",
                "Pipeline links and knowledge profile links for this source are removed.",
              ]
            : undefined
        }
        confirmLabel="Delete source and bucket"
        cancelLabel="Keep source"
        busy={deletingId !== null}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
