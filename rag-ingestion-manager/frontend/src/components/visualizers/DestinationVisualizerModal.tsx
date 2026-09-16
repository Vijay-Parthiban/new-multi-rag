import React, { useEffect, useState } from "react";
import { DestinationInspectData, inspectDestinationStore, KnowledgeProfile } from "../../api";
import { IconClose, IconDatabase, IconRefresh, IconServer, IconZap } from "../Icons";
import { VectorVisualizer } from "./VectorVisualizer";
import { LexicalVisualizer } from "./LexicalVisualizer";
import { GraphVisualizer } from "./GraphVisualizer";
import { RelationalVisualizer } from "./RelationalVisualizer";
import { CacheVisualizer } from "./CacheVisualizer";

interface DestinationVisualizerModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: KnowledgeProfile | null;
  initialDestinationType?: string;
}

const DESTINATION_TABS = [
  { id: "vector_qdrant", label: "Vector Search", engine: "Qdrant", icon: "🌌", color: "#38bdf8" },
  { id: "lexical_opensearch", label: "Lexical BM25", engine: "OpenSearch", icon: "🔍", color: "#818cf8" },
  { id: "graph_neo4j", label: "Knowledge Graph", engine: "Neo4j", icon: "🕸️", color: "#34d399" },
  { id: "relational_pgvector", label: "Relational Chunks", engine: "PostgreSQL", icon: "🗄️", color: "#fbbf24" },
  { id: "cache_redisvl", label: "Semantic Cache", engine: "RedisVL", icon: "⚡", color: "#f472b6" },
];

export const DestinationVisualizerModal: React.FC<DestinationVisualizerModalProps> = ({
  isOpen,
  onClose,
  profile,
  initialDestinationType = "vector_qdrant",
}) => {
  const [activeTab, setActiveTab] = useState<string>(initialDestinationType);
  const [inspectData, setInspectData] = useState<DestinationInspectData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (initialDestinationType) {
      setActiveTab(initialDestinationType);
    }
  }, [initialDestinationType]);

  const loadData = async (destType: string) => {
    if (!profile) return;
    setLoading(true);
    try {
      const res = await inspectDestinationStore(profile.id, destType);
      setInspectData(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load store inspection data";
      setInspectData({ destination_type: destType, error: msg });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen && profile) {
      loadData(activeTab);
    }
  }, [isOpen, profile, activeTab]);

  if (!isOpen || !profile) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(10, 15, 29, 0.85)",
        backdropFilter: "blur(12px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9999,
        padding: "20px",
      }}
    >
      <div
        style={{
          background: "linear-gradient(145deg, #1e293b, #0f172a)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          borderRadius: "20px",
          width: "100%",
          maxWidth: "1150px",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 25px 60px -15px rgba(0, 0, 0, 0.7)",
          overflow: "hidden",
        }}
      >
        {/* Modal Header */}
        <div
          style={{
            padding: "20px 24px",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            background: "rgba(15, 23, 42, 0.6)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "40px",
                height: "40px",
                borderRadius: "10px",
                background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "20px",
              }}
            >
              🔭
            </div>
            <div>
              <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#f8fafc", margin: 0 }}>
                Destination Store Visualizer & Live Inspector
              </h3>
              <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "2px" }}>
                Knowledge Profile: <span style={{ color: "#38bdf8", fontWeight: 600 }}>{profile.name}</span>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <button
              onClick={() => loadData(activeTab)}
              disabled={loading}
              className="btn btn-secondary"
              style={{
                padding: "6px 12px",
                fontSize: "12px",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                borderRadius: "8px",
                background: "rgba(30, 41, 59, 0.7)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                color: "#e2e8f0",
                cursor: "pointer",
              }}
            >
              <IconRefresh style={{ width: "13px", height: "13px", animation: loading ? "spin 1s linear infinite" : undefined }} />
              {loading ? "Refreshing..." : "Refresh Live Data"}
            </button>
            <button
              onClick={onClose}
              style={{
                background: "transparent",
                border: "none",
                color: "#94a3b8",
                cursor: "pointer",
                padding: "6px",
                borderRadius: "6px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <IconClose style={{ width: "20px", height: "20px" }} />
            </button>
          </div>
        </div>

        {/* 5 Destination Navigation Tabs */}
        <div
          style={{
            display: "flex",
            gap: "8px",
            padding: "12px 24px",
            background: "rgba(15, 23, 42, 0.4)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
            overflowX: "auto",
          }}
        >
          {DESTINATION_TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "8px 16px",
                  borderRadius: "10px",
                  border: `1px solid ${isActive ? tab.color : "rgba(255, 255, 255, 0.06)"}`,
                  background: isActive ? `${tab.color}15` : "rgba(30, 41, 59, 0.4)",
                  color: isActive ? "#ffffff" : "#94a3b8",
                  fontWeight: isActive ? 700 : 500,
                  fontSize: "13px",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                <span
                  style={{
                    fontSize: "10px",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    background: "rgba(255, 255, 255, 0.08)",
                    color: tab.color,
                    fontWeight: 600,
                  }}
                >
                  {tab.engine}
                </span>
              </button>
            );
          })}
        </div>

        {/* Modal Content Visualizer Area */}
        <div style={{ padding: "24px", overflowY: "auto", flex: 1 }}>
          {inspectData && (
            <>
              {activeTab === "vector_qdrant" && (
                <VectorVisualizer data={inspectData} loading={loading} />
              )}
              {activeTab === "lexical_opensearch" && (
                <LexicalVisualizer data={inspectData} loading={loading} />
              )}
              {activeTab === "graph_neo4j" && (
                <GraphVisualizer data={inspectData} loading={loading} />
              )}
              {activeTab === "relational_pgvector" && (
                <RelationalVisualizer data={inspectData} loading={loading} />
              )}
              {activeTab === "cache_redisvl" && (
                <CacheVisualizer data={inspectData} loading={loading} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
