import React, { useEffect, useState } from "react";
import {
  createKnowledgeProfile,
  deleteKnowledgeProfile,
  getDestinationOptions,
  listKnowledgeProfiles,
  listSources,
  syncKnowledgeProfile,
  testDestinationConnection,
  updateKnowledgeProfile,
  KnowledgeDestinationOption,
  KnowledgeProfile,
  SourceRecord,
} from "../api";
import {
  IconClose,
  IconDatabase,
  IconDelete,
  IconEdit,
  IconPlus,
  IconRefresh,
  IconServer,
  IconZap,
} from "../components/Icons";

export default function KnowledgeStorePage() {
  const [profiles, setProfiles] = useState<KnowledgeProfile[]>([]);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [destinationOptions, setDestinationOptions] = useState<KnowledgeDestinationOption[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [testingDestMap, setTestingDestMap] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, { status: "success" | "error"; message: string }>>({});

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [editingProfile, setEditingProfile] = useState<KnowledgeProfile | null>(null);
  const [formName, setFormName] = useState<string>("");
  const [formDescription, setFormDescription] = useState<string>("");
  const [formEnabled, setFormEnabled] = useState<boolean>(true);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [destConfigs, setDestConfigs] = useState<
    Record<string, { enabled: boolean; config: Record<string, unknown> }>
  >({});
  const [saving, setSaving] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [profs, srcs, destOpts] = await Promise.all([
        listKnowledgeProfiles(),
        listSources(),
        getDestinationOptions(),
      ]);
      setProfiles(profs);
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

  const openCreateModal = () => {
    setEditingProfile(null);
    setFormName("");
    setFormDescription("");
    setFormEnabled(true);
    setSelectedSourceIds(sources.map((s) => s.id));

    const initialDest: Record<string, { enabled: boolean; config: Record<string, unknown> }> = {};
    destinationOptions.forEach((opt) => {
      initialDest[opt.id] = {
        enabled: true,
        config: { ...opt.default_config },
      };
    });
    setDestConfigs(initialDest);
    setErrorMsg(null);
    setIsModalOpen(true);
  };

  const openEditModal = (profile: KnowledgeProfile) => {
    setEditingProfile(profile);
    setFormName(profile.name);
    setFormDescription(profile.description || "");
    setFormEnabled(profile.enabled);
    setSelectedSourceIds(profile.sources.map((s) => s.source_id));

    const currentDestMap: Record<string, { enabled: boolean; config: Record<string, unknown> }> = {};
    destinationOptions.forEach((opt) => {
      const existing = profile.destinations.find((d) => d.destination_type === opt.id);
      currentDestMap[opt.id] = {
        enabled: existing ? existing.enabled : true,
        config: existing ? { ...existing.config } : { ...opt.default_config },
      };
    });
    setDestConfigs(currentDestMap);
    setErrorMsg(null);
    setIsModalOpen(true);
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) {
      setErrorMsg("Profile name is required.");
      return;
    }
    setSaving(true);
    setErrorMsg(null);

    const formattedDestinations = Object.entries(destConfigs).map(([dest_type, val]) => ({
      destination_type: dest_type,
      enabled: val.enabled,
      config: val.config,
    }));

    try {
      if (editingProfile) {
        await updateKnowledgeProfile(editingProfile.id, {
          name: formName,
          description: formDescription,
          enabled: formEnabled,
          source_ids: selectedSourceIds,
          destinations: formattedDestinations,
        });
      } else {
        await createKnowledgeProfile({
          name: formName,
          description: formDescription,
          enabled: formEnabled,
          source_ids: selectedSourceIds,
          destinations: formattedDestinations,
        });
      }
      setIsModalOpen(false);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save profile.";
      setErrorMsg(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProfile = async (profileId: string) => {
    if (!confirm("Are you sure you want to delete this Knowledge Profile?")) return;
    try {
      await deleteKnowledgeProfile(profileId);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete profile.";
      alert("Failed to delete profile: " + msg);
    }
  };

  const handleSyncProfile = async (profileId: string) => {
    setSyncingId(profileId);
    try {
      await syncKnowledgeProfile(profileId);
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Sync failed.";
      alert("Sync failed: " + msg);
    } finally {
      setSyncingId(null);
    }
  };

  const handleTestConnection = async (profileId: string, destType: string, config: Record<string, unknown>) => {
    const key = `${profileId}-${destType}`;
    setTestingDestMap((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await testDestinationConnection(profileId, destType, config);
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

  // Metrics
  const totalProfiles = profiles.length;
  const linkedBucketsCount = new Set(
    profiles.flatMap((p) => p.sources.map((s) => s.minio_bucket))
  ).size;
  const activeDestinationsCount = profiles.reduce(
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
                Universal Multi-Sink Fanout Engine — Route MinIO documents to 5 enterprise 2026 RAG destinations.
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
            New Knowledge Profile
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
            Total Profiles
          </div>
          <div style={{ fontSize: "28px", fontWeight: 800, color: "#f8fafc" }}>{totalProfiles}</div>
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
            Vector, Lexical, Graph, DB & Cache
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
            5 Parallel Sinks
          </div>
          <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>
            Decoupled MinIO Parser Stream
          </div>
        </div>
      </div>

      {/* Profiles Grid */}
      {loading ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
          Loading Knowledge Profiles...
        </div>
      ) : profiles.length === 0 ? (
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
            No Knowledge Profiles Created
          </h3>
          <p style={{ margin: "0 0 24px 0", fontSize: "14px", color: "#94a3b8" }}>
            Create your first Knowledge Profile to link MinIO document sources with Qdrant, OpenSearch, Neo4j, pgvector & RedisVL.
          </p>
          <button onClick={openCreateModal} className="btn btn-primary">
            <IconPlus style={{ width: "16px", height: "16px", marginRight: "8px" }} />
            Create Knowledge Profile
          </button>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "24px" }}>
          {profiles.map((profile) => {
            const isSyncing = syncingId === profile.id;
            return (
              <div
                key={profile.id}
                style={{
                  background: "rgba(30, 41, 59, 0.6)",
                  border: "1px solid rgba(255, 255, 255, 0.08)",
                  borderRadius: "16px",
                  padding: "24px",
                  backdropFilter: "blur(12px)",
                  boxShadow: "0 4px 20px rgba(0,0,0,0.2)",
                }}
              >
                {/* Profile Card Header */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: "20px",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                      <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#f8fafc" }}>
                        {profile.name}
                      </h2>
                      <span
                        style={{
                          padding: "4px 12px",
                          borderRadius: "20px",
                          fontSize: "12px",
                          fontWeight: 600,
                          background:
                            profile.status === "synced"
                              ? "rgba(52, 211, 153, 0.15)"
                              : profile.status === "syncing"
                              ? "rgba(59, 130, 246, 0.15)"
                              : "rgba(148, 163, 184, 0.15)",
                          color:
                            profile.status === "synced"
                              ? "#34d399"
                              : profile.status === "syncing"
                              ? "#60a5fa"
                              : "#94a3b8",
                          border: `1px solid ${
                            profile.status === "synced"
                              ? "rgba(52, 211, 153, 0.3)"
                              : profile.status === "syncing"
                              ? "rgba(59, 130, 246, 0.3)"
                              : "rgba(148, 163, 184, 0.3)"
                          }`,
                        }}
                      >
                        {profile.status.toUpperCase()}
                      </span>
                    </div>
                    {profile.description && (
                      <p style={{ margin: "6px 0 0 0", fontSize: "14px", color: "#94a3b8" }}>
                        {profile.description}
                      </p>
                    )}
                  </div>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <button
                      onClick={() => handleSyncProfile(profile.id)}
                      disabled={isSyncing}
                      className="btn btn-primary"
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "6px",
                        padding: "8px 16px",
                        fontSize: "13px",
                        fontWeight: 600,
                        background: "linear-gradient(135deg, #10b981 0%, #059669 100%)",
                      }}
                    >
                      <IconZap style={{ width: "15px", height: "15px" }} />
                      {isSyncing ? "Syncing Sinks..." : "Sync All Sinks"}
                    </button>

                    <button
                      onClick={() => openEditModal(profile)}
                      className="btn btn-secondary"
                      style={{ padding: "8px 14px", fontSize: "13px" }}
                    >
                      <IconEdit style={{ width: "15px", height: "15px" }} />
                    </button>

                    <button
                      onClick={() => handleDeleteProfile(profile.id)}
                      className="btn btn-danger"
                      style={{
                        padding: "8px 14px",
                        fontSize: "13px",
                        background: "rgba(239, 68, 68, 0.15)",
                        color: "#ef4444",
                        border: "1px solid rgba(239, 68, 68, 0.3)",
                      }}
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
                    Linked MinIO Source Buckets ({profile.sources.length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
                    {profile.sources.length === 0 ? (
                      <span style={{ fontSize: "13px", color: "#64748b" }}>
                        No MinIO buckets linked.
                      </span>
                    ) : (
                      profile.sources.map((s) => {
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

                {/* 5 Universal RAG Destinations Grid */}
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
                    Configured Destination Stores (Universal 2026 RAG Multi-Sink)
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                      gap: "14px",
                    }}
                  >
                    {destinationOptions.map((opt) => {
                      const destCfg = profile.destinations.find((d) => d.destination_type === opt.id);
                      const isEnabled = destCfg ? destCfg.enabled : false;
                      const testKey = `${profile.id}-${opt.id}`;
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
                              {isEnabled ? "ACTIVE" : "OFF"}
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
                              {opt.id === "vector_qdrant" && `Collection: ${String(destCfg.config.collection_name)}`}
                              {opt.id === "lexical_opensearch" && `Index: ${String(destCfg.config.index_name)}`}
                              {opt.id === "graph_neo4j" && `URI: ${String(destCfg.config.bolt_uri)}`}
                              {opt.id === "relational_pgvector" && `Table: ${String(destCfg.config.table_name)}`}
                              {opt.id === "cache_redisvl" && `Prefix: ${String(destCfg.config.index_prefix)}`}
                            </div>
                          )}

                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            <button
                              onClick={() => handleTestConnection(profile.id, opt.id, destCfg?.config || opt.default_config)}
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
                              {isTesting ? "Testing..." : "Test Connection"}
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
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal / Drawer for Creating / Editing Knowledge Profile */}
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
                {editingProfile ? "Edit Knowledge Profile" : "Configure New Knowledge Profile"}
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

            <form onSubmit={handleSaveProfile}>
              {/* General Info */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "16px", marginBottom: "24px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}>
                    Profile Name *
                  </label>
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Resume Knowledge Fanout Profile"
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

                <div>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: 600, color: "#cbd5e1", marginBottom: "6px" }}>
                    Description
                  </label>
                  <textarea
                    value={formDescription}
                    onChange={(e) => setFormDescription(e.target.value)}
                    placeholder="Universal RAG sink profile routing document embeddings to vector, lexical, graph, DB, and cache stores..."
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

              {/* 5 Universal RAG Destination Configurations */}
              <div style={{ marginBottom: "32px" }}>
                <label style={{ display: "block", fontSize: "14px", fontWeight: 700, color: "#cbd5e1", marginBottom: "12px" }}>
                  Configure 5 Universal 2026 RAG Destination Stores
                </label>

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
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginTop: "12px" }}>
                            {Object.entries(current.config).map(([cfgKey, cfgVal]) => (
                              <div key={cfgKey}>
                                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                                  {cfgKey}
                                </label>
                                <input
                                  type="text"
                                  value={typeof cfgVal === "object" ? JSON.stringify(cfgVal) : String(cfgVal)}
                                  onChange={(e) => {
                                    const val = e.target.value;
                                    setDestConfigs({
                                      ...destConfigs,
                                      [opt.id]: {
                                        ...current,
                                        config: {
                                          ...current.config,
                                          [cfgKey]: val === "true" ? true : val === "false" ? false : isNaN(Number(val)) ? val : Number(val),
                                        },
                                      },
                                    });
                                  }}
                                  style={{
                                    width: "100%",
                                    padding: "6px 10px",
                                    borderRadius: "6px",
                                    background: "rgba(15, 23, 42, 0.8)",
                                    border: "1px solid rgba(255, 255, 255, 0.1)",
                                    color: "#e2e8f0",
                                    fontSize: "12px",
                                  }}
                                />
                              </div>
                            ))}
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
                  {saving ? "Saving Profile..." : editingProfile ? "Update Profile" : "Create Profile"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
