import { useEffect, useState, useCallback, useMemo } from "react";
import {
    GuardrailsTrace,
    GuardrailsStats,
    listGuardrailsTraces,
    getGuardrailsStats,
} from "../api";
import { guardMeta, guardTitle } from "../utils/guardLabels";

type ViewMode = "table" | "charts";
type BlockedFilter = "" | "true" | "false";

const LIMIT = 25;

/**
 * One stacked bar with a labelled legend. A donut was wrong here: a two-way split with one
 * dominant side renders as a circle. The legend carries the numbers, so the split does not
 * depend on colour alone.
 */
function ProportionBar({
    segments,
}: {
    segments: { label: string; value: number; tone: string }[];
}) {
    const total = segments.reduce((sum, s) => sum + s.value, 0);
    const safeTotal = total || 1;
    return (
        <div className="gr-prop">
            <div
                className="gr-prop-track"
                role="img"
                aria-label={segments.map((s) => `${s.label}: ${s.value}`).join(", ")}
            >
                {segments.map((s) => (
                    <span
                        key={s.label}
                        className={`gr-prop-seg gr-prop-seg--${s.tone}`}
                        style={{ width: `${(s.value / safeTotal) * 100}%` }}
                    />
                ))}
            </div>
            <ul className="gr-prop-legend">
                {segments.map((s) => (
                    <li key={s.label}>
                        <span className={`gr-prop-dot gr-prop-dot--${s.tone}`} aria-hidden="true" />
                        <span className="gr-prop-name">{s.label}</span>
                        <span className="gr-prop-value">{s.value}</span>
                        <span className="gr-prop-pct">
                            {total > 0 ? `${((s.value / safeTotal) * 100).toFixed(1)}%` : "0%"}
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    );
}

/** The table shows time first and the day beneath it, so a 25-row list stays scannable. */
function formatClock(iso: string | null): string {
    if (!iso) return "—";
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDay(iso: string | null): string {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Failed and total checks in one trace, read from the per-validator `guard_results`. */
function checkCounts(trace: GuardrailsTrace): { failed: number; total: number } {
    let failed = 0;
    let total = 0;
    for (const result of Object.values(trace.guard_results ?? {})) {
        total += 1;
        if (result.validation_passed === false) failed += 1;
    }
    return { failed, total };
}

interface ValidatorStat {
    id: string;
    failures: number;
    total: number;
}

/** Failure count per validator across the traces that are currently loaded. */
function countValidatorFailures(traces: GuardrailsTrace[]): ValidatorStat[] {
    const counts = new Map<string, ValidatorStat>();
    for (const trace of traces) {
        for (const [id, result] of Object.entries(trace.guard_results ?? {})) {
            const stat = counts.get(id) ?? { id, failures: 0, total: 0 };
            stat.total += 1;
            if (result.validation_passed === false) stat.failures += 1;
            counts.set(id, stat);
        }
    }
    return [...counts.values()].sort(
        (a, b) => b.failures - a.failures || a.id.localeCompare(b.id),
    );
}

export default function GuardrailsTracesPage() {
    const [stats, setStats] = useState<GuardrailsStats | null>(null);
    const [traces, setTraces] = useState<GuardrailsTrace[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [view, setView] = useState<ViewMode>("table");
    const [selectedTrace, setSelectedTrace] = useState<GuardrailsTrace | null>(null);

    // Filters. Blocked and guard go to the service, the text search runs on the loaded rows.
    const [filterGuard, setFilterGuard] = useState("");
    const [filterBlocked, setFilterBlocked] = useState<BlockedFilter>("");
    const [filterText, setFilterText] = useState("");
    const [page, setPage] = useState(0);

    const loadData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [statsRes, tracesRes] = await Promise.all([
                getGuardrailsStats(),
                listGuardrailsTraces({
                    guard: filterGuard || undefined,
                    blocked: filterBlocked === "" ? undefined : filterBlocked === "true",
                    limit: LIMIT,
                    offset: page * LIMIT,
                }),
            ]);
            setStats(statsRes);
            setTraces(tracesRes.items);
            setTotal(tracesRes.total);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Could not load the guard traces.");
        } finally {
            setLoading(false);
        }
    }, [filterGuard, filterBlocked, page]);

    useEffect(() => { loadData(); }, [loadData]);

    useEffect(() => {
        if (!selectedTrace) return;
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") setSelectedTrace(null);
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [selectedTrace]);

    const totalPages = Math.max(1, Math.ceil(total / LIMIT));
    /** Blocks per guard, largest first, with each guard's share of all blocks. */
    const guardBreakdown = useMemo(() => {
        if (!stats) return [];
        const total = stats.blocked_requests || 1;
        return Object.entries(stats.per_guard)
            .filter(([, count]) => count > 0)
            .sort((a, b) => b[1] - a[1])
            .map(([id, count]) => ({ id, count, share: (count / total) * 100 }));
    }, [stats]);

    const guardOptions = useMemo(() => {
        const ids = new Set<string>();
        for (const id of Object.keys(stats?.per_guard ?? {})) ids.add(id);
        for (const trace of traces) {
            if (trace.blocked_by_guard) ids.add(trace.blocked_by_guard);
            for (const id of Object.keys(trace.guard_results ?? {})) ids.add(id);
        }
        return [...ids].sort((a, b) => a.localeCompare(b));
    }, [stats, traces]);

    const visibleTraces = useMemo(() => {
        const needle = filterText.trim().toLowerCase();
        if (!needle) return traces;
        return traces.filter((t) => t.query.toLowerCase().includes(needle));
    }, [traces, filterText]);

    const validatorStats = useMemo(() => countValidatorFailures(traces), [traces]);

    return (
        <div className="page-container guardrails-page">
            <div className="page-header">
                <h1>⛨ Guard Traces & Analytics</h1>
                <div className="gr-view-toggle">
                    <button
                        className={`btn btn-sm ${view === "table" ? "btn-primary" : "btn-secondary"}`}
                        onClick={() => setView("table")}
                    >Table</button>
                    <button
                        className={`btn btn-sm ${view === "charts" ? "btn-primary" : "btn-secondary"}`}
                        onClick={() => setView("charts")}
                    >Charts</button>
                    <button className="btn btn-sm btn-secondary" onClick={loadData}>↻ Refresh</button>
                </div>
            </div>

            {error && (
                <div className="alert alert-error gr-load-error">
                    <span>{error}</span>
                    <button type="button" className="btn btn-sm" onClick={() => void loadData()}>Retry</button>
                </div>
            )}

            {/* KPI Cards */}
            {stats && (
                <div className="gr-kpi-row">
                    <div className="gr-kpi-card">
                        <span className="gr-kpi-value">{stats.total_requests}</span>
                        <span className="gr-kpi-label">Total Requests</span>
                    </div>
                    <div className="gr-kpi-card gr-kpi-blocked">
                        <span className="gr-kpi-value">{stats.blocked_requests}</span>
                        <span className="gr-kpi-label">Blocked</span>
                    </div>
                    <div className="gr-kpi-card gr-kpi-passed">
                        <span className="gr-kpi-value">{stats.passed_requests}</span>
                        <span className="gr-kpi-label">Passed</span>
                    </div>
                    <div className="gr-kpi-card">
                        {/* The service sends block_rate as a fraction, for example 0.069. */}
                        <span className="gr-kpi-value">{(stats.block_rate * 100).toFixed(1)}%</span>
                        <span className="gr-kpi-label">Block Rate</span>
                    </div>
                </div>
            )}

            {stats && (
                <div className="gr-chart-card">
                    <h3>Blocks by guard</h3>
                    <p className="gr-chart-sub">
                        Each row is a validator that blocked. Select one to filter the table below.
                    </p>
                    {guardBreakdown.length === 0 ? (
                        <p className="gr-empty-chart">No blocked requests yet</p>
                    ) : (
                        <ul className="gr-bar-list gr-bar-list--clickable">
                            {guardBreakdown.map(({ id, count, share }) => {
                                const meta = guardMeta(id);
                                return (
                                    <li key={id}>
                                        <button
                                            type="button"
                                            className={`gr-guardbar ${filterGuard === id ? "gr-guardbar--active" : ""}`}
                                            onClick={() => {
                                                setFilterGuard(id);
                                                setFilterBlocked("true");
                                                setPage(0);
                                                setView("table");
                                            }}
                                        >
                                            <span className="gr-bar-head">
                                                <span className="gr-bar-label">{meta.title}</span>
                                                <span className="gr-bar-value">
                                                    {count} blocked · {share.toFixed(1)}%
                                                </span>
                                            </span>
                                            <span className="gr-bar-track">
                                                <span
                                                    className="gr-bar-fill gr-bar-fill--fail"
                                                    style={{ width: `${Math.max(share, 2)}%` }}
                                                />
                                            </span>
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            )}

            {/* Per-validator failure breakdown, built from guard_results */}
            <div className="gr-chart-card gr-breakdown-card">
                <h3>Failures by validator</h3>
                <p className="gr-chart-sub">
                    Counted over the {traces.length} loaded traces. Each trace runs every selected
                    validator, so a check that fails is a would-be block.
                </p>
                {validatorStats.length === 0 ? (
                    <p className="gr-empty-chart">No validator results in these traces yet.</p>
                ) : (
                    <ul className="gr-bar-list">
                        {validatorStats.map((stat) => {
                            const rate = stat.total > 0 ? stat.failures / stat.total : 0;
                            return (
                                <li key={stat.id} className="gr-bar-row">
                                    <div className="gr-bar-head">
                                        <span className="gr-bar-label">{guardTitle(stat.id)}</span>
                                        <span className="gr-bar-value">
                                            {stat.failures} of {stat.total} checks failed
                                        </span>
                                    </div>
                                    <div
                                        className="gr-bar-track"
                                        role="img"
                                        aria-label={`${guardTitle(stat.id)}: ${stat.failures} of ${stat.total} checks failed`}
                                    >
                                        <span
                                            className={`gr-bar-fill ${stat.failures > 0 ? "gr-bar-fill--fail" : ""}`}
                                            style={{ width: `${Math.round(rate * 100)}%` }}
                                        />
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                )}
            </div>

            {view === "charts" ? (
                <div className="gr-charts-container">
                    {stats && stats.total_requests > 0 ? (
                        <>
                            <div className="gr-chart-card">
                                <h3>Blocked vs passed</h3>
                                <p className="gr-chart-sub">
                                    {stats.total_requests} requests, {stats.blocked_requests} blocked
                                    and {stats.passed_requests} passed.
                                </p>
                                <ProportionBar
                                    segments={[
                                        { label: "Blocked", value: stats.blocked_requests, tone: "blocked" },
                                        { label: "Passed", value: stats.passed_requests, tone: "passed" },
                                    ]}
                                />
                            </div>
                            <div className="gr-chart-card">
                                <h3>Blocks by guard</h3>
                                {guardBreakdown.length === 0 ? (
                                    <p className="gr-empty-chart">No blocked requests yet</p>
                                ) : (
                                    <ul className="gr-bar-list">
                                        {guardBreakdown.map(({ id, count, share }) => (
                                            <li key={id} className="gr-bar-row">
                                                <div className="gr-bar-head">
                                                    <span className="gr-bar-label">{guardTitle(id)}</span>
                                                    <span className="gr-bar-value">
                                                        {count} · {share.toFixed(1)}%
                                                    </span>
                                                </div>
                                                <div className="gr-bar-track">
                                                    <span
                                                        className="gr-bar-fill gr-bar-fill--fail"
                                                        style={{ width: `${Math.max(share, 2)}%` }}
                                                    />
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="gr-empty">
                            <p>No data to display charts</p>
                            <p className="gr-param-help">
                                Charts appear once a chat turn runs with a guardrails config attached.
                            </p>
                        </div>
                    )}
                </div>
            ) : (
                <>
                    {/* Filters */}
                    <div className="gr-filters">
                        <select
                            className="gr-select"
                            value={filterBlocked}
                            onChange={(e) => { setFilterBlocked(e.target.value as BlockedFilter); setPage(0); }}
                        >
                            <option value="">All Status</option>
                            <option value="true">Blocked</option>
                            <option value="false">Passed</option>
                        </select>
                        <select
                            className="gr-select"
                            value={filterGuard}
                            onChange={(e) => { setFilterGuard(e.target.value); setPage(0); }}
                        >
                            <option value="">All validators</option>
                            {guardOptions.map((id) => (
                                <option key={id} value={id}>{guardTitle(id)}</option>
                            ))}
                        </select>
                        <input
                            className="gr-input gr-filter-input"
                            placeholder="Search the query text..."
                            value={filterText}
                            onChange={(e) => setFilterText(e.target.value)}
                        />
                        {(filterGuard || filterBlocked || filterText) && (
                            <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => { setFilterGuard(""); setFilterBlocked(""); setFilterText(""); setPage(0); }}
                            >Clear</button>
                        )}
                    </div>

                    {loading ? (
                        <p className="gr-loading">Loading traces...</p>
                    ) : traces.length === 0 ? (
                        <div className="gr-empty">
                            <p>No guard traces yet.</p>
                            <p>
                                A trace is written after a chat turn runs with a guardrails config
                                attached. Open Chat, pick a config in the guardrails selector, then
                                send a message.
                            </p>
                        </div>
                    ) : visibleTraces.length === 0 ? (
                        <div className="gr-empty"><p>No loaded trace matches these filters.</p></div>
                    ) : (
                        <>
                            <div className="gr-table-wrapper">
                                <table className="gr-table">
                                    <thead>
                                        <tr>
                                            <th>Time</th>
                                            <th>Config</th>
                                            <th>Query</th>
                                            <th>Status</th>
                                            <th>Guard</th>
                                            <th>Phase</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {visibleTraces.map((t) => {
                                            const checks = checkCounts(t);
                                            return (
                                                <tr
                                                    key={t.id}
                                                    tabIndex={0}
                                                    role="button"
                                                    aria-label={`Trace from ${formatDay(t.created_at)} ${formatClock(t.created_at)}: ${t.blocked ? "blocked" : "passed"}`}
                                                    className={`gr-row-clickable ${t.blocked ? "gr-row-blocked" : ""} ${selectedTrace?.id === t.id ? "gr-row-selected" : ""}`}
                                                    onClick={() => setSelectedTrace(t)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === "Enter" || e.key === " ") {
                                                            e.preventDefault();
                                                            setSelectedTrace(t);
                                                        }
                                                    }}
                                                >
                                                    <td className="gr-cell-time">
                                                        <span className="gr-time-main">{formatClock(t.created_at)}</span>
                                                        <span className="gr-time-day">{formatDay(t.created_at)}</span>
                                                    </td>
                                                    <td>{t.config_name || "—"}</td>
                                                    <td className="gr-cell-query" title={t.query}>
                                                        {t.query.length > 80 ? t.query.slice(0, 80) + "…" : t.query}
                                                    </td>
                                                    <td>
                                                        <span className={`gr-status-badge ${t.blocked ? "blocked" : "passed"}`}>
                                                            {t.blocked ? "Blocked" : "Passed"}
                                                        </span>
                                                        {checks.failed > 0 && (
                                                            <span className="gr-fail-chip" title={`${checks.failed} of ${checks.total} checks failed`}>
                                                                ! {checks.failed}/{checks.total}
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td>
                                                        {t.blocked_by_guard ? (
                                                            /* A dot plus the guard name. The name carries the
                                                               meaning, so colour is never the only signal. */
                                                            <span className={`gr-guard-chip gr-guard-chip--${guardMeta(t.blocked_by_guard).tone}`}>
                                                                <span className="gr-guard-dot" aria-hidden="true" />
                                                                {guardTitle(t.blocked_by_guard)}
                                                            </span>
                                                        ) : "—"}
                                                    </td>
                                                    <td>{t.blocked_on || "—"}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                            <p className="gr-table-hint">Click a row to see the full query, response and validator detail.</p>
                            {/* Pagination */}
                            <div className="gr-pagination">
                                <button
                                    className="btn btn-sm"
                                    disabled={page === 0}
                                    onClick={() => setPage((p) => p - 1)}
                                >← Prev</button>
                                <span>Page {page + 1} of {totalPages}</span>
                                <button
                                    className="btn btn-sm"
                                    disabled={page + 1 >= totalPages}
                                    onClick={() => setPage((p) => p + 1)}
                                >Next →</button>
                            </div>
                        </>
                    )}
                </>
            )}

            {selectedTrace && (
                <div className="gr-drawer-scrim" onClick={() => setSelectedTrace(null)}>
                    <aside
                        className="gr-drawer"
                        role="dialog"
                        aria-modal="true"
                        aria-label="Trace detail"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="gr-drawer-header">
                            <div>
                                <h3>Trace detail</h3>
                                <p className="gr-drawer-sub">
                                    {selectedTrace.created_at
                                        ? `${formatDay(selectedTrace.created_at)} · ${formatClock(selectedTrace.created_at)}`
                                        : "Unknown time"}
                                    {" · "}
                                    {selectedTrace.config_name || "No config"}
                                </p>
                            </div>
                            <button
                                type="button"
                                className="gr-drawer-close"
                                onClick={() => setSelectedTrace(null)}
                                aria-label="Close detail"
                            >✕</button>
                        </div>

                        <span className={`gr-status-badge ${selectedTrace.blocked ? "blocked" : "passed"}`}>
                            {selectedTrace.blocked ? "Blocked" : "Passed"}
                        </span>
                        {selectedTrace.blocked_by_guard && (
                            <span className="gr-drawer-meta">
                                by <strong>{guardTitle(selectedTrace.blocked_by_guard)}</strong>
                                {selectedTrace.blocked_on ? ` on the ${selectedTrace.blocked_on} phase` : ""}
                            </span>
                        )}

                        <h4 className="gr-drawer-section">Query</h4>
                        <pre className="gr-detail-text">{selectedTrace.query}</pre>

                        <h4 className="gr-drawer-section">Response</h4>
                        {selectedTrace.response ? (
                            <pre className="gr-detail-text">{selectedTrace.response}</pre>
                        ) : (
                            <p className="gr-drawer-muted">
                                No response. The service stopped the chat turn before the model answered.
                            </p>
                        )}

                        <h4 className="gr-drawer-section">
                            Validator results
                            <span className="gr-drawer-count">
                                {Object.keys(selectedTrace.guard_results ?? {}).length}
                            </span>
                        </h4>
                        {Object.keys(selectedTrace.guard_results ?? {}).length === 0 ? (
                            <p className="gr-drawer-muted">This trace has no validator results.</p>
                        ) : (
                            Object.entries(selectedTrace.guard_results).map(([id, result]) => (
                                <div
                                    key={id}
                                    className={`gr-detail-guard ${result.validation_passed ? "gr-detail-guard--pass" : "gr-detail-guard--fail"}`}
                                >
                                    <div className="gr-detail-guard-head">
                                        <span className="gr-detail-guard-name">{guardTitle(id)}</span>
                                        <span className={`gr-status-badge ${result.validation_passed ? "passed" : "blocked"}`}>
                                            {result.validation_passed ? "Passed" : "Failed"}
                                        </span>
                                    </div>
                                    {result.detail && <p className="gr-detail-guard-text">{result.detail}</p>}
                                    {result.error && (
                                        <p className="gr-detail-guard-error">Error: {result.error}</p>
                                    )}
                                </div>
                            ))
                        )}
                    </aside>
                </div>
            )}
        </div>
    );
}
