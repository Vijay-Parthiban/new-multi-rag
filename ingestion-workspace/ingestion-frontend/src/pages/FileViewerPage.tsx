import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavigateFunction, useNavigate, useParams, useLocation } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import StatusBadge from "../components/StatusBadge";
import { API_URL, ApiError, FileRecord, getFile, listDirectoryFiles } from "../api";
import { formatSize } from "../utils/format";

interface FileViewerPageProps {
  routeDir?: string;
  routeFileId?: string;
  routeNavigate?: NavigateFunction;
}

export default function FileViewerPage({ routeDir, routeFileId, routeNavigate }: FileViewerPageProps) {
  const paramsResult = useParams<{ name?: string; fileId?: string; id?: string }>();
  const navigate = routeNavigate ?? useNavigate();

  const activeFileId = routeFileId ?? paramsResult.fileId ?? paramsResult.id ?? "";
  const initialDir = routeDir ?? paramsResult.name ?? "";

  const [directoryName, setDirectoryName] = useState(initialDir);
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [currentName, setCurrentName] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const location = useLocation();

  const viewUrl = useMemo(
    () => (activeFileId ? `${API_URL}/api/files/${activeFileId}/view` : ""),
    [activeFileId],
  );

  const load = useCallback(async () => {
    if (!activeFileId) return;

    try {
      const meta = await getFile(activeFileId);
      const dir = initialDir || meta.directory_name;
      setDirectoryName(dir);
      setCurrentName(meta.original_name);

      if (!initialDir && dir) {
        navigate(`/browse/${dir}/view/${activeFileId}`, { replace: true });
      }

      setFiles(await listDirectoryFiles(dir));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoading(false);
    }
  }, [activeFileId, initialDir, navigate]);

  const isVisible = location.pathname.includes(`/view/${activeFileId}`);

  useEffect(() => {
    if (!isVisible) return;
    load();
    const interval = setInterval(load, 300000); // 5 minutes
    return () => clearInterval(interval);
  }, [isVisible, load]);

  const syncedCount = files.filter((f) => f.status === "synced").length;
  const processingCount = files.filter((f) => f.status === "processing").length;
  const duplicateCount = files.filter((f) => f.status === "duplicate").length;
  const current = files.find((f) => f.id === activeFileId);
  const canView = current?.status === "synced";

  if (loading) {
    return (
      <div className="viewer-page">
        <p className="muted viewer-loading">Loading viewer…</p>
      </div>
    );
  }

  return (
    <div className="viewer-page">
      <header className="viewer-topbar">
        <Breadcrumb
          items={[
            { label: "Overview", to: "/" },
            { label: "Folders", to: "/browse" },
            { label: directoryName, to: `/browse/${directoryName}` },
            { label: currentName || "Preview" },
          ]}
        />
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <p className="viewer-stats muted">
            {syncedCount} synced · {processingCount} syncing · {duplicateCount} duplicate
          </p>
          <button className="btn btn-secondary btn-sm" onClick={() => load()}>
            Refresh
          </button>
        </div>
      </header>

      <div className="viewer-layout">
        <aside className="viewer-sidebar panel">
          {error && (
            <div className="alert alert-error">
              <strong>{error.code}</strong>: {error.message}
            </div>
          )}

          <ul className="viewer-file-list">
            {files.length === 0 ? (
              <li className="viewer-file-empty muted">No files in this folder</li>
            ) : (
              files.map((f) => (
                <li key={f.id} className={f.id === activeFileId ? "active" : ""}>
                  {f.status === "synced" ? (
                    <Link to={`/browse/${directoryName}/view/${f.id}`} className="viewer-file-link">
                      <span className="viewer-file-name">{f.original_name}</span>
                      <StatusBadge status={f.status} />
                    </Link>
                  ) : (
                    <div className="viewer-file-link viewer-file-static">
                      <span className="viewer-file-name">{f.original_name}</span>
                      <StatusBadge status={f.status} />
                    </div>
                  )}
                  <span className="viewer-file-size muted">{formatSize(f.size_bytes)}</span>
                </li>
              ))
            )}
          </ul>
        </aside>

        <section className="viewer-main panel">
          <h1 className="viewer-title">{currentName || "File preview"}</h1>

          {current?.status === "processing" && (
            <div className="alert alert-info">
              This file is still syncing. Preview will appear when status is synced.
            </div>
          )}

          {current?.status === "failed" && (
            <div className="alert alert-error">
              Sync failed: {current.error_message ?? "Unknown error"}
            </div>
          )}

          {current?.status === "duplicate" && (
            <div className="alert alert-warn">
              Duplicate upload — not stored on disk.
              {current.duplicate_of_file_name && (
                <>
                  {" "}
                  Same content as <strong>{current.duplicate_of_file_name}</strong>.
                  {current.duplicate_of_file_id && (
                    <>
                      {" "}
                      <Link to={`/browse/${directoryName}/view/${current.duplicate_of_file_id}`}>
                        View original
                      </Link>
                    </>
                  )}
                </>
              )}
            </div>
          )}

          {canView && viewUrl && (
            <iframe className="viewer-frame" src={viewUrl} title={currentName} />
          )}

          {!canView &&
            current?.status !== "processing" &&
            current?.status !== "failed" &&
            current?.status !== "duplicate" && (
              <p className="muted">Select a synced file from the sidebar to preview it.</p>
            )}
        </section>
      </div>
    </div>
  );
}
