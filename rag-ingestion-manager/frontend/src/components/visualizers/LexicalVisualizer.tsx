import React, { useState } from "react";
import { DestinationInspectData } from "../../api";

interface LexicalVisualizerProps {
  data: DestinationInspectData;
  loading: boolean;
}

export const LexicalVisualizer: React.FC<LexicalVisualizerProps> = ({ data, loading }) => {
  const [selectedDoc, setSelectedDoc] = useState<any | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "60px 0", color: "#94a3b8" }}>
        Loading lexical inverted index & term frequencies from OpenSearch...
      </div>
    );
  }

  if (data.error) {
    return (
      <div style={{ padding: "20px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: "10px", color: "#f87171" }}>
        <strong>OpenSearch Inspection Error:</strong> {data.error}
      </div>
    );
  }

  const docs = data.documents || [];
  const terms = data.terms || [];

  const filteredDocs = searchQuery
    ? docs.filter((d) => {
        const text = d.content || "";
        const file = d.file_key || "";
        return text.toLowerCase().includes(searchQuery.toLowerCase()) || file.toLowerCase().includes(searchQuery.toLowerCase());
      })
    : docs;

  const maxTermVal = Math.max(...terms.map((t) => t.value), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Top Stats Banner */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>OpenSearch Index</div>
          <div style={{ fontSize: "15px", fontWeight: 700, color: "#38bdf8", marginTop: "4px" }}>{data.index_name || "N/A"}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Total Documents</div>
          <div style={{ fontSize: "18px", fontWeight: 800, color: "#4ade80", marginTop: "4px" }}>{data.total_docs ?? docs.length}</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Lexical Algorithm</div>
          <div style={{ fontSize: "14px", fontWeight: 700, color: "#f59e0b", marginTop: "6px" }}>BM25 Okapi Scoring</div>
        </div>
        <div style={{ background: "rgba(30, 41, 59, 0.6)", padding: "14px", borderRadius: "10px", border: "1px solid rgba(255, 255, 255, 0.06)" }}>
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", fontWeight: 700 }}>Top Token Density</div>
          <div style={{ fontSize: "16px", fontWeight: 700, color: "#a855f7", marginTop: "4px" }}>{terms.length} Keywords</div>
        </div>
      </div>

      {/* Main Visualizer Split */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1.3fr", gap: "20px" }}>
        {/* Left: Term Frequency / Token Distribution */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0", marginBottom: "12px" }}>
            Inverted Index BM25 Term Frequencies
          </div>

          {terms.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 0", color: "#64748b", fontSize: "12px" }}>
              No term frequencies available in current index sample.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px", overflowY: "auto", maxHeight: "320px", paddingRight: "4px" }}>
              {terms.map((t, idx) => {
                const pct = Math.max(8, (t.value / maxTermVal) * 100);
                return (
                  <div
                    key={idx}
                    onClick={() => setSearchQuery(t.text)}
                    style={{
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      gap: "4px",
                      background: "rgba(30, 41, 59, 0.4)",
                      padding: "6px 10px",
                      borderRadius: "6px",
                      border: "1px solid rgba(255, 255, 255, 0.04)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                      <span style={{ fontWeight: 600, color: "#38bdf8" }}>#{idx + 1} {t.text}</span>
                      <span style={{ color: "#94a3b8", fontSize: "11px" }}>{t.value} occurrences</span>
                    </div>
                    <div style={{ height: "4px", background: "rgba(255, 255, 255, 0.06)", borderRadius: "2px", overflow: "hidden" }}>
                      <div style={{ width: `${pct}%`, height: "100%", background: "linear-gradient(90deg, #38bdf8, #818cf8)", borderRadius: "2px" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Indexed Documents & BM25 Hit Inspector */}
        <div style={{ background: "rgba(15, 23, 42, 0.8)", borderRadius: "12px", border: "1px solid rgba(255, 255, 255, 0.08)", padding: "16px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <div style={{ fontSize: "13px", fontWeight: 700, color: "#e2e8f0" }}>
              Indexed Postings & Chunks ({filteredDocs.length})
            </div>
            <input
              type="text"
              placeholder="Search index..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
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

          <div style={{ display: "flex", flexDirection: "column", gap: "8px", overflowY: "auto", maxHeight: "320px", paddingRight: "4px" }}>
            {filteredDocs.map((doc, idx) => {
              const isSelected = selectedDoc?.id === doc.id;
              return (
                <div
                  key={doc.id || idx}
                  onClick={() => setSelectedDoc(doc)}
                  style={{
                    cursor: "pointer",
                    padding: "10px",
                    borderRadius: "8px",
                    background: isSelected ? "rgba(59, 130, 246, 0.15)" : "rgba(30, 41, 59, 0.4)",
                    border: `1px solid ${isSelected ? "rgba(59, 130, 246, 0.4)" : "rgba(255, 255, 255, 0.04)"}`,
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                    <span style={{ fontWeight: 600, color: "#f8fafc" }}>📄 {doc.file_key || "Document"}</span>
                    <span style={{ display: "flex", gap: "6px" }}>
                      {doc.record_type && doc.record_type !== "chunk" && (
                        <span style={{ fontSize: "11px", color: "#fbbf24", background: "rgba(251, 191, 36, 0.1)", padding: "2px 6px", borderRadius: "4px" }}>
                          {doc.record_type}
                          {doc.parent_ref ? ` -> ${doc.parent_ref}` : ""}
                        </span>
                      )}
                      <span style={{ fontSize: "11px", color: "#4ade80", background: "rgba(74, 222, 128, 0.1)", padding: "2px 6px", borderRadius: "4px" }}>
                        Score: {doc.score != null ? doc.score.toFixed(2) : "1.00"}
                      </span>
                    </span>
                  </div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: isSelected ? 8 : 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                    {doc.content || "Empty content"}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
