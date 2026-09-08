import { useEffect, useState, useCallback } from "react";
import {
    GuardrailsTrace,
    GuardrailsStats,
    listGuardrailsTraces,
    getGuardrailsStats,
} from "../api";

type ViewMode = "table" | "charts";

const GUARD_META: Record<string, { icon: string; title: string; tone: string }> = {
    ban_list: { icon: "🚫", title: "Banned keyword", tone: "ban" },
    pii_check: { icon: "🔒", title: "Personal information", tone: "pii" },
    toxic_language: { icon: "⚠️", title: "Toxic language", tone: "toxic" },
};

const GUARD_COLORS: Record<string, string> = {
    ban_list: "#ef4444",
    pii_check: "#f59e0b",
    toxic_language: "#8b5cf6",
};

const CHART_COLORS = [
    "#6366f1", "#f59e0b", "#ef4444", "#22c55e", "#06b6d4", "#ec4899",
    "#8b5cf6", "#14b8a6",
];

function blocksByGuardData(perGuard: Record<string, number>): PieSlice[] {
    return Object.entries(perGuard)
        .filter(([, count]) => count > 0)
        .map(([name, count], i) => ({
            label: GUARD_META[name]?.title || name,
            value: count,
            color: GUARD_COLORS[name] || CHART_COLORS[i % CHART_COLORS.length],
        }));
}

