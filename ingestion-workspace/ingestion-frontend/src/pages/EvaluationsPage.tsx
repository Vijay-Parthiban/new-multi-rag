import { useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { getChatStats, RAGChatStatItem } from "../api";
import { formatRelativeTime } from "../utils/format";

type ViewMode = "latency" | "metrics";

export default function EvaluationsPage() {
    const [viewMode, setViewMode] = useState<ViewMode>("latency");
    const [limit, setLimit] = useState(20);
    const [items, setItems] = useState<RAGChatStatItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

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

    useEffect(() => {
        setCurrentPage(1);
    }, [limit]);

    useEffect(() => {
        loadStats();
    }, [loadStats]);

    const formatNumber = (num: number | null | undefined, isPercent: boolean = false) => {
        if (num === null || num === undefined) return "—";
        if (isPercent) return `${(num * 100).toFixed(0)}%`;
        return num.toFixed(3);
    };

    const formatLatency = (ms: number | undefined) => {
        if (ms === undefined) return "—";
        return `${ms.toFixed(0)} ms`;
    };

    return (
        <div className="page">
            <PageHeader
                title="Evaluations & Tracking"
                description="Monitor end-to-end RAG metrics including retrieval, reranking, and generation latency and quality."
                breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Evaluations" }]}
                actions={
                    <button type="button" className="btn btn-secondary" onClick={loadStats}>
                        Refresh
                    </button>
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
                    <div className="alert alert-error" style={{ margin: "1rem" }}>
                        {error}
                    </div>
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
                                    <th style={{ width: "20%" }}>Message ID / Query</th>
                                    <th style={{ width: "10%" }}>Time</th>
                                    {viewMode === "latency" ? (
                                        <>
                                            <th>Retrieval (ms)</th>
                                            <th>Rerank (ms)</th>
                                            <th>Generation (ms)</th>
                                            <th>Total (ms)</th>
                                        </>
                                    ) : (
                                        <>
                                            <th title="Context Precision / Recall">Retrieval Metrics</th>
                                            <th title="MRR / NDCG / Kendall Tau">Reranker Metrics</th>
                                            <th title="Faithfulness / Relevancy">Generation Metrics</th>
                                        </>
                                    )}
                                    <th>Config</th>
                                </tr>
                            </thead>
                            <tbody>
                                {items.slice((currentPage - 1) * ITEMS_PER_PAGE, currentPage * ITEMS_PER_PAGE).map((item) => {
                                    const latencies = item.latency_ms || {};
                                    return (
                                        <tr key={item.message_id}>
                                            <td>
                                                <div className="mono" style={{ fontSize: "0.75rem", marginBottom: "0.25rem" }}>
                                                    {item.message_id.slice(0, 8)}...
                                                </div>
                                                <div className="muted" style={{ fontSize: "0.875rem", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                                                    {item.query || "—"}
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
                                                        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>Recall: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.context_recall, true)}</span></span>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>Precision: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.context_precision, true)}</span></span>
                                                        </div>
                                                    </td>
                                                    <td>
                                                        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>MRR: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.mrr)}</span></span>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>NDCG: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.ndcg)}</span></span>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>Tau: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.kendall_tau)}</span></span>
                                                        </div>
                                                    </td>
                                                    <td>
                                                        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>Faithful: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.faithfulness, true)}</span></span>
                                                            <span className="muted" style={{ fontSize: "0.75rem" }}>Relevant: <span className="mono" style={{ color: "var(--text)" }}>{formatNumber(item.answer_relevancy, true)}</span></span>
                                                        </div>
                                                    </td>
                                                </>
                                            )}

                                            <td>
                                                <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "0.75rem" }}>
                                                    <span className="muted">Mode: <span className="mono">{item.retrieval_mode || "—"}</span></span>
                                                    <span className="muted">Rerank: <span className="mono">{item.rerank_enabled ? "Yes" : "No"}</span></span>
                                                </div>
                                            </td>
                                        </tr>
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
