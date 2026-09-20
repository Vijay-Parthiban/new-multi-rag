/**
 * Knowledge Product — read-only configuration view.
 *
 * A view-only port of the ingestion manager's Knowledge Product page. It shows
 * the live fanout, the ingested-file ledger and each destination's contents, but
 * it holds no write control: no pause, no resume, no configure, no delete. The
 * ingestion manager owns all of that.
 *
 * `Refresh` re-reads the product and asks the ingestion manager for an immediate
 * fanout, so the numbers on screen match the stores.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getDestinationOptions,
  getKnowledgeProduct,
  listProductFiles,
  refreshKnowledgeProduct,
  KnowledgeDestinationConfig,
  KnowledgeDestinationOption,
  KnowledgeProduct,
  ProductFileEntry,
} from "../api";
import { useProductEvents } from "../hooks/useProductEvents";
import StatusBadge from "../components/StatusBadge";
import {
  IconArrowRight,
  IconClock,
  IconDatabase,
  IconFile,
  IconGrid,
  IconRefresh,
  IconSources,
} from "../components/Icons";
import LiveFanoutTimeline from "../components/knowledge/LiveFanoutTimeline";
import { DestinationVisualizerModal } from "../components/visualizers/DestinationVisualizerModal";
import { formatRelativeTime } from "../utils/format";

interface KnowledgeProductPageProps {
  routeProductId?: string;
}

export default function KnowledgeProductPage({ routeProductId }: KnowledgeProductPageProps) {
  const navigate = useNavigate();
  const params = useParams<{ id: string }>();
  const id = routeProductId ?? params.id ?? "";

  const [product, setProduct] = useState<KnowledgeProduct | null>(null);
  const [files, setFiles] = useState<ProductFileEntry[]>([]);
  const [fileTotal, setFileTotal] = useState<number>(0);
  const [options, setOptions] = useState<KnowledgeDestinationOption[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [visualizerOpen, setVisualizerOpen] = useState<boolean>(false);
  const [visualizerDestType, setVisualizerDestType] = useState<string>("vector_qdrant");

  const { events, connected } = useProductEvents(id || null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [prod, fileRes] = await Promise.all([
        getKnowledgeProduct(id),
        listProductFiles(id, { limit: 50 }),
      ]);
      setProduct(prod);
      setFiles(fileRes.files);
      setFileTotal(fileRes.total);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load this Knowledge Product.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    let mounted = true;
    const tick = () => {
      if (mounted) void load();
    };
    setLoading(true);
    tick();
    // 5 s: the timeline must still move when the SSE stream is reconnecting.
    const timer = window.setInterval(tick, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [load]);

  useEffect(() => {
    void getDestinationOptions().then(setOptions).catch(() => setOptions([]));
  }, []);

  /** Re-read the product and ask the ingestion manager to sync it now. */
  const handleRefresh = async () => {
    if (!id) return;
    setRefreshing(true);
    try {
      await refreshKnowledgeProduct(id);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to refresh this Knowledge Product.");
    } finally {
      setRefreshing(false);
    }
  };

  const optionFor = (destinationType: string) => options.find((o) => o.id === destinationType);

  const storeLabel = (dest: KnowledgeDestinationConfig): string => {
    const opt = optionFor(dest.destination_type);
    const config = dest.config || {};
    if (dest.destination_type === "relational_pgvector") {
      return `${String(config.schema_name ?? "")}.${String(config.table_name ?? "")}`;
    }
    const key = (opt?.namespace_fields || []).find((f) => config[f] != null);
    return key ? String(config[key]) : dest.destination_type;
  };

  if (!id) {
    return (
      <div className="page">
        <div className="alert alert-error">No Knowledge Product selected.</div>
      </div>
    );
  }

  if (loading && !product) {
    return (
      <div className="page">
        <p style={{ color: "#8b949e" }}>Loading Knowledge Product…</p>
      </div>
    );
  }

  if (!product) {
    return (
      <div className="page">
        <div className="alert alert-error">{error ?? "Knowledge Product not found."}</div>
        <button className="btn btn-secondary" onClick={() => navigate("/knowledge-store")}>
          Back to Knowledge Store
        </button>
      </div>
    );
  }

  const running = product.enabled && product.destinations.some((d) => d.enabled);
  const monitorText =
    product.monitor_mode === "live"
      ? "Live polling"
      : product.sync_interval_minutes
      ? `Scheduled every ${product.sync_interval_minutes}m`
      : product.sync_interval_seconds
      ? `Scheduled every ${product.sync_interval_seconds}s`
      : "Scheduled";

  return (
    <div className="page">
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: "1.5rem",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: "0.8rem", color: "#8b949e", marginBottom: "0.25rem" }}>
            Overview &gt; Knowledge Store &gt; <span style={{ color: "#c9d1d9" }}>{product.name}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
            <h1
              style={{
                fontSize: "1.75rem",
                fontWeight: 800,
                color: "#e6edf3",
                margin: 0,
                display: "flex",
                alignItems: "center",
                gap: "0.6rem",
              }}
            >
              <div
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "10px",
                  background: "rgba(56, 139, 253, 0.15)",
                  color: "#58a6ff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <IconDatabase size={22} />
              </div>
              <span>{product.name}</span>
            </h1>
            <span className={running ? "status-badge status-synced" : "status-badge status-paused"}>
              {running ? "Running" : "Paused"}
            </span>
            <StatusBadge status={product.status} />
            <span className="status-badge status-paused">{monitorText}</span>
          </div>
          {product.description && (
            <p style={{ margin: "0.4rem 0 0 0", fontSize: "0.875rem", color: "#8b949e" }}>
              {product.description}
            </p>
          )}
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button className="btn btn-secondary" onClick={() => navigate("/knowledge-store")}>
            ← Back to Knowledge Store
          </button>
          <button
            className="btn btn-primary"
            onClick={handleRefresh}
            disabled={refreshing}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
          >
            <IconRefresh size={15} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
          {error}
          <button className="btn btn-sm btn-secondary" style={{ marginLeft: "0.75rem" }} onClick={load}>
            Retry
          </button>
        </div>
      )}

      {/* Stat cards */}
      <div className="stats-overview-grid" style={{ marginBottom: "1.5rem" }}>
        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Source Buckets</div>
            <div className="stats-overview-value">{product.sources.length}</div>
            <div className="stats-overview-subtext">
              {product.sources.map((s) => s.name).join(", ") || "None linked"}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--blue">
            <IconSources size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Files Indexed</div>
            <div className="stats-overview-value">{product.files_synced}</div>
            <div className="stats-overview-subtext">
              {product.files_total} total
              {product.files_pending > 0 ? ` · ${product.files_pending} pending` : ""}
              {product.files_failed > 0 ? ` · ${product.files_failed} failed` : ""}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--green">
            <IconFile size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Pages Indexed</div>
            <div className="stats-overview-value">{product.pages_indexed}</div>
            <div className="stats-overview-subtext">Across every destination</div>
          </div>
          <div className="stats-overview-icon stats-icon--purple">
            <IconGrid size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Last Sync</div>
            <div className="stats-overview-value" style={{ fontSize: "1.35rem" }}>
              {product.last_sync_at ? formatRelativeTime(product.last_sync_at) : "Never"}
            </div>
            <div className="stats-overview-subtext">{monitorText}</div>
          </div>
          <div className="stats-overview-icon stats-icon--amber">
            <IconClock size={22} />
          </div>
        </div>
      </div>

      {/* Live pipeline view */}
      <LiveFanoutTimeline
        events={events}
        connected={connected}
        destinations={product.destinations.filter((d) => d.enabled)}
      />

      {/* Destination cards */}
      <h2 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#e6edf3", margin: "1.5rem 0 0.75rem 0" }}>
        Destination Stores ({product.destinations.filter((d) => d.enabled).length} running)
      </h2>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
          gap: "1rem",
          marginBottom: "1.5rem",
        }}
      >
        {product.destinations.map((dest) => {
          const opt = optionFor(dest.destination_type);
          return (
            <div
              key={dest.id ?? dest.destination_type}
              style={{
                background: "rgba(30, 41, 59, 0.5)",
                border: `1px solid ${
                  dest.enabled ? "rgba(56, 139, 253, 0.25)" : "rgba(255,255,255,0.07)"
                }`,
                borderRadius: "12px",
                padding: "1rem",
                opacity: dest.enabled ? 1 : 0.7,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "0.5rem",
                }}
              >
                <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "#e6edf3" }}>
                  {opt?.name ?? dest.destination_type}
                </span>
                <span
                  className={dest.enabled ? "status-badge status-synced" : "status-badge status-paused"}
                >
                  {dest.enabled ? "Running" : "Paused"}
                </span>
              </div>
              <div style={{ fontSize: "0.75rem", color: "#8b949e", margin: "0.4rem 0 0.6rem 0" }}>
                {opt?.description ?? dest.destination_type}
              </div>
              <div
                className="mono"
                style={{
                  fontSize: "0.72rem",
                  color: "#58a6ff",
                  background: "rgba(0,0,0,0.3)",
                  padding: "0.3rem 0.5rem",
                  borderRadius: "6px",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  marginBottom: "0.5rem",
                }}
                title={storeLabel(dest)}
              >
                {storeLabel(dest)}
              </div>
              <div style={{ fontSize: "0.72rem", color: "#8b949e", marginBottom: "0.6rem" }}>
                Last sync: {dest.last_sync_at ? formatRelativeTime(dest.last_sync_at) : "never"}
              </div>
              {dest.error_message && (
                <div className="alert alert-error" style={{ fontSize: "0.72rem", marginBottom: "0.5rem" }}>
                  {dest.error_message}
                </div>
              )}
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => {
                    setVisualizerDestType(dest.destination_type);
                    setVisualizerOpen(true);
                  }}
                  style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
                >
                  Inspect Store
                  <IconArrowRight size={13} />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Files table */}
      <h2 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#e6edf3", margin: "0 0 0.75rem 0" }}>
        Ingested Files
      </h2>
      <div style={{ overflowX: "auto", marginBottom: "2rem" }}>
        <table className="repo-table">
          <thead>
            <tr>
              <th>File Key</th>
              <th>Source</th>
              <th>Status</th>
              <th>Pages</th>
              <th>Destinations</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {files.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ color: "#8b949e", textAlign: "center", padding: "1.5rem" }}>
                  No files ingested yet. Add a file to a linked bucket.
                </td>
              </tr>
            ) : (
              files.map((file) => (
                <tr key={file.id}>
                  <td>
                    <code>{file.file_key}</code>
                  </td>
                  <td>{file.source_name}</td>
                  <td>
                    <StatusBadge status={file.status} />
                  </td>
                  <td>{file.pages_indexed}</td>
                  <td>
                    <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                      {file.destinations_synced.length === 0 ? (
                        <span style={{ color: "#8b949e", fontSize: "0.72rem" }}>none</span>
                      ) : (
                        file.destinations_synced.map((d) => (
                          <span
                            key={d}
                            style={{
                              fontSize: "0.68rem",
                              padding: "0.1rem 0.35rem",
                              borderRadius: "4px",
                              background: "rgba(56, 139, 253, 0.15)",
                              color: "#58a6ff",
                            }}
                          >
                            {d}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td>{file.updated_at ? formatRelativeTime(file.updated_at) : "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {fileTotal > files.length && (
          <div style={{ fontSize: "0.75rem", color: "#8b949e", marginTop: "0.5rem" }}>
            Showing {files.length} of {fileTotal}.
          </div>
        )}
      </div>

      <DestinationVisualizerModal
        isOpen={visualizerOpen}
        onClose={() => setVisualizerOpen(false)}
        product={product}
        initialDestinationType={visualizerDestType}
      />

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button className="btn btn-sm btn-secondary" onClick={load} disabled={loading}>
          <IconRefresh size={13} /> Reload
        </button>
      </div>
    </div>
  );
}
