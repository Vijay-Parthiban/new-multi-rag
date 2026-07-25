import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import {
  createEvaluationRun,
  deleteGoldenDataset,
  EvalRunItemRow,
  EvalRunResponse,
  getEvaluationRun,
  GoldenDatasetSummary,
  listDatasetRuns,
  listEvaluationRunItems,
  listGoldenDatasets,
  listPipelines,
  PipelineRecord,
  uploadGoldenDataset,
} from "../api";
import { formatRelativeTime } from "../utils/format";

const PAGE_SIZE = 10;

function formatMetric(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

function sourceLabel(src: string | { name: string; page?: number }): string {
  if (typeof src === "string") return src;
  return src.page != null ? `${src.name} (p.${src.page})` : src.name;
}

// MeanBarChart removed per request

function StageKpis({
  title,
  metrics,
}: {
  title: string;
  metrics: Record<string, number> | undefined;
}) {
  const entries = Object.entries(metrics || {}).filter(([, v]) => typeof v === "number");

  // Calculate average weight for the category
  const validValues = entries.map(([, v]) => v).filter(v => typeof v === "number" && !Number.isNaN(v));
  const avgWeight = validValues.length > 0 ? validValues.reduce((a, b) => a + b, 0) / validValues.length : null;

  return (
    <div className="panel" style={{ flex: 1, minWidth: 220 }}>
      <div className="panel-header">
        <h3 className="panel-title">{title}</h3>
      </div>
      <div style={{ padding: "0.75rem 1rem", display: "grid", gap: "0.5rem" }}>
        {avgWeight !== null && (
          <div style={{ paddingBottom: "0.5rem", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ fontSize: "0.85rem" }}>Category Weight</strong>
              <strong className="mono">{formatMetric(avgWeight)}</strong>
            </div>
            {avgWeight < 0.65 && (
              <div style={{ color: "#ef4444", fontSize: "0.75rem", marginTop: "0.25rem", fontWeight: 500 }}>
                Category quality is poor
              </div>
            )}
          </div>
        )}

        {entries.length === 0 ? (
          <span className="muted">No metrics yet</span>
        ) : (
          entries.map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
              <span className="muted" style={{ fontSize: "0.8rem" }}>
                {k.replace(/^mean_/, "")}
              </span>
              <span className="mono">{formatMetric(v)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function RubricTable({ items, status }: { items: EvalRunItemRow[], status?: string }) {
  const dist = useMemo(() => {
    const buckets = {
      retrieval: { excellent: 0, good: 0, poor: 0, total: 0 },
      reranker: { excellent: 0, good: 0, poor: 0, total: 0 },
      generation: { excellent: 0, good: 0, poor: 0, total: 0 },
    };

    items.forEach((item) => {
      // Retrieval Score
      if (item.retrieval_metrics) {
        const rm = item.retrieval_metrics;
        const rVals = [rm.precision, rm.recall, rm.mrr, rm.hit].filter((v): v is number => typeof v === "number");
        if (rVals.length > 0) {
          const score = rVals.reduce((a, b) => a + b, 0) / rVals.length;
          buckets.retrieval.total++;
          if (score >= 0.85) buckets.retrieval.excellent++;
          else if (score >= 0.65) buckets.retrieval.good++;
          else buckets.retrieval.poor++;
        }
      }

      // Reranker Score (using ndcg primarily as MRR delta is unbounded)
      if (item.rerank_metrics?.ndcg !== undefined) {
        const score = item.rerank_metrics.ndcg;
        buckets.reranker.total++;
        if (score >= 0.85) buckets.reranker.excellent++;
        else if (score >= 0.65) buckets.reranker.good++;
        else buckets.reranker.poor++;
      }

      // Generation Score
      if (item.generation_metrics) {
        const gm = item.generation_metrics;
        const gVals = [gm.faithfulness, gm.accuracy, gm.answer_relevancy].filter((v): v is number => typeof v === "number");
        if (gVals.length > 0) {
          const score = gVals.reduce((a, b) => a + b, 0) / gVals.length;
          buckets.generation.total++;
          if (score >= 0.85) buckets.generation.excellent++;
          else if (score >= 0.65) buckets.generation.good++;
          else buckets.generation.poor++;
        }
      }
    });
    return buckets;
  }, [items]);

  const p = (qty: number, total: number) => {
    if (total === 0) return "—";
    return `${Math.round((qty / total) * 100)}%`;
  };

  if (items.length === 0) {
    return <p className="muted" style={{ padding: "1rem" }}>{status === "completed" ? "No valid metrics found." : "Run is not complete yet."}</p>;
  }

  return (
    <table className="repo-table" style={{ width: "100%", marginTop: "0.5rem" }}>
      <thead>
        <tr>
          <th>Category</th>
          <th style={{ color: "var(--success, #10b981)" }}>Excellent (≥ 85%)</th>
          <th style={{ color: "var(--accent, #3b82f6)" }}>Good (65% - 84%)</th>
          <th style={{ color: "var(--error, #ef4444)" }}>Poor (&lt; 65%)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Retrieval</strong></td>
          <td className="mono">{p(dist.retrieval.excellent, dist.retrieval.total)}</td>
          <td className="mono">{p(dist.retrieval.good, dist.retrieval.total)}</td>
          <td className="mono">{p(dist.retrieval.poor, dist.retrieval.total)}</td>
        </tr>
        <tr>
          <td><strong>Reranking</strong></td>
          <td className="mono">{p(dist.reranker.excellent, dist.reranker.total)}</td>
          <td className="mono">{p(dist.reranker.good, dist.reranker.total)}</td>
          <td className="mono">{p(dist.reranker.poor, dist.reranker.total)}</td>
        </tr>
        <tr>
          <td><strong>Generation</strong></td>
          <td className="mono">{p(dist.generation.excellent, dist.generation.total)}</td>
          <td className="mono">{p(dist.generation.good, dist.generation.total)}</td>
          <td className="mono">{p(dist.generation.poor, dist.generation.total)}</td>
        </tr>
      </tbody>
    </table>
  );
}

export default function GoldenEvaluationsPage() {
  const [datasets, setDatasets] = useState<GoldenDatasetSummary[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [pipelineId, setPipelineId] = useState("");
  const [retrievalMode, setRetrievalMode] = useState("hybrid");
  const [retrieveLimit, setRetrieveLimit] = useState(20);
  const [rerankEnabled, setRerankEnabled] = useState(true);
  const [runs, setRuns] = useState<EvalRunResponse[]>([]);
  const [runsCount, setRunsCount] = useState(0);
  const [page, setPage] = useState(0);
  const [selectedRun, setSelectedRun] = useState<EvalRunResponse | null>(null);
  const [runItems, setRunItems] = useState<EvalRunItemRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadReplace, setUploadReplace] = useState(false);
  const [activeTab, setActiveTab] = useState<"analytics" | "drilldown">("analytics");

  const selectedPipeline = useMemo(
    () => pipelines.find((p) => p.id === pipelineId) || null,
    [pipelines, pipelineId],
  );

  const loadDatasets = useCallback(async () => {
    const items = await listGoldenDatasets();
    setDatasets(items);
    setSelectedDatasetId((prev) => {
      if (prev && items.some((d) => d.dataset_id === prev)) return prev;
      return items[0]?.dataset_id ?? null;
    });
  }, []);

  const loadRuns = useCallback(async (datasetId: string, pageIndex: number) => {
    const res = await listDatasetRuns(datasetId, {
      skip: pageIndex * PAGE_SIZE,
      limit: PAGE_SIZE,
    });
    setRuns(res.items || []);
    setRunsCount(res.count || 0);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const pipes = await listPipelines();
      setPipelines(pipes);
      setPipelineId((prev) => prev || pipes[0]?.id || "");
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load golden evaluations");
    } finally {
      setLoading(false);
    }
  }, [loadDatasets]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedDatasetId) {
      setRuns([]);
      setRunsCount(0);
      setSelectedRun(null);
      setRunItems([]);
      return;
    }
    setSelectedRun(null);
    setRunItems([]);
    setPage(0);
    void loadRuns(selectedDatasetId, 0).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load runs"),
    );
  }, [selectedDatasetId, loadRuns]);

  useEffect(() => {
    if (!selectedDatasetId) return;
    void loadRuns(selectedDatasetId, page).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load runs"),
    );
  }, [page, selectedDatasetId, loadRuns]);

  // Poll active run
  useEffect(() => {
    if (!selectedRun) return;
    if (selectedRun.status === "completed" || selectedRun.status === "failed") return;
    const id = window.setInterval(async () => {
      try {
        const updated = await getEvaluationRun(selectedRun.run_id);
        setSelectedRun(updated);
        if (selectedDatasetId) await loadRuns(selectedDatasetId, page);
        if (updated.status === "completed") {
          const items = await listEvaluationRunItems(updated.run_id);
          setRunItems(items);
        }
      } catch {
        /* ignore transient poll errors */
      }
    }, 2500);
    return () => window.clearInterval(id);
  }, [selectedRun, selectedDatasetId, page, loadRuns]);

  const totalPages = Math.max(1, Math.ceil(runsCount / PAGE_SIZE));

  const flatChartMetrics = useMemo(() => {
    const agg = selectedRun?.aggregate_metrics || {};
    const out: Record<string, number> = {};
    for (const stage of ["retrieval", "reranker", "generation"] as const) {
      const block = agg[stage];
      if (block && typeof block === "object") {
        for (const [k, v] of Object.entries(block as Record<string, unknown>)) {
          if (typeof v === "number") out[`${stage}.${k}`] = v;
        }
      } else if (typeof (agg as Record<string, unknown>)[stage] === "number") {
        // legacy flat
      }
    }
    // legacy flat mean_* support
    for (const [k, v] of Object.entries(agg)) {
      if (k.startsWith("mean_") && typeof v === "number") out[k] = v;
    }
    return out;
  }, [selectedRun]);

  async function onUpload(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const res = await uploadGoldenDataset(file, uploadReplace);
      await loadDatasets();
      setSelectedDatasetId(res.dataset_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteDataset(datasetId: string) {
    if (!window.confirm("Delete this dataset and all related evaluation runs?")) return;
    setBusy(true);
    try {
      await deleteGoldenDataset(datasetId);
      if (selectedDatasetId === datasetId) setSelectedDatasetId(null);
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function onStartRun() {
    if (!selectedDatasetId || !selectedPipeline) {
      setError("Select a dataset and pipeline first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createEvaluationRun(selectedDatasetId, {
        retrieval_mode: retrievalMode,
        retrieve_limit: retrieveLimit,
        rerank_enabled: rerankEnabled,
        collection: selectedPipeline.qdrant_collection,
        embedding_model: selectedPipeline.embedding_model,
        sparse_embedding_model: selectedPipeline.sparse_embedding_model,
      });
      const run = await getEvaluationRun(created.run_id);
      setSelectedRun(run);
      setRunItems([]);
      await loadRuns(selectedDatasetId, page);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start run");
    } finally {
      setBusy(false);
    }
  }

  async function onSelectRun(run: EvalRunResponse) {
    setSelectedRun(run);
    setRunItems([]);
    if (run.status === "completed") {
      try {
        const items = await listEvaluationRunItems(run.run_id);
        setRunItems(items);
        const fresh = await getEvaluationRun(run.run_id);
        setSelectedRun(fresh);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load run items");
      }
    }
    setActiveTab("analytics"); // Open analytics by default on new run
  }

  const agg = (selectedRun?.aggregate_metrics || {}) as {
    retrieval?: Record<string, number>;
    reranker?: Record<string, number>;
    generation?: Record<string, number>;
  };

  return (
    <div className="page">
      <PageHeader
        title="Offline Evaluation (Golden Datasets)"
        description="Upload golden datasets, run pipeline-aligned evaluations, and inspect retrieval / rerank / generation KPIs."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Offline Evaluation" },
        ]}
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => void refresh()} disabled={busy}>
            Refresh
          </button>
        }
      />

      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
        <div className="panel">
          <div className="panel-header">
            <h3 className="panel-title">Datasets</h3>
          </div>
          <div style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="file"
                accept=".json,application/json"
                disabled={busy}
                onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
              />
              <label className="muted" style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={uploadReplace}
                  onChange={(e) => setUploadReplace(e.target.checked)}
                />
                Replace if name exists
              </label>
            </div>
            {loading ? (
              <p className="muted">Loading datasets…</p>
            ) : datasets.length === 0 ? (
              <p className="muted">No datasets yet. Upload a golden JSON file.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "0.35rem" }}>
                {datasets.map((ds) => (
                  <li key={ds.dataset_id}>
                    <button
                      type="button"
                      className={`btn btn-sm ${selectedDatasetId === ds.dataset_id ? "btn-primary" : "btn-ghost"}`}
                      style={{ width: "100%", justifyContent: "space-between", display: "flex" }}
                      onClick={() => setSelectedDatasetId(ds.dataset_id)}
                    >
                      <span>
                        {ds.name}{" "}
                        <span className="muted">({ds.item_count} items)</span>
                      </span>
                      <span
                        className="muted"
                        role="button"
                        tabIndex={0}
                        onClick={(e) => {
                          e.stopPropagation();
                          void onDeleteDataset(ds.dataset_id);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.stopPropagation();
                            void onDeleteDataset(ds.dataset_id);
                          }
                        }}
                        title="Delete dataset"
                      >
                        Delete
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3 className="panel-title">New Run</h3>
          </div>
          <div style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
            <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
              Pipeline
              <select
                className="input"
                value={pipelineId}
                onChange={(e) => setPipelineId(e.target.value)}
              >
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.qdrant_collection}
                  </option>
                ))}
              </select>
            </label>
            {selectedPipeline && (
              <p className="muted" style={{ fontSize: "0.8rem", margin: 0 }}>
                collection={selectedPipeline.qdrant_collection} · embedding=
                {selectedPipeline.embedding_model}
                {selectedPipeline.sparse_embedding_model
                  ? ` · sparse=${selectedPipeline.sparse_embedding_model}`
                  : ""}
              </p>
            )}
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                Retrieval
                <select
                  className="input"
                  value={retrievalMode}
                  onChange={(e) => setRetrievalMode(e.target.value)}
                >
                  <option value="dense">dense</option>
                  <option value="sparse">sparse</option>
                  <option value="hybrid">hybrid</option>
                </select>
              </label>
              <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                Chunk limit
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={100}
                  value={retrieveLimit}
                  onChange={(e) => setRetrieveLimit(Number(e.target.value) || 20)}
                  style={{ width: 90 }}
                />
              </label>
              <label className="muted" style={{ display: "flex", gap: "0.35rem", alignItems: "center", marginTop: "1.4rem" }}>
                <input
                  type="checkbox"
                  checked={rerankEnabled}
                  onChange={(e) => setRerankEnabled(e.target.checked)}
                />
                Rerank
              </label>
            </div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !selectedDatasetId || !pipelineId}
              onClick={() => void onStartRun()}
            >
              Start evaluation run
            </button>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <div className="panel-header">
          <h3 className="panel-title">Runs</h3>
        </div>
        {!selectedDatasetId ? (
          <p className="panel-empty">Select a dataset to see runs.</p>
        ) : runs.length === 0 ? (
          <p className="panel-empty">No runs for this dataset yet.</p>
        ) : (
          <>
            <div className="repo-table-wrap">
              <table className="repo-table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Status</th>
                    <th>Progress</th>
                    <th>Created</th>
                    <th>Config</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.run_id}
                      onClick={() => void onSelectRun(run)}
                      style={{
                        cursor: "pointer",
                        background:
                          selectedRun?.run_id === run.run_id ? "var(--surface-2, transparent)" : undefined,
                      }}
                    >
                      <td className="mono">{run.run_id.slice(0, 8)}…</td>
                      <td>{run.status}</td>
                      <td className="mono">
                        {run.progress.items_completed}/{run.progress.items_total}
                        {run.progress.items_failed ? ` (${run.progress.items_failed} failed)` : ""}
                      </td>
                      <td className="muted">
                        {run.created_at ? formatRelativeTime(run.created_at) : "—"}
                      </td>
                      <td className="muted" style={{ fontSize: "0.75rem" }}>
                        {run.config?.retrieval_mode || "—"} · limit {run.config?.retrieve_limit ?? "—"} ·
                        rerank {run.config?.rerank_enabled ? "on" : "off"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "0.75rem 1rem",
              }}
            >
              <span className="muted" style={{ fontSize: "0.875rem" }}>
                Page {page + 1} of {totalPages} · {runsCount} runs
              </span>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  disabled={page <= 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  ◀
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  disabled={page + 1 >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  ▶
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {selectedRun && (
        <>
          <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
            <button
              className={`btn btn-sm ${activeTab === "analytics" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setActiveTab("analytics")}
            >
              Analytics & Rubric
            </button>
            <button
              className={`btn btn-sm ${activeTab === "drilldown" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setActiveTab("drilldown")}
            >
              Drill-down (Per-question)
            </button>
          </div>

          {activeTab === "analytics" && (
            <>
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "1rem" }}>
                <StageKpis title="Retrieval" metrics={agg.retrieval} />
                <StageKpis title="Reranker" metrics={agg.reranker} />
                <StageKpis title="Generation" metrics={agg.generation} />
              </div>

              <div className="panel" style={{ marginBottom: "1rem" }}>
                <div className="panel-header">
                  <h3 className="panel-title">Evaluation Rubric</h3>
                </div>
                <RubricTable items={runItems} status={selectedRun.status} />
              </div>
            </>
          )}

          {activeTab === "drilldown" && (
            <div className="panel">
              <div className="panel-header">
                <h3 className="panel-title">Per-question drill-down</h3>
              </div>
              {runItems.length === 0 ? (
                <p className="panel-empty">
                  {selectedRun.status === "completed"
                    ? "No item rows returned."
                    : "Item metrics appear when the run completes."}
                </p>
              ) : (
                <div className="repo-table-wrap">
                  <table className="repo-table">
                    <thead>
                      <tr>
                        <th>Question</th>
                        <th>Expected sources</th>
                        <th>Retrieval</th>
                        <th>Rerank</th>
                        <th>Generation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runItems.map((item) => (
                        <tr key={item.item_id}>
                          <td>
                            <div style={{ maxWidth: 280 }}>{item.question || "—"}</div>
                            <div className="muted" style={{ fontSize: "0.75rem" }}>
                              {item.status}
                            </div>
                          </td>
                          <td style={{ fontSize: "0.8rem" }}>
                            {(item.expected_sources || []).map(sourceLabel).join(", ") || "—"}
                          </td>
                          <td className="mono" style={{ fontSize: "0.75rem" }}>
                            P {formatMetric(item.retrieval_metrics?.precision)} · R{" "}
                            {formatMetric(item.retrieval_metrics?.recall)} · MRR{" "}
                            {formatMetric(item.retrieval_metrics?.mrr)}
                          </td>
                          <td className="mono" style={{ fontSize: "0.75rem" }}>
                            Δ {formatMetric(item.rerank_metrics?.mrr_delta)} · NDCG{" "}
                            {formatMetric(item.rerank_metrics?.ndcg)} · τ{" "}
                            {formatMetric(item.rerank_metrics?.kendall_tau)}
                          </td>
                          <td className="mono" style={{ fontSize: "0.75rem" }}>
                            Faith {formatMetric(item.generation_metrics?.faithfulness)} · Acc{" "}
                            {formatMetric(item.generation_metrics?.accuracy)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
