import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type ChangeEvent } from "react";
import { IconChevronRight, IconFile, IconFolder, IconUpload } from "../Icons";
import { formatRelativeTime, formatSize } from "../../utils/format";
import {
  ApiError,
  deleteSourceFile,
  listSourceFiles,
  uploadSourceFile,
  type SourceFileEntry,
} from "../../api";
import "./FileBrowser.css";

/* ── Types ── */

export interface FileBrowserProps {
  /** Source ID used for all API calls. */
  sourceId?: string;
  /** MinIO bucket name — shown in the header. */
  bucketName?: string;
  /** Optional initial/pre-loaded file list. */
  files?: SourceFileEntry[];
  /** Optional delete callback. */
  onDelete?: (fileKey: string) => Promise<void>;
  /** Optional error callback so parent can surface toasts/alerts. */
  onError?: (error: ApiError) => void;
  /** Optional info callback for success messages. */
  onInfo?: (message: string) => void;
  /** Whether to show manual upload controls/dropzone. Default: false. */
  allowUpload?: boolean;
  /** Whether to show delete file actions. Default: false. */
  allowDelete?: boolean;
}

interface DirectoryNode {
  name: string;
  count: number;
}

type SortKey = "name" | "size" | "modified";

const PAGE_SIZE = 20;

/* ── Helpers ── */

/**
 * Strip the last segment from a prefix to navigate up one level
 * in the S3-style key path.
 */
function parentPrefix(prefix: string): string {
  if (!prefix) return "";
  const trimmed = prefix.endsWith("/") ? prefix.slice(0, -1) : prefix;
  const lastSlash = trimmed.lastIndexOf("/");
  if (lastSlash === -1) return "";
  return trimmed.slice(0, lastSlash) + "/";
}

/**
 * Convert an unknown error into an ApiError with a consistent code,
 * mirroring the pattern used in SourceDetailPage.
 */
function toApiError(err: unknown, code: string): ApiError {
  if (err instanceof ApiError) return err;
  const message = err instanceof Error ? err.message : String(err);
  return new ApiError(500, { error: { code, message } });
}

/* ── Component ── */

