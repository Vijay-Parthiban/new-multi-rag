import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import {
  PipelineRunWithPipeline,
  ScraperCrawlJob,
  ScraperScrapeJob,
  listAllPipelineRuns,
  listScraperCrawls,
  listScraperScrapes,
} from "../api";
import { formatRelativeTime } from "../utils/format";

type Tab = "ingestion" | "crawls" | "scrapes";

function ScraperStatusBadge({ status }: { status: string }) {
  return <StatusBadge status={status} />;
}

function SectionEmpty({ message }: { message: string }) {
  return <p className="panel-empty muted" style={{ padding: "1.5rem", textAlign: "center" }}>{message}</p>;
}

export default function TrackingPage() {
  const [activeTab, setActiveTab] = useState<Tab>("ingestion");

  const [runs, setRuns] = useState<PipelineRunWithPipeline[]>([]);
  const [crawls, setCrawls] = useState<ScraperCrawlJob[]>([]);
  const [scrapes, setScrapes] = useState<ScraperScrapeJob[]>([]);

  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingCrawls, setLoadingCrawls] = useState(true);
  const [loadingScrapes, setLoadingScrapes] = useState(true);

  const [errorRuns, setErrorRuns] = useState<string | null>(null);
  const [errorCrawls, setErrorCrawls] = useState<string | null>(null);
  const [errorScrapes, setErrorScrapes] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await listAllPipelineRuns(100));
      setErrorRuns(null);
    } catch (e) {
      setErrorRuns(e instanceof Error ? e.message : "Failed to load pipeline runs");
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  const loadCrawls = useCallback(async () => {
    try {
      setCrawls(await listScraperCrawls(50));
      setErrorCrawls(null);
    } catch (e) {
      setErrorCrawls(e instanceof Error ? e.message : "Scraper API unavailable");
    } finally {
      setLoadingCrawls(false);
    }
  }, []);

  const loadScrapes = useCallback(async () => {
    try {
      setScrapes(await listScraperScrapes(50));
      setErrorScrapes(null);
    } catch (e) {
      setErrorScrapes(e instanceof Error ? e.message : "Scraper API unavailable");
    } finally {
      setLoadingScrapes(false);
    }
  }, []);

  const location = useLocation();
  const isVisible = location.pathname === "/tracking";

  useEffect(() => {
    if (!isVisible) return;
    loadRuns();
    loadCrawls();
    loadScrapes();
    const interval = setInterval(() => {
      loadRuns();
      loadCrawls();
      loadScrapes();
    }, 300000); // 5 minutes
    return () => clearInterval(interval);
  }, [isVisible, loadRuns, loadCrawls, loadScrapes]);

  const pendingCount = runs.filter((r) => r.status === "pending" || r.status === "processing").length;

  return (
    <div className="page">
      <PageHeader
        title="Pipeline Tracking"
        description="Monitor document ingestion status and web scraper job history."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Tracking" }]}
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={async () => {
              await Promise.all([loadRuns(), loadCrawls(), loadScrapes()]);
            }}
          >
            Refresh
          </button>
        }
      />

      {/* Summary cards */}
      <div className="tracking-summary">
        <div className="tracking-card">
          <span className="tracking-card-num">{runs.length}</span>
          <span className="tracking-card-label">Total runs</span>
        </div>
        <div className="tracking-card tracking-card-active">
          <span className="tracking-card-num">{pendingCount}</span>
          <span className="tracking-card-label">Active</span>
        </div>
        <div className="tracking-card tracking-card-success">
          <span className="tracking-card-num">{runs.filter((r) => r.status === "completed" || r.status === "success").length}</span>
          <span className="tracking-card-label">Completed</span>
        </div>
        <div className="tracking-card tracking-card-error">
          <span className="tracking-card-num">{runs.filter((r) => r.status === "failed").length}</span>
          <span className="tracking-card-label">Failed</span>
        </div>
        <div className="tracking-card">
          <span className="tracking-card-num">{crawls.length}</span>
          <span className="tracking-card-label">Crawl jobs</span>
        </div>
        <div className="tracking-card">
          <span className="tracking-card-num">{scrapes.length}</span>
          <span className="tracking-card-label">Scrape jobs</span>
        </div>
      </div>

      {/* Tab navigation */}
      <div className="tracking-tabs">
        <button
          type="button"
          className={`tracking-tab${activeTab === "ingestion" ? " active" : ""}`}
          onClick={() => setActiveTab("ingestion")}
        >
          File Ingestion Runs
          {pendingCount > 0 && <span className="tab-badge">{pendingCount}</span>}
        </button>
        <button
          type="button"
          className={`tracking-tab${activeTab === "crawls" ? " active" : ""}`}
          onClick={() => setActiveTab("crawls")}
        >
          Crawl Jobs
        </button>
        <button
          type="button"
          className={`tracking-tab${activeTab === "scrapes" ? " active" : ""}`}
          onClick={() => setActiveTab("scrapes")}
        >
          Scrape Jobs
        </button>
      </div>

      {/* Ingestion Runs tab */}
      {activeTab === "ingestion" && (
        <div className="panel">
          <div className="panel-toolbar">
            <span className="panel-toolbar-label">
              {loadingRuns ? "Loading…" : `${runs.length} pipeline run${runs.length !== 1 ? "s" : ""}`}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={loadRuns}
            >
              Refresh
            </button>
          </div>

          {errorRuns && (
            <div className="alert alert-error" style={{ margin: "0.75rem" }}>
              {errorRuns}
            </div>
          )}

          {!loadingRuns && runs.length === 0 && !errorRuns && (
            <SectionEmpty message="No pipeline runs yet. Go to Pipelines to start one." />
          )}

          {runs.length > 0 && (
            <div className="repo-table-wrap">
              <table className="repo-table tracking-table">
                <thead>
                  <tr>
                    <th>Pipeline</th>
                    <th>Status</th>
                    <th>Files</th>
                    <th>Pages</th>
                    <th>Points</th>
                    <th>Scraper job</th>
                    <th>Started</th>
                    <th>Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id} className={r.status === "failed" ? "row-failed" : r.status === "processing" ? "row-active" : ""}>
                      <td>
                        <div className="tracking-pipeline-cell">
                          <span className="tracking-pipeline-name">
                            {r.pipeline_name ?? r.pipeline_id.slice(0, 8)}
                          </span>
                          {r.pipeline_description && (
                            <span className="muted tracking-pipeline-desc">{r.pipeline_description}</span>
                          )}
                          {r.qdrant_collection && (
                            <span className="mono muted" style={{ fontSize: "0.75rem" }}>{r.qdrant_collection}</span>
                          )}
                        </div>
                      </td>
                      <td><StatusBadge status={r.status} /></td>
                      <td className="muted">
                        <span className={r.files_processed === r.files_total && r.files_total > 0 ? "text-success" : ""}>
                          {r.files_processed}/{r.files_total}
                        </span>
                      </td>
                      <td className="muted">{r.pages_indexed}</td>
                      <td className="muted">{r.points_upserted}</td>
                      <td className="muted mono" style={{ fontSize: "0.75rem" }}>
                        {r.scraper_crawl_job_id ? (
                          <span title={r.scraper_crawl_job_id}>{r.scraper_crawl_job_id.slice(0, 8)}…</span>
                        ) : "—"}
                      </td>
                      <td className="muted">{r.started_at ? formatRelativeTime(r.started_at) : "—"}</td>
                      <td className="muted">{r.completed_at ? formatRelativeTime(r.completed_at) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {runs.some((r) => r.error_message) && (
            <div style={{ padding: "0.75rem 1rem", borderTop: "1px solid var(--border-muted)" }}>
              {runs.filter((r) => r.error_message).map((r) => (
                <div key={r.id} className="alert alert-error" style={{ marginBottom: "0.5rem", fontSize: "0.8125rem" }}>
                  <strong>{r.pipeline_name ?? r.pipeline_id.slice(0, 8)}</strong>: {r.error_message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Crawl Jobs tab */}
      {activeTab === "crawls" && (
        <div className="panel">
          <div className="panel-toolbar">
            <span className="panel-toolbar-label">
              {loadingCrawls ? "Loading…" : `${crawls.length} crawl job${crawls.length !== 1 ? "s" : ""}`}
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={loadCrawls}>Refresh</button>
          </div>

          {errorCrawls && (
            <div className="alert alert-warn" style={{ margin: "0.75rem" }}>
              Scraper API: {errorCrawls}. Make sure the scraper service is running at {import.meta.env.VITE_SCRAPER_URL ?? "http://localhost:8000"}.
            </div>
          )}

          {!loadingCrawls && crawls.length === 0 && !errorCrawls && (
            <SectionEmpty message="No crawl jobs found in the scraper service." />
          )}

          {crawls.length > 0 && (
            <div className="repo-table-wrap">
              <table className="repo-table tracking-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Seed URL</th>
                    <th>Status</th>
                    <th>Mode</th>
                    <th>Pages crawled</th>
                    <th>Total links</th>
                    <th>Markdown</th>
                    <th>Image</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {crawls.map((c) => (
                    <tr key={c.id} className={c.status === "failed" ? "row-failed" : c.status === "running" ? "row-active" : ""}>
                      <td className="muted mono" style={{ fontSize: "0.75rem" }}>
                        <span title={c.id}>{c.id.slice(0, 8)}…</span>
                      </td>
                      <td>
                        <a
                          href={c.seed_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="tracking-url"
                          title={c.seed_url}
                        >
                          {c.seed_url.length > 40 ? c.seed_url.slice(0, 40) + "…" : c.seed_url}
                        </a>
                      </td>
                      <td><ScraperStatusBadge status={c.status} /></td>
                      <td className="muted mono">{c.mode}</td>
                      <td className="muted">{c.result?.pages_crawled ?? "—"}</td>
                      <td className="muted">{c.result?.total_links ?? "—"}</td>
                      <td>
                        {c.markdown_ingested ? (
                          <span className="status-badge status-synced">Yes</span>
                        ) : (
                          <span className="status-badge status-pending">No</span>
                        )}
                      </td>
                      <td>
                        {c.image_ingested ? (
                          <span className="status-badge status-synced">Yes</span>
                        ) : (
                          <span className="status-badge status-pending">No</span>
                        )}
                      </td>
                      <td className="muted" style={{ fontSize: "0.75rem", maxWidth: "200px" }}>
                        {c.error_message ? (
                          <span className="text-danger" title={c.error_message}>
                            {c.error_message.slice(0, 50)}{c.error_message.length > 50 ? "…" : ""}
                          </span>
                        ) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Scrape Jobs tab */}
      {activeTab === "scrapes" && (
        <div className="panel">
          <div className="panel-toolbar">
            <span className="panel-toolbar-label">
              {loadingScrapes ? "Loading…" : `${scrapes.length} scrape job${scrapes.length !== 1 ? "s" : ""}`}
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={loadScrapes}>Refresh</button>
          </div>

          {errorScrapes && (
            <div className="alert alert-warn" style={{ margin: "0.75rem" }}>
              Scraper API: {errorScrapes}. Make sure the scraper service is running.
            </div>
          )}

          {!loadingScrapes && scrapes.length === 0 && !errorScrapes && (
            <SectionEmpty message="No scrape jobs found. Start a pipeline with web scraping enabled." />
          )}

          {scrapes.length > 0 && (
            <div className="repo-table-wrap">
              <table className="repo-table tracking-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Crawl job</th>
                    <th>Status</th>
                    <th>Embedding source</th>
                    <th>Pages scraped</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {scrapes.map((s) => (
                    <tr key={s.id} className={s.status === "failed" ? "row-failed" : s.status === "running" ? "row-active" : ""}>
                      <td className="muted mono" style={{ fontSize: "0.75rem" }}>
                        <span title={s.id}>{s.id.slice(0, 8)}…</span>
                      </td>
                      <td className="muted mono" style={{ fontSize: "0.75rem" }}>
                        <span title={s.crawl_job_id}>{s.crawl_job_id.slice(0, 8)}…</span>
                      </td>
                      <td><ScraperStatusBadge status={s.status} /></td>
                      <td>
                        <span className={`embedding-badge embedding-${s.embedding_source}`}>
                          {s.embedding_source}
                        </span>
                      </td>
                      <td className="muted">{s.pages_scraped}</td>
                      <td className="muted" style={{ fontSize: "0.75rem", maxWidth: "200px" }}>
                        {s.error_message ? (
                          <span className="text-danger" title={s.error_message}>
                            {s.error_message.slice(0, 60)}{s.error_message.length > 60 ? "…" : ""}
                          </span>
                        ) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
