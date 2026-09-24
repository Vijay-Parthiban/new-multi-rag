import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import {
  IconBucket,
  IconClose,
  IconCode,
  IconDownload,
  IconEye,
  IconFile,
  IconFolder,
  IconInfo,
  IconRefresh,
  IconSearch,
  IconServer,
} from "../components/Icons";

type SortKey = "key" | "size" | "modified";
type SortDir = "asc" | "desc";

/**
 * A MinIO object key is a path, and the path is long. The file name leads the row and the
 * folder follows it, so two files with the same name stay tellable apart without either
 * one pushing the metadata columns onto a second line.
 */
function splitKey(key: string): { name: string; folder: string } {
  const cut = key.lastIndexOf("/");
  return cut === -1
    ? { name: key, folder: "" }
    : { name: key.slice(cut + 1), folder: key.slice(0, cut + 1) };
}

function compareFiles(a: SourceFileEntry, b: SourceFileEntry, key: SortKey): number {
  if (key === "size") return (a.size ?? 0) - (b.size ?? 0);
  if (key === "modified") {
    // A missing or unparseable timestamp sorts as the epoch rather than breaking the sort.
    return (Date.parse(a.last_modified) || 0) - (Date.parse(b.last_modified) || 0);
  }
  return splitKey(a.key).name.localeCompare(splitKey(b.key).name);
}

function SortHeader({
  label,
  sortKey,
  sort,
  onToggle,
  className,
}: {
  label: string;
  sortKey: SortKey;
  sort: { key: SortKey; dir: SortDir };
  onToggle: (key: SortKey) => void;
  className?: string;
}) {
  const active = sort.key === sortKey;
  return (
    <th
      className={className}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className="folders-sort"
        data-dir={active ? sort.dir : undefined}
        onClick={() => onToggle(sortKey)}
      >
        {label}
        <span className="folders-sort-caret" aria-hidden>
          {active && sort.dir === "desc" ? "▼" : "▲"}
        </span>
      </button>
    </th>
  );
}

