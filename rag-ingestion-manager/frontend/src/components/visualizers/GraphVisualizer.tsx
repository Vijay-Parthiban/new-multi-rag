import React, { useEffect, useRef, useState } from "react";
import { DestinationInspectData } from "../../api";

interface GraphVisualizerProps {
  data: DestinationInspectData;
  loading: boolean;
}

interface SimNode {
  id: string;
  label: string;
  type: string;
  color: string;
  snippet?: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

export const GraphVisualizer: React.FC<GraphVisualizerProps> = ({ data, loading }) => {
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const animRef = useRef<number | null>(null);

  useEffect(() => {
    if (!data.nodes || data.nodes.length === 0) {
      setNodes([]);
      return;
    }

    // Initialize node positions in a circular pattern around (250, 160)
    const initialNodes: SimNode[] = data.nodes.map((n, idx) => {
      const angle = (idx / data.nodes!.length) * 2 * Math.PI;
      const radius = n.type === "Document" ? 80 : 130;
      return {
        ...n,
        x: 250 + radius * Math.cos(angle) + (Math.random() - 0.5) * 20,
        y: 160 + radius * Math.sin(angle) + (Math.random() - 0.5) * 20,
        vx: 0,
        vy: 0,
      };
    });

    setNodes(initialNodes);

    // Run simple force-directed simulation step for smooth graph stabilization
    let stepCount = 0;
    const simulate = () => {
      if (stepCount > 80) return;
      stepCount++;

      setNodes((prevNodes) => {
        const next = prevNodes.map((node) => ({ ...node }));
        const links = data.links || [];

        // 1. Repulsion between all nodes
        for (let i = 0; i < next.length; i++) {
          for (let j = i + 1; j < next.length; j++) {
            const dx = next[j].x - next[i].x;
            const dy = next[j].y - next[i].y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            if (dist < 180) {
              const force = (180 - dist) / (dist * 18);
              next[i].vx -= dx * force;
              next[i].vy -= dy * force;
              next[j].vx += dx * force;
              next[j].vy += dy * force;
            }
          }
        }

        // 2. Attraction along links
        links.forEach((l) => {
          const s = next.find((n) => n.id === l.source);
          const t = next.find((n) => n.id === l.target);
          if (s && t) {
            const dx = t.x - s.x;
            const dy = t.y - s.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const force = (dist - 90) * 0.04;
            s.vx += (dx / dist) * force;
            s.vy += (dy / dist) * force;
            t.vx -= (dx / dist) * force;
            t.vy -= (dy / dist) * force;
          }
        });

        // 3. Center gravity and damping
        next.forEach((n) => {
          n.vx += (250 - n.x) * 0.02;
          n.vy += (160 - n.y) * 0.02;
          n.vx *= 0.75;
          n.vy *= 0.75;
          n.x = Math.max(30, Math.min(470, n.x + n.vx));
          n.y = Math.max(30, Math.min(290, n.y + n.vy));
        });

        return next;
      });

      animRef.current = requestAnimationFrame(simulate);
    };

    animRef.current = requestAnimationFrame(simulate);

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [data]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
        Loading Neo4j knowledge graph topology & chunk relationships...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: "20px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "10px", color: "#f87171" }}>
        <strong>Neo4j Graph Inspection Error:</strong> {data.error}
      </div>
    );
  }

  const links = data.links || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Top Stats Banner */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Total Nodes</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#38bdf8", marginTop: "4px" }}>{data.total_nodes ?? nodes.length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Total Relationships</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#4ade80", marginTop: "4px" }}>{data.total_edges ?? links.length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Graph Schema</div>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#fbbf24", marginTop: "6px" }}>Doc ➔ CONTAINS_CHUNK</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Engine Protocol</div>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#a855f7", marginTop: "6px" }}>Bolt / Cypher 5.x</div>
        </div>
      </div>

      {/* Main Visualizer Split */}
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "20px" }}>
        {/* Left: Interactive Force Graph Canvas */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0" }}>
              Force-Directed Entity Graph ({nodes.length} Nodes, {links.length} Edges)
            </div>
            <div style={{ display: "flex", gap: "10px", fontSize: "11px" }}>
              <span style={{ display: "flex", alignItems: "center", gap: "4px", color: "#38bdf8" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#3B82F6" }} /> Document
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: "4px", color: "#4ade80" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#10B981" }} /> Chunk
              </span>
            </div>
          </div>

          <svg
            viewBox="0 0 500 320"
            style={{
              width: "100%",
              height: "320px",
              background: "radial-gradient(circle at 50% 50%, rgba(15, 23, 42, 0.5) 0%, rgba(10, 15, 30, 0.95) 100%)",
              borderRadius: "8px",
              border: "1px solid rgba(59, 130, 246, 0.2)",
            }}
          >
            {/* Draw Links */}
            {links.map((link, idx) => {
              const s = nodes.find((n) => n.id === link.source);
              const t = nodes.find((n) => n.id === link.target);
              if (!s || !t) return null;
              return (
                <g key={idx}>
                  <line
                    x1={s.x}
                    y1={s.y}
                    x2={t.x}
                    y2={t.y}
                    stroke="rgba(255, 255, 255, 0.18)"
                    strokeWidth="1.5"
                    strokeDasharray="3 3"
                  />
                </g>
              );
            })}

            {/* Draw Nodes */}
            {nodes.map((n) => {
              const isSelected = selectedNode?.id === n.id;
              const isDoc = n.type === "Document";
              const r = isDoc ? 18 : 12;

              return (
                <g
                  key={n.id}
                  onClick={() => setSelectedNode(n)}
                  style={{ cursor: "pointer", transition: "all 0.2s ease" }}
                >
                  <circle
                    cx={n.x}
                    cy={n.y}
                    r={r}
                    fill={isDoc ? "#3B82F6" : "#10B981"}
                    stroke={isSelected ? "#ffffff" : "rgba(255, 255, 255, 0.3)"}
                    strokeWidth={isSelected ? 3 : 1.5}
                    style={{
                      filter: isSelected ? `drop-shadow(0 0 10px ${isDoc ? "#60a5fa" : "#34d399"})` : undefined,
                    }}
                  />
                  <text
                    x={n.x}
                    y={n.y + 4}
                    fill="#ffffff"
                    fontSize={isDoc ? "11" : "9"}
                    fontWeight="700"
                    textAnchor="middle"
                    style={{ pointerEvents: "none" }}
                  >
                    {isDoc ? "DOC" : "CHK"}
                  </text>
                  <text
                    x={n.x}
                    y={n.y + r + 11}
                    fill="#94a3b8"
                    fontSize="9"
                    textAnchor="middle"
                    style={{ pointerEvents: "none" }}
                  >
                    {n.label.length > 14 ? n.label.substring(0, 12) + "..." : n.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        {/* Right: Selected Node Properties & Cypher Inspector */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0", marginBottom: "12px" }}>
            Entity Properties & Cypher Record
          </div>

          {selectedNode ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", overflowY: "auto", maxHeight: "300px" }}>
              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "10px", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ fontSize: "11px", color: "#94a3b8" }}>Node Identifier</div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#38bdf8", wordBreak: "break-all" }}>{selectedNode.id}</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Node Type</div>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: selectedNode.type === "Document" ? "#38bdf8" : "#4ade80" }}>
                    {selectedNode.type}
                  </div>
                </div>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Label</div>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "#f8fafc" }}>{selectedNode.label}</div>
                </div>
              </div>
              {selectedNode.snippet && (
                <div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Chunk Text Preview</div>
                  <div style={{ background: "rgba(15, 23, 42, 0.9)", padding: "10px", borderRadius: "6px", fontSize: "12px", color: "#cbd5e1", lineHeight: 1.5, border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                    {selectedNode.snippet}...
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "60px 20px", color: "#64748b", fontSize: "12px" }}>
              👈 Click any Document or Chunk node on the graph canvas to inspect its relationships and properties.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