export default function GuardrailsTracesPage() {
    const [stats, setStats] = useState<GuardrailsStats | null>(null);
    const [traces, setTraces] = useState<GuardrailsTrace[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [view, setView] = useState<ViewMode>("table");

    // Filters
    const [filterGuard, setFilterGuard] = useState("");
    const [filterBlocked, setFilterBlocked] = useState<"" | "true" | "false">("");
    const [page, setPage] = useState(0);
    const LIMIT = 25;

    const loadData = useCallback(async () => {
        setLoading(true);
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
            console.error("Failed to load guardrails data", e);
        } finally {
            setLoading(false);
        }
    }, [filterGuard, filterBlocked, page]);

    useEffect(() => { loadData(); }, [loadData]);

    const totalPages = Math.max(1, Math.ceil(total / LIMIT));
    const guardPie = stats ? blocksByGuardData(stats.per_guard) : [];

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
                        <span className="gr-kpi-value">{stats.block_rate}%</span>
                        <span className="gr-kpi-label">Block Rate</span>
                    </div>
                </div>
            )}

            {stats && (
                <div className="gr-analytics-row">
                    <div className="gr-chart-card gr-chart-card--pie">
                        <h3>Blocks by Guard</h3>
                        {guardPie.length > 0 ? (
                            <PieChart data={guardPie} />
                        ) : (
                            <p className="gr-empty-chart">No blocked requests yet</p>
                        )}
                    </div>
                    {Object.keys(stats.per_guard).length > 0 && (
                        <div className="gr-block-cards">
                            {Object.entries(stats.per_guard).map(([guard, count]) => {
                                const meta = GUARD_META[guard] || { icon: "🛡️", title: guard, tone: "ban" };
                                return (
                                    <button
                                        key={guard}
                                        type="button"
                                        className={`gr-block-card gr-block-card--${meta.tone}`}
                                        onClick={() => { setFilterGuard(guard); setFilterBlocked("true"); setPage(0); setView("table"); }}
                                    >
                                        <span className="gr-block-card-icon">{meta.icon}</span>
                                        <span className="gr-block-card-title">{meta.title}</span>
                                        <span className="gr-block-card-count">{count} blocked</span>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            {view === "charts" ? (
                <div className="gr-charts-container">
                    {stats && stats.total_requests > 0 ? (
                        <div className="gr-charts-grid">
                            <div className="gr-chart-card">
                                <h3>Blocked vs Passed</h3>
                                <PieChart
                                    data={[
                                        { label: "Blocked", value: stats.blocked_requests, color: "#ef4444" },
                                        { label: "Passed", value: stats.passed_requests, color: "#22c55e" },
                                    ]}
                                />
                            </div>
                            <div className="gr-chart-card">
                                <h3>Blocks by Guard</h3>
                                {guardPie.length > 0 ? (
                                    <PieChart data={guardPie} />
                                ) : (
                                    <p className="gr-empty-chart">No blocked requests yet</p>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="gr-empty"><p>No data to display charts</p></div>
                    )}
                </div>
            ) : (
                <>
                    {/* Filters */}
                    <div className="gr-filters">
                        <select
                            className="gr-select"
                            value={filterBlocked}
                            onChange={(e) => { setFilterBlocked(e.target.value as any); setPage(0); }}
                        >
                            <option value="">All Status</option>
                            <option value="true">Blocked</option>
                            <option value="false">Passed</option>
                        </select>
                        <input
                            className="gr-input gr-filter-input"
                            placeholder="Filter by guard name..."
                            value={filterGuard}
                            onChange={(e) => { setFilterGuard(e.target.value); setPage(0); }}
                        />
                    </div>

                    {loading ? (
                        <p className="gr-loading">Loading traces...</p>
                    ) : traces.length === 0 ? (
                        <div className="gr-empty"><p>No traces found</p></div>
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
                                        {traces.map((t) => (
                                            <tr key={t.id} className={t.blocked ? "gr-row-blocked" : ""}>
                                                <td className="gr-cell-time">
                                                    {t.created_at ? new Date(t.created_at).toLocaleString() : "—"}
                                                </td>
                                                <td>{t.config_name || "—"}</td>
                                                <td className="gr-cell-query" title={t.query}>
                                                    {t.query.length > 80 ? t.query.slice(0, 80) + "…" : t.query}
                                                </td>
                                                <td>
                                                    <span className={`gr-status-badge ${t.blocked ? "blocked" : "passed"}`}>
                                                        {t.blocked ? "Blocked" : "Passed"}
                                                    </span>
                                                </td>
                                                <td>
                                                    {t.blocked_by_guard ? (
                                                        <span className={`gr-guard-chip gr-guard-chip--${(GUARD_META[t.blocked_by_guard]?.tone) || "ban"}`}>
                                                            {GUARD_META[t.blocked_by_guard]?.icon || "🛡️"}{" "}
                                                            {GUARD_META[t.blocked_by_guard]?.title || t.blocked_by_guard}
                                                        </span>
                                                    ) : "—"}
                                                </td>
                                                <td>{t.blocked_on || "—"}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
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
        </div>
    );
}

// ── Inline SVG donut chart ──────────────────────────────────────────

interface PieSlice {
    label: string;
    value: number;
    color: string;
}

function PieChart({ data }: { data: PieSlice[] }) {
    const slices = data.filter((d) => d.value > 0);
    const total = slices.reduce((s, d) => s + d.value, 0);
    if (total === 0) return <p className="gr-empty-chart">No data</p>;

    const size = 200;
    const cx = size / 2;
    const cy = size / 2;
    const r = 68;
    const stroke = 28;
    const circ = 2 * Math.PI * r;
    let offset = 0;

    const rings = slices.map((slice) => {
        const dash = (slice.value / total) * circ;
        const el = (
            <circle
                key={slice.label}
                cx={cx}
                cy={cy}
                r={r}
                fill="none"
                stroke={slice.color}
                strokeWidth={stroke}
                strokeDasharray={`${dash} ${circ - dash}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${cx} ${cy})`}
                strokeLinecap="butt"
            />
        );
        offset += dash;
        return el;
    });

    return (
        <div className="gr-pie-container">
            <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
                <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border-muted)" strokeWidth={stroke} />
                {rings}
                <text x={cx} y={cy - 6} textAnchor="middle" className="gr-pie-center-value">
                    {total}
                </text>
                <text x={cx} y={cy + 14} textAnchor="middle" className="gr-pie-center-label">
                    blocked
                </text>
            </svg>
            <div className="gr-pie-legend">
                {slices.map((s) => (
                    <div key={s.label} className="gr-legend-item">
                        <span className="gr-legend-dot" style={{ background: s.color }} />
                        <span>{s.label}: {s.value} ({Math.round(s.value / total * 100)}%)</span>
                    </div>
                ))}
            </div>
        </div>
    );
}
