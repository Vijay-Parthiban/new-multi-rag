import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import FileBrowser from "../components/Sources/FileBrowser";
import ConnectorConfigForm, {
  defaultConfigFor,
} from "../components/Sources/ConnectorConfigForm";
import {
  IconBucket,
  IconFile,
  IconPipeline,
  IconPlus,
  IconSources,
  IconSync,
  IconTrash,
  IconZap,
} from "../components/Icons";
import type {
  ConnectorOption,
  PipelineRecord,
  SourceConnectorRecord,
  SourceFileEntry,
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
  updateSourceConnector,
} from "../api";

function toApiError(err: unknown, code = "UNKNOWN"): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(500, {
    error: { code, message: err instanceof Error ? err.message : String(err) },
  });
}

type TabId = "connectors" | "files" | "pipeline";

interface ConnectorCatalogItem {
  id: string;
  label: string;
  category: "cloud" | "database" | "files" | "workspace";
  icon: string;
  description: string;
  badge?: string;
}

const EXTENDED_CATALOG: ConnectorCatalogItem[] = [
  { id: "google_drive", label: "Google Drive", category: "cloud", icon: "📁", description: "Sync documents, PDFs & folders directly from Google Drive" },
  { id: "s3", label: "Amazon S3", category: "cloud", icon: "🪣", description: "Pull objects from AWS S3 buckets into MinIO namespace" },
  { id: "azure_blob", label: "Azure Blob Storage", category: "cloud", icon: "☁️", description: "Stream files from Microsoft Azure Blob Storage containers" },
  { id: "google_sheets", label: "Google Sheets", category: "files", icon: "📊", description: "Import tabular data & spreadsheets automatically" },
  { id: "onedrive", label: "OneDrive", category: "cloud", icon: "💾", description: "Sync personal and enterprise Microsoft OneDrive files" },
  { id: "sharepoint", category: "workspace", label: "SharePoint", icon: "🌐", description: "Connect enterprise SharePoint document libraries" },
  { id: "postgres", label: "PostgreSQL Database", category: "database", icon: "🐘", description: "Ingest tables, schemas, or query results into vectors" },
  { id: "mysql", label: "MySQL Database", category: "database", icon: "🐬", description: "Real-time CDC capture from MySQL database tables" },
  { id: "mongodb", label: "MongoDB", category: "database", icon: "🍃", description: "Stream NoSQL documents and BSON collections" },
  { id: "web_scraper", label: "Web Scraper / Crawler", category: "files", icon: "🕸️", description: "Crawl documentation sites, blogs & web APIs" },
  { id: "confluence", label: "Confluence", category: "workspace", icon: "📘", description: "Extract space articles & wiki documents" },
  { id: "sftp", label: "SFTP / FTP Server", category: "files", icon: "🔒", description: "Secure SSH File Transfer Protocol watcher" },
];

interface SourceDetailPageProps {
  routeSourceId?: string;
}

