import { Link } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { IconBrowse, IconDatabase, IconFolder, IconSources } from "../components/Icons";
import { DirectorySummary, listDirectories, listKnowledgeProfiles, listSources } from "../api";
import { formatRelativeTime } from "../utils/format";

const QUICK_LINKS = [
  {
    to: "/sources",
    title: "Data Sources & Storage",
    description: "Create NiFi connector sources or manual upload sources. Each source gets its own MinIO bucket.",
    icon: IconSources,
    cta: "Manage Sources",
  },
  {
    to: "/browse",
    title: "Folders & Files",
    description: "Explore virtual directory workspaces and raw object storage contents.",
    icon: IconBrowse,
    cta: "Open Workspace",
  },
  {
    to: "/sources",
    title: "External Connectors",
    description: "Sync Google Drive, Amazon S3, and Azure Blob Storage into MinIO buckets.",
    icon: IconSources,
    cta: "Manage Sources",
  },
  {
    to: "/knowledge-store",
    title: "Knowledge Store Fanout",
    description: "Manage 5-sink multi-vector fanout sync to Qdrant, OpenSearch, Neo4j, Postgres, & RedisVL.",
    icon: IconDatabase,
    cta: "Manage Knowledge Store",
  },
] as const;

export default function HomePage() {
  const [directories, setDirectories] = useState<DirectorySummary[]>([]);
  const [sourcesCount, setSourcesCount] = useState<number>(0);
  const [profilesCount, setProfilesCount] = useState<number>(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [dirs, sources, profiles] = await Promise.all([
        listDirectories().catch(() => []),
        listSources().catch(() => []),
        listKnowledgeProfiles().catch(() => []),
      ]);
      setDirectories(dirs);
      setSourcesCount(sources.length);
      setProfilesCount(profiles.length);
    } catch {
      /* overview stays usable */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const totalFiles = directories.reduce((acc, d) => acc + (d.fileCount || 0), 0);

  return (
    <div className="page">
      <PageHeader
        title="Ingestion Overview"
        description="Ingest documents, manage connected data sources, and orchestrate 5-sink Knowledge Store fanout sync."
      />

      {/* Metric Highlights Banner */}
      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>{sourcesCount}</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Connected Data Sources</div>
        </div>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>{directories.length}</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Workspace Folders</div>
        </div>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>{totalFiles}</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Ingested Files</div>
        </div>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>{profilesCount}</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Knowledge Profiles</div>
        </div>
      </section>

      <section className="quick-grid">
        {QUICK_LINKS.map(({ to, title, description, icon: Icon, cta }) => (
          <Link key={title} to={to} className="quick-card">
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
            Recent Folder Workspaces
          </h2>
          <Link to="/browse" className="btn btn-ghost btn-sm">
            View All
          </Link>
        </div>

        {loading ? (
          <p className="muted">Loading workspace folders…</p>
        ) : directories.length === 0 ? (
          <div className="empty-inline">
            <p>No workspace folders created yet.</p>
            <Link to="/sources" className="btn btn-primary btn-sm">
              Create Data Source
            </Link>
          </div>
        ) : (
          <div className="overview-dirs-grid">
            {directories.slice(0, 6).map((dir) => (
              <Link key={dir.id} to={`/browse/${encodeURIComponent(dir.name)}`} className="dir-card">
                <div className="dir-card-header">
                  <IconFolder size={20} className="dir-card-icon" />
                  <span className="dir-card-name">{dir.name}</span>
                </div>
                <div className="dir-card-footer">
                  <span>{(dir.fileCount ?? dir.file_count ?? 0)} file{(dir.fileCount ?? dir.file_count) === 1 ? "" : "s"}</span>
                  <span className="muted">{formatRelativeTime(dir.updatedAt ?? dir.updated_at ?? dir.created_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Knowledge Sink Engine Banner */}
      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <div className="panel-header">
          <h2 className="panel-title">
            <IconDatabase className="panel-title-icon" />
            Universal Multi-Sink Knowledge Engine (2026 Edition)
          </h2>
          <Link to="/knowledge-store" className="btn btn-ghost btn-sm">Configure Sinks</Link>
        </div>
        <p style={{ fontSize: "0.9rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
          Ingestion streams document object bytes into MinIO source buckets, chunks text with token window splitters, and executes 5-destination multi-vector fanout.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.75rem" }}>
          <div style={{ background: "var(--bg-card-alt)", padding: "0.75rem", borderRadius: "6px", fontSize: "0.85rem", borderLeft: "3px solid #3b82f6" }}>
            <strong>Qdrant:</strong> Dense Vector Embeddings (HNSW)
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "0.75rem", borderRadius: "6px", fontSize: "0.85rem", borderLeft: "3px solid #10b981" }}>
            <strong>OpenSearch:</strong> BM25 Lexical & Inverted Index
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "0.75rem", borderRadius: "6px", fontSize: "0.85rem", borderLeft: "3px solid #8b5cf6" }}>
            <strong>Neo4j:</strong> GraphRAG Entity-Relation Triples
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "0.75rem", borderRadius: "6px", fontSize: "0.85rem", borderLeft: "3px solid #f59e0b" }}>
            <strong>PostgreSQL:</strong> Relational & pgvector ACLs
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "0.75rem", borderRadius: "6px", fontSize: "0.85rem", borderLeft: "3px solid #ef4444" }}>
            <strong>RedisVL:</strong> Parent-Child & Semantic Cache
          </div>
        </div>
      </section>
    </div>
  );
}
