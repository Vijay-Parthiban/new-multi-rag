import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import PageHeader from "../components/PageHeader";
import TriadPanel from "../components/TriadPanel";
import {
  createEvaluationRun,
  DatasetKind,
  DatasetProfile,
  DatasetProfileFile,
  destinationStoreLabel,
  EvalPipelineDefaults,
  EvalRunItemRow,
  EvalRunResponse,
  GuardrailsConfig,
  RunDiagnosis,
  getEvalPipelineDefaults,
  getEvaluationRun,
  getAssistant,
  getLiteLLMModels,
  listDatasetProfiles,
  listDatasetRuns,
  listEvaluationRunItems,
  listGuardrailsConfigs,
  listPipelines,
  listPromptTemplates,
  PipelineRecord,
  PromptTemplate,
} from "../api";
import { formatRelativeTime } from "../utils/format";

const PAGE_SIZE = 10;

// The strategies this page can score. Retrieval-to-generation metrics read text passages;
// the page-image strategy answers from page images, so it has nothing for them to read. The
// route refuses it as well, so this is the copy and the frozen button, not the only gate.
const EVALUABLE_STRATEGIES: readonly string[] = ["vector", "lexical", "hybrid", "self_rag", "corrective"];

// Named once, so the check and the message can never disagree about which strategy it is.
const VISION_STRATEGY = "image_vision";

const VISION_BLOCK_MESSAGE =
  "Image Vision RAG cannot be evaluated offline. Retrieval-to-generation scoring reads text passages, and this pipeline answers from page images. Pick a vector, keyword, hybrid, self-reflective or corrective pipeline.";

// The two radios the page offers. A kind the selected profile does not hold is frozen,
// not hidden, so the page says which dataset is missing.
const KIND_LABEL: Record<DatasetKind, string> = {
  single_turn: "Only Single turn",
  multi_turn: "Only Multi-Turn",
};

const MEMORY_BLOCK_MESSAGE =
  "This dataset holds multi-turn conversations, and the selected pipeline has no session memory. Enable a Redis destination on its Knowledge Product, or pick a single-turn dataset.";

