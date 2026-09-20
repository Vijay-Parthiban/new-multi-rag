import React, { useState } from "react";
import { DestinationInspectData } from "../../api";

interface RelationalVisualizerProps {
  data: DestinationInspectData;
  loading: boolean;
}

export const RelationalVisualizer: React.FC<RelationalVisualizerProps> = ({ data, loading }) => {
  const [selectedRow, setSelectedRow] = useState<any | null>(null);
  const [filterQuery, setFilterQuery] = useState<string>("");

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
        Loading relational chunk records from PostgreSQL...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: "20px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "10px", color: "#f87171" }}>
        <strong>PostgreSQL Inspection Error:</strong> {data.error}
      </div>
    );
  }

  const rows = data.rows || [];
  const filteredRows = filterQuery
    ? rows.filter((r) => {
        const text = r.content || "";
        const file = r.file_key || "";
        return text.toLowerCase().includes(filterQuery.toLowerCase()) || file.toLowerCase().includes(filterQuery.toLowerCase());
      })
    : rows;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Top Stats Banner */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Table Name</div>
          <div style={{ fontSize: "15px", fontWeight: 700, color: "#38bdf8", marginTop: "4px" }}>{data.table_name || "knowledge_chunks"}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Total Table Rows</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#4ade80", marginTop: "4px" }}>{data.total_rows ?? rows.length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Storage Engine</div>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#a855f7", marginTop: "6px" }}>PostgreSQL 16 + pgvector</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>SQL Partitioning</div>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#fbbf24", marginTop: "6px" }}>Indexed by file_key</div>
        </div>
      </div>

      {/* Main Table & Chunk Inspector */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1.1fr", gap: "20px" }}>
        {/* Left: Tabular Chunk Explorer */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0" }}>
              Relational Chunks Table ({filteredRows.length} Rows)
            </div>
            <input
              type="text"
              placeholder="Search table..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              style={{
                background: "rgba(30, 41, 59, 0.7)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "12px",
                color: "#e2e8f0",
                width: "160px",
              }}
            />
          </div>

          <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "320px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", textAlign: "left" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.1)", color: "#94a3b8" }}>
                  <th style={{ padding: "8px" }}>ID</th>
                  <th style={{ padding: "8px" }}>File Key</th>
                  <th style={{ padding: "8px" }}>Page</th>
                  <th style={{ padding: "8px" }}>Snippet</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r) => {
                  const isSelected = selectedRow?.id === r.id;
                  return (
                    <tr
                      key={r.id}
                      onClick={() => setSelectedRow(r)}
                      style={{
                        cursor: "pointer",
                        borderBottom: "1px solid rgba(255, 255, 255, 0.04)",
                        background: isSelected ? "rgba(59, 130, 246, 0.2)" : "transparent",
                        transition: "background 0.15s ease",
                      }}
                    >
                      <td style={{ padding: "8px", color: "#64748b", fontWeight: 600 }}>#{r.id}</td>
                      <td style={{ padding: "8px", color: "#38bdf8", fontWeight: 600 }}>{r.file_key}</td>
                      <td style={{ padding: "8px", color: "#4ade80" }}>P.{r.page_index}</td>
                      <td style={{ padding: "8px", color: "#94a3b8", maxWidth: "160px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {r.content}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Selected Row Content Expander */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0", marginBottom: "12px" }}>
            Relational Record Full Content
          </div>

          {selectedRow ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "12px", overflowY: "auto", maxHeight: "300px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Primary Key ID</div>
                  <div style={{ fontSize: "13px", fontWeight: 700, color: "#f8fafc" }}>#{selectedRow.id}</div>
                </div>
                <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Page Index</div>
                  <div style={{ fontSize: "13px", fontWeight: 700, color: "#4ade80" }}>Page {selectedRow.page_index}</div>
                </div>
              </div>
              <div style={{ background: "rgba(30, 41, 59, 0.5)", padding: "8px", borderRadius: "6px" }}>
                <div style={{ fontSize: "11px", color: "#94a3b8" }}>File Path</div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#38bdf8" }}>{selectedRow.file_key}</div>
              </div>
              <div>
                <div style={{ fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Full Content</div>
                <div style={{ background: "rgba(15, 23, 42, 0.9)", padding: "12px", borderRadius: "6px", fontSize: "12px", color: "#cbd5e1", lineHeight: 1.5, maxHeight: "150px", overflowY: "auto", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                  {selectedRow.content}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "60px 20px", color: "#64748b", fontSize: "12px" }}>
              👈 Select any row in the chunks table to view its full text and attributes.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
