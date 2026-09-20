/**
 * Knowledge Store — view only.
 *
 * This page displays the Knowledge Products that the rag-ingestion-manager owns.
 * It never creates, edits or deletes one: the ingestion manager is the only place
 * that writes them. Its two actions are read-only:
 *
 *  - `Refresh` re-reads every product and asks the ingestion manager for an
 *    immediate fanout, so the page shows current data and the stores catch up.
 *  - `View` opens the read-only configuration page for one product.
 *
 * The page also re-reads automatically whenever the route is entered, so the
 * numbers are current on every visit.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  getDestinationOptions,
  listKnowledgeProducts,
  refreshKnowledgeProduct,
  testDestinationConnection,
  KnowledgeDestinationOption,
  KnowledgeProduct,
} from "../api";
import { IconArrowRight, IconDatabase, IconPlus, IconRefresh, IconServer } from "../components/Icons";

export default function KnowledgeStorePage() {
  const navigate = useNavigate();
  const location = useLocation();

  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [destinationOptions, setDestinationOptions] = useState<KnowledgeDestinationOption[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [testingDestMap, setTestingDestMap] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<
    Record<string, { status: "success" | "error"; message: string }>
  >({});

  const loadData = useCallback(async () => {
    try {
      const [prods, destOpts] = await Promise.all([
        listKnowledgeProducts(),
        getDestinationOptions(),
      ]);
      setProducts(prods);
      setDestinationOptions(destOpts);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load Knowledge Products.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The layout keeps every page mounted and toggles visibility, so a plain mount
  // effect runs once. Re-read whenever this route is entered instead.
  const pathname = location.pathname;
  useEffect(() => {
    if (pathname === "/knowledge-store") void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  /** Re-read every product and ask the ingestion manager to sync each one now. */
  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await Promise.allSettled(products.map((p) => refreshKnowledgeProduct(p.id)));
      await loadData();
    } finally {
      setRefreshing(false);
    }
  };

  const describeStore = (opt: KnowledgeDestinationOption, config: Record<string, unknown>): string => {
    if (opt.id === "relational_pgvector") {
      return `${String(config.schema_name ?? "")}.${String(config.table_name ?? "")}`;
    }
    const key = (opt.namespace_fields || []).find((f: string) => config[f] != null);
    return key ? String(config[key]) : opt.category;
  };

  const handleTestConnection = async (
    profileId: string,
    destType: string,
    config: Record<string, unknown>
  ) => {
    const key = `${profileId}-${destType}`;
    setTestingDestMap((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await testDestinationConnection(profileId, destType, config);
      setTestResults((prev) => ({ ...prev, [key]: { status: res.status, message: res.message } }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Connection failed";
      setTestResults((prev) => ({ ...prev, [key]: { status: "error", message: msg } }));
    } finally {
      setTestingDestMap((prev) => ({ ...prev, [key]: false }));
    }
  };

  // Metrics
  const totalProducts = products.length;
  const linkedBucketsCount = new Set(products.flatMap((p) => p.sources.map((s) => s.minio_bucket))).size;
  const activeDestinationsCount = products.reduce(
    (acc, p) => acc + p.destinations.filter((d) => d.enabled).length,
    0
  );

  /** A product is running when it is enabled and at least one destination is on. */
  const isRunning = (product: KnowledgeProduct): boolean =>
    product.enabled && product.destinations.some((d) => d.enabled);

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
              Knowledge Store
            </h1>
            <p style={{ margin: "4px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
              View only — the Knowledge Products configured in the Ingestion Manager.
            </p>
          </div>
        </div>

        <button
          onClick={handleRefresh}
          disabled={loading || refreshing}
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
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
          {error}
          <button className="btn btn-sm btn-secondary" style={{ marginLeft: "0.75rem" }} onClick={loadData}>
            Retry
          </button>
        </div>
      )}

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
            Vector, Lexical, DB &amp; Cache
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

      {/* Products */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
          Loading Knowledge Products…
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
            No Knowledge Products
          </h3>
          <p style={{ margin: 0, fontSize: "14px", color: "#94a3b8" }}>
            Create one in the Ingestion Manager, then press Refresh here.
          </p>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "24px" }}>
          {products.map((product) => {
            const running = isRunning(product);
            return (
              <div
                key={product.id}
                style={{
                  background: "rgba(30, 41, 59, 0.6)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "16px",
                  padding: "24px",
                  backdropFilter: "blur(12px)",
                  boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
                }}
              >
                {/* Card header */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: "20px",
                    gap: "16px",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
                      <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#f8fafc" }}>
                        {product.name}
                      </h2>
                      <span className={running ? "status-badge status-synced" : "status-badge status-paused"}>
                        {running ? "Running" : "Paused"}
                      </span>
                      <span
                        style={{
                          padding: "4px 12px",
                          borderRadius: "20px",
                          fontSize: "12px",
                          fontWeight: 600,
                          background:
                            product.status === "synced"
                              ? "rgba(52, 211, 153, 0.15)"
                              : product.status === "syncing"
                              ? "rgba(59, 130, 246, 0.15)"
                              : "rgba(148, 163, 184, 0.15)",
                          color:
                            product.status === "synced"
                              ? "#34d399"
                              : product.status === "syncing"
                              ? "#60a5fa"
                              : "#94a3b8",
                          border: `1px solid ${
                            product.status === "synced"
                              ? "rgba(52, 211, 153, 0.3)"
                              : product.status === "syncing"
                              ? "rgba(59, 130, 246, 0.3)"
                              : "rgba(148, 163, 184, 0.3)"
                          }`,
                        }}
                      >
                        {product.status.toUpperCase()}
                      </span>
                    </div>
                    {product.description && (
                      <p style={{ margin: "6px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
                        {product.description}
                      </p>
                    )}
                  </div>

                  <button
                    onClick={() => navigate(`/knowledge-store/${product.id}`)}
                    className="btn btn-primary"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "8px",
                      padding: "8px 16px",
                      fontSize: "13px",
                      flexShrink: 0,
                    }}
                  >
                    View
                    <IconArrowRight style={{ width: "15px", height: "15px" }} />
                  </button>
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
                      <span style={{ fontSize: "13px", color: "#64748b" }}>No MinIO buckets linked.</span>
                    ) : (
                      product.sources.map((s) => (
                        <div
                          key={s.source_id}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                            padding: "6px 14px",
                            borderRadius: "8px",
                            background: "rgba(15, 23, 42, 0.6)",
                            border: "1px solid rgba(56, 189, 248, 0.2)",
                            fontSize: "13px",
                            color: "#e2e8f0",
                          }}
                        >
                          <IconServer style={{ width: "14px", height: "14px", color: "#38bdf8" }} />
                          <span style={{ fontWeight: 600 }}>{s.name}</span>
                          <span style={{ color: "#64748b", fontSize: "11px" }}>({s.minio_bucket})</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Destination Stores */}
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
                            background: "rgba(15, 23, 42, 0.5)",
                            border: `1px solid ${
                              isEnabled ? "rgba(56, 189, 248, 0.2)" : "rgba(255, 255, 255, 0.05)"
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
                            <span style={{ fontSize: "14px", fontWeight: 700, color: "#f8fafc" }}>
                              {opt.name}
                            </span>
                            <span
                              style={{
                                fontSize: "10px",
                                fontWeight: 700,
                                padding: "2px 8px",
                                borderRadius: "4px",
                                background: isEnabled
                                  ? "rgba(34, 197, 94, 0.2)"
                                  : "rgba(148, 163, 184, 0.2)",
                                color: isEnabled ? "#4ade80" : "#94a3b8",
                              }}
                            >
                              {isEnabled ? "RUNNING" : "PAUSED"}
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

                          {isEnabled && destCfg?.config && (
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

                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                            }}
                          >
                            <button
                              onClick={() =>
                                handleTestConnection(
                                  product.id,
                                  opt.id,
                                  destCfg?.config || opt.default_config
                                )
                              }
                              disabled={isTesting || !isEnabled}
                              style={{
                                background: "none",
                                border: "1px solid rgba(255, 255, 255, 0.15)",
                                borderRadius: "6px",
                                color: "#cbd5e1",
                                fontSize: "11px",
                                padding: "4px 8px",
                                cursor: isEnabled ? "pointer" : "not-allowed",
                              }}
                            >
                              {isTesting ? "Testing…" : "Test Connection"}
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

                  {/* Linked RAG Pipelines */}
                  <div
                    style={{
                      marginTop: "24px",
                      paddingTop: "20px",
                      borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: "16px",
                      }}
                    >
                      <div>
                        <h4 style={{ fontSize: "14px", fontWeight: 700, color: "#f8fafc", margin: 0 }}>
                          Linked RAG Pipelines ({product.pipelines?.length || 0})
                        </h4>
                        <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "2px" }}>
                          RAG pipelines reading this Knowledge Product
                        </div>
                      </div>
                      <Link
                        to="/pipelines"
                        className="btn btn-secondary"
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
                      </Link>
                    </div>

                    {!product.pipelines || product.pipelines.length === 0 ? (
                      <div
                        style={{
                          padding: "16px",
                          textAlign: "center",
                          background: "rgba(15, 23, 42, 0.4)",
                          borderRadius: "10px",
                          border: "1px dashed rgba(255, 255, 255, 0.1)",
                          fontSize: "13px",
                          color: "#64748b",
                        }}
                      >
                        No RAG pipelines linked to this product. Create one on the Pipelines page.
                      </div>
                    ) : (
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                          gap: "12px",
                        }}
                      >
                        {product.pipelines.map((pipe) => (
                          <div
                            key={pipe.id}
                            style={{
                              background: "rgba(15, 23, 42, 0.6)",
                              border: "1px solid rgba(255, 255, 255, 0.08)",
                              borderRadius: "10px",
                              padding: "14px",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "flex-start",
                                marginBottom: "8px",
                              }}
                            >
                              <span style={{ fontWeight: 700, fontSize: "14px", color: "#f8fafc" }}>
                                {pipe.name}
                              </span>
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
                            <div
                              style={{
                                fontSize: "12px",
                                color: "#94a3b8",
                                display: "flex",
                                flexDirection: "column",
                                gap: "4px",
                              }}
                            >
                              <div>
                                <strong>Collection:</strong> <code>{pipe.qdrant_collection}</code>
                              </div>
                              <div>
                                <strong>Strategy:</strong> {pipe.rag_strategy} ({pipe.chunk_size} /{" "}
                                {pipe.chunk_overlap})
                              </div>
                              <div>
                                <strong>Embedding:</strong> {pipe.embedding_model}
                              </div>
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
    </div>
  );
}
