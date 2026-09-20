import React, { useState } from "react";
import { DestinationInspectData } from "../../api";

interface VectorVisualizerProps {
  data: DestinationInspectData;
  loading: boolean;
}

export const VectorVisualizer: React.FC<VectorVisualizerProps> = ({ data, loading }) => {
  const [selectedPoint, setSelectedPoint] = useState<any | null>(null);
  const [filterQuery, setFilterQuery] = useState<string>("");

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
        Loading high-dimensional vector embeddings from Qdrant...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: "20px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "10px", color: "#f87171" }}>
        <strong>Qdrant Inspection Error:</strong> {data.error}
      </div>
    );
  }

  const points = data.points || [];
  const filteredPoints = filterQuery
    ? points.filter((p) => {
        const text = p.payload?.text || "";
        const file = p.payload?.file_key || "";
        return text.toLowerCase().includes(filterQuery.toLowerCase()) || file.toLowerCase().includes(filterQuery.toLowerCase());
      })
    : points;

  // Coordinate normalizer for 500x320 SVG canvas
  const minX = Math.min(...points.map((p) => p.x), -10);
  const maxX = Math.max(...points.map((p) => p.x), 10);
  const minY = Math.min(...points.map((p) => p.y), -10);
  const maxY = Math.max(...points.map((p) => p.y), 10);

  const scaleX = (val: number) => {
    const range = maxX - minX || 1;
    return 40 + ((val - minX) / range) * 420;
  };
  const scaleY = (val: number) => {
    const range = maxY - minY || 1;
    return 30 + ((val - minY) / range) * 260;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Top Stats Banner */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Collection</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "#38bdf8", marginTop: "4px" }}>{data.collection_name || "N/A"}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Total Vectors</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#4ade80", marginTop: "4px" }}>{data.total_points ?? points.length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Collection Status</div>
          <div style={{ fontSize: "14px", fontWeight: 700, color: "#a855f7", marginTop: "6px" }}>🟢 {data.status?.toUpperCase() || "READY"}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Vector Dimensions</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "#fbbf24", marginTop: "4px" }}>{points[0]?.vector_len || 384}D Dense</div>
        </div>
      </div>

      {/* Main Visualizer Body */}
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "20px" }}>
        {/* Left: 2D Projected Vector Scatter Canvas */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0" }}>
              2D UMAP / PCA Semantic Cluster Space ({filteredPoints.length} points)
            </div>
            <input
              type="text"
              placeholder="Filter by keyword..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              style={{
                background: "rgba(30, 41, 59, 0.7)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "12px",
                color: "#e2e8f0",
                width: "170px",
              }}
            />
          </div>

          <svg
            viewBox="0 0 500 320"
            style={{
              width: "100%",
              height: "320px",
              background: "radial-gradient(circle at 50% 50%, rgba(30, 58, 138, 0.2) 0%, rgba(15, 23, 42, 0.9) 100%)",
              borderRadius: "8px",
              border: "1px solid rgba(59, 130, 246, 0.2)",
            }}
          >
            {/* Grid lines */}
            <line x1="250" y1="10" x2="250" y2="310" stroke="rgba(255, 255, 255, 0.06)" strokeDasharray="4" />
            <line x1="10" y1="160" x2="490" y2="160" stroke="rgba(255, 255, 255, 0.06)" strokeDasharray="4" />

            {/* Scatter points */}
            {filteredPoints.map((pt, idx) => {
              const cx = scaleX(pt.x);
              const cy = scaleY(pt.y);
              const isSelected = selectedPoint?.id === pt.id;
              return (
                <g key={pt.id || idx} onClick={() => setSelectedPoint(pt)} style={{ cursor: "pointer" }}>
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isSelected ? 9 : 6}
                    fill={isSelected ? "#f59e0b" : "#38bdf8"}
                    stroke={isSelected ? "#ffffff" : "rgba(56, 189, 248, 0.4)"}
                    strokeWidth={isSelected ? 3 : 1.5}
                    style={{
                      transition: "all 0.2s ease",
                      filter: isSelected ? "drop-shadow(0 0 8px #f59e0b)" : "drop-shadow(0 0 4px #38bdf8)",
                    }}
                  />
                  <text
                    x={cx}
                    y={cy - 10}
                    fill="#94a3b8"
                    fontSize="9"
                    textAnchor="middle"
                    style={{ pointerEvents: "none" }}
                  >
                    #{idx + 1}
                  </text>
                </g>
              );
            })}
          </svg>
          <div style={{ fontSize: "11px", color: "#64748b", marginTop: "8px", textAlign: "center" }}>
            Click on any vector point in the scatter space to inspect high-dimensional metadata & chunk payload.
          </div>
        </div>

        {/* Right: Point Payload & Metadata Inspector */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0", marginBottom: "12px" }}>
            Vector Payload & Chunk Inspector
          </div>

          {selectedPoint ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", overflowY: "auto", maxHeight: "300px" }}>
              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "10px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ fontSize: "11px", color: "#94a3b8" }}>Point ID</div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#f8fafc", wordBreak: "break-all" }}>{selectedPoint.id}</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>File Source</div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "#38bdf8" }}>{selectedPoint.payload?.file_key || "Unknown"}</div>
                </div>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Page / Index</div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "#4ade80" }}>Page {selectedPoint.payload?.page_index ?? 0}</div>
                </div>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Record Type</div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "#fbbf24" }}>
                    {selectedPoint.payload?.record_type || "chunk"}
                    {selectedPoint.payload?.parent_ref ? ` -> ${selectedPoint.payload.parent_ref}` : ""}
                  </div>
                </div>
              </div>
              <div>
                <div style={{ fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Chunk Text Content</div>
                <div style={{ background: "rgba(15, 23, 42, 0.9)", padding: "10px", borderRadius: "6px", fontSize: "12px", color: "#cbd5e1", lineHeight: 1.5, maxHeight: "140px", overflowY: "auto", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                  {selectedPoint.payload?.text || "No text payload"}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "60px 20px", color: "#64748b", fontSize: "12px" }}>
              👈 Click any vector point on the cluster plot to inspect its semantic payload.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
