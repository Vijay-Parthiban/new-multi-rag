import { Fragment, useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { getChatStats, RAGChatStatItem } from "../api";
import { formatRelativeTime } from "../utils/format";

/** Full Langfuse traces URL, e.g. https://cloud.langfuse.com/project/<id>/traces */
const LANGFUSE_TRACES_URL =
    import.meta.env.VITE_LANGFUSE_TRACES_URL ?? "https://cloud.langfuse.com";

type ViewMode = "latency" | "metrics";

interface IterationMetric {
    loop?: number;
    query?: string;
    retrieval?: Record<string, number | null>;
    reranker?: Record<string, number | null>;
    rerank?: Record<string, number | null>;
    generation?: Record<string, number | null>;
}

function fmt(v: number | null | undefined, pct = false) {
    if (v == null || typeof v !== "number" || Number.isNaN(v)) return "—";
    return pct ? `${(v * 100).toFixed(0)}%` : v.toFixed(3);
}

function ScoreBar({ value }: { value: number | null | undefined }) {
    const v = typeof value === "number" && !Number.isNaN(value) ? value : null;
    if (v == null) return null;
    const colour = v >= 0.85 ? "#10b981" : v >= 0.65 ? "#3b82f6" : "#ef4444";
    return (
        <div style={{ height: 3, borderRadius: 2, background: "var(--border)", marginTop: 2, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${Math.min(100, v * 100)}%`, background: colour, borderRadius: 2 }} />
        </div>
    );
}

function RetrievalCell({
    precision,
    recall,
}: {
    precision?: number | null;
    recall?: number | null;
}) {
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
            <span className="muted" style={{ fontSize: "0.75rem" }}>
                Recall: <span className="mono">{fmt(recall, true)}</span>
            </span>
            <ScoreBar value={recall} />
            <span className="muted" style={{ fontSize: "0.75rem" }}>
                Precision: <span className="mono">{fmt(precision, true)}</span>
            </span>
            <ScoreBar value={precision} />
        </div>
    );
}

function RerankerCell({
    mrr,
    ndcg,
    tau,
}: {
    mrr?: number | null;
    ndcg?: number | null;
    tau?: number | null;
}) {
    const hasAny = mrr != null || ndcg != null || tau != null;
    if (!hasAny) return <span className="muted">—</span>;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
            <span className="muted" style={{ fontSize: "0.75rem" }}>MRR: <span className="mono">{fmt(mrr)}</span></span>
            <span className="muted" style={{ fontSize: "0.75rem" }}>NDCG: <span className="mono">{fmt(ndcg)}</span></span>
            <span className="muted" style={{ fontSize: "0.75rem" }}>Tau: <span className="mono">{fmt(tau)}</span></span>
        </div>
    );
}

function GenerationCell({
    faithfulness,
    relevancy,
}: {
    faithfulness?: number | null;
    relevancy?: number | null;
}) {
    const hasAny = faithfulness != null || relevancy != null;
    if (!hasAny) return <span className="muted">—</span>;
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
            <span className="muted" style={{ fontSize: "0.75rem" }}>Faithful: <span className="mono">{fmt(faithfulness, true)}</span></span>
            <ScoreBar value={faithfulness} />
            <span className="muted" style={{ fontSize: "0.75rem" }}>Relevant: <span className="mono">{fmt(relevancy, true)}</span></span>
            <ScoreBar value={relevancy} />
        </div>
    );
}

export default function EvaluationsPage() {
    const [viewMode, setViewMode] = useState<ViewMode>("latency");
    const [limit, setLimit] = useState(20);
    const [items, setItems] = useState<RAGChatStatItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

    const [currentPage, setCurrentPage] = useState(1);
    const ITEMS_PER_PAGE = 10;

    const loadStats = useCallback(async () => {
        setLoading(true);
        try {
            const res = await getChatStats(limit);
            setItems(res.items || []);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load evaluation stats");
        } finally {
            setLoading(false);
        }
    }, [limit]);

    useEffect(() => { setCurrentPage(1); }, [limit]);
    useEffect(() => { loadStats(); }, [loadStats]);

    const formatLatency = (ms: number | undefined) => {
        if (ms === undefined) return "—";
        return `${ms.toFixed(0)} ms`;
    };

    const paginated = items.slice((currentPage - 1) * ITEMS_PER_PAGE, currentPage * ITEMS_PER_PAGE);

    function toggleExpanded(id: string) {
        setExpandedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    return (
        <div className="page">
            <PageHeader
                title="Real Time Monitoring"
                description="Monitor LLM response quality metrics across chats and pipeline configurations."
                breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Real Time Monitoring" }]}
                actions={
                    <>
                        <a
                            className="btn btn-sm btn-secondary"
                            href={LANGFUSE_TRACES_URL}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Open Langfuse traces"
                        >
                            Open Langfuse
                        </a>
                        <button type="button" className="btn btn-secondary" onClick={loadStats}>
                            Refresh
                        </button>
                    </>
                }
            />

            <div className="panel">
                <div className="panel-toolbar" style={{ display: "flex", gap: "1rem" }}>
                    <div style={{ flex: 1, display: "flex", gap: "0.5rem" }}>
                        <button
                            className={`btn btn-sm ${viewMode === "latency" ? "btn-primary" : "btn-ghost"}`}
                            onClick={() => setViewMode("latency")}
                        >
                            Latency View
                        </button>
                        <button
                            className={`btn btn-sm ${viewMode === "metrics" ? "btn-primary" : "btn-ghost"}`}
                            onClick={() => setViewMode("metrics")}
                        >
                            Metrics View
                        </button>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <label className="muted" style={{ fontSize: "0.875rem" }}>Limit</label>
                        <select
                            className="input"
                            value={limit}
                            onChange={(e) => setLimit(parseInt(e.target.value, 10))}
                            style={{ width: "80px", padding: "0.2rem 0.5rem" }}
                        >
                            <option value={10}>10</option>
                            <option value={20}>20</option>
                            <option value={50}>50</option>
                            <option value={100}>100</option>
                        </select>
                    </div>
                </div>

                {error && (
                    <div className="alert alert-error" style={{ margin: "1rem" }}>{error}</div>
                )}

                {loading ? (
                    <div style={{ padding: "2rem", textAlign: "center" }} className="muted">Loading...</div>
                ) : items.length === 0 ? (
                    <div style={{ padding: "2rem", textAlign: "center" }} className="muted">No stats available for the selected limit.</div>
                ) : (
                    <div className="repo-table-wrap">
                        <table className="repo-table">
                            <thead>
                                <tr>
                                    <th style={{ width: "22%" }}>Message ID / Query</th>
                                    <th style={{ width: "9%" }}>Time</th>
                                    {viewMode === "latency" ? (
                                        <>
                                            <th>Retrieval (ms)</th>
                                            <th>Rerank (ms)</th>
                                            <th>Generation (ms)</th>
                                            <th>Total (ms)</th>
                                        </>
                                    ) : (
                                        <>
                                            <th title="Context Precision / Recall">Retrieval</th>
                                            <th title="MRR / NDCG / Kendall Tau">Reranker</th>
                                            <th title="Faithfulness / Relevancy">Generation</th>
                                            <th>Status</th>
                                        </>
                                    )}
                                    <th>Config</th>
                                </tr>
                            </thead>
                            <tbody>
                                {paginated.map((item) => {
                                    const latencies = item.latency_ms || {};
                                    const raw = (item.metrics || {}) as Record<string, unknown>;
                                    const scIterations: IterationMetric[] = (() => {
                                        const gen = raw.generation as Record<string, unknown> | undefined;
                                        const iters = gen?.sc_iterations as IterationMetric[] | undefined;
                                        return Array.isArray(iters) ? iters : [];
                                    })();
                                    const scLoops: number | undefined = typeof latencies.sc_loops === "number" ? latencies.sc_loops : undefined;
                                    const hasLoops = viewMode === "metrics" && scIterations.length > 0;
                                    const isExpanded = expandedIds.has(item.message_id);
                                    // CRAG: parent row mirrors last loop exactly (including missing scores as —).
                                    // Flat DB columns are also filled from last loop for new runs; prefer latest when present.
                                    const latest = scIterations.length > 0 ? scIterations[scIterations.length - 1] : null;
                                    const parentPrecision = latest
                                        ? (latest.retrieval?.context_precision as number | null | undefined) ?? null
                                        : item.context_precision;
                                    const parentRecall = latest
                                        ? (latest.retrieval?.context_recall as number | null | undefined) ?? null
                                        : item.context_recall;
                                    const parentMrr = latest
                                        ? (latest.reranker?.mrr as number | null | undefined) ?? (latest.rerank?.mrr as number | null | undefined) ?? null
                                        : item.mrr;
                                    const parentNdcg = latest
                                        ? (latest.reranker?.ndcg as number | null | undefined) ?? (latest.rerank?.ndcg as number | null | undefined) ?? null
                                        : item.ndcg;
                                    const parentTau = latest
                                        ? (latest.reranker?.kendall_tau as number | null | undefined) ?? (latest.rerank?.kendall_tau as number | null | undefined) ?? null
                                        : item.kendall_tau;
                                    const parentFaith = latest
                                        ? (latest.generation?.faithfulness as number | null | undefined) ?? null
                                        : item.faithfulness;
                                    const parentRelev = latest
                                        ? (latest.generation?.answer_relevancy as number | null | undefined) ?? null
                                        : item.answer_relevancy;

                                    return (
                                        <Fragment key={item.message_id}>
                                            <tr>
                                                <td>
                                                    <div style={{ display: "flex", gap: "0.35rem", alignItems: "flex-start" }}>
                                                        {hasLoops && (
                                                            <button
                                                                type="button"
                                                                className="btn btn-sm btn-ghost"
                                                                aria-expanded={isExpanded}
                                                                title={isExpanded ? "Hide CRAG loops" : "Show CRAG loops"}
                                                                onClick={() => toggleExpanded(item.message_id)}
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
                                                            <div className="mono" style={{ fontSize: "0.75rem", marginBottom: "0.25rem" }}>
                                                                {item.message_id.slice(0, 8)}...
                                                            </div>
                                                            <div className="muted" style={{ fontSize: "0.875rem", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                                                                {item.query || "—"}
                                                            </div>
                                                            {(scLoops !== undefined || hasLoops) && (
                                                                <div style={{ marginTop: "0.2rem" }}>
                                                                    <span style={{ fontSize: "0.68rem", padding: "0.1rem 0.4rem", borderRadius: 4, background: "rgba(59,130,246,0.15)", color: "#3b82f6" }}>
                                                                        CRAG · {scLoops ?? scIterations.length} loop{(scLoops ?? scIterations.length) !== 1 ? "s" : ""}
                                                                    </span>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </td>
                                                <td className="muted" style={{ fontSize: "0.875rem" }}>
                                                    {item.created_at ? formatRelativeTime(item.created_at) : "—"}
                                                </td>

                                                {viewMode === "latency" ? (
                                                    <>
                                                        <td className="mono">{formatLatency(latencies.retrieve || latencies.retrieval)}</td>
                                                        <td className="mono">{formatLatency(latencies.reranking || latencies.rerank)}</td>
                                                        <td className="mono">{formatLatency(latencies.generate || latencies.generation)}</td>
                                                        <td className="mono">
                                                            <strong style={{ color: "var(--accent-emphasis)" }}>
                                                                {formatLatency(latencies.total)}
                                                            </strong>
                                                        </td>
                                                    </>
                                                ) : (
                                                    <>
                                                        <td>
                                                            <RetrievalCell precision={parentPrecision} recall={parentRecall} />
                                                        </td>
                                                        <td>
                                                            <RerankerCell mrr={parentMrr} ndcg={parentNdcg} tau={parentTau} />
                                                        </td>
                                                        <td>
                                                            <GenerationCell faithfulness={parentFaith} relevancy={parentRelev} />
                                                        </td>
                                                        <td>
                                                            <span
                                                                style={{
                                                                    fontSize: "0.7rem",
                                                                    padding: "0.15rem 0.45rem",
                                                                    borderRadius: 4,
                                                                    background:
                                                                        item.metrics_status === "completed"
                                                                            ? "rgba(16,185,129,0.15)"
                                                                            : item.metrics_status === "pending"
                                                                                ? "rgba(245,158,11,0.15)"
                                                                                : "rgba(239,68,68,0.12)",
                                                                    color:
                                                                        item.metrics_status === "completed"
                                                                            ? "#10b981"
                                                                            : item.metrics_status === "pending"
                                                                                ? "#f59e0b"
                                                                                : "#ef4444",
                                                                    textTransform: "capitalize",
                                                                }}
                                                            >
                                                                {item.metrics_status || "—"}
                                                            </span>
                                                        </td>
                                                    </>
                                                )}

                                                <td>
                                                    <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.75rem" }}>
                                                        <span className="muted">Mode: <span className="mono">{item.retrieval_mode || "—"}</span></span>
                                                        <span className="muted">Rerank: <span className="mono">{item.rerank_enabled ? "Yes" : "No"}</span></span>
                                                        {item.generation_model && (
                                                            <span className="muted">Model: <span className="mono" style={{ fontSize: "0.7rem" }}>{item.generation_model}</span></span>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>

                                            {isExpanded && scIterations.map((it, idx) => {
                                                const loop = it.loop ?? idx + 1;
                                                const rRet = it.retrieval || {};
                                                const rRnk = it.reranker || it.rerank || {};
                                                const rGen = it.generation || {};
                                                const isLatest = idx === scIterations.length - 1;
                                                return (
                                                    <tr
                                                        key={`${item.message_id}-loop-${loop}`}
                                                        style={{ background: "var(--surface-2, rgba(255,255,255,0.02))" }}
                                                    >
                                                        <td colSpan={2} style={{ paddingLeft: "2.25rem", fontSize: "0.75rem" }}>
                                                            <span style={{ fontWeight: 700, color: "var(--accent, #3b82f6)" }}>
                                                                Loop {loop}
                                                            </span>
                                                            {isLatest && (
                                                                <span className="muted" style={{ marginLeft: "0.4rem", fontSize: "0.68rem" }}>
                                                                    (latest)
                                                                </span>
                                                            )}
                                                            {it.query && (
                                                                <div className="muted" style={{ marginTop: "0.15rem", fontSize: "0.7rem", maxWidth: 360 }}>
                                                                    Query: {it.query}
                                                                </div>
                                                            )}
                                                        </td>
                                                        <td>
                                                            {Object.keys(rRet).length > 0 ? (
                                                                <RetrievalCell
                                                                    precision={rRet.context_precision as number | null}
                                                                    recall={rRet.context_recall as number | null}
                                                                />
                                                            ) : (
                                                                <span className="muted">—</span>
                                                            )}
                                                        </td>
                                                        <td>
                                                            <RerankerCell
                                                                mrr={rRnk.mrr as number | null}
                                                                ndcg={rRnk.ndcg as number | null}
                                                                tau={rRnk.kendall_tau as number | null}
                                                            />
                                                        </td>
                                                        <td>
                                                            <GenerationCell
                                                                faithfulness={rGen.faithfulness as number | null}
                                                                relevancy={rGen.answer_relevancy as number | null}
                                                            />
                                                        </td>
                                                        <td><span className="muted">—</span></td>
                                                        <td><span className="muted">—</span></td>
                                                    </tr>
                                                );
                                            })}
                                        </Fragment>
                                    );
                                })}
                            </tbody>
                        </table>

                        {Math.ceil(items.length / ITEMS_PER_PAGE) > 1 && (
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "1rem" }}>
                                <span className="muted" style={{ fontSize: "0.875rem" }}>
                                    Showing {(currentPage - 1) * ITEMS_PER_PAGE + 1} to {Math.min(currentPage * ITEMS_PER_PAGE, items.length)} of {items.length} records
                                </span>
                                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                                    <button
                                        className="btn btn-sm btn-ghost"
                                        disabled={currentPage === 1}
                                        onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                                    >
                                        Previous
                                    </button>
                                    <span style={{ padding: "0.25rem 0.5rem", fontSize: "0.875rem" }}>
                                        Page {currentPage} of {Math.ceil(items.length / ITEMS_PER_PAGE)}
                                    </span>
                                    <button
                                        className="btn btn-sm btn-ghost"
                                        disabled={currentPage >= Math.ceil(items.length / ITEMS_PER_PAGE)}
                                        onClick={() => setCurrentPage((p) => Math.min(Math.ceil(items.length / ITEMS_PER_PAGE), p + 1))}
                                    >
                                        Next
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
