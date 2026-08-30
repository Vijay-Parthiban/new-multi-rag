import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import {
  ApiError,
  SourceFileEntry,
  SourceRecord,
  getSourceFileContent,
  getSourceFileContentUrl,
  listSourceFiles,
  listSources,
} from "../api";
import { formatSize, formatRelativeTime, formatBytes } from "../utils/format";
import MarkdownMessage from "../components/MarkdownMessage";

export default function BrowsePage() {
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [files, setFiles] = useState<SourceFileEntry[]>([]);
  const [bucketName, setBucketName] = useState<string>("");

  const [loadingSources, setLoadingSources] = useState(true);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const [searchTerm, setSearchTerm] = useState("");
  const [selectedFile, setSelectedFile] = useState<SourceFileEntry | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [viewMode, setViewMode] = useState<"preview" | "raw" | "meta">("preview");

  const loadSources = useCallback(async () => {
    try {
      setLoadingSources(true);
      const res = await listSources();
      setSources(res);
      if (res.length > 0 && !selectedSourceId) {
        setSelectedSourceId(res[0].id);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoadingSources(false);
    }
  }, [selectedSourceId]);

  const loadFiles = useCallback(async (sourceId: string) => {
    if (!sourceId) return;
    try {
      setLoadingFiles(true);
      const res = await listSourceFiles(sourceId);
      setFiles(res.files);
      setBucketName(res.bucket);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoadingFiles(false);
    }
  }, []);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  useEffect(() => {
    if (selectedSourceId) {
      loadFiles(selectedSourceId);
    }
  }, [selectedSourceId, loadFiles]);

  const handleOpenFile = async (file: SourceFileEntry) => {
    setSelectedFile(file);
    setViewMode("preview");
    setFileContent(null);
    setLoadingContent(true);

    try {
      const content = await getSourceFileContent(selectedSourceId, file.key);
      setFileContent(content);
    } catch (err) {
      setFileContent(`[Error loading file content: ${String(err)}]`);
    } finally {
      setLoadingContent(false);
    }
  };

  const filteredFiles = files.filter((f) =>
    f.key.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  const activeSource = sources.find((s) => s.id === selectedSourceId);

  // Helper renderer for CSV files into a table grid
  const renderCsvTable = (text: string) => {
    const lines = text.trim().split("\n");
    if (lines.length === 0) return <div>Empty CSV file</div>;
    const rows = lines.map((l) => l.split(","));
    const header = rows[0];
    const body = rows.slice(1);

    return (
      <div style={{ overflowX: "auto" }}>
        <table className="table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr>
              {header.map((h, idx) => (
                <th key={idx} style={{ padding: "0.5rem", borderBottom: "2px solid var(--border)", textAlign: "left" }}>
                  {h.trim()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r, rIdx) => (
              <tr key={rIdx}>
                {r.map((c, cIdx) => (
                  <td key={cIdx} style={{ padding: "0.4rem 0.5rem", borderBottom: "1px solid var(--border)" }}>
                    {c.trim()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const getFileExtension = (filename: string) => {
    return filename.split(".").pop()?.toLowerCase() ?? "";
  };

  return (
    <div className="page">
      <PageHeader
        title="MinIO Sources & Files Browser"
        description="Select an existing MinIO source bucket to browse files, open, and visualize content directly."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Folders / Sources" },
        ]}
        actions={
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-secondary" onClick={() => selectedSourceId && loadFiles(selectedSourceId)}>
              Refresh Files
            </button>
            <Link to="/upload" className="btn btn-primary">
              Upload Files
            </Link>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}

      {/* MinIO Source Selector Toolbar */}
      <div className="panel" style={{ marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
          <div style={{ flex: 1, minWidth: "280px" }}>
            <label className="field-label" style={{ marginBottom: "0.3rem" }}>
              Selected MinIO Source
            </label>
            {loadingSources ? (
              <div>Loading sources...</div>
            ) : sources.length === 0 ? (
              <div>
                No sources configured. <Link to="/sources">Create a source first</Link>.
              </div>
            ) : (
              <select
                className="select-input"
                style={{ width: "100%", padding: "0.6rem", borderRadius: "6px", border: "1px solid var(--border)" }}
                value={selectedSourceId}
                onChange={(e) => setSelectedSourceId(e.target.value)}
              >
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.minio_bucket}) — {s.connectors?.length || 0} connector(s)
                  </option>
                ))}
              </select>
            )}
          </div>

          {activeSource && (
            <div style={{ display: "flex", gap: "1rem", fontSize: "0.9rem", background: "var(--bg-subtle)", padding: "0.6rem 1rem", borderRadius: "6px" }}>
              <div>
                <span style={{ color: "var(--muted)" }}>Bucket:</span> <strong className="mono">{bucketName || activeSource.minio_bucket}</strong>
              </div>
              <div>
                <span style={{ color: "var(--muted)" }}>Total Files:</span> <strong>{files.length}</strong>
              </div>
              <div>
                <span style={{ color: "var(--muted)" }}>Connectors:</span> <strong>{activeSource.connectors?.length || 0}</strong>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* File Search & Directory Grid */}
      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <div style={{ position: "relative", flex: "1", maxWidth: "400px" }}>
            <input
              type="text"
              placeholder="Search files by name or key..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="text-input"
              style={{ width: "100%", padding: "0.5rem 0.5rem 0.5rem 2.2rem" }}
            />
            <span style={{ position: "absolute", left: "0.7rem", top: "0.6rem", color: "var(--muted)" }}>🔍</span>
          </div>

          <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
            Showing {filteredFiles.length} of {files.length} file(s)
          </span>
        </div>

        {loadingFiles ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)" }}>
            Loading files from MinIO bucket...
          </div>
        ) : filteredFiles.length === 0 ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "var(--muted)" }}>
            No files found in this MinIO source bucket.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--border)", textAlign: "left" }}>
                  <th style={{ padding: "0.6rem" }}>File Key / Name</th>
                  <th style={{ padding: "0.6rem" }}>Size</th>
                  <th style={{ padding: "0.6rem" }}>Last Modified</th>
                  <th style={{ padding: "0.6rem", textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredFiles.map((file) => (
                    <tr key={file.key} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "0.6rem" }}>
                        <button
                          className="btn-link"
                          onClick={() => handleOpenFile(file)}
                          style={{ fontWeight: 600, background: "none", border: "none", color: "var(--primary)", cursor: "pointer", textDecoration: "underline" }}
                        >
                          📄 {file.key}
                        </button>
                      </td>
                      <td style={{ padding: "0.6rem", fontSize: "0.85rem", color: "var(--muted)" }}>
                        {formatSize(file.size)}
                      </td>
                      <td style={{ padding: "0.6rem", fontSize: "0.85rem", color: "var(--muted)" }}>
                        {formatRelativeTime(file.last_modified)}
                      </td>
                      <td style={{ padding: "0.6rem", textAlign: "right" }}>
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => handleOpenFile(file)}
                        >
                          Open & Visualize
                        </button>
                      </td>
                    </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* File Visualizer & Content Viewer Dialog / Modal */}
      {selectedFile && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0,0,0,0.65)",
            zIndex: 1000,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            padding: "1.5rem",
          }}
          onClick={() => setSelectedFile(null)}
        >
          <div
            style={{
              backgroundColor: "var(--bg-panel, #fff)",
              borderRadius: "10px",
              width: "100%",
              maxWidth: "900px",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 10px 30px rgba(0,0,0,0.3)",
              overflow: "hidden",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div
              style={{
                padding: "1rem 1.5rem",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                background: "var(--bg-subtle)",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem" }}>📄 {selectedFile.key}</h3>
                <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                  Bucket: <span className="mono">{bucketName}</span> | Size: {formatBytes(selectedFile.size)}
                </span>
              </div>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => setSelectedFile(null)}
                style={{ fontSize: "1.2rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>

                  Bucket: <span className="mono">{bucketName}</span> | Size: {formatSize(selectedFile.size)}
            <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--bg-subtle)", padding: "0 1.5rem" }}>
              <button
                className={`btn btn-sm btn-ghost${viewMode === "preview" ? " active" : ""}`}
                onClick={() => setViewMode("preview")}
                style={{ borderRadius: 0, borderBottom: viewMode === "preview" ? "2px solid var(--primary)" : "none" }}
              >
                🎨 Rendered Visualizer
              </button>
              <button
                className={`btn btn-sm btn-ghost${viewMode === "raw" ? " active" : ""}`}
                onClick={() => setViewMode("raw")}
                style={{ borderRadius: 0, borderBottom: viewMode === "raw" ? "2px solid var(--primary)" : "none" }}
              >
                📝 Raw Code / Text
              </button>
              <button
                className={`btn btn-sm btn-ghost${viewMode === "meta" ? " active" : ""}`}
                onClick={() => setViewMode("meta")}
                style={{ borderRadius: 0, borderBottom: viewMode === "meta" ? "2px solid var(--primary)" : "none" }}
              >
                ℹ️ Metadata & Links
              </button>
            </div>

            {/* Body Content */}
            <div style={{ padding: "1.5rem", overflowY: "auto", flex: 1 }}>
              {loadingContent ? (
                <div style={{ textAlign: "center", padding: "2rem", color: "var(--muted)" }}>
                  Fetching file object from MinIO...
                </div>
              ) : viewMode === "meta" ? (
                <div>
                  <h4 style={{ marginTop: 0 }}>File Details</h4>
                  <table className="table" style={{ width: "100%", fontSize: "0.9rem" }}>
                    <tbody>
                      <tr>
                        <td><strong>File Key</strong></td>
                        <td className="mono">{selectedFile.key}</td>
                      </tr>
                      <tr>
                        <td><strong>MinIO Bucket</strong></td>
                        <td className="mono">{bucketName}</td>
                      </tr>
                      <tr>
                        <td><strong>File Size</strong></td>
                        <td>{formatBytes(selectedFile.size)} ({selectedFile.size} bytes)</td>
                      </tr>
                      <tr>
                        <td><strong>Last Modified</strong></td>
                        <td>{selectedFile.last_modified}</td>
                      </tr>
                      <tr>
                        <td><strong>Direct Stream URL</strong></td>
                        <td>
                          <a
                            href={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                            target="_blank"
                            rel="noreferrer"
                            className="link-like"
                          >
                            Open raw endpoint ↗
                          </a>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : viewMode === "raw" ? (
                <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", background: "var(--code-bg, #f4f4f4)", padding: "1rem", borderRadius: "6px", fontSize: "0.85rem" }}>
                  {fileContent}
                </pre>
              ) : (
                /* Rendered Preview Visualizer */
                <div>
                  {(() => {
                    const ext = getFileExtension(selectedFile.key);
                    const content = fileContent || "";

                    if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) {
                      return (
                        <div style={{ textAlign: "center" }}>
                          <img
                            src={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                            alt={selectedFile.key}
                            style={{ maxWidth: "100%", maxHeight: "60vh", borderRadius: "6px" }}
                          />
                        </div>
                      );
                    }

                    if (ext === "csv") {
                      return renderCsvTable(content);
                    }

                    if (ext === "json") {
                      try {
                        const parsed = JSON.parse(content);
                        return (
                          <pre style={{ background: "var(--code-bg, #f4f4f4)", padding: "1rem", borderRadius: "6px", fontSize: "0.85rem", overflowX: "auto" }}>
                            {JSON.stringify(parsed, null, 2)}
                          </pre>
                        );
                      } catch {
                        return <pre>{content}</pre>;
                      }
                    }

                    if (ext === "pdf") {
                      return (
                        <iframe
                          src={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                          title={selectedFile.key}
                          style={{ width: "100%", height: "60vh", border: "none" }}
                        />
                      );
                    }

                    // Markdown or standard text document
                    return <MarkdownMessage content={content} />;
                  })()}
                </div>
              )}
            </div>

            {/* Footer */}
            <div style={{ padding: "0.8rem 1.5rem", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "space-between", background: "var(--bg-subtle)" }}>
              <a
                href={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                download={selectedFile.key.split("/").pop()}
                className="btn btn-sm btn-secondary"
              >
                ⬇ Download File
              </a>
              <button className="btn btn-sm btn-primary" onClick={() => setSelectedFile(null)}>
                Close Visualizer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
