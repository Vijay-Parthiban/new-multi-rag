import { useCallback, useEffect, useState } from "react";
import { Link, NavigateFunction, useLocation, useNavigate, useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import { IconFile } from "../components/Icons";
import { ApiError, deleteFile, FileRecord, listDirectoryFiles, renameFile } from "../api";
import { formatRelativeTime, formatSize } from "../utils/format";

interface DirectoryPageProps {
  routeName?: string;
  routeNavigate?: NavigateFunction;
}

export default function DirectoryPage({ routeName, routeNavigate }: DirectoryPageProps) {
  const paramsName = useParams<{ name: string }>().name;
  const name = routeName ?? paramsName;
  const navigate = routeNavigate ?? useNavigate();
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const location = useLocation();

  const load = useCallback(async () => {
    if (!name) return;
    try {
      setFiles(await listDirectoryFiles(name));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoading(false);
    }
  }, [name]);

  const isVisible = location.pathname === `/browse/${name}` || location.pathname === `/directories/${name}`;

  useEffect(() => {
    if (!isVisible) return;
    load();
    const interval = setInterval(load, 300000); // 5 minutes
    return () => clearInterval(interval);
  }, [isVisible, load]);

  async function handleRename(fileId: string) {
    if (!newName.trim()) return;
    try {
      await renameFile(fileId, newName.trim());
      setRenamingId(null);
      setNewName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  }

  async function handleDelete(fileId: string) {
    try {
      await deleteFile(fileId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  }

  const firstSynced = files.find((f) => f.status === "synced");

  return (
    <div className="page">
      <PageHeader
        title={name ?? "Folder"}
        description="Files with syncing status update automatically in the background."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Folders", to: "/browse" },
          { label: name ?? "" },
        ]}
        actions={
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-secondary" onClick={() => load()}>
              Refresh
            </button>
            {firstSynced && (
              <Link to={`/browse/${name}/view/${firstSynced.id}`} className="btn btn-secondary">
                Open viewer
              </Link>
            )}
            <Link to="/upload" state={{ directory: name }} className="btn btn-primary">
              Upload here
            </Link>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}

      <div className="panel">
        <div className="panel-toolbar">
          <span className="panel-toolbar-label">
            {loading ? "…" : `${files.length} file${files.length === 1 ? "" : "s"}`}
          </span>
        </div>

        {loading ? (
          <p className="panel-empty muted">Loading files…</p>
        ) : files.length === 0 ? (
          <div className="panel-empty">
            <IconFile className="empty-icon" size={40} />
            <p>This folder is empty</p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate("/upload", { state: { directory: name } })}
            >
              Upload files
            </button>
          </div>
        ) : (
          <div className="repo-table-wrap">
            <table className="repo-table repo-table-files">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {files.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <div className="file-name-cell">
                        <IconFile className="row-icon file-icon" />
                        {f.status === "synced" ? (
                          <Link to={`/browse/${name}/view/${f.id}`} className="repo-row-link mono">
                            {f.original_name}
                          </Link>
                        ) : (
                          <span className="mono">{f.original_name}</span>
                        )}
                        {f.status === "duplicate" && f.duplicate_of_file_name && (
                          <span className="file-meta">
                            Same as {f.duplicate_of_file_name}
                          </span>
                        )}
                        {f.error_message && f.status !== "duplicate" && (
                          <span className="file-meta file-meta-error">{f.error_message}</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={f.status} />
                    </td>
                    <td className="muted">{formatSize(f.size_bytes)}</td>
                    <td className="muted">{formatRelativeTime(f.updated_at)}</td>
                    <td>
                      <div className="row-actions">
                        {f.status === "synced" && (
                          <Link to={`/browse/${name}/view/${f.id}`} className="btn btn-ghost btn-sm">
                            View
                          </Link>
                        )}
                        {f.status === "duplicate" && f.duplicate_of_file_id && (
                          <Link
                            to={`/browse/${name}/view/${f.duplicate_of_file_id}`}
                            className="btn btn-ghost btn-sm"
                          >
                            Original
                          </Link>
                        )}
                        {renamingId === f.id ? (
                          <div className="inline-edit">
                            <input
                              value={newName}
                              onChange={(e) => setNewName(e.target.value)}
                              placeholder="new-name.pdf"
                              className="input input-sm"
                            />
                            <button type="button" className="btn btn-primary btn-sm" onClick={() => handleRename(f.id)}>
                              Save
                            </button>
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRenamingId(null)}>
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={f.status === "processing" || f.status === "duplicate"}
                            onClick={() => {
                              setRenamingId(f.id);
                              setNewName(f.original_name);
                            }}
                          >
                            Rename
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn-danger-ghost btn-sm"
                          disabled={f.status === "processing"}
                          onClick={() => handleDelete(f.id)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
