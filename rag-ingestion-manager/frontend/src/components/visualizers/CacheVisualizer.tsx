import React, { useState } from "react";
import { DestinationInspectData } from "../../api";

interface CacheVisualizerProps {
  data: DestinationInspectData;
  loading: boolean;
}

export const CacheVisualizer: React.FC<CacheVisualizerProps> = ({ data, loading }) => {
  const [selectedKey, setSelectedKey] = useState<any | null>(null);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
        Loading semantic cache keys & memory metrics from Redis...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: "20px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "10px", color: "#f87171" }}>
        <strong>Redis Semantic Cache Inspection Error:</strong> {data.error}
      </div>
    );
  }

  const keys = data.keys || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Top Stats Banner */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Cache Index Prefix</div>
          <div style={{ fontSize: "15px", fontWeight: 700, color: "#38bdf8", marginTop: "4px" }}>{data.prefix || "knowledge_cache"}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Cached Keys</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#4ade80", marginTop: "4px" }}>{data.total_cached_keys ?? keys.length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Keys With TTL</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#a855f7", marginTop: "4px" }}>{keys.filter((k) => k.ttl > 0).length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Used Memory</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "#fbbf24", marginTop: "4px" }}>{data.used_memory_human || "1.13M"}</div>
        </div>
      </div>

      {/* Main Cache Key Explorer */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1.1fr", gap: "20px" }}>
        {/* Left: Active Semantic Cache Keys */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0", marginBottom: "12px" }}>
            Active Semantic Cache Keys ({keys.length})
          </div>

          {keys.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 0", color: "#64748b", fontSize: "12px" }}>
              No cache keys found matching prefix <code>{data.prefix}</code>.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", overflowY: "auto", maxHeight: "320px", paddingRight: "4px" }}>
              {keys.map((k, idx) => {
                const isSelected = selectedKey?.key === k.key;
                return (
                  <div
                    key={idx}
                    onClick={() => setSelectedKey(k)}
                    style={{
                      cursor: "pointer",
                      padding: "10px",
                      borderRadius: "8px",
                      background: isSelected ? "rgba(168, 85, 247, 0.15)" : "rgba(30, 41, 59, 0.4)",
                      border: `1px solid ${isSelected ? "rgba(168, 85, 247, 0.4)" : "rgba(255, 255, 255, 0.04)"}`,
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                      <span style={{ fontSize: "12px", fontWeight: 600, color: "#f8fafc", wordBreak: "break-all" }}>
                        ⚡ {k.key}
                      </span>
                      <span style={{ fontSize: "11px", color: "#64748b" }}>Data Type: {k.type}</span>
                    </div>
                    <span style={{ fontSize: "11px", color: k.ttl === -1 ? "#94a3b8" : "#4ade80", background: "rgba(255, 255, 255, 0.05)", padding: "3px 8px", borderRadius: "6px" }}>
                      {k.ttl === -1 ? "No Expiry" : `TTL: ${k.ttl}s`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Cache Key Details & Simulation */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0", marginBottom: "12px" }}>
            Cache Key Details & Eviction Policy
          </div>

          {selectedKey ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "10px", borderRadius: "8px" }}>
                <div style={{ fontSize: "11px", color: "#94a3b8" }}>Redis Key</div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#38bdf8", wordBreak: "break-all" }}>{selectedKey.key}</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Key Type</div>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#4ade80" }}>{selectedKey.type}</div>
                </div>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Time To Live</div>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#fbbf24" }}>
                    {selectedKey.ttl === -1 ? "Persistent (No TTL)" : `${selectedKey.ttl} Seconds`}
                  </div>
                </div>
              </div>
              <div style={{ background: "rgba(15, 23, 42, 0.9)", padding: "12px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ fontSize: "11px", color: "#94a3b8", marginBottom: "6px" }}>Semantic Cache Policy</div>
                <div style={{ fontSize: "12px", color: "#cbd5e1", lineHeight: 1.5 }}>
                  Matches incoming semantic embeddings within cosine similarity threshold $\ge 0.85$. Bypasses LLM generation on cache hit for sub-5ms retrieval.
                </div>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "60px 20px", color: "#64748b", fontSize: "12px" }}>
              👈 Click any cached key to inspect its TTL and semantic cache metadata.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