export default function FileBrowser({
  sourceId = "",
  bucketName = "",
  files: propFiles,
  onDelete: propOnDelete,
  onError,
  onInfo,
  allowUpload = false,
  allowDelete = false,
}: FileBrowserProps) {
  const [files, setFiles] = useState<SourceFileEntry[]>(propFiles ?? []);
  const [prefix, setPrefix] = useState("");
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<"flat" | "tree">("flat");

  useEffect(() => {
    if (propFiles !== undefined) {
      setFiles(propFiles);
    }
  }, [propFiles]);

  // Upload state
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Sort
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const loadFiles = useCallback(
    async (p: string) => {
      if (!sourceId) return;
      setLoading(true);
      try {
        const res = await listSourceFiles(sourceId, p);
        setFiles(res.files);
        setPrefix(p);
      } catch (err) {
        onError?.(toApiError(err, "LIST_FILES_FAILED"));
      } finally {
        setLoading(false);
      }
    },
    [sourceId, onError],
  );

  useEffect(() => {
    void loadFiles("");
  }, [loadFiles]);

  /* ── Upload handlers ── */

  const handleUpload = useCallback(async () => {
    if (uploadFiles.length === 0) return;
    setUploading(true);
    try {
      for (const file of uploadFiles) {
        await uploadSourceFile(sourceId, file);
      }
      onInfo?.(`Uploaded ${uploadFiles.length} file(s) to ${bucketName}.`);
      setUploadFiles([]);
      await loadFiles(prefix);
    } catch (err) {
      onError?.(toApiError(err, "UPLOAD_FAILED"));
    } finally {
      setUploading(false);
    }
  }, [uploadFiles, sourceId, bucketName, prefix, loadFiles, onInfo, onError]);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragActive(false);
      const dropped = Array.from(e.dataTransfer.files);
      if (dropped.length > 0) {
        setUploadFiles((prev) => [...prev, ...dropped]);
      }
    },
    [],
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
  }, []);

  const handleFileSelect = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? []);
    if (selected.length > 0) {
      setUploadFiles((prev) => [...prev, ...selected]);
    }
    // Reset input so the same file can be selected again
    e.target.value = "";
  }, []);

  /* ── Delete handler ── */

  const handleDelete = useCallback(
    async (file: SourceFileEntry) => {
      if (!window.confirm(`Delete ${file.key} from the bucket?`)) return;
      try {
        if (propOnDelete) {
          await propOnDelete(file.key);
        } else if (sourceId) {
          await deleteSourceFile(sourceId, file.key);
        }
        onInfo?.(`Deleted ${file.key}.`);
        await loadFiles(prefix);
      } catch (err) {
        onError?.(toApiError(err, "FILE_DELETE_FAILED"));
      }
    },
    [propOnDelete, sourceId, prefix, loadFiles, onInfo, onError],
  );

  /* ── Derived data ── */

  const { directories, rootFiles } = useMemo(() => {
    const dirs: DirectoryNode[] = [];
    const roots: SourceFileEntry[] = [];
    for (const file of files) {
      const rest = file.key.slice(prefix.length);
      const slash = rest.indexOf("/");
      if (slash === -1) {
        roots.push(file);
      } else {
        const folder = rest.slice(0, slash);
        const existing = dirs.find((d) => d.name === folder);
        if (existing) {
          existing.count += 1;
        } else {
          dirs.push({ name: folder, count: 1 });
        }
      }
    }
    return { directories: dirs, rootFiles: roots };
  }, [files, prefix]);

  const sortedFiles = useMemo(() => {
    const targetList = viewMode === "flat" ? files : rootFiles;
    const sorted = [...targetList].sort((a, b) => {
      const nameA = a.key.split("/").pop() ?? a.key;
      const nameB = b.key.split("/").pop() ?? b.key;
      switch (sortKey) {
        case "size":
          return a.size - b.size;
        case "modified":
          return (a.last_modified ?? "").localeCompare(b.last_modified ?? "");
        case "name":
        default:
          return nameA.localeCompare(nameB);
      }
    });
    return sorted;
  }, [files, rootFiles, viewMode, sortKey]);
  // Pagination derived from sorted results
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [prefix, sortKey]);

  const totalPages = Math.max(1, Math.ceil(sortedFiles.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const pagedFiles = sortedFiles.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );

  const breadcrumbs = prefix.split("/").filter(Boolean);

  /* ── Sort header handler ── */

  const handleSort = useCallback((key: SortKey) => {
    setSortKey(key);
  }, []);

  /* ── Keyboard nav for table rows ── */

  const handleFileKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTableRowElement>, file: SourceFileEntry, index: number) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        void handleDelete(file);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = document.querySelector<HTMLTableRowElement>(
          `tr[data-file-index="${index + 1}"]`,
        );
        next?.focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = document.querySelector<HTMLTableRowElement>(
          `tr[data-file-index="${index - 1}"]`,
        );
        prev?.focus();
      }
    },
    [handleDelete],
  );

  /* ── Render ── */

  return (
    <div className="file-browser panel">
      {/* Header */}
      <div className="panel-toolbar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <IconFolder className="panel-title-icon" size={16} />
          <span className="panel-toolbar-label">
            <span className="mono">{bucketName}</span>
            {prefix && <span className="muted"> · {prefix}</span>}
          </span>
        </div>
        <div className="file-browser-view-toggle" style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            className={`btn btn-sm ${viewMode === "flat" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setViewMode("flat")}
          >
            All Files (Flat)
          </button>
          <button
            type="button"
            className={`btn btn-sm ${viewMode === "tree" ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setViewMode("tree")}
          >
            Folder View
          </button>
        </div>
      </div>
      <div className="file-browser-breadcrumbs" role="navigation" aria-label="Directory path">
        <button
          className="btn btn-sm btn-ghost file-browser-crumb"
          onClick={() => void loadFiles("")}
          aria-label="Go to root"
          tabIndex={0}
        >
          <IconFolder size={14} />
          <span>root</span>
        </button>
        {breadcrumbs.map((crumb, i) => {
          const crumbPrefix = breadcrumbs.slice(0, i + 1).join("/") + "/";
          const isLast = i === breadcrumbs.length - 1;
          return (
            <span key={crumbPrefix} className="file-browser-crumb-segment">
              <IconChevronRight className="file-browser-sep" size={12} />
              {isLast ? (
                <span className="file-browser-crumb-current" aria-current="page">
                  {crumb}
                </span>
              ) : (
                <button
                  type="button"
                  className="btn btn-sm btn-ghost file-browser-crumb"
                  onClick={() => void loadFiles(crumbPrefix)}
                  tabIndex={0}
                >
                  {crumb}
                </button>
              )}
            </span>
          );
        })}
        {prefix && (
          <button
            type="button"
            className="btn btn-sm btn-ghost file-browser-up"
            onClick={() => void loadFiles(parentPrefix(prefix))}
            aria-label="Go to parent directory"
            tabIndex={0}
          >
            ↑ up
          </button>
        )}
      </div>

      {/* Upload zone (only rendered when allowUpload is true) */}
      {allowUpload && (
        <div className="upload-zone-wrap">
          <div
            className={`dropzone file-browser-dropzone${dragActive ? " dropzone-active" : ""}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            aria-label="Upload files by clicking or dragging"
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <IconUpload className="dropzone-icon" size={28} />
            <p className="dropzone-title">Drop files here or click to upload</p>
            <p className="dropzone-sub">
              Files are stored in the MinIO bucket{" "}
              <span className="mono">{bucketName}</span>
              {prefix ? (
                <span>
                  {" "}under <span className="mono">{prefix}</span>
                </span>
              ) : null}
            </p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={handleFileSelect}
              aria-label="File input"
            />
          </div>

          {uploadFiles.length > 0 && (
            <div className="upload-queue">
              <ul className="upload-list">
                {uploadFiles.map((file, i) => (
                  <li key={`${file.name}-${i}`}>
                    <IconFile size={14} className="muted" />
                    <span className="mono">{file.name}</span>
                    <span className="muted">{formatSize(file.size)}</span>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => setUploadFiles((prev) => prev.filter((_, j) => j !== i))}
                      aria-label={`Remove ${file.name} from upload queue`}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
              <div className="upload-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={uploading}
                  onClick={() => void handleUpload()}
                >
                  {uploading
                    ? "Uploading…"
                    : `Upload ${uploadFiles.length} file${uploadFiles.length === 1 ? "" : "s"}`}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  disabled={uploading}
                  onClick={() => setUploadFiles([])}
                >
                  Clear
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      {/* Directory tree */}
      {directories.length > 0 && (
        <div className="file-browser-tree">
          <div className="file-browser-section-label">Folders</div>
          <div className="repo-table-wrap">
            <table className="repo-table">
              <tbody>
                {directories.map((dir) => (
                  <tr key={dir.name} className="file-browser-dir-row">
                    <td>
                      <button
                        type="button"
                        className="btn-link file-name-cell"
                        onClick={() => void loadFiles(`${prefix}${dir.name}/`)}
                        tabIndex={0}
                        aria-label={`Open folder ${dir.name}`}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            void loadFiles(`${prefix}${dir.name}/`);
                          }
                        }}
                      >
                        <IconFolder size={14} />
                        <span>{dir.name}/</span>
                      </button>
                    </td>
                    <td className="muted file-browser-dir-count">
                      {dir.count} item{dir.count === 1 ? "" : "s"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* File listing */}
      <div className="file-browser-files">
        <div className="file-browser-section-label">
          {prefix ? `Files in ${prefix}` : "Root files"}
        </div>

        {loading ? (
          <p className="panel-empty muted">Loading files…</p>
        ) : sortedFiles.length === 0 && directories.length === 0 ? (
          <div className="panel-empty">
            <IconFile className="empty-icon muted" size={32} />
            <p>No files in this location</p>
            <p className="muted">
              {allowUpload
                ? "Upload files using the dropzone above."
                : "Files in this MinIO bucket are automatically ingested and updated via configured connector sync streams."}
            </p>
          </div>
        ) : sortedFiles.length === 0 ? (
          <p className="panel-empty muted">No files at this level — switch to "All Files (Flat)" or select a folder above.</p>
        ) : (
          <>
            <div className="repo-table-wrap">
              <table className="repo-table">
                <thead>
                  <tr>
                    <th>
                      <button
                        type="button"
                        className={`sort-header${sortKey === "name" ? " sort-active" : ""}`}
                        onClick={() => handleSort("name")}
                        tabIndex={0}
                      >
                        Name {sortKey === "name" && "↑"}
                      </button>
                    </th>
                    <th>
                      <button
                        type="button"
                        className={`sort-header${sortKey === "size" ? " sort-active" : ""}`}
                        onClick={() => handleSort("size")}
                        tabIndex={0}
                      >
                        Size {sortKey === "size" && "↑"}
                      </button>
                    </th>
                    <th>
                      <button
                        type="button"
                        className={`sort-header${sortKey === "modified" ? " sort-active" : ""}`}
                        onClick={() => handleSort("modified")}
                        tabIndex={0}
                      >
                        Modified {sortKey === "modified" && "↑"}
                      </button>
                    </th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedFiles.map((file, i) => (
                    <tr
                      key={file.key}
                      data-file-index={i}
                      tabIndex={0}
                      onKeyDown={(e) => handleFileKeyDown(e, file, i)}
                    >
                      <td>
                        <span className="file-name-cell" style={{ display: "inline-flex", flexDirection: "column", gap: "2px" }}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                            <IconFile size={14} className="muted" />
                            <span className="mono" style={{ fontWeight: 600 }}>{file.key.split("/").pop()}</span>
                          </span>
                          <span className="muted" style={{ fontSize: "11px", paddingLeft: "20px" }}>{file.key}</span>
                        </span>
                      </td>
                      <td>{formatSize(file.size)}</td>
                      <td>
                        {file.last_modified ? formatRelativeTime(file.last_modified) : "—"}
                      </td>
                      <td>
                        <div className="row-actions" style={{ display: "flex", gap: "0.5rem" }}>
                          {sourceId && file.key && (
                            <a
                              href={`http://localhost:8007/api/sources/${sourceId}/files?key=${encodeURIComponent(file.key)}`}
                              target="_blank"
                              rel="noreferrer"
                              className="btn btn-sm btn-secondary"
                              style={{ textDecoration: "none" }}
                            >
                              Open & Visualize
                            </a>
                          )}
                          {(allowDelete || propOnDelete) && (
                            <button
                              type="button"
                              className="btn btn-sm btn-danger-ghost"
                              onClick={() => void handleDelete(file)}
                              aria-label={`Delete ${file.key}`}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div
                className="file-browser-pagination"
                role="navigation"
                aria-label="File pagination"
              >
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                  aria-label="Previous page"
                  tabIndex={0}
                >
                  ← Prev
                </button>
                <span className="file-browser-page-info muted">
                  Page {currentPage + 1} of {totalPages} ({sortedFiles.length} files)
                </span>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  disabled={currentPage === totalPages - 1}
                  onClick={() => setPage(currentPage + 1)}
                  aria-label="Next page"
                  tabIndex={0}
                >
                  Next →
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
