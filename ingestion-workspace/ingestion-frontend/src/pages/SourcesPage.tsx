import { FormEvent, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import {
  IconArrowRight,
  IconBucket,
  IconCheck,
  IconCheckCircle,
  IconCopy,
  IconGrid,
  IconList,
  IconPlus,
  IconRadio,
  IconSearch,
  IconSources,
  IconSync,
  IconTrash,
  IconZap,
} from "../components/Icons";
import { formatRelativeTime } from "../utils/format";
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

/* ── Connector status summary ── */

interface StatusSummary {
  connected: number;
  syncing: number;
  errored: number;
  disabled: number;
  other: number;
}

function summarizeConnectors(connectors: SourceConnectorRecord[]): StatusSummary {
  const summary: StatusSummary = { connected: 0, syncing: 0, errored: 0, disabled: 0, other: 0 };
  if (!connectors) return summary;
  for (const c of connectors) {
    if (!c.enabled) {
      summary.disabled += 1;
      continue;
    }
    const s = c.status;
    if (s === "synced" || s === "connected" || s === "success" || s === "completed") {
      summary.connected += 1;
    } else if (s === "processing" || s === "syncing" || s === "running" || s === "pending") {
      summary.syncing += 1;
    } else if (s === "failed" || s === "error") {
      summary.errored += 1;
    } else {
      summary.other += 1;
    }
  }
  return summary;
}

function StatusPill({ label, count, variant }: { label: string; count: number; variant: string }) {
  if (count === 0) return null;
  return (
    <span className={`status-pill ${variant}`}>
      <span className="status-pill-dot" />
      {count} {label}
    </span>
  );
}

function ConnectorStatusSummary({ connectors }: { connectors: SourceConnectorRecord[] }) {
  const summary = summarizeConnectors(connectors);
  const total = connectors?.length ?? 0;

  if (total === 0) {
    return (
      <div className="source-card-empty-connectors">
        <span>+ No connectors attached</span>
      </div>
    );
  }

  return (
    <div className="status-pill-group">
      <StatusPill label="connected" count={summary.connected} variant="status-pill--connected" />
      <StatusPill label="syncing" count={summary.syncing} variant="status-pill--syncing" />
      <StatusPill label="error" count={summary.errored} variant="status-pill--error" />
      <StatusPill label="disabled" count={summary.disabled} variant="status-pill--disabled" />
      <StatusPill label="other" count={summary.other} variant="status-pill--other" />
    </div>
  );
}

/* ── Source card ── */

function SourceCard({
  source,
  onNavigate,
  onSync,
  onDelete,
  syncing,
  deleting,
}: {
  source: SourceRecord;
  onNavigate: (id: string) => void;
  onSync: (id: string) => void;
  onDelete: (id: string, name: string) => void;
  syncing: boolean;
  deleting: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const connectorCount = source.connector_count ?? source.connectors?.length ?? 0;

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
      {/* Header */}
      <div className="source-card-header">
        <div className="source-card-title">
          <div className="source-card-icon">
            <IconSources size={18} />
          </div>
          <div>
            <h3 className="source-card-name">{source.name}</h3>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <StatusBadge status={source.status || "idle"} />
          <IconArrowRight className="source-card-arrow" size={16} />
        </div>
      </div>

      {/* Meta Stats & Bucket Badge */}
      <div className="source-card-meta">
        <div className="source-card-stat">
          <span className="source-card-stat-value">{connectorCount}</span>
          <span className="source-card-stat-label">{connectorCount === 1 ? "connector" : "connectors"}</span>
        </div>
        <div className="source-card-divider" />
        <div className="source-card-bucket" title={`MinIO Bucket: ${source.minio_bucket}`}>
          <IconBucket size={14} style={{ color: "var(--accent)", flexShrink: 0 }} />
          <span className="source-card-bucket-code">{source.minio_bucket}</span>
          <button
            type="button"
            onClick={handleCopyBucket}
            className="btn btn-ghost btn-sm"
            style={{ padding: "0.125rem 0.25rem", height: "auto", minHeight: 0 }}
            title="Copy Bucket Name"
          >
            {copied ? <IconCheck size={12} style={{ color: "var(--success-text)" }} /> : <IconCopy size={12} />}
          </button>
        </div>
      </div>

      {/* Connector Status Summary */}
      <div className="source-card-connectors">
        <ConnectorStatusSummary connectors={source.connectors || []} />
      </div>

      {/* Error Message if present */}
      {source.error_message && (
        <div className="source-card-error" title={source.error_message}>
          <span>⚠️</span> {source.error_message}
        </div>
      )}

      {/* Footer Timestamp & Actions */}
      <div className="source-card-footer">
        <span className="muted" style={{ fontSize: "0.75rem" }}>
          {source.last_sync_at ? `Synced ${formatRelativeTime(source.last_sync_at)}` : "Never synced"}
        </span>

        <div className="source-card-actions" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => onSync(source.id)}
            disabled={syncing || source.status === "syncing"}
            aria-label={`Sync ${source.name}`}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.375rem" }}
          >
            <IconSync size={13} className={syncing || source.status === "syncing" ? "spin" : ""} />
            {syncing || source.status === "syncing" ? "Syncing" : "Sync"}
          </button>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => onNavigate(source.id)}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.25rem" }}
          >
            Manage →
          </button>

          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={() => onDelete(source.id, source.name)}
            disabled={deleting}
            aria-label={`Delete ${source.name}`}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.375rem" }}
          >
            <IconTrash size={13} />
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
  syncingId,
  deletingId,
}: {
  sources: SourceRecord[];
  onNavigate: (id: string) => void;
  onSync: (id: string) => void;
  onDelete: (id: string, name: string) => void;
  syncingId: string | null;
  deletingId: string | null;
}) {
  return (
    <div className="repo-table-wrap">
      <table className="repo-table">
        <thead>
          <tr>
            <th>Source Name</th>
            <th>Status</th>
            <th>MinIO S3 Bucket</th>
            <th>Connectors</th>
            <th>Last Synced</th>
            <th style={{ textAlign: "right" }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => {
            const count = s.connector_count ?? s.connectors?.length ?? 0;
            return (
              <tr key={s.id} onClick={() => onNavigate(s.id)} style={{ cursor: "pointer" }}>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <IconSources size={16} style={{ color: "var(--accent)" }} />
                    <span style={{ fontWeight: 600 }}>{s.name}</span>
                  </div>
                </td>
                <td>
                  <StatusBadge status={s.status || "idle"} />
                </td>
                <td>
                  <code className="source-card-bucket-code">{s.minio_bucket}</code>
                </td>
                <td>
                  <span className="sources-filter-count">{count} attached</span>
                </td>
                <td>
                  <span className="muted" style={{ fontSize: "0.8125rem" }}>
                    {s.last_sync_at ? formatRelativeTime(s.last_sync_at) : "Never"}
                  </span>
                </td>
                <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                  <div style={{ display: "inline-flex", gap: "0.375rem" }}>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => onSync(s.id)}
                      disabled={syncingId === s.id || s.status === "syncing"}
                    >
                      <IconSync size={13} className={syncingId === s.id ? "spin" : ""} />
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => onNavigate(s.id)}
                    >
                      Manage
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      onClick={() => onDelete(s.id, s.name)}
                      disabled={deletingId === s.id}
                    >
                      <IconTrash size={13} />
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
  const totalConnectors = sources.reduce(
    (sum, s) => sum + (s.connector_count ?? s.connectors?.length ?? 0),
    0
  );
  const syncingSources = sources.filter((s) => s.status === "syncing" || s.status === "processing").length;

  return (
    <div className="stats-overview-grid">
      <div
        className={`stats-overview-card${activeFilter === "all" ? " active" : ""}`}
        onClick={() => onSelectFilter("all")}
        style={{ cursor: "pointer" }}
      >
        <div>
          <div className="stats-overview-label">Total Sources</div>
          <div className="stats-overview-value">{totalSources}</div>
          <div className="stats-overview-subtext">Configured storage buckets</div>
        </div>
        <div className="stats-overview-icon stats-icon--blue">
          <IconSources size={20} />
        </div>
      </div>

      <div
        className={`stats-overview-card${activeFilter === "active" ? " active" : ""}`}
        onClick={() => onSelectFilter("active")}
        style={{ cursor: "pointer" }}
      >
        <div>
          <div className="stats-overview-label">Active Sources</div>
          <div className="stats-overview-value">{activeSources}</div>
          <div className="stats-overview-subtext">Ready for ingestion</div>
        </div>
        <div className="stats-overview-icon stats-icon--green">
          <IconCheckCircle size={20} />
        </div>
      </div>

      <div className="stats-overview-card">
        <div>
          <div className="stats-overview-label">Total Connectors</div>
          <div className="stats-overview-value">{totalConnectors}</div>
          <div className="stats-overview-subtext">External integrations</div>
        </div>
        <div className="stats-overview-icon stats-icon--purple">
          <IconZap size={20} />
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
          <div className="stats-overview-subtext">Active background sync</div>
        </div>
        <div className="stats-overview-icon stats-icon--amber">
          <IconRadio size={20} />
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

  const handleDelete = useCallback(
    async (sourceId: string, name: string) => {
      if (!window.confirm(`Are you sure you want to delete source "${name}"?`)) return;
      setDeletingId(sourceId);
      try {
        await deleteSource(sourceId);
        setInfo(`Source "${name}" deleted.`);
        await load();
      } catch (err) {
        setError(toApiError(err, "DELETE_FAILED"));
      } finally {
        setDeletingId(null);
      }
    },
    [load]
  );

  const handleCreate = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (!newSourceName.trim()) return;
      setCreating(true);
      try {
        const created = await createSource({ name: newSourceName.trim() });
        setInfo(`Source "${created.name}" created successfully.`);
        setNewSourceName("");
        setShowCreateForm(false);
        await load();
        navigate(`/sources/${created.id}`);
      } catch (err) {
        setError(toApiError(err, "CREATE_FAILED"));
      } finally {
        setCreating(false);
      }
    },
    [newSourceName, load, navigate]
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
      <PageHeader
        title="Sources"
        description="Connect multiple data sources — each source manages its own connectors, MinIO bucket, and pipeline links."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Sources" }]}
        actions={
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowCreateForm(!showCreateForm)}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}
          >
            <IconPlus size={16} />
            {showCreateForm ? "Cancel" : "New Source"}
          </button>
        }
      />

      {error && (
        <div className="alert alert-error" role="alert">
          <strong>{error.code}:</strong> {error.message}
        </div>
      )}

      {info && (
        <div className="alert alert-info" role="status">
          {info}
        </div>
      )}

      {/* Styled Create Source Form Card */}
      {showCreateForm && (
        <div className="source-create-card">
          <div className="source-create-header">
            <h2 className="source-create-title">
              <IconSources size={20} style={{ color: "var(--accent)" }} />
              Create New Data Source
            </h2>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setShowCreateForm(false)}
            >
              ✕
            </button>
          </div>

          <p className="muted" style={{ fontSize: "0.875rem", marginBottom: "1rem" }}>
            Each source gets a dedicated, isolated MinIO bucket to store and sync your external data documents into RAG vector pipelines.
          </p>

          <div style={{ marginBottom: "1rem" }}>
            <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--text-secondary)", display: "block", marginBottom: "0.5rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Available Connector Types
            </span>
            <div className="source-presets-grid">
              <div className="source-preset-item active">
                <span className="source-preset-icon">📁</span>
                <span className="source-preset-name">Google Drive</span>
              </div>
              <div className="source-preset-item active">
                <span className="source-preset-icon">🪣</span>
                <span className="source-preset-name">Amazon S3</span>
              </div>
              <div className="source-preset-item active">
                <span className="source-preset-icon">☁️</span>
                <span className="source-preset-name">Azure Blob</span>
              </div>
              <div className="source-preset-item active">
                <span className="source-preset-icon">📂</span>
                <span className="source-preset-name">Local Directory</span>
              </div>
              <div className="source-preset-item active">
                <span className="source-preset-icon">🌐</span>
                <span className="source-preset-name">Web Scraper</span>
              </div>
            </div>
          </div>

          <form onSubmit={handleCreate}>
            <div style={{ marginBottom: "1.25rem" }}>
              <label htmlFor="source-name-input" className="field-label" style={{ fontWeight: 600 }}>
                Source Identifier Name
              </label>
              <input
                id="source-name-input"
                type="text"
                className="input"
                placeholder="e.g. customer-support-docs, engineering-specs..."
                value={newSourceName}
                onChange={(e) => setNewSourceName(e.target.value)}
                autoFocus
                required
                style={{ fontSize: "0.9375rem" }}
              />
              <span className="muted" style={{ fontSize: "0.75rem", marginTop: "0.375rem", display: "block" }}>
                Bucket will be auto-slugified: <code>source-&lt;name&gt;-&lt;id&gt;</code>
              </span>
            </div>

            <div className="form-actions" style={{ justifyContent: "flex-end", gap: "0.75rem" }}>
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
                style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}
              >
                <IconPlus size={16} />
                {creating ? "Creating Source..." : "Create Data Source"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Stats Dashboard */}
      {!loading && sources.length > 0 && (
        <StatsOverview
          sources={sources}
          activeFilter={statusFilter}
          onSelectFilter={(f) => setStatusFilter(f)}
        />
      )}

      {/* Toolbar — Search, Filters & View Mode Toggle */}
      {!loading && sources.length > 0 && (
        <div className="sources-toolbar">
          <div className="sources-toolbar-group">
            <div className="sources-search-box">
              <IconSearch size={14} className="sources-search-icon" />
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
                    right: "0.5rem",
                    top: "50%",
                    transform: "translateY(-50%)",
                    background: "none",
                    border: "none",
                    color: "var(--text-secondary)",
                    cursor: "pointer",
                  }}
                >
                  ✕
                </button>
              )}
            </div>

            <div className="sources-filter-pills">
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
                >
                  Errors <span className="sources-filter-count" style={{ color: "var(--danger)" }}>{errorCount}</span>
                </button>
              )}
            </div>
          </div>

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
      )}

      {/* Loading state */}
      {loading && (
        <div className="panel" style={{ padding: "3rem", textAlign: "center" }}>
          <p className="muted">Loading sources...</p>
        </div>
      )}

      {/* Empty state */}
      {!loading && sources.length === 0 && (
        <div className="panel" style={{ padding: "3rem", textAlign: "center" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>📁</div>
          <h3 style={{ margin: "0 0 0.5rem" }}>No data sources created yet</h3>
          <p className="muted" style={{ margin: "0 0 1.5rem", maxWidth: "480px", marginLeft: "auto", marginRight: "auto" }}>
            Create your first data source to begin connecting external files (Google Drive, S3, Azure Blob, Local Dir, Web Scraper).
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowCreateForm(true)}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}
          >
            <IconPlus size={16} />
            Create First Source
          </button>
        </div>
      )}

      {/* Filtered Empty State */}
      {!loading && sources.length > 0 && filteredSources.length === 0 && (
        <div className="panel" style={{ padding: "3rem", textAlign: "center" }}>
          <h3 style={{ margin: "0 0 0.5rem" }}>No matching sources found</h3>
          <p className="muted" style={{ margin: "0 0 1.5rem" }}>
            No sources matched your search "{searchQuery}" or selected status filter.
          </p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setSearchQuery("");
              setStatusFilter("all");
            }}
          >
            Clear Filters
          </button>
        </div>
      )}

      {/* Sources Display View (Grid or Table) */}
      {!loading && filteredSources.length > 0 && (
        <>
          {viewMode === "grid" ? (
            <div className="source-grid">
              {filteredSources.map((source) => (
                <SourceCard
                  key={source.id}
                  source={source}
                  onNavigate={handleNavigate}
                  onSync={handleSync}
                  onDelete={handleDelete}
                  syncing={syncingId === source.id}
                  deleting={deletingId === source.id}
                />
              ))}
            </div>
          ) : (
            <SourceTable
              sources={filteredSources}
              onNavigate={handleNavigate}
              onSync={handleSync}
              onDelete={handleDelete}
              syncingId={syncingId}
              deletingId={deletingId}
            />
          )}
        </>
      )}
    </div>
  );
}
