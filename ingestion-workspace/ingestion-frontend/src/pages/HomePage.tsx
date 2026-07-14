import { Link } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { IconBrowse, IconFolder, IconPipeline, IconTracking, IconUpload } from "../components/Icons";
import { DirectorySummary, listDirectories } from "../api";
import { formatRelativeTime } from "../utils/format";

const QUICK_LINKS = [
  {
    to: "/upload",
    title: "Upload documents",
    description: "Chunked upload with hash verification and duplicate detection.",
    icon: IconUpload,
    cta: "Start upload",
  },
  {
    to: "/browse",
    title: "Browse folders",
    description: "Explore directories and files like a repository file tree.",
    icon: IconBrowse,
    cta: "Open folders",
  },
  {
    to: "/pipelines",
    title: "RAG pipelines",
    description: "Index folders into Qdrant with naive, hybrid, multimodal, or metadata strategies.",
    icon: IconPipeline,
    cta: "Configure pipelines",
  },
  {
    to: "/tracking",
    title: "Pipeline tracking",
    description: "Monitor ingestion runs and web scraper crawl/scrape job status.",
    icon: IconTracking,
    cta: "View tracking",
  },
] as const;

export default function HomePage() {
  const [directories, setDirectories] = useState<DirectorySummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setDirectories(await listDirectories());
    } catch {
      /* overview stays usable without folder list */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="page">
      <PageHeader
        title="Overview"
        description="Upload documents, organize them in folders, and preview synced files."
      />

      <section className="quick-grid">
        {QUICK_LINKS.map(({ to, title, description, icon: Icon, cta }) => (
          <Link key={to} to={to} className="quick-card">
            <div className="quick-card-icon">
              <Icon size={22} />
            </div>
            <h2>{title}</h2>
            <p>{description}</p>
            <span className="quick-card-cta">{cta} →</span>
          </Link>
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <IconFolder className="panel-title-icon" />
            Recent folders
          </h2>
          <Link to="/browse" className="btn btn-ghost btn-sm">
            View all
          </Link>
        </div>

        {loading ? (
          <p className="muted">Loading folders…</p>
        ) : directories.length === 0 ? (
          <div className="empty-inline">
            <p>No folders yet.</p>
            <Link to="/upload" className="btn btn-primary btn-sm">
              Upload your first files
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
                {directories.slice(0, 5).map((d) => (
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
      </section>
    </div>
  );
}
