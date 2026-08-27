import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { IconUpload } from "../components/Icons";
import { ApiError, SourceRecord, listSources, uploadFileChunked, uploadSourceFile } from "../api";

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

  const [targetType, setTargetType] = useState<"source" | "folder">("source");
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [loadingSources, setLoadingSources] = useState(true);

  const [directoryName, setDirectoryName] = useState(presetDir);
  const [usePreset, setUsePreset] = useState(!!presetDir);
  const [newFolderName, setNewFolderName] = useState("");
  const [contentType, setContentType] = useState<ContentType>("document");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    listSources()
      .then((res) => {
        setSources(res);
        if (res.length > 0) {
          setSelectedSourceId(res[0].id);
        }
      })
      .catch(() => {})
      .finally(() => setLoadingSources(false));
  }, []);

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
    if (files.length === 0) return;

    if (targetType === "source") {
      if (!selectedSourceId) {
        setError(new ApiError(400, { error: { code: "SOURCE_REQUIRED", message: "Please select a target MinIO Source bucket." } }));
        return;
      }

      setSubmitting(true);
      setError(null);
      setInfo("Uploading files directly to selected MinIO source bucket...");

      let uploaded = 0;
      try {
        for (const file of files) {
          await uploadSourceFile(selectedSourceId, file);
          uploaded += 1;
        }

        const activeSource = sources.find((s) => s.id === selectedSourceId);
        setInfo(`Successfully uploaded ${uploaded} file(s) to MinIO source bucket '${activeSource?.name || selectedSourceId}'.`);
        setTimeout(() => {
          navigate(`/sources/${selectedSourceId}`);
        }, 1200);
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(500, { error: { code: "UPLOAD_FAILED", message: String(err) } }));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    // Legacy folder mode
    const dir = effectiveDir.trim().toLowerCase();
    if (!dir) return;

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
      if (duplicates > 0) parts.push(`${duplicates} duplicates skipped`);
      if (corrupted.length > 0) parts.push(`${corrupted.length} corrupted file(s) failed integrity check`);

      setInfo(parts.join(", "));
      setTimeout(() => {
        navigate(`/browse/${encodeURIComponent(dir)}`);
      }, 1500);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Upload Documents"
        description="Add files manually to an existing MinIO Source bucket or folder target."
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
        {/* Upload Destination Target Selector */}
        <label className="field-label">Target Destination</label>
        <div className="content-type-group" style={{ marginBottom: "1rem" }}>
          <label className={`content-type-option${targetType === "source" ? " selected" : ""}`}>
            <input
              type="radio"
              name="target-type"
              value="source"
              checked={targetType === "source"}
              onChange={() => setTargetType("source")}
              className="sr-only"
            />
            <span className="content-type-label">MinIO Source Bucket</span>
            <span className="content-type-hint">Upload directly into an existing Source bucket created in Sources page</span>
          </label>

          <label className={`content-type-option${targetType === "folder" ? " selected" : ""}`}>
            <input
              type="radio"
              name="target-type"
              value="folder"
              checked={targetType === "folder"}
              onChange={() => setTargetType("folder")}
              className="sr-only"
            />
            <span className="content-type-label">Folder Directory</span>
            <span className="content-type-hint">Upload to a local document folder</span>
          </label>
        </div>

        {targetType === "source" ? (
          <div style={{ marginBottom: "1.5rem" }}>
            <label className="field-label">Select MinIO Source</label>
            {loadingSources ? (
              <div style={{ color: "var(--muted)" }}>Loading available sources...</div>
            ) : sources.length === 0 ? (
              <div className="alert alert-info" style={{ marginTop: "0.5rem" }}>
                No sources configured yet. <Link to="/sources">Create a source first</Link> in the Sources page.
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
        ) : (
          <div style={{ marginBottom: "1.5rem" }}>
            <label className="field-label">Target folder</label>
            {presetDir ? (
              <div className="folder-preset-block">
                <div className="folder-preset-badge">
                  <span className="folder-preset-name mono">{presetDir}</span>
                  <span className="folder-preset-tag">current folder</span>
                </div>
              </div>
            ) : (
              <input
                type="text"
                placeholder="Folder name (e.g. invoices, research)"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                className="text-input"
                style={{ width: "100%", padding: "0.6rem" }}
              />
            )}
          </div>
        )}

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

        {/* Drop zone */}
        <div
          className={`drop-zone${dragOver ? " drag-over" : ""}`}
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
          onClick={() => {
            const input = document.createElement("input");
            input.type = "file";
            input.multiple = true;
            input.accept = selectedContentType.accept;
            input.onchange = () => onFileChange(input.files);
            input.click();
          }}
          style={{ cursor: "pointer", marginTop: "1.5rem" }}
        >
          <IconUpload className="drop-zone-icon" />
          <p className="drop-zone-text">
            Drag & drop files here, or <span className="link-like">browse</span>
          </p>
          <p className="drop-zone-sub">
            Accepted: {selectedContentType.accept}. Max size 100MB per file.
          </p>
        </div>

        {/* File list */}
        {files.length > 0 && (
          <div className="file-preview-list" style={{ marginTop: "1rem" }}>
            <h4 style={{ margin: "0 0 0.5rem 0" }}>Selected Files ({files.length})</h4>
            {files.map((file, idx) => (
              <div key={idx} className="file-preview-item" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.5rem 0", borderBottom: "1px solid var(--border)" }}>
                <div>
                  <span className="mono">{file.name}</span>
                  <span style={{ color: "var(--muted)", marginLeft: "0.5rem", fontSize: "0.85rem" }}>
                    ({(file.size / 1024 / 1024).toFixed(2)} MB)
                  </span>
                </div>
                <button className="btn btn-sm btn-ghost" onClick={() => removeFile(idx)}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="form-actions" style={{ marginTop: "1.5rem" }}>
          <button
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={submitting || files.length === 0 || (targetType === "source" && !selectedSourceId)}
          >
            {submitting ? "Uploading..." : `Upload ${files.length} File(s)`}
          </button>
        </div>
      </div>
    </div>
  );
}
