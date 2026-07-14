import { Link, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { IconFolder } from "../components/Icons";
import { ApiError, DirectorySummary, listDirectories } from "../api";
import { formatRelativeTime } from "../utils/format";

export default function BrowsePage() {
  const [directories, setDirectories] = useState<DirectorySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const location = useLocation();

  const load = useCallback(async () => {
    try {
      setDirectories(await listDirectories());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoading(false);
    }
  }, []);

  const isVisible = location.pathname === "/browse" || location.pathname === "/directories";

  useEffect(() => {
    if (!isVisible) return;
    load();
    const interval = setInterval(load, 300000); // 5 minutes polling when visible
    return () => clearInterval(interval);
  }, [isVisible, load]);

  return (
    <div className="page">
      <PageHeader
        title="Folders"
        description="Each folder groups uploaded documents. Open one to manage files."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Folders" },
        ]}
        actions={
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-secondary" onClick={() => load()}>
              Refresh
            </button>
            <Link to="/upload" className="btn btn-primary">
              Upload files
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
            {loading ? "…" : `${directories.length} folder${directories.length === 1 ? "" : "s"}`}
          </span>
        </div>

        {loading ? (
          <p className="panel-empty muted">Loading folders…</p>
        ) : directories.length === 0 ? (
          <div className="panel-empty">
            <IconFolder className="empty-icon" size={40} />
            <p>No folders yet</p>
            <p className="muted">Upload files and choose a directory name to create one.</p>
            <Link to="/upload" className="btn btn-primary">
              Upload files
            </Link>
          </div>
        ) : (
          <div className="repo-table-wrap">
            <table className="repo-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {directories.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <Link to={`/browse/${d.name}`} className="repo-row-link">
                        <IconFolder className="row-icon folder-icon" />
                        <span className="mono">{d.name}</span>
                      </Link>
                    </td>
                    <td className="muted">{formatRelativeTime(d.created_at)}</td>
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
