import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  type EvalRunItemRow,
  type EvalRunResponse,
  type RunDiagnosis,
  getEvaluationRun,
  listEvaluationRunItems,
} from "../api";
import TriadPanel, { STAGE_TONE, stageLabel } from "../components/TriadPanel";

/**
 * One evaluation run, in full.
 *
 * The summary at the top answers "is this pipeline good". The table answers "where is it
 * bad", which is the question that decides what to change. Each row carries its own three
 * triad scores and the stage those scores point at, and opens to show the passages the
 * retriever returned beside the passages the generator actually saw.
 */

const POLL_MS = 5000;

function parseRunId(pathname: string): string | null {
  const m = pathname.match(/^\/golden-evaluations\/runs\/([^/]+)/);
  return m ? m[1] : null;
}

function fmt(value: number | null | undefined, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits);
}

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function duration(from: string | null, to: string | null): string {
  if (!from) return "—";
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const s = Math.max(0, Math.round((end - start) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** A row's own reading, with the sentence that justifies it. */
function RowDiagnosis({ item }: { item: EvalRunItemRow }) {
  const stage = item.diagnosis?.stage ?? "unknown";
  const tone = STAGE_TONE[stage] ?? STAGE_TONE.unknown;
  return (
    <div style={{ display: "grid", gap: "0.35rem" }}>
      <span className="status-badge" style={{ background: `${tone}22`, color: tone, justifySelf: "start" }}>
        {stageLabel(stage)}
      </span>
      {item.diagnosis?.reason && (
        <span style={{ fontSize: "0.72rem", color: "#94a3b8", lineHeight: 1.45 }}>{item.diagnosis.reason}</span>
      )}
    </div>
  );
}

/** The three numbers on one line, coloured, so the table stays scannable. */
function MiniTriad({ item }: { item: EvalRunItemRow }) {
  const cells: Array<[string, number | null | undefined]> = [
    ["CR", item.triad?.context_relevance],
    ["GR", item.triad?.response_groundedness],
    ["AR", item.triad?.answer_relevancy],
  ];
  return (
    <div style={{ display: "flex", gap: "0.5rem" }}>
      {cells.map(([label, value]) => (
        <span key={label} title={label} style={{ fontSize: "0.72rem", color: "#94a3b8" }}>
          {label}
          <strong
            style={{
              marginLeft: 3,
              color:
                value == null ? "#64748b" : value >= 0.7 ? "#34d399" : value >= 0.5 ? "#fbbf24" : "#f87171",
            }}
          >
            {value == null ? "—" : value.toFixed(2)}
          </strong>
        </span>
      ))}
    </div>
  );
}

function ChunkList({
  title,
  chunks,
  tone,
}: {
  title: string;
  chunks: Array<Record<string, any>>;
  tone: string;
}) {
  if (!chunks.length) {
    return (
      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
        {title}: none
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: "0.4rem" }}>
      <div style={{ fontSize: "0.75rem", fontWeight: 700, color: tone }}>
        {title} ({chunks.length})
      </div>
      {chunks.slice(0, 8).map((c, i) => (
        <div
          key={i}
          style={{
            fontSize: "0.72rem",
            color: "#cbd5e1",
            lineHeight: 1.5,
            background: "rgba(15,23,42,0.55)",
            border: "1px solid rgba(148,163,184,0.14)",
            borderRadius: 6,
            padding: "0.45rem 0.6rem",
          }}
        >
          <div style={{ color: "#64748b", marginBottom: 3 }}>
            {String(c.file_name ?? c.source_id ?? "chunk")}
            {c.page_index != null ? ` · page ${Number(c.page_index) + 1}` : ""}
            {c.rerank_score != null ? ` · score ${Number(c.rerank_score).toFixed(3)}` : ""}
          </div>
          {String(c.content ?? c.text ?? "").slice(0, 320) || "(no text)"}
        </div>
      ))}
      {chunks.length > 8 && (
        <div style={{ fontSize: "0.7rem", color: "#64748b" }}>and {chunks.length - 8} more</div>
      )}
    </div>
  );
}

export default function EvalRunDetailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const runId = parseRunId(location.pathname);

  const [run, setRun] = useState<EvalRunResponse | null>(null);
  const [items, setItems] = useState<EvalRunItemRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [openItems, setOpenItems] = useState<Set<string>>(new Set());
  const [onlyProblems, setOnlyProblems] = useState(false);

  const load = useCallback(async (id: string) => {
    const [r, rows] = await Promise.all([getEvaluationRun(id), listEvaluationRunItems(id)]);
    setRun(r);
    setItems(rows);
  }, []);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        await load(runId);
        if (!cancelled) setError(null);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Could not read this run.");
      }
    };
    void tick();
    return () => {
      cancelled = true;
    };
  }, [runId, load]);

  // A running evaluation is worth watching, so the page follows it. The worker writes one
  // row at a time, so a poll picks up each finished row within the interval.
  const active = run?.status === "running" || run?.status === "queued";
  useEffect(() => {
    if (!runId || !active) return;
    const timer = setInterval(() => {
      void load(runId).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [runId, active, load]);

  const diagnosis = useMemo<RunDiagnosis | null>(() => {
    const d = run?.diagnosis as RunDiagnosis | undefined;
    return d && "stage_counts" in d ? d : null;
  }, [run]);

  const shown = useMemo(() => {
    if (!onlyProblems) return items;
    return items.filter((i) => (i.diagnosis?.stage ?? "unknown") !== "healthy");
  }, [items, onlyProblems]);

  if (!runId) {
    return <div className="alert alert-error">No run id in the address.</div>;
  }

  const toggle = (id: string) =>
    setOpenItems((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div style={{ display: "grid", gap: "1rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate("/golden-evaluations")}>
          ← Offline Evaluation
        </button>
        <h2 style={{ margin: 0, fontSize: "1.15rem" }}>
          Evaluation run {runId.slice(0, 8)}
        </h2>
        {run && (
          <span
            className="status-badge"
            style={{
              background: active ? "rgba(56,189,248,0.15)" : "rgba(52,211,153,0.15)",
              color: active ? "#38bdf8" : "#34d399",
            }}
          >
            {run.status}
          </span>
        )}
        {active && <span className="muted" style={{ fontSize: "0.75rem" }}>refreshing every 5s</span>}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {run && (
        <div className="panel" style={{ padding: "0.9rem 1.1rem", display: "grid", gap: "0.6rem" }}>
          <div
            style={{
              display: "grid",
              gap: "0.75rem",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            }}
          >
            <Stat label="Rows done" value={`${run.progress.items_completed} / ${run.progress.items_total}`} />
            <Stat label="Failed" value={String(run.progress.items_failed)} />
            <Stat label="Elapsed" value={duration(run.started_at, run.completed_at)} />
            <Stat label="Pipeline" value={String(run.config?.rag_strategy ?? "—")} />
            <Stat label="Retrieval" value={String(run.config?.retrieval_mode ?? "—")} />
            <Stat label="Rerank" value={run.config?.rerank_enabled ? "on" : "off"} />
            <Stat label="Chat model" value={String(run.config?.generation_model ?? "—")} />
            <Stat label="Judge" value={String(run.config?.judge_model ?? "service default")} />
            <Stat label="Started" value={when(run.started_at)} />
          </div>
          <div style={{ fontSize: "0.72rem", color: "#64748b" }}>
            reads {String(run.config?.collection ?? "the service default collection")}
            {run.config?.embedding_model ? ` · embedding ${run.config.embedding_model}` : ""}
          </div>
        </div>
      )}

      {run?.error_message && <div className="alert alert-warn">{run.error_message}</div>}

      {run && <TriadPanel triad={diagnosis?.triad ?? {}} diagnosis={diagnosis} />}

      <div className="panel">
        <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
          <span className="panel-title">Rows ({shown.length}{onlyProblems ? ` of ${items.length}` : ""})</span>
          <label className="muted" style={{ fontSize: "0.75rem", display: "flex", gap: "0.35rem", alignItems: "center" }}>
            <input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
            only rows with a problem
          </label>
        </div>

        {!shown.length && (
          <div className="panel-empty">
            {items.length ? "Every scored row passed." : active ? "Waiting for the first row." : "No rows."}
          </div>
        )}

        {shown.map((item) => {
          const open = openItems.has(item.item_id);
          const stage = item.diagnosis?.stage ?? "unknown";
          return (
            <div key={item.item_id} style={{ borderTop: "1px solid rgba(148,163,184,0.12)", padding: "0.7rem 0.9rem" }}>
              <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start" }}>
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ flexShrink: 0, minWidth: 30 }}
                  onClick={() => toggle(item.item_id)}
                  aria-expanded={open}
                >
                  {open ? "−" : "+"}
                </button>
                <div style={{ flex: 1, display: "grid", gap: "0.35rem", minWidth: 0 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
                    <span style={{ fontSize: "0.85rem", color: "#e2e8f0" }}>{item.question ?? "(no question)"}</span>
                    <MiniTriad item={item} />
                  </div>
                  <div style={{ display: "flex", gap: "1rem", alignItems: "baseline", flexWrap: "wrap" }}>
                    <RowDiagnosis item={item} />
                    {item.category && (
                      <span style={{ fontSize: "0.7rem", color: "#64748b" }}>type: {item.category}</span>
                    )}
                    {item.status !== "completed" && (
                      <span style={{ fontSize: "0.7rem", color: "#f87171" }}>{item.status}</span>
                    )}
                  </div>
                  {item.error_message && (
                    <span style={{ fontSize: "0.72rem", color: "#f87171" }}>{item.error_message}</span>
                  )}

                  {open && (
                    <div style={{ display: "grid", gap: "0.6rem", marginTop: "0.5rem" }}>
                      <div>
                        <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#94a3b8", marginBottom: 3 }}>
                          Answer
                        </div>
                        <div style={{ fontSize: "0.78rem", color: "#cbd5e1", lineHeight: 1.55 }}>
                          {item.generated_answer || "(empty)"}
                        </div>
                      </div>
                      {item.ground_truth_answer && (
                        <div>
                          <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#94a3b8", marginBottom: 3 }}>
                            Expected
                          </div>
                          <div style={{ fontSize: "0.78rem", color: "#cbd5e1", lineHeight: 1.55 }}>
                            {item.ground_truth_answer}
                          </div>
                        </div>
                      )}
                      <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
                        <ChunkList title="Retrieved" chunks={item.retrieved_chunks ?? []} tone="#38bdf8" />
                        <ChunkList title="After rerank (what the model read)" chunks={item.reranked_chunks ?? []} tone="#a78bfa" />
                      </div>
                      <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap", fontSize: "0.7rem", color: "#64748b" }}>
                        <span>
                          retrieval mrr {fmt(item.retrieval_metrics?.mrr)} · recall {fmt(item.retrieval_metrics?.recall)}
                        </span>
                        <span>
                          rerank mrr {fmt(item.rerank_metrics?.mrr_after)} · delta {fmt(item.rerank_metrics?.mrr_delta)}
                        </span>
                        <span>stage: {stageLabel(stage)}</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "grid", gap: "0.15rem" }}>
      <span style={{ fontSize: "0.68rem", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </span>
      <span style={{ fontSize: "0.85rem", color: "#e2e8f0", fontWeight: 600 }}>{value}</span>
    </div>
  );
}
