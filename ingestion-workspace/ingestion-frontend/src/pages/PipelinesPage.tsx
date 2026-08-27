import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import {
  ApiError,
  CreatePipelineRequest,
  DirectorySummary,
  PipelineOptions,
  PipelineRecord,
  PipelineRunRecord,
  PipelineStats,
  listDirectories,
  listPipelineRuns,
  listPipelines,
  startPipelineRun,
  getPipelineStats,
  triggerPipelineSync,
  listSources,
  linkSourceToPipeline,
  SourceRecord,
} from "../api";

const NEEDS_MODALITY = new Set(["multimodal", "metadata"]);
const NEEDS_SPARSE = new Set(["sparse", "hybrid", "metadata"]);

export default function PipelinesPage() {
  const [options, setOptions] = useState<PipelineOptions | null>(null);
  const [directories, setDirectories] = useState<DirectorySummary[]>([]);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [runs, setRuns] = useState<PipelineRunRecord[]>([]);
  const [activePipelineStats, setActivePipelineStats] = useState<PipelineStats | null>(null);
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ragStrategy, setRagStrategy] = useState("hybrid");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [sparseEmbeddingModel, setSparseEmbeddingModel] = useState("");
  const [modality, setModality] = useState<string>("text");
  const [selectedDirs, setSelectedDirs] = useState<Set<string>>(new Set());
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(new Set());
  const [chunkSize, setChunkSize] = useState(1000);
  const [chunkOverlap, setChunkOverlap] = useState(120);
  const [qdrantCollection, setQdrantCollection] = useState("");
  const [webScraperEnabled, setWebScraperEnabled] = useState(false);
  const [scraperSeedUrl, setScraperSeedUrl] = useState("");
  const [scraperMaxDepth, setScraperMaxDepth] = useState(2);
  const [scraperMaxPages, setScraperMaxPages] = useState(50);
  const [scraperMode, setScraperMode] = useState("httpx");
  const [scraperEmbeddingSource, setScraperEmbeddingSource] = useState<"markdown" | "image">("markdown");
  const location = useLocation();

  const load = useCallback(async () => {
    try {
      const [opts, dirs, pipes, srcs] = await Promise.all([
        getPipelineOptions(),
        listDirectories(),
        listPipelines(),
        listSources(),
      ]);
      setOptions(opts);
      setDirectories(dirs);
      setPipelines(pipes);
      setSources(srcs);
      setPipelines(pipes);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPipelineDetails = useCallback(async (pipelineId: string) => {
    try {
      const [runList, statData] = await Promise.all([
        listPipelineRuns(pipelineId),
        getPipelineStats(pipelineId)
      ]);
      setRuns(runList);
      setActivePipelineStats(statData);
    } catch {
      /* keep previous data on failure to not flash empty state */
    }
  }, []);

  const isVisible = location.pathname === "/pipelines";

  useEffect(() => {
    if (isVisible) {
      load();
    }
  }, [isVisible, load]);

  useEffect(() => {
    if (!selectedPipelineId || !isVisible) return;
    loadPipelineDetails(selectedPipelineId);
    const interval = setInterval(() => loadPipelineDetails(selectedPipelineId), 15000); // 15 seconds polling when visible
    return () => clearInterval(interval);
  }, [selectedPipelineId, isVisible, loadPipelineDetails]);

  function toggleDir(dirName: string) {
    setSelectedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dirName)) next.delete(dirName);
      else next.add(dirName);
      return next;
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfo(null);

    const body: CreatePipelineRequest = {
      name: name.trim(),
      description: description.trim(),
      rag_strategy: ragStrategy,
      embedding_model: embeddingModel.trim(),
      sparse_embedding_model: NEEDS_SPARSE.has(ragStrategy)
        ? sparseEmbeddingModel.trim()
        : null,
      modality: NEEDS_MODALITY.has(ragStrategy)
        ? modality
        : webScraperEnabled
          ? scraperEmbeddingSource === "image"
            ? "image"
            : "text"
          : null,
      directory_names: Array.from(selectedDirs),
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
      qdrant_collection: qdrantCollection.trim(),
      web_scraper_enabled: webScraperEnabled,
      scraper_seed_url: webScraperEnabled ? scraperSeedUrl.trim() : null,
      scraper_max_depth: scraperMaxDepth,
      scraper_max_pages: scraperMaxPages,
      scraper_mode: scraperMode,
    };

    try {
      const created = await createPipeline(body);
      setInfo(`Pipeline "${created.description}" saved. Use this description in chat to select it.`);
      setName("");
      setDescription("");
      setQdrantCollection("");
      setEmbeddingModel("");
      setSparseEmbeddingModel("");
      await load();
      setSelectedPipelineId(created.id);
      // Link selected MinIO sources to the newly created pipeline
      for (const srcId of Array.from(selectedSourceIds)) {
        try {
          await linkSourceToPipeline(srcId, created.id);
        } catch {}
      }
      await loadPipelineDetails(created.id);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRun(pipelineId: string) {
    setError(null);
    try {
      const run = await startPipelineRun(pipelineId);
      setSelectedPipelineId(pipelineId);
      setInfo(`Pipeline run started (${run.status}).`);
      await loadPipelineDetails(pipelineId);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  }

  async function handleSync(pipelineId: string) {
    setError(null);
    try {
      const res = await triggerPipelineSync(pipelineId);
      setInfo(`Pipeline sync started (${res.status}).`);
      await loadPipelineDetails(pipelineId);
    } catch (err) {
      setError(err instanceof ApiError ? err : null);
    }
  }

  const showModality = NEEDS_MODALITY.has(ragStrategy);
  const showSparse = NEEDS_SPARSE.has(ragStrategy);
  const canSubmit =
    name.trim().length > 0 &&
    description.trim().length >= 8 &&
    embeddingModel.trim().length > 0 &&
    qdrantCollection.trim().length >= 3 &&
    (!showSparse || sparseEmbeddingModel.trim().length > 0) &&
    (selectedDirs.size > 0 || selectedSourceIds.size > 0 || webScraperEnabled);

  return (
    <div className="page">
      <PageHeader
        title="Pipelines"
        description="Each pipeline has its own Qdrant collection, embedding models, and a unique description for chat selection."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Pipelines" },
        ]}
        actions={
          <div style={{ display: "flex", gap: "0.5rem" }}>
            {selectedPipelineId && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => handleSync(selectedPipelineId)}
              >
                Trigger Sync
              </button>
            )}
            {selectedPipelineId && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => loadPipelineDetails(selectedPipelineId)}
              >
                Refresh stats
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => load()}
            >
              Refresh pipelines
            </button>
            <Link to="/tracking" className="btn btn-secondary">
              View tracking
            </Link>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error">
          <strong>{error.code}</strong>: {error.message}
        </div>
      )}
      {info && <div className="alert alert-info">{info}</div>}

      {loading ? (
        <p className="muted">Loading pipeline options…</p>
      ) : (
        <div className="pipeline-layout">
          <form className="panel pipeline-form" onSubmit={handleSubmit}>
            <div className="panel-header">
              <h2 className="panel-title">New pipeline</h2>
            </div>
            <div className="form-body">
              <label className="field-label" htmlFor="pipeline-name">Internal name</label>
              <input
                id="pipeline-name"
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="legal-docs-v1"
                required
              />

              <label className="field-label" htmlFor="pipeline-description">
                Description (unique — used in chat UI)
              </label>
              <input
                id="pipeline-description"
                className="input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Legal contract hybrid RAG for M&A due diligence"
                minLength={8}
                required
              />
              <p className="field-hint">
                Chat users select pipelines by this description, not by UUID.
              </p>

              <label className="field-label" htmlFor="rag-strategy">Search Strategy</label>
              <select
                id="rag-strategy"
                className="input"
                value={ragStrategy}
                onChange={(e) => setRagStrategy(e.target.value)}
              >
                {options?.rag_strategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label} — {s.description}
                  </option>
                ))}
              </select>

              <label className="field-label" htmlFor="embedding-model">Primary Text Engine</label>
              <select
                id="embedding-model"
                className="input mono"
                value={embeddingModel}
                onChange={(e) => setEmbeddingModel(e.target.value)}
                required
              >
                <option value="" disabled>Select an engine...</option>
                {options?.suggested_embedding_models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>

              {showSparse && (
                <>
                  <label className="field-label" htmlFor="sparse-model">Keyword Search Engine</label>
                  <select
                    id="sparse-model"
                    className="input mono"
                    value={sparseEmbeddingModel}
                    onChange={(e) => setSparseEmbeddingModel(e.target.value)}
                    required
                  >
                    <option value="" disabled>Select an engine...</option>
                    {options?.suggested_sparse_models.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </>
              )}

              {showModality && (
                <>
                  <label className="field-label" htmlFor="modality">Content Type</label>
                  <select
                    id="modality"
                    className="input"
                    value={modality}
                    onChange={(e) => setModality(e.target.value)}
                  >
                    {options?.modalities.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label} — {m.description}
                      </option>
                    ))}
                  </select>
                </>
              )}

              <label className="field-label">Folders to index</label>
              {directories.length === 0 ? (
                <p className="field-hint">No folders yet — upload files first.</p>
              ) : (
                <ul className="folder-checklist">
                  {directories.map((d) => (
                    <li key={d.id}>
                      <label className="check-row">
                        <input
                          type="checkbox"
                          checked={selectedDirs.has(d.name)}
                          onChange={() => toggleDir(d.name)}
                        />
                        <span className="mono">{d.name}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              <label className="field-label" style={{ marginTop: "1rem" }}>MinIO Sources to link</label>
              {sources.length === 0 ? (
                <p className="field-hint">No sources created yet — <Link to="/sources">create a MinIO source first</Link>.</p>
              ) : (
                <ul className="folder-checklist">
                  {sources.map((s) => (
                    <li key={s.id}>
                      <label className="check-row">
                        <input
                          type="checkbox"
                          checked={selectedSourceIds.has(s.id)}
                          onChange={() => {
                            const next = new Set(selectedSourceIds);
                            if (next.has(s.id)) next.delete(s.id);
                            else next.add(s.id);
                            setSelectedSourceIds(next);
                          }}
                        />
                        <span>
                          <strong>{s.name}</strong> <span className="mono" style={{ color: "var(--muted)", fontSize: "0.85rem" }}>({s.minio_bucket})</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}

              <div className="form-row">
                <div>
                  <label className="field-label" htmlFor="chunk-size">Document processing size</label>
                  <input
                    id="chunk-size"
                    type="number"
                    className="input"
                    value={chunkSize}
                    min={100}
                    max={8000}
                    onChange={(e) => setChunkSize(Number(e.target.value))}
                  />
                </div>
                <div>
                  <label className="field-label" htmlFor="chunk-overlap">Overlap</label>
                  <input
                    id="chunk-overlap"
                    type="number"
                    className="input"
                    value={chunkOverlap}
                    min={0}
                    max={2000}
                    onChange={(e) => setChunkOverlap(Number(e.target.value))}
                  />
                </div>
              </div>

              <label className="field-label" htmlFor="qdrant-collection">Qdrant collection</label>
              <input
                id="qdrant-collection"
                className="input mono"
                value={qdrantCollection}
                onChange={(e) => setQdrantCollection(e.target.value)}
                placeholder={options?.collection_naming_hint ?? "my-pipeline-collection-v1"}
                minLength={3}
                required
              />
              <p className="field-hint">
                Unique per pipeline. Web scraper and file indexing both write to this collection.
              </p>

              <label className="check-row scraper-toggle">
                <input
                  type="checkbox"
                  checked={webScraperEnabled}
                  onChange={(e) => setWebScraperEnabled(e.target.checked)}
                />
                <span>Enable web scraper (uses this pipeline&apos;s collection and models)</span>
              </label>

              {webScraperEnabled && (
                <div className="scraper-fields">
                  <label className="field-label" htmlFor="seed-url">Seed URL</label>
                  <input
                    id="seed-url"
                    className="input"
                    type="url"
                    value={scraperSeedUrl}
                    onChange={(e) => setScraperSeedUrl(e.target.value)}
                    placeholder="https://example.com/docs"
                    required={webScraperEnabled}
                  />
                  <div className="form-row">
                    <div>
                      <label className="field-label" htmlFor="max-depth">Max depth</label>
                      <input
                        id="max-depth"
                        type="number"
                        className="input"
                        min={0}
                        value={scraperMaxDepth}
                        onChange={(e) => setScraperMaxDepth(Number(e.target.value))}
                      />
                    </div>
                    <div>
                      <label className="field-label" htmlFor="max-pages">Max pages</label>
                      <input
                        id="max-pages"
                        type="number"
                        className="input"
                        min={1}
                        value={scraperMaxPages}
                        onChange={(e) => setScraperMaxPages(Number(e.target.value))}
                      />
                    </div>
                  </div>
                  <label className="field-label">Scraper embedding source</label>
                  <div className="content-type-group">
                    <label className={`content-type-option${scraperEmbeddingSource === "markdown" ? " selected" : ""}`}>
                      <input
                        type="radio"
                        name="scraper-embedding"
                        value="markdown"
                        checked={scraperEmbeddingSource === "markdown"}
                        onChange={() => setScraperEmbeddingSource("markdown")}
                        className="sr-only"
                      />
                      <span className="content-type-label">Markdown</span>
                      <span className="content-type-hint">Extract page text and embed as markdown chunks</span>
                    </label>
                    <label className={`content-type-option${scraperEmbeddingSource === "image" ? " selected" : ""}`}>
                      <input
                        type="radio"
                        name="scraper-embedding"
                        value="image"
                        checked={scraperEmbeddingSource === "image"}
                        onChange={() => setScraperEmbeddingSource("image")}
                        className="sr-only"
                      />
                      <span className="content-type-label">Image</span>
                      <span className="content-type-hint">Capture webpage screenshots for visual analysis</span>
                    </label>
                  </div>
                  <label className="field-label" htmlFor="scraper-mode">Crawl mode</label>
                  <select
                    id="scraper-mode"
                    className="input"
                    value={scraperMode}
                    onChange={(e) => setScraperMode(e.target.value)}
                  >
                    {options?.scraper_modes.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
              )}

              <button type="submit" className="btn btn-primary" disabled={submitting || !canSubmit}>
                {submitting ? "Saving…" : "Save pipeline"}
              </button>
            </div>
          </form>

          <section className="panel pipeline-list-panel">
            <div className="panel-header">
              <h2 className="panel-title">Saved pipelines</h2>
            </div>
            {pipelines.length === 0 ? (
              <p className="panel-empty muted">No pipelines configured yet.</p>
            ) : (
              <ul className="pipeline-list">
                {pipelines.map((p) => (
                  <li key={p.id} className={selectedPipelineId === p.id ? "active" : ""}>
                    <button
                      type="button"
                      className="pipeline-list-item"
                      onClick={() => setSelectedPipelineId(p.id)}
                    >
                      <strong>{p.description}</strong>
                      <span className="muted">{p.name} · {p.rag_strategy}</span>
                      <span className="muted mono">{p.qdrant_collection}</span>
                      <span className="muted">
                        {p.embedding_model}
                        {p.sparse_embedding_model ? ` + ${p.sparse_embedding_model}` : ""}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleRun(p.id)}
                    >
                      Run
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {selectedPipelineId && (
              <div className="runs-section" style={{ marginTop: "2rem" }}>
                <h3 className="runs-title">Pipeline Details & Stats</h3>
                <div className="panel" style={{ background: "var(--bg-inset)", marginTop: "1rem" }}>
                  <div className="repo-table-wrap">
                    <table className="repo-table">
                      <thead>
                        <tr>
                          <th>Resource</th>
                          <th>Count</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td><strong>Indexed Files</strong></td>
                          <td><span className="mono">{activePipelineStats?.indexed_files_count ?? 0}</span></td>
                          <td className="muted">Files configured via directory selection</td>
                        </tr>
                        <tr>
                          <td><strong>Scraped Pages</strong></td>
                          <td><span className="mono">{activePipelineStats?.scraped_pages_count ?? 0}</span></td>
                          <td className="muted">Pages crawled via web scraper</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {(() => {
                    const activePipeline = pipelines.find(p => p.id === selectedPipelineId);
                    if (!activePipeline) return null;
                    return (
                      <div className="repo-table-wrap" style={{ marginTop: "1rem", borderTop: "1px solid var(--border)" }}>
                        <table className="repo-table">
                          <thead>
                            <tr>
                              <th>Config</th>
                              <th>Value</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td className="muted">Search Strategy</td>
                              <td><span className="mono">{activePipeline.rag_strategy}</span></td>
                            </tr>
                            <tr>
                              <td className="muted">Processing Engines</td>
                              <td>
                                <span className="mono">{activePipeline.embedding_model}</span>
                                {activePipeline.sparse_embedding_model && (
                                  <> + <span className="mono">{activePipeline.sparse_embedding_model}</span></>
                                )}
                              </td>
                            </tr>
                            <tr>
                              <td className="muted">Collection</td>
                              <td><span className="mono">{activePipeline.qdrant_collection}</span></td>
                            </tr>
                            <tr>
                              <td className="muted">Processing Size</td>
                              <td><span className="mono">Size: {activePipeline.chunk_size} | Overlap: {activePipeline.chunk_overlap}</span></td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    )
                  })()}
                </div>

                <h3 className="runs-title" style={{ marginTop: "2rem" }}>Recent Activity</h3>
                {runs.length === 0 ? (
                  <p className="muted">No runs yet.</p>
                ) : (
                  <div className="repo-table-wrap">
                    <table className="repo-table">
                      <thead>
                        <tr>
                          <th>Status</th>
                          <th>Files</th>
                          <th>Pages</th>
                          <th>Points</th>
                          <th>Scraper</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runs.map((r) => (
                          <tr key={r.id}>
                            <td><StatusBadge status={r.status} /></td>
                            <td className="muted">{r.files_processed}/{r.files_total}</td>
                            <td className="muted">{r.pages_indexed}</td>
                            <td className="muted">{r.points_upserted}</td>
                            <td className="muted mono">
                              {r.scraper_crawl_job_id ? r.scraper_crawl_job_id.slice(0, 8) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {runs[0]?.error_message && (
                  <div className="alert alert-error">{runs[0].error_message}</div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
