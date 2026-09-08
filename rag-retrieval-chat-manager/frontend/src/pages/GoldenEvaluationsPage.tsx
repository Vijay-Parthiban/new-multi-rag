import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  itemCount,
}: {
  title: string;
  metrics: Record<string, number> | undefined;
  itemCount?: number;
}) {
  // Prefer canonical quality scores; skip rank-correlation / delta keys in the headline bar
  const QUALITY_KEYS = new Set([
    "mean_precision", "mean_recall", "mean_mrr", "mean_hit", "mean_ndcg",
    "mean_faithfulness", "mean_answer_relevancy", "mean_accuracy", "mean_answer_correctness",
    "precision", "recall", "mrr", "hit", "ndcg", "faithfulness", "answer_relevancy", "accuracy", "answer_correctness",
  ]);
  const entries = Object.entries(metrics || {}).filter(([, v]) => typeof v === "number");
  const qualityValues = entries
    .filter(([k]) => QUALITY_KEYS.has(k) || QUALITY_KEYS.has(k.replace(/^mean_/, "")))
    .map(([, v]) => v);
  const avgQuality = qualityValues.length > 0
    ? qualityValues.reduce((a, b) => a + b, 0) / qualityValues.length
    : null;

  return (
    <div className="panel" style={{ flex: 1, minWidth: 220 }}>
      <div className="panel-header">
        <h3 className="panel-title">{title}</h3>
        {itemCount !== undefined && (
          <span className="muted" style={{ fontSize: "0.75rem" }}>{itemCount} items</span>
        )}
      </div>
      <div style={{ padding: "0.75rem 1rem", display: "grid", gap: "0.5rem" }}>
        {avgQuality !== null && (
          <div style={{ paddingBottom: "0.5rem", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ fontSize: "0.85rem" }}>Avg quality</strong>
              <strong className="mono">{formatMetric(avgQuality)}</strong>
            </div>
            {avgQuality < 0.65 && (
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

// ── Canvas chart (bar) – no external deps ──────────────────────────────────
function MetricsBarChart({ data }: { data: { label: string; value: number }[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const W = canvas.width;
    const H = canvas.height;
    const PAD = { top: 16, right: 16, bottom: 36, left: 48 };
    const chartW = W - PAD.left - PAD.right;
    const chartH = H - PAD.top - PAD.bottom;
    const barGap = 12;
    const barW = Math.max(20, (chartW - barGap * (data.length - 1)) / Math.max(data.length, 1));
    const isDark = document.documentElement.classList.contains("dark") ||
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const textCol = isDark ? "rgba(200,212,233,0.85)" : "rgba(50,60,80,0.9)";
    const gridCol = isDark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.07)";
    const barCols = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#06b6d4"];

    ctx.clearRect(0, 0, W, H);

    // Grid lines at 0, 0.25, 0.5, 0.75, 1
    for (let t = 0; t <= 4; t++) {
      const y = PAD.top + chartH - (t / 4) * chartH;
      ctx.strokeStyle = gridCol;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(PAD.left + chartW, y);
      ctx.stroke();
      ctx.fillStyle = textCol;
      ctx.font = "10px system-ui";
      ctx.textAlign = "right";
      ctx.fillText((t * 0.25).toFixed(2), PAD.left - 6, y + 3);
    }

    data.forEach((d, i) => {
      // Signed metrics (tau / delta) use absolute magnitude for bar height
      const magnitude = Math.abs(d.value || 0);
      const bh = Math.min(1, magnitude <= 1 ? magnitude : Math.min(1, magnitude / Math.max(...data.map(x => Math.abs(x.value) || 1)))) * chartH;
      const x = PAD.left + i * (barW + barGap);
      const y = PAD.top + chartH - bh;
      ctx.fillStyle = barCols[i % barCols.length];
      ctx.beginPath();
      ctx.roundRect(x, y, barW, bh, [4, 4, 0, 0]);
      ctx.fill();

      // Value label
      ctx.fillStyle = textCol;
      ctx.font = "bold 10px system-ui";
      ctx.textAlign = "center";
      ctx.fillText(d.value.toFixed(3), x + barW / 2, Math.max(PAD.top + 12, y - 4));

      // Key label (rotated)
      ctx.save();
      ctx.translate(x + barW / 2, PAD.top + chartH + 6);
      ctx.rotate(Math.PI / 5);
      ctx.font = "10px system-ui";
      ctx.textAlign = "left";
      ctx.fillStyle = textCol;
      ctx.fillText(d.label.replace(/^mean_/, ""), 0, 0);
      ctx.restore();
    });
  }, [data]);

  return (
    <canvas
      ref={canvasRef}
      width={Math.max(280, data.length * 80)}
      height={180}
      style={{ display: "block", width: "100%", height: 180 }}
    />
  );
}

// ── Stage-filtered KPI panel with chart toggle ────────────────────────────
type Stage = "retrieval" | "reranker" | "generation";

function OverallKpis({ agg }: { agg: { retrieval?: Record<string, number>; reranker?: Record<string, number>; generation?: Record<string, number> } }) {
  const [stage, setStage] = useState<Stage>("retrieval");
  const [showChart, setShowChart] = useState(false);

  const stageMetrics: Record<string, number> | undefined = agg[stage];
  const entries = Object.entries(stageMetrics || {}).filter(([, v]) => typeof v === "number");
  const chartData = entries.map(([k, v]) => ({ label: k.replace(/^mean_/, ""), value: v }));

  const STAGES: { key: Stage; label: string; emoji: string }[] = [
    { key: "retrieval", label: "Retrieval", emoji: "🔍" },
    { key: "reranker", label: "Reranker", emoji: "🔀" },
    { key: "generation", label: "Generation", emoji: "✨" },
  ];

  return (
    <div className="panel" style={{ marginBottom: "1rem" }}>
      <div className="panel-header" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <h3 className="panel-title">Overall KPIs</h3>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          {STAGES.map(s => (
            <button
              key={s.key}
              type="button"
              className={`btn btn-sm ${stage === s.key ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setStage(s.key)}
            >
              {s.emoji} {s.label}
            </button>
          ))}
          <button
            type="button"
            className={`btn btn-sm ${showChart ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setShowChart(prev => !prev)}
            title="Toggle chart view"
          >
            📊 Chart
          </button>
        </div>
      </div>
      <div style={{ padding: "0.75rem 1rem" }}>
        {entries.length === 0 ? (
          <span className="muted">No metrics for {stage} yet</span>
        ) : showChart ? (
          <MetricsBarChart data={chartData} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.75rem" }}>
            {entries.map(([k, v]) => (
              <div
                key={k}
                style={{
                  background: "var(--surface-2, rgba(255,255,255,0.04))",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "0.6rem 0.9rem",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.2rem",
                }}
              >
                <span className="muted" style={{ fontSize: "0.75rem" }}>{k.replace(/^mean_/, "")}</span>
                <span className="mono" style={{ fontSize: "1.1rem", fontWeight: 700 }}>{formatMetric(v)}</span>
                <div style={{
                  height: 4,
                  borderRadius: 2,
                  background: "var(--border)",
                  marginTop: 2,
                  overflow: "hidden",
                }}>
                  <div style={{
                    height: "100%",
                    // Support signed metrics (e.g. kendall_tau, mrr_delta) without clipping to junk
                    width: `${Math.min(100, Math.abs(v) <= 1 ? Math.abs(v) * 100 : Math.min(100, Math.abs(v)))}%`,
                    background: (v >= 0.85 || (v < 0 && v > -0.15)) ? "#10b981" : Math.abs(v) >= 0.65 ? "#3b82f6" : "#ef4444",
                    borderRadius: 2,
                  }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function RubricTable({ items, status }: { items: EvalRunItemRow[], status?: string }) {
  const [rubricCategory, setRubricCategory] = useState("all");

  const categories = useMemo(() => {
    const cats = Array.from(new Set(items.map(i => i.category || "Uncategorized")));
    return ["all", ...cats.sort()];
  }, [items]);

  const filtered = rubricCategory === "all"
    ? items
    : items.filter(i => (i.category || "Uncategorized") === rubricCategory);

  const dist = useMemo(() => {
    const buckets = {
      retrieval: { excellent: 0, good: 0, poor: 0, total: 0 },
      reranker: { excellent: 0, good: 0, poor: 0, total: 0 },
      generation: { excellent: 0, good: 0, poor: 0, total: 0 },
    };

    filtered.forEach((item) => {
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
  }, [filtered]);

  const p = (qty: number, total: number) => {
    if (total === 0) return "—";
    return `${Math.round((qty / total) * 100)}%`;
  };

  if (items.length === 0) {
    return <p className="muted" style={{ padding: "1rem" }}>{status === "completed" ? "No valid metrics found." : "Run is not complete yet."}</p>;
  }

  return (
    <>
      <div style={{ padding: "0.75rem 1rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <label className="muted" style={{ fontSize: "0.85rem" }}>Filter by category:</label>
        <select
          className="input"
          style={{ width: "auto", minWidth: 180 }}
          value={rubricCategory}
          onChange={(e) => setRubricCategory(e.target.value)}
        >
          {categories.map(c => (
            <option key={c} value={c}>{c === "all" ? "All Categories" : c}</option>
          ))}
        </select>
        <span className="muted" style={{ fontSize: "0.8rem" }}>
          {filtered.length} of {items.length} items
        </span>
      </div>
      <table className="repo-table" style={{ width: "100%" }}>
        <thead>
          <tr>
            <th>Stage</th>
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
    </>
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
  const [drilldownCategory, setDrilldownCategory] = useState("all");
  const [expandedItemIds, setExpandedItemIds] = useState<Set<string>>(new Set());
  // RAG mode config
  const [ragMode, setRagMode] = useState("normal");
  const [scMaxLoops, setScMaxLoops] = useState(3);
  const [routerEnabled, setRouterEnabled] = useState(false);
  const [routerMode, setRouterMode] = useState("llm");

  function toggleItemExpanded(itemId: string) {
    setExpandedItemIds((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

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



  // All unique categories from run items (for drilldown filter)
  const drilldownCategories = useMemo(() => {
    const cats = Array.from(new Set(runItems.map(i => i.category || "Uncategorized")));
    return ["all", ...cats.sort()];
  }, [runItems]);

  const filteredRunItems = useMemo(() =>
    drilldownCategory === "all"
      ? runItems
      : runItems.filter(i => (i.category || "Uncategorized") === drilldownCategory),
    [runItems, drilldownCategory],
  );

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
        rag_mode: routerEnabled ? "normal" : ragMode,
        self_corrective_max_loops: scMaxLoops,
        router_enabled: routerEnabled,
        router_mode: routerEnabled ? routerMode : undefined,
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
    categories?: Record<string, {
      retrieval?: Record<string, number>;
      reranker?: Record<string, number>;
      generation?: Record<string, number>;
      item_count?: number;
    }>;
  };

  const categoryEntries = Object.entries(agg.categories || {});

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
              <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                Strategy
                <select
                  className="input"
                  value={routerEnabled ? "auto" : "manual"}
                  onChange={(e) => setRouterEnabled(e.target.value === "auto")}
                >
                  <option value="manual">Manual Selection</option>
                  <option value="auto">Intelligent (Auto)</option>
                </select>
              </label>
              {routerEnabled && (
                <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                  Classifier
                  <select
                    className="input"
                    value={routerMode}
                    onChange={(e) => setRouterMode(e.target.value)}
                  >
                    <option value="llm">LLM (small model)</option>
                    <option value="heuristic">Heuristic rules</option>
                  </select>
                </label>
              )}
              {!routerEnabled && (
                <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                  RAG Mode
                  <select
                    className="input"
                    value={ragMode}
                    onChange={(e) => setRagMode(e.target.value)}
                  >
                    <option value="normal">Normal</option>
                    <option value="self_corrective">Self-Corrective</option>
                  </select>
                </label>
              )}
              {(routerEnabled || ragMode === "self_corrective") && (
                <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                  Max Loops
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={5}
                    value={scMaxLoops}
                    onChange={(e) => setScMaxLoops(Math.min(5, Math.max(1, Number(e.target.value) || 1)))}
                    style={{ width: 72 }}
                  />
                </label>
              )}
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
                        {(() => {
                          const routerOn = run.config?.router_enabled;
                          const mode = run.config?.rag_mode || "normal";
                          const loops = run.config?.self_corrective_max_loops ?? 3;
                          const routeLabel = routerOn
                            ? `⚡ Auto (${(run.config?.router_mode || "llm") === "heuristic" ? "heuristic" : "LLM"})`
                            : mode === "self_corrective"
                              ? `🔄 SC (×${loops})`
                              : "🔍 Normal RAG";
                          return (
                            <>
                              {run.config?.retrieval_mode || "—"} · limit {run.config?.retrieve_limit ?? "—"} ·
                              rerank {run.config?.rerank_enabled ? "on" : "off"}
                              {run.config?.generation_model && (
                                <> · <span style={{ fontFamily: "monospace" }}>{run.config.generation_model}</span></>
                              )}
                              {" · "}{routeLabel}
                            </>
                          );
                        })()}
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
              {/* ── Overall KPIs with stage tabs + chart ────────────────── */}
              <OverallKpis agg={agg} />


              {/* ── Per-Category KPIs ───────────────────────────────────── */}
              {categoryEntries.length > 0 && (
                <div className="panel" style={{ marginBottom: "1rem" }}>
                  <div className="panel-header">
                    <h3 className="panel-title">Metrics by Category</h3>
                    <span className="muted" style={{ fontSize: "0.8rem" }}>{categoryEntries.length} categories</span>
                  </div>
                  <div style={{ padding: "0.75rem 1rem", display: "grid", gap: "1.25rem" }}>
                    {categoryEntries.map(([cat, catMetrics]) => (
                      <div key={cat}>
                        <div style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "0.5rem", display: "flex", gap: "0.5rem", alignItems: "center" }}>
                          <span
                            style={{
                              background: "var(--surface-2, rgba(255,255,255,0.06))",
                              border: "1px solid var(--border)",
                              borderRadius: 4,
                              padding: "0.1rem 0.5rem",
                              fontSize: "0.75rem",
                              fontFamily: "monospace",
                            }}
                          >
                            {cat}
                          </span>
                          <span className="muted" style={{ fontSize: "0.75rem" }}>{catMetrics.item_count ?? 0} items</span>
                        </div>
                        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                          {(catMetrics.retrieval && Object.keys(catMetrics.retrieval).length > 0) && (
                            <StageKpis title="Retrieval" metrics={catMetrics.retrieval} />
                          )}
                          {(catMetrics.reranker && Object.keys(catMetrics.reranker).length > 0) && (
                            <StageKpis title="Reranker" metrics={catMetrics.reranker} />
                          )}
                          {(catMetrics.generation && Object.keys(catMetrics.generation).length > 0) && (
                            <StageKpis title="Generation" metrics={catMetrics.generation} />
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Rubric Table ─────────────────────────────────────────── */}
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
                <>
                  {/* Category filter */}
                  <div style={{ padding: "0.75rem 1rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
                    <label className="muted" style={{ fontSize: "0.85rem" }}>Filter by category:</label>
                    <select
                      className="input"
                      style={{ width: "auto", minWidth: 200 }}
                      value={drilldownCategory}
                      onChange={(e) => setDrilldownCategory(e.target.value)}
                    >
                      {drilldownCategories.map(c => (
                        <option key={c} value={c}>{c === "all" ? "All Categories" : c}</option>
                      ))}
                    </select>
                    <span className="muted" style={{ fontSize: "0.8rem" }}>
                      {filteredRunItems.length} of {runItems.length} items
                    </span>
                  </div>
                  <div className="repo-table-wrap">
                    <table className="repo-table">
                      <thead>
                        <tr>
                          <th>Question</th>
                          <th>Category</th>
                          <th>Route</th>
                          <th>Expected sources</th>
                          <th>Retrieval</th>
                          <th>Rerank</th>
                          <th>Generation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredRunItems.map((item) => {
                          const scIters = Array.isArray(item.generation_metrics?.sc_iterations)
                            ? (item.generation_metrics.sc_iterations as Array<Record<string, any>>)
                            : [];
                          const hasLoops = scIters.length > 0;
                          const isExpanded = expandedItemIds.has(item.item_id);
                          // Parent row: final/latest metrics only (top-level payload = last CRAG loop)
                          const latestIter = hasLoops ? scIters[scIters.length - 1] : null;
                          const parentRet = item.retrieval_metrics || latestIter?.retrieval;
                          const parentRnk = item.rerank_metrics || latestIter?.rerank;
                          const parentGen = item.generation_metrics;

                          return (
                            <Fragment key={item.item_id}>
                              <tr>
                                <td>
                                  <div style={{ display: "flex", gap: "0.35rem", alignItems: "flex-start" }}>
                                    {hasLoops && (
                                      <button
                                        type="button"
                                        className="btn btn-sm btn-ghost"
                                        aria-expanded={isExpanded}
                                        title={isExpanded ? "Hide CRAG loops" : "Show CRAG loops"}
                                        onClick={() => toggleItemExpanded(item.item_id)}
                                        style={{
                                          padding: "0 0.35rem",
                                          minWidth: 28,
                                          fontSize: "0.7rem",
                                          lineHeight: 1.4,
                                          flexShrink: 0,
                                        }}
                                      >
                                        {isExpanded ? "▼" : "▶"}
                                      </button>
                                    )}
                                    <div>
                                      <div style={{ maxWidth: 260 }}>{item.question || "—"}</div>
                                      <div className="muted" style={{ fontSize: "0.75rem" }}>
                                        {item.status}
                                        {hasLoops && (
                                          <span style={{ marginLeft: "0.35rem", color: "var(--accent, #3b82f6)" }}>
                                            · {scIters.length} loop{scIters.length !== 1 ? "s" : ""}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                </td>
                                <td>
                                  {item.category ? (
                                    <span
                                      style={{
                                        background: "var(--surface-2, rgba(255,255,255,0.06))",
                                        border: "1px solid var(--border)",
                                        borderRadius: 4,
                                        padding: "0.15rem 0.45rem",
                                        fontSize: "0.72rem",
                                        fontFamily: "monospace",
                                        whiteSpace: "nowrap",
                                      }}
                                    >
                                      {item.category}
                                    </span>
                                  ) : (
                                    <span className="muted">—</span>
                                  )}
                                </td>
                                <td>
                                  {(() => {
                                    const actualRoute: string | undefined =
                                      item.generation_metrics?.route as string | undefined;
                                    const routerOn = selectedRun?.config?.router_enabled;
                                    const mode = selectedRun?.config?.rag_mode || "normal";
                                    const derivedKey = actualRoute || (routerOn ? "unknown" : mode);
                                    const routeMap: Record<string, { icon: string; label: string; bg: string }> = {
                                      greeting: { icon: "💬", label: "Greeting", bg: "rgba(59,130,246,.15)" },
                                      normal: { icon: "🔍", label: "Normal RAG", bg: "rgba(34,197,94,.15)" },
                                      simple_rag_auto: { icon: "🔍", label: "Simple RAG (Auto)", bg: "rgba(34,197,94,.15)" },
                                      self_corrective: { icon: "🔄", label: "Self-Corrective", bg: "rgba(139,92,246,.15)" },
                                      self_corrective_auto: { icon: "⚡", label: "CRAG (Auto)", bg: "rgba(245,158,11,.15)" },
                                      unknown: { icon: "⚡", label: "Intelligent (Auto)", bg: "rgba(245,158,11,.15)" },
                                    };
                                    const rt = routeMap[derivedKey] || routeMap["normal"];
                                    return (
                                      <span title={actualRoute ? `Actual route: ${actualRoute}` : "Derived from run config"} style={{
                                        fontSize: "0.72rem",
                                        background: rt.bg,
                                        borderRadius: 10,
                                        padding: "1px 7px",
                                        fontWeight: 600,
                                        whiteSpace: "nowrap",
                                        border: "1px solid rgba(255,255,255,0.08)",
                                      }}>
                                        {rt.icon} {rt.label}
                                      </span>
                                    );
                                  })()}
                                </td>
                                <td style={{ fontSize: "0.8rem" }}>
                                  {(item.expected_sources || []).map(sourceLabel).join(", ") || "—"}
                                </td>
                                <td className="mono" style={{ fontSize: "0.75rem" }}>
                                  {parentRet
                                    ? <>P {formatMetric(parentRet.precision)} · R{" "}
                                      {formatMetric(parentRet.recall)} · MRR{" "}
                                      {formatMetric(parentRet.mrr)}</>
                                    : <span className="muted">—</span>}
                                </td>
                                <td className="mono" style={{ fontSize: "0.75rem" }}>
                                  {parentRnk
                                    ? <>Δ {formatMetric(parentRnk.mrr_delta)} · NDCG{" "}
                                      {formatMetric(parentRnk.ndcg)} · τ{" "}
                                      {formatMetric(parentRnk.kendall_tau)}</>
                                    : <span className="muted">—</span>}
                                </td>
                                <td className="mono" style={{ fontSize: "0.75rem" }}>
                                  Faith {formatMetric(parentGen?.faithfulness)} · Relev{" "}
                                  {formatMetric(parentGen?.answer_relevancy)} · Acc{" "}
                                  {formatMetric(parentGen?.accuracy || parentGen?.answer_correctness)}
                                </td>
                              </tr>
                              {isExpanded && scIters.map((iter, idx) => {
                                const loop = iter.loop ?? idx + 1;
                                const rRet = iter.retrieval || {};
                                const rRnk = iter.rerank || {};
                                const rGen = iter.generation || {};
                                const isLatest = idx === scIters.length - 1;
                                return (
                                  <tr
                                    key={`${item.item_id}-loop-${loop}`}
                                    style={{ background: "var(--surface-2, rgba(255,255,255,0.02))" }}
                                  >
                                    <td colSpan={4} style={{ paddingLeft: "2.25rem", fontSize: "0.75rem" }}>
                                      <span style={{ fontWeight: 700, color: "var(--accent, #3b82f6)" }}>
                                        Loop {loop}
                                      </span>
                                      {isLatest && (
                                        <span className="muted" style={{ marginLeft: "0.4rem", fontSize: "0.68rem" }}>
                                          (latest)
                                        </span>
                                      )}
                                      {iter.query && (
                                        <div className="muted" style={{ marginTop: "0.15rem", fontSize: "0.7rem", maxWidth: 420 }}>
                                          Query: {String(iter.query)}
                                        </div>
                                      )}
                                    </td>
                                    <td className="mono" style={{ fontSize: "0.75rem" }}>
                                      {Object.keys(rRet).length > 0
                                        ? <>P {formatMetric(rRet.precision)} · R{" "}
                                          {formatMetric(rRet.recall)} · MRR{" "}
                                          {formatMetric(rRet.mrr)}</>
                                        : <span className="muted">—</span>}
                                    </td>
                                    <td className="mono" style={{ fontSize: "0.75rem" }}>
                                      {Object.keys(rRnk).length > 0
                                        ? <>Δ {formatMetric(rRnk.mrr_delta)} · NDCG{" "}
                                          {formatMetric(rRnk.ndcg)} · τ{" "}
                                          {formatMetric(rRnk.kendall_tau)}</>
                                        : <span className="muted">—</span>}
                                    </td>
                                    <td className="mono" style={{ fontSize: "0.75rem" }}>
                                      {Object.keys(rGen).length > 0
                                        ? <>Faith {formatMetric(rGen.faithfulness)} · Relev{" "}
                                          {formatMetric(rGen.answer_relevancy)} · Acc{" "}
                                          {formatMetric(rGen.accuracy ?? rGen.answer_correctness)}</>
                                        : <span className="muted">—</span>}
                                    </td>
                                  </tr>
                                );
                              })}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )
      }
    </div >
  );
}