// 2026 Engine Source Detail Component
export default function SourceDetailPage({ routeSourceId }: SourceDetailPageProps) {
  const { id: paramId } = useParams<{ id: string }>();
  const id = routeSourceId ?? paramId;
  const navigate = useNavigate();

  const [source, setSource] = useState<SourceRecord | null>(null);
  const [catalog, setCatalog] = useState<ConnectorOption[]>([]);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [files, setFiles] = useState<SourceFileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("connectors");

  const [syncingAll, setSyncingAll] = useState(false);
  const [copiedBucket, setCopiedBucket] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  // Connector Modal State
  const [connectorModalOpen, setConnectorModalOpen] = useState(false);
  const [editingConnector, setEditingConnector] = useState<SourceConnectorRecord | null>(null);
  const [connectorForm, setConnectorForm] = useState<{
    connectorType: string;
    config: Record<string, unknown>;
    monitorMode: "live" | "scheduled";
    syncIntervalMinutes: string;
  }>({
    connectorType: "google_drive",
    config: defaultConfigFor("google_drive"),
    monitorMode: "live",
    syncIntervalMinutes: "",
  });
  const [savingConnector, setSavingConnector] = useState(false);

  // Pipeline Link Modal State
  const [pipelineModalOpen, setPipelineModalOpen] = useState(false);

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
        const [srcData, catData, pipeData] = await Promise.all([
          getSource(id!),
          listConnectors().catch(() => []),
          listPipelines().catch(() => []),
        ]);
        if (!mounted) return;
        setSource(srcData);
        setCatalog(catData);
        setPipelines(pipeData);

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

  const handleSyncAll = async () => {
    if (!source) return;
    setSyncingAll(true);
    try {
      const res = await triggerSourceSync(source.id);
      setInfo(res.message ?? "Source sync triggered.");
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "SYNC_FAILED"));
    } finally {
      setSyncingAll(false);
    }
  };

  const handleOpenCatalogueConnector = (item: ConnectorCatalogItem) => {
    setEditingConnector(null);
    setConnectorForm({
      connectorType: item.id,
      config: defaultConfigFor(item.id),
      monitorMode: "live",
      syncIntervalMinutes: "",
    });
    setConnectorModalOpen(true);
  };

  const handleEditConnector = (conn: SourceConnectorRecord) => {
    setEditingConnector(conn);
    setConnectorForm({
      connectorType: conn.connector_type,
      config: conn.config ?? {},
      monitorMode: (conn.monitor_mode as "live" | "scheduled") ?? "live",
      syncIntervalMinutes: conn.sync_interval_minutes?.toString() ?? "",
    });
    setConnectorModalOpen(true);
  };

  const handleSaveConnector = async (e: FormEvent) => {
    e.preventDefault();
    if (!source) return;
    setSavingConnector(true);

    try {
      const syncInterval = connectorForm.syncIntervalMinutes
        ? parseInt(connectorForm.syncIntervalMinutes, 10)
        : undefined;

      if (editingConnector) {
        await updateSourceConnector(source.id, editingConnector.id, {
          config: connectorForm.config,
          monitor_mode: connectorForm.monitorMode,
          sync_interval_minutes: syncInterval,
        });
        setInfo("Connector configuration updated.");
      } else {
        await addSourceConnector(source.id, {
          connector_type: connectorForm.connectorType,
          config: connectorForm.config,
          monitor_mode: connectorForm.monitorMode,
          sync_interval_minutes: syncInterval,
        });
        setInfo("Connector attached successfully.");
      }
      setConnectorModalOpen(false);
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "SAVE_CONNECTOR_FAILED"));
    } finally {
      setSavingConnector(false);
    }
  };

  const handleDeleteConnector = async (conn: SourceConnectorRecord) => {
    if (!source) return;
    if (!window.confirm(`Remove connector "${conn.connector_type}"?`)) return;
    try {
      await deleteSourceConnector(source.id, conn.id);
      setInfo("Connector removed.");
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "DELETE_CONNECTOR_FAILED"));
    }
  };

  const handleSyncSingleConnector = async (connId: string) => {
    if (!source) return;
    try {
      await triggerConnectorSync(source.id, connId);
      setInfo("Connector sync started.");
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "SYNC_CONNECTOR_FAILED"));
    }
  };

  const handleLinkPipelineSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!source || !selectedPipelineId) return;
    setLinkingPipeline(true);
    try {
      await linkSourceToPipeline(source.id, selectedPipelineId);
      setInfo("Linked to RAG pipeline.");
      setPipelineModalOpen(false);
      setSelectedPipelineId("");
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "LINK_PIPELINE_FAILED"));
    } finally {
      setLinkingPipeline(false);
    }
  };

  const handleUnlinkPipeline = async (pipelineId: string) => {
    if (!source) return;
    if (!window.confirm("Unlink this source from the RAG pipeline?")) return;
    try {
      await unlinkSourceFromPipeline(source.id, pipelineId);
      setInfo("Pipeline unlinked.");
      await fetchSource();
    } catch (err) {
      setError(toApiError(err, "UNLINK_PIPELINE_FAILED"));
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
  const linkedPipelines = source.pipelines ?? [];
  const filteredCatalog = EXTENDED_CATALOG.filter(
    (item) => categoryFilter === "all" || item.category === categoryFilter
  );

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

            {/* MinIO Bucket Pill */}
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
              <span>{copiedBucket ? "✓" : "📋"}</span>
            </div>
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
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSyncAll}
            disabled={syncingAll}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
          >
            <IconSync size={15} className={syncingAll ? "spin" : ""} />
            <span>{syncingAll ? "Syncing All..." : "Sync All Connectors"}</span>
          </button>
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
            <div className="stats-overview-label">RAG Pipeline Delivery</div>
            <div className="stats-overview-value">{linkedPipelines.length}</div>
            <div className="stats-overview-subtext">
              {linkedPipelines.length === 0 ? "Not linked to vector index" : "Connected to vector store"}
            </div>
          </div>
          <div className="stats-overview-icon stats-icon--purple">
            <IconPipeline size={22} />
          </div>
        </div>
      </div>

      {/* Tab Navigation */}
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
          <span>Bucket Storage Files</span>
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

        <button
          type="button"
          onClick={() => setActiveTab("pipeline")}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.55rem 1.1rem",
            borderRadius: "7px",
            border: "none",
            background: activeTab === "pipeline" ? "linear-gradient(135deg, #388bfd 0%, #1f6feb 100%)" : "transparent",
            color: activeTab === "pipeline" ? "#ffffff" : "#94a3b8",
            fontSize: "0.875rem",
            fontWeight: activeTab === "pipeline" ? 600 : 500,
            cursor: "pointer",
            transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
            boxShadow: activeTab === "pipeline" ? "0 2px 10px rgba(56, 139, 253, 0.35)" : "none",
          }}
        >
          <IconPipeline size={15} />
          <span>Linked RAG Pipelines</span>
          <span
            style={{
              fontSize: "0.72rem",
              padding: "0.15rem 0.5rem",
              borderRadius: "999px",
              background: activeTab === "pipeline" ? "rgba(255, 255, 255, 0.25)" : "rgba(255, 255, 255, 0.08)",
              color: activeTab === "pipeline" ? "#ffffff" : "#8b949e",
              fontWeight: 600,
            }}
          >
            {linkedPipelines.length}
          </span>
        </button>
      </div>

      {/* TAB 1: CONNECTORS CATALOGUE & ACTIVE CONNECTORS */}
      {activeTab === "connectors" && (
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
                <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>⚡</div>
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
                          <span style={{ fontSize: "1.5rem" }}>
                            {EXTENDED_CATALOG.find((item) => item.id === conn.connector_type)?.icon || "⚡"}
                          </span>
                          <div>
                            <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#e6edf3", textTransform: "capitalize" }}>
                              {conn.connector_type.replace(/_/g, " ")}
                            </div>
                            <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>
                              Mode: <span style={{ color: "#58a6ff", fontWeight: 600 }}>{conn.monitor_mode === "scheduled" ? `${conn.sync_interval_minutes || 15}m interval` : "Live Webhooks / CDC"}</span>
                            </div>
                          </div>
                        </div>
                        <StatusBadge status={conn.status || "idle"} />
                      </div>

                      <div style={{ fontSize: "0.78rem", color: "#8b949e", marginBottom: "1rem", background: "rgba(0, 0, 0, 0.2)", padding: "0.5rem 0.75rem", borderRadius: "6px" }}>
                        Last sync: {conn.last_sync_at ? new Date(conn.last_sync_at).toLocaleString() : "Never synced"}
                      </div>
                    </div>

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: "0.75rem", borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleSyncSingleConnector(conn.id)}
                        style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}
                      >
                        <IconSync size={12} />
                        <span>Sync Now</span>
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

          {/* Categorized Connector Catalogue Grid */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "1rem" }}>
              <div>
                <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                  Integration Catalogue
                </h2>
                <div style={{ fontSize: "0.8rem", color: "#8b949e" }}>
                  Attach external services to MinIO bucket <code>{source.minio_bucket}</code>
                </div>
              </div>

              {/* Category Filter Pills */}
              <div style={{ display: "flex", gap: "0.4rem" }}>
                {[
                  { id: "all", label: "All Connectors" },
                  { id: "cloud", label: "Cloud Storage" },
                  { id: "database", label: "Databases" },
                  { id: "files", label: "Files & Web" },
                  { id: "workspace", label: "Workspaces" },
                ].map((cat) => (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => setCategoryFilter(cat.id)}
                    style={{
                      padding: "0.35rem 0.75rem",
                      borderRadius: "6px",
                      fontSize: "0.78rem",
                      fontWeight: 600,
                      border: "none",
                      cursor: "pointer",
                      background: categoryFilter === cat.id ? "#58a6ff" : "rgba(255, 255, 255, 0.06)",
                      color: categoryFilter === cat.id ? "#0b0e14" : "#c9d1d9",
                      transition: "all 0.15s ease",
                    }}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Grid of Catalogue Connectors */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "1rem" }}>
              {filteredCatalog.map((item) => (
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
                      <span style={{ fontSize: "1.75rem" }}>{item.icon}</span>
                      <div>
                        <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#e6edf3" }}>
                          {item.label}
                        </div>
                        <div style={{ fontSize: "0.72rem", color: "#58a6ff", textTransform: "uppercase", fontWeight: 600 }}>
                          {item.category}
                        </div>
                      </div>
                    </div>
                    <p style={{ fontSize: "0.8125rem", color: "#8b949e", lineHeight: 1.4, margin: "0 0 1rem 0" }}>
                      {item.description}
                    </p>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: "0.75rem", borderTop: "1px solid rgba(255, 255, 255, 0.06)" }}>
                    <span style={{ fontSize: "0.75rem", color: "#3fb950", fontWeight: 600 }}>
                      ✓ CDC Poller Supported
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
      {activeTab === "files" && (
        <FileBrowser
          sourceId={source?.id ?? id ?? ""}
          bucketName={source?.bucket_name ?? ""}
          files={files}
          allowUpload={false}
          allowDelete={false}
          onError={(err) => setError(err)}
          onInfo={(msg) => console.log(msg)}
        />
      )}

      {/* TAB 3: LINKED RAG PIPELINES */}
      {activeTab === "pipeline" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                Linked Vector Pipelines ({linkedPipelines.length})
              </h2>
              <div style={{ fontSize: "0.8rem", color: "#8b949e" }}>
                RAG index target vector stores connected to MinIO bucket <code>{source.minio_bucket}</code>
              </div>
            </div>

            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setPipelineModalOpen(true)}
              style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}
            >
              <IconPlus size={15} />
              <span>Link to RAG Pipeline</span>
            </button>
          </div>

          {linkedPipelines.length === 0 ? (
            <div style={{ padding: "3rem 1.5rem", textAlign: "center", background: "rgba(17, 21, 30, 0.4)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
              <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🔮</div>
              <div style={{ fontSize: "0.95rem", fontWeight: 600, color: "#e6edf3", marginBottom: "0.25rem" }}>
                Source not linked to any vector pipeline yet
              </div>
              <div style={{ fontSize: "0.8125rem", color: "#8b949e", marginBottom: "1rem" }}>
                Link this source to a RAG pipeline to automatically vectorize uploaded files into Qdrant collections.
              </div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setPipelineModalOpen(true)}
              >
                + Link Pipeline Now
              </button>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "1rem" }}>
              {linkedPipelines.map((pipe) => (
                <div
                  key={pipe.id}
                  style={{
                    background: "rgba(17, 21, 30, 0.6)",
                    border: "1px solid rgba(88, 166, 253, 0.25)",
                    borderRadius: "12px",
                    padding: "1.25rem",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                      <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "rgba(163, 113, 247, 0.15)", color: "#a371f7", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <IconPipeline size={18} />
                      </div>
                      <div>
                        <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#e6edf3" }}>
                          {pipe.name}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "#8b949e" }}>
                          Qdrant Collection: <code style={{ color: "#a371f7" }}>{pipe.qdrant_collection ?? "default"}</code>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: "0.75rem", borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.75rem", color: "#3fb950" }}>
                      ● Automatic Vector Delivery Active
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleUnlinkPipeline(pipe.id)}
                      style={{ color: "#f85149" }}
                    >
                      Unlink
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
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
                  {editingConnector ? `Configure ${editingConnector.connector_type}` : `Attach ${connectorForm.connectorType.replace(/_/g, " ")}`}
                </h2>
                <div style={{ fontSize: "0.78rem", color: "#8b949e" }}>
                  Destination MinIO Bucket: <code>{source.minio_bucket}</code>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setConnectorModalOpen(false)}
                style={{ background: "none", border: "none", color: "#8b949e", fontSize: "1.25rem", cursor: "pointer" }}
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
                      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e6edf3" }}>Live Webhooks / CDC</div>
                      <div style={{ fontSize: "0.72rem", color: "#8b949e" }}>Real-time change events</div>
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
                      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e6edf3" }}>Scheduled Interval</div>
                      <div style={{ fontSize: "0.72rem", color: "#8b949e" }}>Periodic background poll</div>
                    </div>
                  </label>
                </div>
              </div>

              {connectorForm.monitorMode === "scheduled" && (
                <div>
                  <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "#c9d1d9", marginBottom: "0.4rem" }}>
                    Sync Interval (Minutes)
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={connectorForm.syncIntervalMinutes}
                    onChange={(e) => setConnectorForm((prev) => ({ ...prev, syncIntervalMinutes: e.target.value }))}
                    placeholder="15"
                    style={{
                      width: "100%",
                      padding: "0.65rem 0.85rem",
                      borderRadius: "8px",
                      border: "1px solid rgba(56, 68, 100, 0.45)",
                      background: "rgba(11, 14, 20, 0.6)",
                      color: "#e6edf3",
                    }}
                  />
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

      {/* PIPELINE LINK MODAL */}
      {pipelineModalOpen && (
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
          onClick={() => setPipelineModalOpen(false)}
        >
          <div
            style={{
              width: "100%",
              maxWidth: "480px",
              background: "#111622",
              border: "1px solid rgba(88, 166, 253, 0.3)",
              borderRadius: "16px",
              padding: "1.75rem",
              boxShadow: "0 20px 50px rgba(0, 0, 0, 0.5)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h2 style={{ fontSize: "1.2rem", fontWeight: 700, color: "#e6edf3", margin: 0 }}>
                Link to RAG Pipeline
              </h2>
              <button
                type="button"
                onClick={() => setPipelineModalOpen(false)}
                style={{ background: "none", border: "none", color: "#8b949e", fontSize: "1.25rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleLinkPipelineSubmit}>
              <div style={{ marginBottom: "1.25rem" }}>
                <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: "#c9d1d9", marginBottom: "0.4rem" }}>
                  Select Target Pipeline *
                </label>
                <select
                  value={selectedPipelineId}
                  onChange={(e) => setSelectedPipelineId(e.target.value)}
                  required
                  style={{
                    width: "100%",
                    padding: "0.75rem 1rem",
                    borderRadius: "8px",
                    border: "1px solid rgba(56, 68, 100, 0.5)",
                    background: "rgba(17, 21, 30, 0.8)",
                    color: "#e6edf3",
                    fontSize: "0.9rem",
                  }}
                >
                  <option value="">-- Choose RAG Pipeline --</option>
                  {pipelines.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.qdrant_collection ?? "default collection"})
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setPipelineModalOpen(false)}
                  disabled={linkingPipeline}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={linkingPipeline || !selectedPipelineId}
                >
                  {linkingPipeline ? "Linking..." : "Link Pipeline"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
