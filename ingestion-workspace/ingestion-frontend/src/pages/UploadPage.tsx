import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { IconUpload } from "../components/Icons";
import { ApiError, uploadFileChunked } from "../api";

const BLOCKED_EXTENSIONS = new Set([
  "mp4", "mov", "avi", "mkv", "webm", "wmv", "flv",
  "mp3", "wav", "ogg", "aac", "flac", "m4a", "wma",
]);

const CONTENT_TYPES = [
  { id: "document", label: "Documents", hint: "PDF, DOCX, TXT and other text documents", accept: ".pdf,.doc,.docx,.txt,.csv,.json,.xml,.html,.htm" },
  { id: "image", label: "Images", hint: "PNG, JPG, JPEG, GIF, WEBP image files", accept: ".png,.jpg,.jpeg,.gif,.webp,.bmp,.tiff,.svg" },
  { id: "markdown", label: "Markdown", hint: "Markdown (.md) and plain text files", accept: ".md,.mdx,.rst,.txt" },
] as const;

type ContentType = (typeof CONTENT_TYPES)[number]["id"];

function isBlocked(file: File): boolean {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (BLOCKED_EXTENSIONS.has(ext)) return true;
  if (file.type.startsWith("video/") || file.type.startsWith("audio/")) return true;
  return false;
}

export default function UploadPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const presetDir = (location.state as { directory?: string } | null)?.directory ?? "";

  const [directoryName, setDirectoryName] = useState(presetDir);
  const [usePreset, setUsePreset] = useState(!!presetDir);
  const [newFolderName, setNewFolderName] = useState("");
  const [contentType, setContentType] = useState<ContentType>("document");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const effectiveDir = usePreset ? presetDir : (newFolderName || directoryName);
  const selectedContentType = CONTENT_TYPES.find((c) => c.id === contentType)!;

  function onFileChange(selected: FileList | null) {
    if (!selected) return;
    const blocked = Array.from(selected).filter(isBlocked);
    if (blocked.length > 0) {
      setError(
        new ApiError(422, {
          error: {
            code: "FILE_TYPE_BLOCKED",
            message: `Blocked ${blocked.length} video/audio file(s): ${blocked.map((f) => f.name).join(", ")}`,
          },
        }),
      );
    }
    setFiles((prev) => [...prev, ...Array.from(selected).filter((f) => !isBlocked(f))]);
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleUpload() {
    const dir = effectiveDir.trim().toLowerCase();
    if (!dir || files.length === 0) return;

    setSubmitting(true);
    setError(null);
    setInfo("Uploading — files will sync in the background.");

    let queued = 0;
    let duplicates = 0;
    const corrupted: string[] = [];

    try {
      for (const file of files) {
        try {
          const result = await uploadFileChunked(dir, file);
          if (result.status === "duplicate") duplicates += 1;
          else queued += 1;
        } catch (err) {
          if (err instanceof ApiError && err.code === "CORRUPTION_DETECTED") {
            corrupted.push(file.name);
            continue;
          }
          throw err;
        }
      }

      const parts: string[] = [];
      if (queued > 0) parts.push(`${queued} queued for sync`);
      if (duplicates > 0) parts.push(`${duplicates} duplicate(s) recorded`);
      if (corrupted.length > 0) parts.push(`${corrupted.length} corrupted (hash mismatch)`);
      setInfo(parts.join(" · ") || "Upload finished.");

      navigate(`/browse/${dir}`);
    } catch (err) {
      setInfo(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError(500, {
              error: { code: "UPLOAD_FAILED", message: err instanceof Error ? err.message : "Upload failed" },
            }),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page page-narrow">
      <PageHeader
        title="Upload"
        description="Documents only — no video or audio. Duplicates are recorded without saving to disk."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          ...(presetDir ? [{ label: "Folders", to: "/browse" }, { label: presetDir, to: `/browse/${presetDir}` }] : []),
          { label: "Upload" },
        ]}
      />

      {error && (
        <div className="alert alert-error">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}
      {info && <div className="alert alert-info">{info}</div>}

      <div className="panel upload-panel">
        {/* Content type selector */}
        <label className="field-label">Content type</label>
        <div className="content-type-group">
          {CONTENT_TYPES.map((ct) => (
            <label
              key={ct.id}
              className={`content-type-option${contentType === ct.id ? " selected" : ""}`}
            >
              <input
                type="radio"
                name="content-type"
                value={ct.id}
                checked={contentType === ct.id}
                onChange={() => setContentType(ct.id)}
                className="sr-only"
              />
              <span className="content-type-label">{ct.label}</span>
              <span className="content-type-hint">{ct.hint}</span>
            </label>
          ))}
        </div>

        {/* Folder selection */}
        <label className="field-label" style={{ marginTop: "1rem" }}>
          Target folder
        </label>

        {presetDir ? (
          <div className="folder-preset-block">
            <div className="folder-preset-row">
              <div className="folder-preset-badge">
                <span className="folder-preset-name mono">{presetDir}</span>
                <span className="folder-preset-tag">current folder</span>
              </div>
              <label className="check-row folder-preset-toggle">
                <input
                  type="checkbox"
                  checked={!usePreset}
                  onChange={(e) => setUsePreset(!e.target.checked)}
                />
                <span>Use a different folder</span>
              </label>
            </div>
            {!usePreset && (
              <div style={{ marginTop: "0.625rem" }}>
                <input
                  type="text"
                  className="input"
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  placeholder="new-folder-name"
                />
                <p className="field-hint">Lowercase. Created automatically on first upload.</p>
              </div>
            )}
          </div>
        ) : (
          <>
            <input
              id="directory-name"
              type="text"
              className="input"
              value={directoryName}
              onChange={(e) => setDirectoryName(e.target.value)}
              placeholder="project-alpha"
            />
            <p className="field-hint">Lowercase folder name. Created automatically on first upload.</p>
          </>
        )}

        <div
          className={`dropzone${dragOver ? " dropzone-active" : ""}`}
          style={{ marginTop: "1rem" }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            onFileChange(e.dataTransfer.files);
          }}
          onClick={() => document.getElementById("file-input")?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") document.getElementById("file-input")?.click();
          }}
        >
          <IconUpload className="dropzone-icon" size={28} />
          <p className="dropzone-title">Drag & drop {selectedContentType.label.toLowerCase()} here</p>
          <p className="dropzone-sub">or click to browse · {selectedContentType.hint}</p>
          <input
            id="file-input"
            type="file"
            multiple
            hidden
            accept={selectedContentType.accept}
            onChange={(e) => onFileChange(e.target.files)}
          />
        </div>

        {files.length > 0 && (
          <div className="upload-queue">
            <div className="panel-toolbar">
              <span className="panel-toolbar-label">{files.length} file(s) selected</span>
            </div>
            <ul className="upload-list">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`}>
                  <span className="mono">{f.name}</span>
                  <span className="muted">{(f.size / 1024).toFixed(1)} KB</span>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => removeFile(i)}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="upload-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={submitting || !effectiveDir.trim() || files.length === 0}
            onClick={handleUpload}
          >
            {submitting ? "Uploading…" : "Upload & queue sync"}
          </button>
          <Link to="/browse" className="btn btn-secondary">
            Browse folders
          </Link>
        </div>
      </div>
    </div>
  );
}
