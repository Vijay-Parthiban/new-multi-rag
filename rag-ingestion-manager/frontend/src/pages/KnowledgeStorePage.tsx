import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createKnowledgeProduct,
  deleteKnowledgeProduct,
  deletePipeline,
  getDestinationOptions,
  getLiteLLMModels,
  listKnowledgeProducts,
  listSources,
  pauseAllProductDestinations,
  resumeAllProductDestinations,
  testDestinationConnection,
  updateKnowledgeProduct,
  KnowledgeDestinationOption,
  KnowledgeProduct,
  LiteLLMModelOption,
  SourceRecord,
} from "../api";
import ConfirmDialog from "../components/ConfirmDialog";
import DestinationConfigFields from "../components/DestinationConfigFields";
import {
  IconClose,
  IconDatabase,
  IconDelete,
  IconEdit,
  IconPause,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconServer,
} from "../components/Icons";

export default function KnowledgeStorePage() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [destinationOptions, setDestinationOptions] = useState<KnowledgeDestinationOption[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [togglingAllId, setTogglingAllId] = useState<string | null>(null);
  const [testingDestMap, setTestingDestMap] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, { status: "success" | "error"; message: string }>>({});

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingProduct, setEditingProduct] = useState<KnowledgeProduct | null>(null);
  const [formName, setFormName] = useState<string>("");
  const [formDescription, setFormDescription] = useState<string>("");
  const [formEnabled, setFormEnabled] = useState<boolean>(true);
  const [formMonitorMode, setFormMonitorMode] = useState<"live" | "scheduled">("scheduled");
  const [formIntervalValue, setFormIntervalValue] = useState<number>(300);
  const [formIntervalUnit, setFormIntervalUnit] = useState<"seconds" | "minutes">("seconds");
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [destConfigs, setDestConfigs] = useState<
    Record<string, { enabled: boolean; config: Record<string, unknown> }>
  >({});
  const [saving, setSaving] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [litellmModels, setLitellmModels] = useState<LiteLLMModelOption[]>([]);
  const [litellmWarning, setLitellmWarning] = useState<string | null>(null);
  const [productToDelete, setProductToDelete] = useState<KnowledgeProduct | null>(null);
  const [deleting, setDeleting] = useState<boolean>(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [prods, srcs, destOpts] = await Promise.all([
        listKnowledgeProducts(),
        listSources(),
        getDestinationOptions(),
      ]);
      setProducts(prods);
      setSources(srcs);
      setDestinationOptions(destOpts);
    } catch (err: unknown) {
      console.error("Failed to load Knowledge Store data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const buildInitialDestConfigs = (product?: KnowledgeProduct | null) => {
    const initialDest: Record<string, { enabled: boolean; config: Record<string, unknown> }> = {};
    destinationOptions.forEach((opt) => {
      const existing = product?.destinations.find((d) => d.destination_type === opt.id);
      initialDest[opt.id] = {
        enabled: existing ? existing.enabled : true,
        config: {
          ...opt.default_config,
          ...(existing?.config || {}),
        },
      };
    });
    return initialDest;
  };

  const loadLiteLLMModels = async () => {
    try {
      const response = await getLiteLLMModels("all");
      setLitellmModels(response.models);
      setLitellmWarning(response.warning || null);
    } catch {
      setLitellmModels([]);
      setLitellmWarning("Could not load LiteLLM models. You can still type model names manually.");
    }
  };

  const openCreateModal = async () => {
    setEditingProduct(null);
    setFormName("");
    setFormDescription("");
    setFormEnabled(true);
    setFormMonitorMode("scheduled");
    setFormIntervalValue(300);
    setFormIntervalUnit("seconds");
    setSelectedSourceIds(sources.map((s) => s.id));
    setDestConfigs(buildInitialDestConfigs());
    setErrorMsg(null);
    setIsModalOpen(true);
    await loadLiteLLMModels();
  };

  const openEditModal = async (product: KnowledgeProduct) => {
    setEditingProduct(product);
    setFormName(product.name);
    setFormDescription(product.description || "");
    setFormEnabled(product.enabled);
    setFormMonitorMode(product.monitor_mode || "scheduled");
    if (product.sync_interval_minutes) {
      setFormIntervalValue(product.sync_interval_minutes);
      setFormIntervalUnit("minutes");
    } else {
      setFormIntervalValue(product.sync_interval_seconds || 300);
      setFormIntervalUnit("seconds");
    }
    setSelectedSourceIds(product.sources.map((s) => s.source_id));
    setDestConfigs(buildInitialDestConfigs(product));
    setErrorMsg(null);
    setIsModalOpen(true);
    await loadLiteLLMModels();
  };

  const handleSaveProduct = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) {
      setErrorMsg("Product name is required.");
      return;
    }
    if (selectedSourceIds.length === 0) {
      setErrorMsg("Select at least one MinIO bucket source.");
      return;
    }
    if (!Object.values(destConfigs).some((d) => d.enabled)) {
      setErrorMsg("Enable at least one destination.");
      return;
    }

    setSaving(true);
    setErrorMsg(null);

    const formattedDestinations = Object.entries(destConfigs).map(([destination_type, val]) => ({
      destination_type,
      enabled: val.enabled,
      config: val.config,
    }));

    const schedule =
      formMonitorMode === "live"
        ? { monitor_mode: "live" as const, sync_interval_seconds: null, sync_interval_minutes: null }
        : formIntervalUnit === "minutes"
        ? { monitor_mode: "scheduled" as const, sync_interval_seconds: null, sync_interval_minutes: formIntervalValue }
        : { monitor_mode: "scheduled" as const, sync_interval_seconds: formIntervalValue, sync_interval_minutes: null };

    try {
      if (editingProduct) {
        await updateKnowledgeProduct(editingProduct.id, {
          name: formName,
          description: formDescription,
          enabled: formEnabled,
          source_ids: selectedSourceIds,
          destinations: formattedDestinations,
          ...schedule,
        });
      } else {
        await createKnowledgeProduct({
          name: formName,
          description: formDescription,
          enabled: formEnabled,
          source_ids: selectedSourceIds,
          destinations: formattedDestinations,
          ...schedule,
        });
      }
      setIsModalOpen(false);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save product.";
      setErrorMsg(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProduct = async () => {
    if (!productToDelete) return;
    setDeleting(true);
    try {
      await deleteKnowledgeProduct(productToDelete.id);
      setProductToDelete(null);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete product.";
      setErrorMsg(msg);
    } finally {
      setDeleting(false);
    }
  };

  const handleDeletePipeline = async (pipelineId: string) => {
    if (!confirm("Are you sure you want to delete this RAG Pipeline?")) return;
    try {
      await deletePipeline(pipelineId);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete pipeline.";
      alert("Failed to delete pipeline: " + msg);
    }
  };

  const handleToggleAllDestinations = async (product: KnowledgeProduct) => {
    const allPaused = product.destinations.every((d) => !d.enabled);
    setTogglingAllId(product.id);
    try {
      if (allPaused) {
        await resumeAllProductDestinations(product.id);
      } else {
        await pauseAllProductDestinations(product.id);
      }
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to change destinations.";
      alert("Failed to change destinations: " + msg);
    } finally {
      setTogglingAllId(null);
    }
  };

  const handleTestConnection = async (productId: string, destType: string, config: Record<string, unknown>) => {
    const key = `${productId}-${destType}`;
    setTestingDestMap((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await testDestinationConnection(productId, destType, config);
      setTestResults((prev) => ({
        ...prev,
        [key]: { status: res.status, message: res.message },
      }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Connection failed";
      setTestResults((prev) => ({
        ...prev,
        [key]: { status: "error", message: msg },
      }));
    } finally {
      setTestingDestMap((prev) => ({ ...prev, [key]: false }));
    }
  };

  const describeStore = (opt: KnowledgeDestinationOption, config: Record<string, unknown>): string => {
    const fields = opt.namespace_fields || [];
    if (opt.id === "relational_pgvector") {
      return `${String(config.schema_name ?? "")}.${String(config.table_name ?? "")}`;
    }
    const key = fields.find((f) => config[f] != null);
    return key ? String(config[key]) : opt.category;
  };

  const monitorLabel = (product: KnowledgeProduct): string => {
    if (product.monitor_mode === "live") return "Live polling";
    if (product.sync_interval_minutes) return `Scheduled every ${product.sync_interval_minutes}m`;
    if (product.sync_interval_seconds) return `Scheduled every ${product.sync_interval_seconds}s`;
    return "Scheduled";
  };

  // Metrics
  const totalProducts = products.length;
  const linkedBucketsCount = new Set(
    products.flatMap((p) => p.sources.map((s) => s.minio_bucket))
  ).size;
  const activeDestinationsCount = products.reduce(
    (acc, p) => acc + p.destinations.filter((d) => d.enabled).length,
    0
  );

  return (
    <div className="page-container" style={{ padding: "24px", maxWidth: "1400px", margin: "0 auto" }}>
      {/* Header Banner */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "28px",
          background: "linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%)",
          padding: "24px 32px",
          borderRadius: "16px",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "44px",
                height: "44px",
                borderRadius: "12px",
                background: "linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 4px 14px rgba(59, 130, 246, 0.4)",
              }}
            >
              <IconDatabase style={{ width: "24px", height: "24px", color: "#fff" }} />
            </div>
            <div>
              <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 700, color: "#f8fafc" }}>
                Knowledge Store Manager
              </h1>
              <p style={{ margin: "4px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
                Universal Multi-Sink Fanout Engine — Route MinIO documents to 4 enterprise RAG destinations.
              </p>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: "12px" }}>
          <button
            onClick={loadData}
            disabled={loading}
            className="btn btn-secondary"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 18px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
            }}
          >
            <IconRefresh style={{ width: "16px", height: "16px" }} />
            Refresh
          </button>
          <button
            onClick={openCreateModal}
            className="btn btn-primary"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 20px",
              borderRadius: "10px",
              fontSize: "14px",
              fontWeight: 600,
              background: "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
              boxShadow: "0 4px 14px rgba(37, 99, 235, 0.4)",
            }}
          >
            <IconPlus style={{ width: "18px", height: "18px" }} />
            Create Knowledge Product
          </button>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: "20px",
          marginBottom: "32px",
        }}
      >
        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Total Products
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#f8fafc" }}>{totalProducts}</div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Active Knowledge Routing Sets
          </div>
        </div>

        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Connected MinIO Buckets
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#38bdf8" }}>{linkedBucketsCount}</div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Remote Document Repositories
          </div>
        </div>

        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Active RAG Sinks
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#a855f7" }}>{activeDestinationsCount}</div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Vector, Lexical, DB & Cache
          </div>
        </div>

        <div
          style={{
            background: "rgba(30, 41, 59, 0.5)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "20px",
            backdropFilter: "blur(12px)",
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>
            Fanout Engine Architecture
          </div>
          <div style={{ fontSize: "20px", fontWeight: 700, color: "#34d399", marginTop: "4px" }}>
            4 Parallel Sinks
          </div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Decoupled MinIO Parser Stream
          </div>
        </div>
      </div>

      {/* Products Grid */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
          Loading Knowledge Products...
        </div>
      ) : products.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: "60px 20px",
            background: "rgba(30, 41, 59, 0.3)",
            borderRadius: "16px",
            border: "1px dashed rgba(255, 255, 255, 0.12)",
          }}
        >
          <IconDatabase style={{ width: "48px", height: "48px", color: "#64748b", marginBottom: "16px" }} />
          <h3 style={{ margin: "0 0 8px 0", fontSize: "18px", color: "#f8fafc" }}>
            No Knowledge Products Created
          </h3>
          <p style={{ margin: "0 0 24px 0", fontSize: "14px", color: "#94a3b8" }}>
            Create your first Knowledge Product to link MinIO document sources with Qdrant, OpenSearch, pgvector & RedisVL.
          </p>
          <button onClick={openCreateModal} className="btn btn-primary">
            <IconPlus style={{ width: "16px", height: "16px", marginRight: "8px" }} />
            Create Knowledge Product
          </button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "24px" }}>
          {products.map((product) => {
            const allPaused = product.destinations.length > 0 && product.destinations.every((d) => !d.enabled);
            const isTogglingAll = togglingAllId === product.id;
            return (
              <div
                key={product.id}
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/knowledge-store/${product.id}`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate(`/knowledge-store/${product.id}`);
                  }
                }}
                style={{
                  background: "rgba(30, 41, 59, 0.6)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "16px",
                  padding: "24px",
                  backdropFilter: "blur(12px)",
                  boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
                  cursor: "pointer",
                }}
              >
                {/* Product Card Header */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: "20px",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
                      <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#f8fafc" }}>
                        {product.name}
                      </h2>
                      <span className={`status-badge status-${product.status}`}>
                        {product.status.toUpperCase()}
                      </span>
                      <span className="status-badge status-paused">{monitorLabel(product)}</span>
                    </div>
                    {product.description && (
                      <p style={{ margin: "6px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
                        {product.description}
                      </p>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: "8px" }} onKeyDown={(e) => e.stopPropagation()}>
                    {product.destinations.length > 0 && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleToggleAllDestinations(product);
                        }}
                        disabled={isTogglingAll}
                        className="btn btn-secondary"
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "6px",
                          padding: "8px 16px",
                          fontSize: "13px",
                          fontWeight: 600,
                        }}
                      >
                        {allPaused ? (
                          <IconPlay style={{ width: "15px", height: "15px" }} />
                        ) : (
                          <IconPause style={{ width: "15px", height: "15px" }} />
                        )}
                        {allPaused ? "Resume All" : "Pause All"}
                      </button>
                    )}

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openEditModal(product);
                      }}
                      className="btn btn-secondary"
                      style={{ padding: "8px 14px", fontSize: "13px" }}
                      aria-label={`Edit ${product.name}`}
                    >
                      <IconEdit style={{ width: "15px", height: "15px" }} />
                    </button>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setProductToDelete(product);
                      }}
                      className="btn btn-danger"
                      style={{
                        padding: "8px 14px",
                        fontSize: "13px",
                        background: "rgba(239, 68, 68, 0.15)",
                        color: "#ef4444",
                        border: "1px solid rgba(239, 68, 68, 0.3)",
                      }}
                      aria-label={`Delete ${product.name}`}
                    >
                      <IconDelete style={{ width: "15px", height: "15px" }} />
                    </button>
                  </div>
                </div>

                {/* Linked MinIO Source Buckets */}
                <div style={{ marginBottom: "20px" }}>
                  <div
                    style={{
                      fontSize: "12px",
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: "#64748b",
                      marginBottom: "10px",
                    }}
                  >
                    Linked MinIO Source Buckets ({product.sources.length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
                    {product.sources.length === 0 ? (
                      <span style={{ fontSize: "13px", color: "#64748b" }}>
                        No MinIO buckets linked.
                      </span>
                    ) : (
                      product.sources.map((s) => {
                        const isLocal = s.connector_type === "local_filesystem" || s.source_type === "local_filesystem" || s.minio_bucket?.startsWith("local-");
                        const folderName = (s.config?.folder_name as string) || s.minio_bucket?.replace("local-", "");
                        return (
                          <div
                            key={s.source_id}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "8px",
                              padding: "6px 14px",
                              borderRadius: "8px",
                              background: "rgba(15, 23, 42, 0.6)",
                              border: `1px solid ${isLocal ? "rgba(46, 160, 67, 0.3)" : "rgba(56, 189, 248, 0.2)"}`,
                              fontSize: "13px",
                              color: "#e2e8f0",
                            }}
                          >
                            {isLocal ? (
                              <>
                                <span style={{ fontSize: "13px" }}>📁</span>
                                <span style={{ fontWeight: 600 }}>{s.name}</span>
                                <span style={{ color: "#7ee787", fontSize: "11px", fontWeight: 500 }}>
                                  (Local FS: {folderName})
                                </span>
                              </>
                            ) : (
                              <>
                                <IconServer style={{ width: "14px", height: "14px", color: "#38bdf8" }} />
                                <span style={{ fontWeight: 600 }}>{s.name}</span>
                                <span style={{ color: "#64748b", fontSize: "11px" }}>({s.minio_bucket})</span>
                              </>
                            )}
                          </div>
                        );
                      }))}
                  </div>
                </div>

                {/* Destination Stores Grid */}
                <div>
                  <div
                    style={{
                      fontSize: "12px",
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: "#64748b",
                      marginBottom: "12px",
                    }}
                  >
                    Configured Destination Stores
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                      gap: "14px",
                    }}
                  >
                    {destinationOptions.map((opt) => {
                      const destCfg = product.destinations.find((d) => d.destination_type === opt.id);
                      const isEnabled = destCfg ? destCfg.enabled : false;
                      const testKey = `${product.id}-${opt.id}`;
                      const isTesting = testingDestMap[testKey] || false;
                      const testRes = testResults[testKey];

                      return (
                        <div
                          key={opt.id}
                          style={{
                            background: isEnabled ? "rgba(15, 23, 42, 0.7)" : "rgba(15, 23, 42, 0.3)",
                            border: `1px solid ${
                              isEnabled ? "rgba(59, 130, 246, 0.3)" : "rgba(255, 255, 255, 0.05)"
                            }`,
                            borderRadius: "12px",
                            padding: "16px",
                            opacity: isEnabled ? 1 : 0.6,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              marginBottom: "8px",
                            }}
                          >
                            <div style={{ fontWeight: 700, fontSize: "14px", color: "#f8fafc" }}>
                              {opt.name}
                            </div>
                            <span
                              style={{
                                fontSize: "10px",
                                fontWeight: 700,
                                padding: "2px 8px",
                                borderRadius: "4px",
                                background: isEnabled ? "rgba(34, 197, 94, 0.2)" : "rgba(148, 163, 184, 0.1)",
                                color: isEnabled ? "#4ade80" : "#64748b",
                              }}
                            >
                              {isEnabled ? "ACTIVE" : "PAUSED"}
                            </span>
                          </div>

                          <div
                            style={{
                              fontSize: "11px",
                              color: "#94a3b8",
                              marginBottom: "12px",
                              minHeight: "32px",
                              lineHeight: "1.4",
                            }}
                          >
                            {opt.description}
                          </div>

                          {destCfg?.config && (
                            <div
                              style={{
                                fontSize: "11px",
                                fontFamily: "monospace",
                                color: "#64748b",
                                background: "rgba(0,0,0,0.3)",
                                padding: "6px 8px",
                                borderRadius: "6px",
                                marginBottom: "12px",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {describeStore(opt, destCfg.config)}
                            </div>
                          )}

                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px" }}>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTestConnection(product.id, opt.id, destCfg?.config || opt.default_config);
                              }}
                              disabled={isTesting || !isEnabled}
                              style={{
                                background: "none",
                                border: "1px solid rgba(255, 255, 255, 0.15)",
                                borderRadius: "6px",
                                color: "#cbd5e1",
                                fontSize: "11px",
                                padding: "4px 8px",
                                cursor: "pointer",
                              }}
                            >
                              {isTesting ? "Testing..." : "Test Link"}
                            </button>

                            {testRes && (
                              <span
                                style={{
                                  fontSize: "11px",
                                  color: testRes.status === "success" ? "#4ade80" : "#f87171",
                                }}
                              >
                                {testRes.status === "success" ? "Connected" : "Failed"}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  {/* Linked RAG Pipelines Section */}
                  <div style={{ marginTop: "24px", paddingTop: "20px", borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                      <div>
                        <h4 style={{ fontSize: "14px", fontWeight: 700, color: "#f8fafc", margin: 0 }}>
                          Linked RAG Pipelines ({product.pipelines?.length || 0})
                        </h4>
                        <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "2px" }}>
                          Vector search & ingestion pipelines connected to this Knowledge Product
                        </div>
                      </div>
                      <a
                        href="/pipelines"
                        className="btn btn-secondary"
                        onClick={(e) => e.stopPropagation()}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "6px",
                          padding: "6px 12px",
                          fontSize: "12px",
                          fontWeight: 600,
                          textDecoration: "none",
                        }}
                      >
                        <IconPlus style={{ width: "14px", height: "14px" }} />
                        Create / Manage Pipelines
                      </a>
                    </div>

                    {(!product.pipelines || product.pipelines.length === 0) ? (
                      <div style={{ padding: "16px", textAlign: "center", background: "rgba(15, 23, 42, 0.4)", borderRadius: "10px", border: "1px dashed rgba(255, 255, 255, 0.1)", fontSize: "13px", color: "#64748b" }}>
                        No RAG pipelines linked to this product. Create one on the Pipelines page.
                      </div>
                    ) : (
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "12px" }}>
                        {product.pipelines.map((pipe) => (
                          <div
                            key={pipe.id}
                            style={{
                              background: "rgba(15, 23, 42, 0.6)",
                              border: "1px solid rgba(255, 255, 255, 0.08)",
                              borderRadius: "10px",
                              padding: "14px",
                              display: "flex",
                              flexDirection: "column",
                              justifyContent: "space-between",
                            }}
                          >
                            <div>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                                <span style={{ fontWeight: 700, fontSize: "14px", color: "#f8fafc" }}>{pipe.name}</span>
                                <span
                                  style={{
                                    fontSize: "10px",
                                    fontWeight: 700,
                                    padding: "2px 8px",
                                    borderRadius: "4px",
                                    background: "rgba(34, 197, 94, 0.2)",
                                    color: "#4ade80",
                                  }}
                                >
                                  ACTIVE
                                </span>
                              </div>
                              <div style={{ fontSize: "12px", color: "#94a3b8", display: "flex", flexDirection: "column", gap: "4px" }}>
                                <div><strong>Collection:</strong> <code>{pipe.qdrant_collection}</code></div>
                                <div><strong>Strategy:</strong> {pipe.rag_strategy} ({pipe.chunk_size} / {pipe.chunk_overlap})</div>
                                <div><strong>Embedding:</strong> {pipe.embedding_model}</div>
                              </div>
                            </div>
                            <div style={{ marginTop: "12px", paddingTop: "8px", borderTop: "1px solid rgba(255, 255, 255, 0.05)", display: "flex", justifyContent: "flex-end" }}>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePipeline(pipe.id);
                                }}
                                style={{
                                  background: "rgba(239, 68, 68, 0.1)",
                                  border: "1px solid rgba(239, 68, 68, 0.2)",
                                  color: "#ef4444",
                                  borderRadius: "6px",
                                  padding: "4px 10px",
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  cursor: "pointer",
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "4px",
                                }}
                              >
                                <IconDelete style={{ width: "12px", height: "12px" }} />
                                Delete
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal / Drawer for Creating / Editing a Knowledge Product */}
      {isModalOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.75)",
            backdropFilter: "blur(8px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              borderRadius: "20px",
              width: "100%",
              maxWidth: "850px",
              maxHeight: "90vh",
              overflowY: "auto",
              padding: "32px",
              boxShadow: "0 20px 50px rgba(0, 0, 0, 0.5)",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "24px",
                paddingBottom: "16px",
                borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#f8fafc" }}>
                {editingProduct ? "Edit Knowledge Product" : "Configure New Knowledge Product"}
              </h2>
              <button
                onClick={() => setIsModalOpen(false)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#94a3b8",
                  cursor: "pointer",
                  padding: "4px",
                }}
                aria-label="Close"
              >
                <IconClose style={{ width: "20px", height: "20px" }} />
              </button>
            </div>

            {errorMsg && (
              <div
                style={{
                  padding: "12px 16px",
                  borderRadius: "10px",
                  background: "rgba(239, 68, 68, 0.15)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  color: "#f87171",
                  fontSize: "13px",
                  marginBottom: "20px",
                }}
              >
                {errorMsg}
              </div>
            )}

            <form onSubmit={handleSaveProduct}>
              {/* General Info */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "16px", marginBottom: "24px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}>
                    Product Name *
                  </label>
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Resume Knowledge Fanout Product"
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      borderRadius: "10px",
                      background: "rgba(30, 41, 59, 0.8)",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      color: "#f8fafc",
                      fontSize: "14px",
                    }}
                  />
                </div>

                <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={formEnabled}
                    onChange={(e) => setFormEnabled(e.target.checked)}
                  />
                  <span style={{ fontSize: "13px", color: "#cbd5e1" }}>Product enabled</span>
                </label>

                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}>
                    Description
                  </label>
                  <textarea
                    value={formDescription}
                    onChange={(e) => setFormDescription(e.target.value)}
                    placeholder="Universal RAG sink product routing document embeddings to vector, lexical, DB, and cache stores..."
                    rows={2}
                    style={{
                      width: "100%",
                      padding: "10px 14px",
                      borderRadius: "10px",
                      background: "rgba(30, 41, 59, 0.8)",
                      border: "1px solid rgba(255, 255, 255, 0.1)",
                      color: "#f8fafc",
                      fontSize: "14px",
                      resize: "none",
                    }}
                  />
                </div>

                {/* Sync schedule */}
                <div
                  style={{
                    padding: "16px",
                    borderRadius: "12px",
                    background: "rgba(30, 41, 59, 0.5)",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                  }}
                >
                  <div style={{ fontSize: "13px", fontWeight: 700, color: "#cbd5e1", marginBottom: "4px" }}>
                    Sync Mode
                  </div>
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "12px" }}>
                    Ingestion runs on its own. There is no manual sync.
                  </div>

                  <div style={{ display: "flex", gap: "20px", flexWrap: "wrap" }}>
                    <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                      <input
                        type="radio"
                        name="monitor-mode"
                        checked={formMonitorMode === "live"}
                        onChange={() => setFormMonitorMode("live")}
                      />
                      <span style={{ fontSize: "13px", color: "#cbd5e1" }}>Immediate live sync</span>
                    </label>
                    <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                      <input
                        type="radio"
                        name="monitor-mode"
                        checked={formMonitorMode === "scheduled"}
                        onChange={() => setFormMonitorMode("scheduled")}
                      />
                      <span style={{ fontSize: "13px", color: "#cbd5e1" }}>Scheduled sync</span>
                    </label>
                  </div>

                  {formMonitorMode === "scheduled" && (
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "14px", flexWrap: "wrap" }}>
                      <label htmlFor="sync-interval" style={{ fontSize: "13px", color: "#cbd5e1" }}>
                        Check for new data every
                      </label>
                      <input
                        id="sync-interval"
                        type="number"
                        min={1}
                        value={formIntervalValue}
                        onChange={(e) => setFormIntervalValue(Math.max(1, Number(e.target.value) || 1))}
                        style={{
                          width: "100px",
                          padding: "8px 12px",
                          borderRadius: "8px",
                          background: "rgba(30, 41, 59, 0.8)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          color: "#f8fafc",
                          fontSize: "13px",
                        }}
                      />
                      <select
                        value={formIntervalUnit}
                        onChange={(e) => setFormIntervalUnit(e.target.value as "seconds" | "minutes")}
                        style={{
                          padding: "8px 12px",
                          borderRadius: "8px",
                          background: "rgba(30, 41, 59, 0.8)",
                          border: "1px solid rgba(255, 255, 255, 0.1)",
                          color: "#f8fafc",
                          fontSize: "13px",
                        }}
                      >
                        <option value="seconds">Seconds (minimum 5)</option>
                        <option value="minutes">Minutes</option>
                      </select>
                    </div>
                  )}
                </div>
              </div>

              {/* MinIO Bucket & Local File System Source Selection */}
              <div style={{ marginBottom: "28px" }}>
                <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#cbd5e1", marginBottom: "4px" }}>
                  Link Data Sources (MinIO Buckets & Local File Systems)
                </label>
                <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "10px" }}>
                  Select at least one MinIO bucket source, at least one Local File System source, or any combination of both.
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {sources.length === 0 ? (
                    <div style={{ fontSize: "13px", color: "#64748b" }}>No sources available.</div>
                  ) : (
                    sources.map((src) => {
                      const isSelected = selectedSourceIds.includes(src.id);
                      const isLocal = src.connector_type === "local_filesystem" || src.source_type === "local_filesystem" || src.minio_bucket?.startsWith("local-");
                      const folderName = (src.config?.folder_name as string) || src.minio_bucket?.replace("local-", "");
                      return (
                        <label
                          key={src.id}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "12px",
                            padding: "10px 14px",
                            borderRadius: "10px",
                            background: isSelected ? (isLocal ? "rgba(46, 160, 67, 0.15)" : "rgba(59, 130, 246, 0.12)") : "rgba(30, 41, 59, 0.5)",
                            border: `1px solid ${isSelected ? (isLocal ? "rgba(46, 160, 67, 0.4)" : "rgba(59, 130, 246, 0.3)") : "rgba(255, 255, 255, 0.08)"}`,
                            cursor: "pointer",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedSourceIds([...selectedSourceIds, src.id]);
                              } else {
                                setSelectedSourceIds(selectedSourceIds.filter((id) => id !== src.id));
                              }
                            }}
                          />
                          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 600, fontSize: "14px", color: "#f8fafc" }}>
                              {src.name}
                            </span>
                            {isLocal ? (
                              <span
                                style={{
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  color: "#7ee787",
                                  padding: "2px 8px",
                                  borderRadius: "6px",
                                  background: "rgba(46, 160, 67, 0.2)",
                                  border: "1px solid rgba(46, 160, 67, 0.3)",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "4px",
                                }}
                              >
                                📁 Local File System (storage/local_sources/{folderName})
                              </span>
                            ) : (
                              <span
                                style={{
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  color: "#38bdf8",
                                  padding: "2px 8px",
                                  borderRadius: "6px",
                                  background: "rgba(56, 189, 248, 0.15)",
                                  border: "1px solid rgba(56, 189, 248, 0.25)",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "4px",
                                }}
                              >
                                🪣 MinIO Bucket ({src.minio_bucket})
                              </span>
                            )}
                          </div>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Destination Configurations */}
              <div style={{ marginBottom: "32px" }}>
                <label style={{ display: "block", fontSize: "14px", fontWeight: 700, color: "#cbd5e1", marginBottom: "12px" }}>
                  Configure Destination Stores
                </label>
                {litellmWarning && (
                  <div style={{ fontSize: "12px", color: "#fbbf24", marginBottom: "10px" }}>
                    {litellmWarning}
                  </div>
                )}
                {litellmModels.length > 0 && (
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "12px" }}>
                    LiteLLM models loaded: {litellmModels.length} available for embedding, chat, and sparse fields.
                  </div>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {destinationOptions.map((opt) => {
                    const current = destConfigs[opt.id] || { enabled: true, config: opt.default_config };
                    return (
                      <div
                        key={opt.id}
                        style={{
                          background: "rgba(30, 41, 59, 0.5)",
                          border: "1px solid rgba(255, 255, 255, 0.08)",
                          borderRadius: "12px",
                          padding: "16px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            marginBottom: "12px",
                          }}
                        >
                          <div>
                            <span style={{ fontSize: "11px", fontWeight: 700, color: "#38bdf8", textTransform: "uppercase" }}>
                              {opt.category}
                            </span>
                            <h4 style={{ margin: "2px 0 0 0", fontSize: "15px", fontWeight: 700, color: "#f8fafc" }}>
                              {opt.name}
                            </h4>
                          </div>

                          <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                            <span style={{ fontSize: "12px", color: "#94a3b8" }}>Enable Fanout</span>
                            <input
                              type="checkbox"
                              checked={current.enabled}
                              onChange={(e) => {
                                setDestConfigs({
                                  ...destConfigs,
                                  [opt.id]: { ...current, enabled: e.target.checked },
                                });
                              }}
                            />
                          </label>
                        </div>

                        {current.enabled && (
                          <div style={{ marginTop: "12px" }}>
                            <DestinationConfigFields
                              option={opt}
                              config={current.config}
                              litellmModels={litellmModels}
                              onChange={(nextConfig) => {
                                setDestConfigs({
                                  ...destConfigs,
                                  [opt.id]: {
                                    ...current,
                                    config: nextConfig,
                                  },
                                });
                              }}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Form Footer Actions */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px" }}>
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="btn btn-secondary"
                  style={{ padding: "10px 20px" }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="btn btn-primary"
                  style={{
                    padding: "10px 24px",
                    background: "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
                  }}
                >
                  {saving ? "Saving Product..." : editingProduct ? "Update Product" : "Create Knowledge Product"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={productToDelete !== null}
        title="Delete Knowledge Product"
        message={`Delete '${productToDelete?.name ?? ""}'? Its content is removed from every destination store.`}
        details={
          productToDelete
            ? [
                `Bucket sources: ${productToDelete.sources.length}`,
                `Destinations: ${productToDelete.destinations.length}`,
                `Indexed files: ${productToDelete.files_total}`,
              ]
            : undefined
        }
        confirmLabel="Delete product"
        cancelLabel="Keep product"
        danger
        busy={deleting}
        onConfirm={handleDeleteProduct}
        onCancel={() => setProductToDelete(null)}
      />
    </div>
  );
}