export default function BrowsePage() {
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [files, setFiles] = useState<SourceFileEntry[]>([]);
  const [bucketName, setBucketName] = useState<string>("");

  const [loadingSources, setLoadingSources] = useState(true);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const [searchTerm, setSearchTerm] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "key", dir: "asc" });
  const [selectedFile, setSelectedFile] = useState<SourceFileEntry | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [viewMode, setViewMode] = useState<"preview" | "raw" | "meta">("preview");

  const viewerRef = useRef<HTMLDivElement | null>(null);
  const viewerOpen = selectedFile !== null;

  const loadSources = useCallback(async () => {
    try {
      setLoadingSources(true);
      const res = await listSources();
      setSources(res);
      setSelectedSourceId((prev) => (prev ? prev : res.length > 0 ? res[0].id : ""));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoadingSources(false);
    }
  }, []);

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

  // The viewer owns its own lifetime. Depending on the file object here would re-run the
  // effect on every unrelated render and pull focus back out of the tab strip.
  useEffect(() => {
    if (!viewerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedFile(null);
    };
    window.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    viewerRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [viewerOpen]);

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

  const toggleSort = (key: SortKey) =>
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" },
    );

  const visibleFiles = useMemo(() => {
    const term = searchTerm.trim().toLowerCase();
    const matched = term ? files.filter((f) => f.key.toLowerCase().includes(term)) : files;
    const sorted = [...matched].sort((a, b) => compareFiles(a, b, sort.key));
    return sort.dir === "desc" ? sorted.reverse() : sorted;
  }, [files, searchTerm, sort]);

  const activeSource = sources.find((s) => s.id === selectedSourceId);
  const connectorCount = activeSource?.connectors?.length ?? 0;

  // Helper renderer for CSV files into a table grid
  const renderCsvTable = (text: string) => {
    const lines = text.trim().split("\n");
    if (lines.length === 0) return <div>Empty CSV file</div>;
    const rows = lines.map((l) => l.split(","));
    const header = rows[0];
    const body = rows.slice(1);

    return (
      <div className="repo-table-wrap">
        <table className="repo-table">
          <thead>
            <tr>
              {header.map((h, idx) => (
                <th key={idx}>{h.trim()}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r, rIdx) => (
              <tr key={rIdx}>
                {r.map((c, cIdx) => (
                  <td key={cIdx}>{c.trim()}</td>
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
        title="Folders"
        description="Browse the files in a source bucket. Open one to read it, or to see where it lives and when it last changed."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Folders" }]}
        actions={
          <div className="page-actions">
            <button
              className="btn btn-secondary"
              onClick={() => selectedSourceId && loadFiles(selectedSourceId)}
              disabled={!selectedSourceId || loadingFiles}
            >
              <IconRefresh size={15} />
              Refresh files
            </button>
            <Link to="/sources" className="btn btn-primary">
              Manage sources
            </Link>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error" role="alert">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}

      {/* Which bucket is open, and what is in it */}
      <div className="panel">
        <div className="panel-header">
          <h2 className="panel-title">Source bucket</h2>
          {activeSource && (
            <div className="folders-summary">
              <span className="folders-summary-item">
                <IconBucket size={14} />
                <strong className="mono">{bucketName || activeSource.minio_bucket}</strong>
              </span>
              <span className="folders-summary-item">
                <IconFile size={14} />
                <strong>{files.length}</strong> file{files.length === 1 ? "" : "s"}
              </span>
              <span className="folders-summary-item">
                <IconServer size={14} />
                <strong>{connectorCount}</strong> connector{connectorCount === 1 ? "" : "s"}
              </span>
            </div>
          )}
        </div>

        <div style={{ padding: "1rem 1.125rem" }}>
          <label className="field-label" htmlFor="folders-source">
            MinIO source
          </label>

          {loadingSources ? (
            <p className="muted" style={{ margin: 0, fontSize: "0.875rem" }}>
              Loading sources…
            </p>
          ) : sources.length === 0 ? (
            <p className="muted" style={{ margin: 0, fontSize: "0.875rem" }}>
              No sources configured yet.{" "}
              <Link to="/sources" className="link-like">
                Create a source first
              </Link>
              .
            </p>
          ) : (
            <select
              id="folders-source"
              className="input"
              value={selectedSourceId}
              onChange={(e) => setSelectedSourceId(e.target.value)}
            >
              {sources.map((s) => {
                const n = s.connectors?.length || 0;
                return (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.minio_bucket}) — {n} connector{n === 1 ? "" : "s"}
                  </option>
                );
              })}
            </select>
          )}
        </div>
      </div>

      {/* The files themselves */}
      <div className="panel" style={{ marginTop: "1.5rem" }}>
        <div className="panel-header">
          <h2 className="panel-title">Files</h2>
          {!loadingFiles && files.length > 0 && (
            <span className="folders-count">
              Showing {visibleFiles.length} of {files.length}
            </span>
          )}
        </div>

        <div className="panel-toolbar">
          <div className="folders-toolbar">
            <div className="folders-search">
              <span className="folders-search-icon">
                <IconSearch size={15} />
              </span>
              <input
                id="folders-search"
                type="search"
                className="input"
                placeholder="Search by name or path…"
                aria-label="Search files by name or path"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
              {searchTerm && (
                <button
                  type="button"
                  className="folders-search-clear"
                  aria-label="Clear the search"
                  onClick={() => setSearchTerm("")}
                >
                  <IconClose size={14} />
                </button>
              )}
            </div>
          </div>
        </div>

        {loadingFiles ? (
          <div className="repo-table-wrap">
            <table className="repo-table">
              <tbody>
                {[0, 1, 2, 3].map((i) => (
                  <tr key={i}>
                    <td>
                      <div className="folders-skeleton" style={{ width: `${58 - i * 9}%` }} />
                    </td>
                    <td>
                      <div className="folders-skeleton" style={{ width: "46px", marginLeft: "auto" }} />
                    </td>
                    <td>
                      <div className="folders-skeleton" style={{ width: "56px", marginLeft: "auto" }} />
                    </td>
                    <td>
                      <div className="folders-skeleton" style={{ width: "62px", marginLeft: "auto" }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : visibleFiles.length === 0 ? (
          <div className="folders-empty">
            <span className="folders-empty-icon">
              <IconFolder size={40} />
            </span>
            <p className="folders-empty-title">
              {searchTerm ? "No file matches that search" : "This bucket has no files"}
            </p>
            <p style={{ margin: 0, fontSize: "0.8125rem", maxWidth: "46ch" }}>
              {searchTerm
                ? "Try a shorter term, or clear the search to see everything."
                : "Sync the source, or pick a different one above."}
            </p>
            {searchTerm && (
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                style={{ marginTop: "0.5rem" }}
                onClick={() => setSearchTerm("")}
              >
                Clear search
              </button>
            )}
          </div>
        ) : (
          <div className="repo-table-wrap">
            <table className="repo-table">
              <thead>
                <tr>
                  <SortHeader label="File name" sortKey="key" sort={sort} onToggle={toggleSort} />
                  <SortHeader
                    label="Size"
                    sortKey="size"
                    sort={sort}
                    onToggle={toggleSort}
                    className="folders-col-meta"
                  />
                  <SortHeader
                    label="Modified"
                    sortKey="modified"
                    sort={sort}
                    onToggle={toggleSort}
                    className="folders-col-meta"
                  />
                  <th className="folders-col-actions">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleFiles.map((file) => {
                  const { name, folder } = splitKey(file.key);
                  return (
                    <tr key={file.key}>
                      <td>
                        <div className="folders-file-cell">
                          <span className="folders-file-icon">
                            <IconFile size={15} />
                          </span>
                          <span className="folders-file-text">
                            <button
                              type="button"
                              className="folders-file-name"
                              title={file.key}
                              onClick={() => handleOpenFile(file)}
                            >
                              {name}
                            </button>
                            {folder && <span className="folders-file-path">{folder}</span>}
                          </span>
                        </div>
                      </td>
                      <td className="folders-col-meta">{formatSize(file.size)}</td>
                      <td className="folders-col-meta">{formatRelativeTime(file.last_modified)}</td>
                      <td className="folders-col-actions">
                        <button
                          type="button"
                          className="btn btn-sm btn-secondary"
                          onClick={() => handleOpenFile(file)}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* File viewer */}
      {selectedFile && (
        <div
          style={{
            position: "fixed",
            inset: 0,
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
            ref={viewerRef}
            role="dialog"
            aria-modal="true"
            aria-label={`File viewer: ${splitKey(selectedFile.key).name}`}
            tabIndex={-1}
            style={{
              backgroundColor: "var(--bg-default)",
              borderRadius: "12px",
              border: "1px solid var(--border-default)",
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
                borderBottom: "1px solid var(--border-muted)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: "1rem",
                background: "var(--bg-subtle)",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <h3
                  style={{
                    margin: 0,
                    fontSize: "1.05rem",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.45rem",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={selectedFile.key}
                >
                  <IconFile size={16} />
                  {splitKey(selectedFile.key).name}
                </h3>
                <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                  <span className="mono">{bucketName}</span> · {formatBytes(selectedFile.size)} ·{" "}
                  {formatRelativeTime(selectedFile.last_modified)}
                </span>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                aria-label="Close the file viewer"
                onClick={() => setSelectedFile(null)}
                style={{ flexShrink: 0 }}
              >
                <IconClose size={16} />
              </button>
            </div>

            {/* View mode */}
            <div className="folders-viewer-tabs">
              <button
                type="button"
                className="folders-viewer-tab"
                aria-pressed={viewMode === "preview"}
                onClick={() => setViewMode("preview")}
              >
                <IconEye size={14} />
                Preview
              </button>
              <button
                type="button"
                className="folders-viewer-tab"
                aria-pressed={viewMode === "raw"}
                onClick={() => setViewMode("raw")}
              >
                <IconCode size={14} />
                Raw text
              </button>
              <button
                type="button"
                className="folders-viewer-tab"
                aria-pressed={viewMode === "meta"}
                onClick={() => setViewMode("meta")}
              >
                <IconInfo size={14} />
                Details
              </button>
            </div>

            {/* Body */}
            <div style={{ padding: "1.5rem", overflowY: "auto", flex: 1 }}>
              {loadingContent ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                  {[92, 78, 85, 60].map((w, i) => (
                    <div key={i} className="folders-skeleton" style={{ width: `${w}%` }} />
                  ))}
                </div>
              ) : viewMode === "meta" ? (
                <div className="repo-table-wrap">
                  <table className="repo-table">
                    <tbody>
                      <tr>
                        <td>
                          <strong>File name</strong>
                        </td>
                        <td className="mono">{splitKey(selectedFile.key).name}</td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Folder</strong>
                        </td>
                        <td className="mono">{splitKey(selectedFile.key).folder || "—"}</td>
                      </tr>
                      <tr>
                        <td>
                          <strong>MinIO bucket</strong>
                        </td>
                        <td className="mono">{bucketName}</td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Size</strong>
                        </td>
                        <td>
                          {formatBytes(selectedFile.size)} ({selectedFile.size} bytes)
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Last modified</strong>
                        </td>
                        <td>{selectedFile.last_modified}</td>
                      </tr>
                      <tr>
                        <td>
                          <strong>Direct link</strong>
                        </td>
                        <td>
                          <a
                            href={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                            target="_blank"
                            rel="noreferrer"
                            className="link-like"
                          >
                            Open the raw endpoint
                          </a>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : viewMode === "raw" ? (
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    background: "var(--bg-inset)",
                    padding: "1rem",
                    borderRadius: "8px",
                    fontSize: "0.85rem",
                    margin: 0,
                  }}
                >
                  {fileContent}
                </pre>
              ) : (
                /* Preview */
                <div>
                  {(() => {
                    const ext = getFileExtension(selectedFile.key);
                    const content = fileContent || "";

                    if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) {
                      return (
                        <div style={{ textAlign: "center" }}>
                          <img
                            src={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                            alt={splitKey(selectedFile.key).name}
                            style={{ maxWidth: "100%", maxHeight: "60vh", borderRadius: "8px" }}
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
                          <pre
                            style={{
                              background: "var(--bg-inset)",
                              padding: "1rem",
                              borderRadius: "8px",
                              fontSize: "0.85rem",
                              overflowX: "auto",
                              margin: 0,
                            }}
                          >
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
                          title={splitKey(selectedFile.key).name}
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
            <div
              style={{
                padding: "0.8rem 1.5rem",
                borderTop: "1px solid var(--border-muted)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
                background: "var(--bg-subtle)",
              }}
            >
              <a
                href={getSourceFileContentUrl(selectedSourceId, selectedFile.key)}
                download={splitKey(selectedFile.key).name}
                className="btn btn-sm btn-secondary"
                style={{ gap: "0.4rem" }}
              >
                <IconDownload size={14} />
                Download
              </a>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => setSelectedFile(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