function formatMetric(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toFixed(3);
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

/** The stores a pipeline reads: one name per destination, or null when it has none. */
interface PipelineStores {
  collection: string | null;
  embedding: string | null;
  sparse: string | null;
  opensearch: string | null;
  pgSchema: string | null;
  pgTable: string | null;
}

/**
 * The stores a pipeline's own turns read.
 *
 * A Knowledge-Product-backed pipeline leaves `qdrant_collection` and `embedding_model` empty,
 * because its stores live on the product's destinations, one per destination type. Reading the
 * legacy field would evaluate the service default collection instead of the pipeline's own,
 * which retrieves nothing and scores zero for a reason that has nothing to do with the pipeline.
 */
function pipelineStores(pipeline: PipelineRecord | null): PipelineStores {
  const product = pipeline?.knowledge_product;
  if (!product) {
    return {
      collection: pipeline?.qdrant_collection ?? null,
      embedding: pipeline?.embedding_model ?? null,
      sparse: pipeline?.sparse_embedding_model ?? null,
      opensearch: null as string | null,
      pgSchema: null as string | null,
      pgTable: null as string | null,
    };
  }
  const enabled = (destinationType: string) =>
    (product.destinations ?? []).find(
      (d) => d.destination_type === destinationType && d.enabled,
    );
  const name = (destinationType: string) => {
    const found = enabled(destinationType);
    return found ? destinationStoreLabel(found) : null;
  };
  const relational = enabled("relational_pgvector");
  // The vector collection and the search index are stores; the sparse field is a model.
  return {
    collection: name("vector_qdrant"),
    embedding: product.text_embedding_model ?? null,
    sparse: product.sparse_embedding_model ?? null,
    opensearch: name("lexical_opensearch"),
    pgSchema: name("relational_pgvector"),
    pgTable: relational ? ((relational.config?.table_name as string) ?? null) : null,
  };
}

/**
 * The pipeline under test, stated rather than offered.
 *
 * A run measures this pipeline as it stands, so the page shows its configuration and
 * gives no control over the retrieval settings. One line states what the run will
 * read: the pipeline's own settings, which the run carries, with the deployment's
 * values filling any gap the record leaves.
 */
function PipelineSummary({
  pipeline,
  stores,
  defaults,
  templates,
  guardrails,
  memoryEnabled,
  memoryTtl,
  memoryReason,
}: {
  pipeline: PipelineRecord;
  stores: PipelineStores;
  defaults: EvalPipelineDefaults | null;
  templates: PromptTemplate[];
  guardrails: GuardrailsConfig[];
  memoryEnabled: boolean | null;
  memoryTtl: number | null;
  memoryReason: string | null;
}) {
  const product = pipeline.knowledge_product;
  const model = pipeline.model_settings;
  const templateName = pipeline.prompt_template_id
    ? templates.find((t) => t.id === pipeline.prompt_template_id)?.name || "set (name unavailable)"
    : "service default";
  const guardrailsName = pipeline.guardrails_config_id
    ? guardrails.find((g) => g.id === pipeline.guardrails_config_id)?.name ||
      "set (name unavailable)"
    : "none";
  const sampling = [
    model?.temperature != null ? `temperature ${model.temperature}` : null,
    model?.top_p != null ? `top_p ${model.top_p}` : null,
    model?.max_tokens != null ? `max_tokens ${model.max_tokens}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const rows: [string, string][] = [
    ["Strategy", pipeline.rag_strategy],
    ["Chat model", pipeline.chat_model || "service default"],
    ["Sampling", sampling || "service default"],
    ["Prompt template", templateName],
    ["Guardrails", guardrailsName],
    ["Knowledge product", product?.name || "none"],
    ["Modality", pipeline.modality || "text"],
    [
      // Stated before a dataset is picked, because it is what decides whether a multi-turn
      // dataset can run at all.
      "Memory",
      memoryEnabled
        ? `enabled · ${memoryTtl ?? "—"} s TTL`
        : `none · ${memoryReason ?? "the Knowledge Product has no enabled Redis destination"}`,
    ],
    [
      "Chunking",
      `${product?.chunk_strategy || "—"} · ${pipeline.chunk_size} size / ${pipeline.chunk_overlap} overlap`,
    ],
    [
      // The pipeline's own settings, because the run carries them. The deployment fills
      // a gap only where the record has none to give, which is what a pipeline written
      // before those columns existed looks like.
      "Retrieval",
      `${defaults?.retrieval_mode ?? "dense"} · ${
        pipeline.retrieve_limit ?? defaults?.retrieve_limit ?? "—"
      } chunks read · ${
        pipeline.rerank_enabled ?? defaults?.rerank_enabled ?? true
          ? `rerank on (${pipeline.rerank_model ?? defaults?.rerank_model ?? "default"}), top ${
              pipeline.rerank_top_k ?? defaults?.top_k ?? "—"
            } reach the prompt`
          : "rerank off, all of them reach the prompt"
      }`,
    ],
    ["Dense store", stores.collection || "service default collection"],
    ["Embedding model", stores.embedding || "service default"],
    [
      "Lexical store",
      stores.opensearch
        ? `${stores.opensearch}${stores.sparse ? ` · sparse ${stores.sparse}` : ""}`
        : "none",
    ],
    [
      "Relational store",
      stores.pgSchema && stores.pgTable ? `${stores.pgSchema}.${stores.pgTable}` : "none",
    ],
  ];

  return (
    <div
      className="muted"
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr",
        gap: "0.3rem 0.9rem",
        fontSize: "0.8rem",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 6,
        padding: "0.7rem 0.8rem",
      }}
    >
      <div style={{ gridColumn: "1 / -1" }}>
        <strong>{pipeline.name}</strong>
        {pipeline.description ? <span> · {pipeline.description}</span> : null}
      </div>
      {rows.map(([label, value]) => (
        <Fragment key={label}>
          <span>{label}</span>
          <span className="mono">{value}</span>
        </Fragment>
      ))}
    </div>
  );
}

export default function GoldenEvaluationsPage() {
  // Only the profiles linked to the selected pipeline appear here. A profile with no
  // pipeline is authored in Dataset Fabric and is not runnable from this page.
  const [profiles, setProfiles] = useState<DatasetProfile[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [kind, setKind] = useState<DatasetKind>("single_turn");
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [pipelineId, setPipelineId] = useState("");
  // The retrieval settings a run uses. They come from the deployment, not from this
  // page: a run measures the selected pipeline as it stands, so the page shows them
  // and offers no control over them.
  const [pipelineDefaults, setPipelineDefaults] = useState<EvalPipelineDefaults | null>(null);
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [guardrails, setGuardrails] = useState<GuardrailsConfig[]>([]);
  const [runs, setRuns] = useState<EvalRunResponse[]>([]);
  const [runsCount, setRunsCount] = useState(0);
  const [page, setPage] = useState(0);
  const [selectedRun, setSelectedRun] = useState<EvalRunResponse | null>(null);

  const navigate = useNavigate();

  // The backend reads the stage breakdown from the stored row metrics when it builds the run
  // response, so this follows the current attribution rules rather than a value frozen at
  // write time. Empty until at least one row scores.
  const runDiagnosis = useMemo<RunDiagnosis | null>(() => {
    const d = selectedRun?.diagnosis as RunDiagnosis | undefined;
    return d && "stage_counts" in d ? d : null;
  }, [selectedRun]);
  const [runItems, setRunItems] = useState<EvalRunItemRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // How many rows of the evaluation set to run, and whether the built-in set is being fetched.
  const [rowsToTest, setRowsToTest] = useState(5);
  // Empty means the service default judge. The dropdown still offers "Service default" so
  // the choice is visible rather than implicit.
  const [judgeModel, setJudgeModel] = useState("");
  const [judgeModels, setJudgeModels] = useState<{ id: string; label: string }[]>([]);
  // Whether the selected pipeline's Knowledge Product has session memory, and why not. Null
  // while the answer is unknown, which is not the same as a definite "none".
  const [memoryEnabled, setMemoryEnabled] = useState<boolean | null>(null);
  const [memoryTtl, setMemoryTtl] = useState<number | null>(null);
  const [memoryReason, setMemoryReason] = useState<string | null>(null);

  const selectedPipeline = useMemo(
    () => pipelines.find((p) => p.id === pipelineId) || null,
    [pipelines, pipelineId],
  );

  // What the selected pipeline actually reads, and how large the selected set is.
  const stores = useMemo(() => pipelineStores(selectedPipeline), [selectedPipeline]);
  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === profileId) ?? null,
    [profiles, profileId],
  );

  // The newest upload of each kind. The API returns them newest first, so the first match
  // is the dataset a run uses.
  const datasetsByKind = useMemo(() => {
    const map: Record<DatasetKind, DatasetProfileFile[]> = { single_turn: [], multi_turn: [] };
    for (const file of selectedProfile?.datasets ?? []) {
      (map[file.kind] ?? map.single_turn).push(file);
    }
    return map;
  }, [selectedProfile]);

  const chosenDataset = datasetsByKind[kind][0] ?? null;
  const selectedDatasetId = chosenDataset?.dataset_id ?? null;
  const selectedDatasetCount = chosenDataset?.row_count ?? 0;

  // A run cannot sample more rows than the chosen upload holds. Clamping here keeps the
  // input, the copy and the button label on the number the worker will actually run.
  useEffect(() => {
    if (selectedDatasetCount > 0) {
      setRowsToTest((current) => Math.min(current, selectedDatasetCount));
    }
  }, [selectedDatasetCount]);

  // A multi-turn run drives the pipeline's session memory, so the page has to know whether
  // the selected pipeline has one. Only an assistant pipeline can: the memory lives on its
  // Knowledge Product's Redis destination, and no other pipeline reads a product at all.
  useEffect(() => {
    let cancelled = false;
    const slug = selectedPipeline?.slug;
    if (!selectedPipeline?.is_assistant || !slug) {
      setMemoryEnabled(false);
      setMemoryTtl(null);
      setMemoryReason("This pipeline is not an assistant pipeline, so it has no session memory.");
      return;
    }
    void getAssistant(slug)
      .then((config) => {
        if (cancelled) return;
        setMemoryEnabled(config.session_memory?.enabled ?? false);
        setMemoryTtl(config.session_memory?.ttl_seconds ?? null);
        setMemoryReason(config.session_memory?.reason ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        // An unreachable probe must not block a single-turn run, so it reads as "no memory".
        setMemoryEnabled(false);
        setMemoryTtl(null);
        setMemoryReason("Could not read this pipeline's session memory setting.");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPipeline]);

  // The two reasons a run is refused, each computed before the button is pressed.
  const strategy = selectedPipeline?.rag_strategy ?? "";
  const strategyBlocked = Boolean(selectedPipeline) && !EVALUABLE_STRATEGIES.includes(strategy);
  const datasetBlocked = kind === "multi_turn" && memoryEnabled === false;
  const blockMessage = strategyBlocked
    ? strategy === VISION_STRATEGY
      ? VISION_BLOCK_MESSAGE
      : `This page cannot evaluate the '${strategy}' strategy. Pick a vector, keyword, hybrid, self-reflective or corrective pipeline.`
    : datasetBlocked
      ? MEMORY_BLOCK_MESSAGE
      : null;

  const loadProfiles = useCallback(async (slug: string | null) => {
    if (!slug) {
      setProfiles([]);
      setProfileId(null);
      return;
    }
    const items = await listDatasetProfiles(slug);
    setProfiles(items);
    setProfileId((prev) => {
      if (prev && items.some((p) => p.id === prev)) return prev;
      return items[0]?.id ?? null;
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
    setError(null);
    try {
      const pipes = await listPipelines();
      setPipelines(pipes);
      setPipelineId((prev) => prev || pipes[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load golden evaluations");
    } finally {
    }
  }, []);

  // A run reads a profile, and a profile is linked to one pipeline. So the list follows the
  // selected pipeline, and a profile with no pipeline never appears.
  useEffect(() => {
    void loadProfiles(selectedPipeline?.slug ?? null).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load dataset profiles"),
    );
  }, [selectedPipeline?.slug, loadProfiles]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The judge list comes from the same proxy catalog the Pipelines page uses. A failure here
  // leaves the list empty, which means every run uses the service default rather than failing.
  useEffect(() => {
    let cancelled = false;
    void getLiteLLMModels("chat")
      .then((models) => {
        if (!cancelled) setJudgeModels(models);
      })
      .catch(() => {
        if (!cancelled) setJudgeModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // What a run will use, and the names of the prompt template and guardrails config the
  // selected pipeline points at. A failure here costs the detail line and the two names, and
  // must not stop a run, so every call is caught on its own.
  useEffect(() => {
    let cancelled = false;
    void getEvalPipelineDefaults()
      .then((defaults) => {
        if (!cancelled) setPipelineDefaults(defaults);
      })
      .catch(() => {
        if (!cancelled) setPipelineDefaults(null);
      });
    void listPromptTemplates()
      .then((res) => {
        if (!cancelled) setTemplates(res.items || []);
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      });
    void listGuardrailsConfigs()
      .then((res) => {
        if (!cancelled) setGuardrails(res.items || []);
      })
      .catch(() => {
        if (!cancelled) setGuardrails([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  // The id, not the run object. The tick is what replaces the object, so depending on the
  // object would tear the interval down and rebuild it on every tick, and a slow reply could
  // land after the user picked another run and put the old one back.
  const activeRunId =
    selectedRun && selectedRun.status !== "completed" && selectedRun.status !== "failed"
      ? selectedRun.run_id
      : null;

  // Follow a run while it works. The worker writes one row at a time and the run response
  // carries a stage breakdown read from those rows, so refreshing both here is what makes
  // the triad fill in as the run progresses rather than only at the end.
  useEffect(() => {
    if (!activeRunId) return;
    const id = window.setInterval(async () => {
      try {
        const updated = await getEvaluationRun(activeRunId);
        setSelectedRun(updated);
        if (selectedDatasetId) await loadRuns(selectedDatasetId, page);
        const items = await listEvaluationRunItems(updated.run_id);
        setRunItems(items);
      } catch {
        /* ignore transient poll errors */
      }
    }, 2500);
    return () => window.clearInterval(id);
  }, [activeRunId, selectedDatasetId, page, loadRuns]);

  const totalPages = Math.max(1, Math.ceil(runsCount / PAGE_SIZE));



  async function onStartRun() {
    if (!selectedDatasetId || !selectedPipeline) {
      setError("Select a dataset and pipeline first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // The run carries the pipeline's own stores and retrieval settings, so the
      // evaluation measures that pipeline rather than whatever the service defaults to.
      // The strategy and the store names travel together: the evaluator reads the
      // knowledge-product stores only when both are present.
      //
      // The pipeline's retrieval settings travel the same way — how many chunks the
      // search returns, whether a reranker reorders them, and how many survive it. The
      // route keeps its own deployment fallback for a caller that sends none, which is
      // what a pipeline record written before those columns existed produces.
      const stores = pipelineStores(selectedPipeline);
      const created = await createEvaluationRun(selectedDatasetId, {
        rag_strategy: selectedPipeline.rag_strategy,
        retrieve_limit: selectedPipeline.retrieve_limit,
        rerank_enabled: selectedPipeline.rerank_enabled,
        top_k: selectedPipeline.rerank_top_k,
        // The reranker the pipeline pinned, when it pinned one. Null leaves the
        // route to resolve the deployment's model.
        rerank_model: selectedPipeline.rerank_model,
        // The pipeline's own chat model. Without it the service default applies, and the
        // service default is a model the proxy does not serve.
        generation_model: selectedPipeline.chat_model,
        // The slug, not the store names: the route resolves the pipeline's session memory
        // from it, so a multi-turn run drives the memory a live turn would drive. The Redis
        // namespace never leaves the server.
        pipeline_slug: selectedPipeline.slug,
        collection: stores.collection,
        embedding_model: stores.embedding,
        sparse_embedding_model: stores.sparse,
        opensearch_index: stores.opensearch,
        pg_schema: stores.pgSchema,
        pg_table: stores.pgTable,
        // A random sample, so a run stays cheap. No seed, so each run draws a fresh one.
        sample_size: rowsToTest,
        // Empty means the service default judge.
        judge_model: judgeModel || null,
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
        title="Offline Evaluation"
        description="Pick a pipeline configuration, run a random sample of the evaluation set through it, and read the retrieval, rerank and generation scores."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Offline Evaluation" },
        ]}
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              // The pipeline list and the profiles both change outside this page, so one
              // click has to reload both or a profile made in Dataset Fabric never appears.
              void refresh();
              void loadProfiles(selectedPipeline?.slug ?? null);
            }}
            disabled={busy}
          >
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
          <div className="panel-header" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
            <h3 className="panel-title">Dataset profile</h3>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => navigate("/dataset-fabric")}
            >
              Manage in Dataset Fabric
            </button>
          </div>
          <div style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
            {profiles.length === 0 ? (
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem", lineHeight: 1.5 }}>
                {selectedPipeline?.slug
                  ? "No dataset profile is linked to this pipeline. Create one in Dataset Fabric and link it to this pipeline."
                  : "Select a pipeline to see the dataset profiles linked to it."}
              </p>
            ) : (
              <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
                Dataset profile
                <select
                  className="input"
                  value={profileId ?? ""}
                  onChange={(e) => setProfileId(e.target.value)}
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {selectedProfile?.description && (
              <p className="muted" style={{ margin: 0, fontSize: "0.78rem", lineHeight: 1.5 }}>
                {selectedProfile.description}
              </p>
            )}

            <div style={{ display: "grid", gap: "0.5rem" }}>
              {(Object.keys(KIND_LABEL) as DatasetKind[]).map((option) => {
                const files = datasetsByKind[option];
                const available = files.length > 0;
                const checked = kind === option && available;
                return (
                  <label
                    key={option}
                    style={{
                      display: "flex",
                      gap: "0.5rem",
                      alignItems: "flex-start",
                      padding: "0.5rem 0.6rem",
                      borderRadius: 6,
                      border: `1px solid ${checked ? "var(--accent, #6366f1)" : "var(--border)"}`,
                      opacity: available ? 1 : 0.5,
                      cursor: available ? "pointer" : "not-allowed",
                    }}
                  >
                    <input
                      type="radio"
                      name="dataset-kind"
                      value={option}
                      checked={checked}
                      disabled={!available || !selectedProfile}
                      onChange={() => setKind(option)}
                      style={{ marginTop: 2 }}
                    />
                    <span style={{ display: "grid", gap: "0.1rem" }}>
                      <span style={{ fontSize: "0.85rem" }}>{KIND_LABEL[option]}</span>
                      <span className="muted" style={{ fontSize: "0.72rem" }}>
                        {available
                          ? `${files[0].row_count ?? "?"} ${
                              files[0].row_count === 1 ? "row" : "rows"
                            } · ${files[0].filename ?? "dataset"}`
                          : "Not uploaded for this profile"}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3 className="panel-title">Run</h3>
          </div>
          <div style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
            <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
              Pipeline configuration
              <select
                className="input"
                value={pipelineId}
                onChange={(e) => setPipelineId(e.target.value)}
              >
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.rag_strategy}
                    {p.knowledge_product ? ` · ${p.knowledge_product.name}` : ""}
                  </option>
                ))}
              </select>
            </label>
            {selectedPipeline && (
              <PipelineSummary
                pipeline={selectedPipeline}
                stores={stores}
                defaults={pipelineDefaults}
                templates={templates}
                guardrails={guardrails}
                memoryEnabled={memoryEnabled}
                memoryTtl={memoryTtl}
                memoryReason={memoryReason}
              />
            )}
            <label className="muted" style={{ display: "grid", gap: "0.25rem" }}>
              Rows to test
              <input
                className="input"
                type="number"
                min={1}
                max={selectedDatasetCount > 0 ? selectedDatasetCount : 200}
                value={rowsToTest}
                onChange={(e) => setRowsToTest(Math.max(1, Number(e.target.value) || 1))}
                style={{ width: 110 }}
              />
            </label>
            <p className="muted" style={{ fontSize: "0.75rem", margin: 0 }}>
              {rowsToTest} of {selectedDatasetCount} rows, chosen at random on every run. Each row
              costs one retrieval, one generation and one scoring pass.
            </p>
            {/* The retrieval settings are not controls. A run measures the pipeline above as it
                stands, so the route resolves the mode, the chunk limit, the rerank switch and
                top-k from the deployment, and the summary above states them. The evaluator runs
                through RAGPipeline.chat, which is the path a live turn takes, so the
                self-reflective and corrective branches are scored rather than skipped. */}
            <label className="muted" style={{ display: "grid", gap: "0.25rem", maxWidth: 320 }}>
              LLM-as-a-judge (optional)
              <select
                className="input"
                value={judgeModel}
                onChange={(e) => setJudgeModel(e.target.value)}
              >
                <option value="">Service default</option>
                {judgeModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted" style={{ fontSize: "0.75rem", margin: 0 }}>
              The model that grades faithfulness, answer relevancy, correctness and the
              retrieval scores. A stronger judge is slower and costs more; the same judge across
              two runs is what makes their scores comparable.
            </p>
            {blockMessage && (
              <div className="alert alert-warn" style={{ fontSize: "0.8rem", margin: 0 }}>
                {blockMessage}
              </div>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !selectedDatasetId || !pipelineId || strategyBlocked || datasetBlocked}
              onClick={() => void onStartRun()}
            >
              {busy ? "Running…" : `Run evaluation on ${rowsToTest} row${rowsToTest === 1 ? "" : "s"}`}
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
          {/* The triad leads. It is the part that names a stage, so everything below it
              is the evidence for that reading rather than the headline. */}
          <div style={{ marginBottom: "1rem" }}>
            <TriadPanel triad={runDiagnosis?.triad ?? {}} diagnosis={runDiagnosis} />
          </div>

          <div
            style={{
              display: "flex",
              gap: "0.75rem",
              alignItems: "center",
              marginBottom: "1rem",
              flexWrap: "wrap",
            }}
          >
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => navigate(`/golden-evaluations/runs/${selectedRun.run_id}`)}
            >
              Open full run details
            </button>
            <span className="muted" style={{ fontSize: "0.78rem" }}>
              Per-question triad, the passages the model actually read, and the stage each row
              points at.
            </span>
          </div>

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
      )
      }
    </div >
  );
}
