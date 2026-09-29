import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { RAG_API_KEY, RAG_API_URL, listGuardrailsConfigs, type GuardrailsConfig } from "../api";
import {
  createGuardrailsEvalRun,
  deleteGuardrailsGoldenDataset,
  getGuardrailsEvalRun,
  listGuardrailsDatasetRuns,
  listGuardrailsEvalRunItems,
  listGuardrailsGoldenDatasets,
  uploadGuardrailsGoldenDataset,
  type GuardrailsEvalRunItemRow,
  type GuardrailsEvalRunResponse,
  type GuardrailsGoldenDatasetSummary,
} from "../guardrailsEvalApi";
import { formatRelativeTime } from "../utils/format";
import { guardMeta, guardTitle } from "../utils/guardLabels";

/**
 * POST /guardrails-evaluate/datasets/seed imports the golden/guardrails-dataset.json that
 * ships with the repository. The wrapper file does not expose it, so it lives here.
 */
async function seedGuardrailsGoldenDataset(): Promise<{ dataset_id: string; replaced: boolean }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (RAG_API_KEY) headers["X-API-Key"] = RAG_API_KEY;
  const res = await fetch(`${RAG_API_URL}/guardrails-evaluate/datasets/seed`, {
    method: "POST",
    headers,
    body: JSON.stringify({ replace: true }),
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const value = (parsed as { detail?: unknown }).detail;
        if (typeof value === "string") detail = value;
      }
    } catch {
      // The body is not JSON. The raw text is the best message we have.
    }
    throw new Error(detail || `Could not load the bundled dataset (HTTP ${res.status}).`);
  }
  return (await res.json()) as { dataset_id: string; replaced: boolean };
}

function percent(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 1000) / 10}%`;
}

function formatCategory(name: string): string {
  if (name.toLowerCase() === "pii") return "PII";
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

type ItemVerdict = "ok" | "false-negative" | "false-positive" | "guard-miss" | "failed" | "skipped";

const VERDICT_LABEL: Record<ItemVerdict, string> = {
  ok: "Correct",
  "false-negative": "Missed block",
  "false-positive": "False alarm",
  "guard-miss": "Wrong guard",
  failed: "Error",
  skipped: "Skipped",
};

/** False negatives and false positives are the rows that need a config change. */
function verdictOf(row: GuardrailsEvalRunItemRow): ItemVerdict {
  if (row.skipped || row.status === "skipped") return "skipped";
  if (row.status === "failed") return "failed";
  if (row.expected_blocked && !row.actual_blocked) return "false-negative";
  if (!row.expected_blocked && row.actual_blocked) return "false-positive";
  if (row.correct_guard === false) return "guard-miss";
  return "ok";
}

/**
 * One KPI: a label, the value, and a bar. `role="img"` was wrong here — it announces the bar as
 * a picture. `progressbar` with the three aria values is what a screen reader can act on.
 */
function ScoreBar({ label, value }: { label: string; value: number | null | undefined }) {
  const ratio = typeof value === "number" && !Number.isNaN(value) ? value : null;
  const width = ratio === null ? 0 : Math.max(0, Math.min(100, Math.round(ratio * 100)));
  const text = percent(ratio);
  return (
    <div className="gr-score">
      <div className="gr-score-head">
        <span className="gr-score-label">{label}</span>
        <span className="gr-score-value">{text}</span>
      </div>
      <div
        className="gr-bar-track"
        role="progressbar"
        aria-label={label}
        aria-valuenow={ratio === null ? undefined : Math.round(ratio * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={text}
      >
        <span className={`gr-bar-fill${ratio !== null && ratio < 0.5 ? " gr-bar-fill--low" : ""}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

export default function GuardrailsEvaluationPage() {
  const [datasets, setDatasets] = useState<GuardrailsGoldenDatasetSummary[]>([]);
  const [configs, setConfigs] = useState<GuardrailsConfig[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [selectedConfigId, setSelectedConfigId] = useState("");
  const [runs, setRuns] = useState<GuardrailsEvalRunResponse[]>([]);
  const [runsCount, setRunsCount] = useState(0);
  const [selectedRun, setSelectedRun] = useState<GuardrailsEvalRunResponse | null>(null);
  const [runItems, setRunItems] = useState<GuardrailsEvalRunItemRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replaceOnUpload, setReplaceOnUpload] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState("");
  // The dataset awaiting a delete confirmation. A native confirm() cannot be themed, reads as
  // a browser dialog rather than part of the page, and blocks the whole tab.
  const [pendingDelete, setPendingDelete] = useState<GuardrailsGoldenDatasetSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Seconds since Start was pressed. The run endpoint is synchronous and has no progress to
  // poll, so this is the only signal that the request is still alive.
  const [elapsed, setElapsed] = useState(0);
  const [running, setRunning] = useState(false);

  // One interval for the whole run. A synchronous request cannot report progress, so the page
  // shows a moving indeterminate bar and a live second count instead of a frozen button.
  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const selectedConfig = useMemo(
    () => configs.find((c) => c.id === selectedConfigId) || null,
    [configs, selectedConfigId],
  );

  const loadDatasets = useCallback(async () => {
    const res = await listGuardrailsGoldenDatasets();
    setDatasets(res.items);
    if (!selectedDatasetId && res.items.length > 0) {
      setSelectedDatasetId(res.items[0].dataset_id);
    }
  }, [selectedDatasetId]);

  const loadConfigs = useCallback(async () => {
    // Same DB list Chat uses (Guard Config page → guardrails_configs).
    const res = await listGuardrailsConfigs(false);
    setConfigs(res.items);
    if (!selectedConfigId && res.items.length > 0) {
      setSelectedConfigId(res.items[0].id);
    }
  }, [selectedConfigId]);

  const loadRuns = useCallback(async (datasetId: string) => {
    const res = await listGuardrailsDatasetRuns(datasetId, { limit: 20 });
    setRuns(res.items);
    setRunsCount(res.count);
  }, []);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await Promise.all([loadDatasets(), loadConfigs()]);
      if (selectedDatasetId) await loadRuns(selectedDatasetId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh");
    } finally {
      setBusy(false);
    }
  }, [loadConfigs, loadDatasets, loadRuns, selectedDatasetId]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedDatasetId) {
      setRuns([]);
      setRunsCount(0);
      return;
    }
    void loadRuns(selectedDatasetId).catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    });
  }, [selectedDatasetId, loadRuns]);

  async function onSeedDataset() {
    setBusy(true);
    setError(null);
    try {
      const seeded = await seedGuardrailsGoldenDataset();
      await loadDatasets();
      setSelectedDatasetId(seeded.dataset_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the bundled dataset");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const created = await uploadGuardrailsGoldenDataset(file, replaceOnUpload);
      await loadDatasets();
      setSelectedDatasetId(created.dataset_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function runDelete() {
    if (!pendingDelete) return;
    const datasetId = pendingDelete.dataset_id;
    setDeleting(true);
    setBusy(true);
    try {
      await deleteGuardrailsGoldenDataset(datasetId);
      setPendingDelete(null);
      if (selectedDatasetId === datasetId) {
        setSelectedDatasetId(null);
        setSelectedRun(null);
        setRunItems([]);
      }
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
      setBusy(false);
    }
  }

  async function onStartRun() {
    if (!selectedDatasetId || !selectedConfigId) {
      setError("Select a dataset and guardrails configuration first");
      return;
    }
    setBusy(true);
    setRunning(true);
    setError(null);
    setElapsed(0);
    try {
      const created = await createGuardrailsEvalRun(selectedDatasetId, selectedConfigId);
      const run = await getGuardrailsEvalRun(created.run_id);
      setSelectedRun(run);
      const items = await listGuardrailsEvalRunItems(created.run_id);
      setRunItems(items.items);
      setCategoryFilter("");
      await loadRuns(selectedDatasetId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start evaluation");
    } finally {
      setBusy(false);
      setRunning(false);
    }
  }

  async function onSelectRun(run: GuardrailsEvalRunResponse) {
    setSelectedRun(run);
    setRunItems([]);
    setCategoryFilter("");
    try {
      const items = await listGuardrailsEvalRunItems(run.run_id);
      setRunItems(items.items);
      const fresh = await getGuardrailsEvalRun(run.run_id);
      setSelectedRun(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run items");
    }
  }

  const agg = selectedRun?.aggregate_metrics || null;

  const categories = useMemo(() => {
    const names = new Set<string>();
    for (const row of runItems) if (row.category) names.add(row.category);
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [runItems]);

  const visibleItems = useMemo(
    () => (categoryFilter ? runItems.filter((row) => row.category === categoryFilter) : runItems),
    [runItems, categoryFilter],
  );

  // Every item failed, so the zeros are not a score. Say what went wrong instead.
  const allItemsFailed = runItems.length > 0 && runItems.every((row) => row.status === "failed");
  const hideScores = Boolean(selectedRun && agg?.accuracy === 0 && allItemsFailed);
  const failureMessage =
    runItems.find((row) => row.error_message)?.error_message || selectedRun?.error_message || null;

  // The tone follows the value, not the metric. A red tile reading "FP 0" says there is a
  // problem while the number says there is none. Zero false positives is the goal, so it
  // reads as clean; a non-zero count is what earns the warning colour.
  const confusion = [
    { key: "TP", label: "True positives", value: agg?.true_positives, tone: "good" },
    { key: "TN", label: "True negatives", value: agg?.true_negatives, tone: "good" },
    {
      key: "FP",
      label: "False positives",
      value: agg?.false_positives,
      tone: (agg?.false_positives ?? 0) > 0 ? "bad" : "clean",
    },
    {
      key: "FN",
      label: "False negatives",
      value: agg?.false_negatives,
      tone: (agg?.false_negatives ?? 0) > 0 ? "bad" : "clean",
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Guardrails Offline Evaluation"
        description="Load a golden dataset, pick one of the Guard Configs already saved in the database (the same ones Chat applies), and score block accuracy against that config."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Guardrails Evaluation" },
        ]}
        actions={
          <div className="gr-eval-actions">
            {/* Secondary here on purpose. The page's primary action is Start evaluation. */}
            {datasets.length > 0 && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void onSeedDataset()}
                disabled={busy}
              >
                {busy ? "Working…" : "Re-load bundled dataset"}
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => void refresh()} disabled={busy}>
              Refresh
            </button>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error gr-eval-alert">
          {error}
        </div>
      )}

      {!busy && datasets.length === 0 && (
        <div className="gr-eval-empty">
          <h3>No golden dataset yet</h3>
          <p>
            This repository ships a golden set at <code>golden/guardrails-dataset.json</code>. It has
            12 items over 4 categories: clean, ban_list, pii and toxic. Load it into the database,
            then run a config against it.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void onSeedDataset()}
          >
            Load bundled golden dataset
          </button>
          <p className="gr-eval-empty-hint">
            You can also upload your own JSON file in the panel below.
          </p>
        </div>
      )}

      <div className="gr-eval-grid">
        <div className="panel golden-dataset-panel">
          <div className="panel-header">
            <h3 className="panel-title">Golden dataset</h3>
          </div>
          <div className="gr-eval-panel-body">
            <label className="field" htmlFor="gr-eval-upload">
              <span className="field-label">Upload JSON</span>
              <input
                id="gr-eval-upload"
                type="file"
                accept="application/json,.json"
                disabled={busy}
                onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="field gr-eval-check-field" htmlFor="gr-eval-replace">
              <input
                id="gr-eval-replace"
                type="checkbox"
                checked={replaceOnUpload}
                onChange={(e) => setReplaceOnUpload(e.target.checked)}
              />
              <span className="muted">Replace if name already exists</span>
            </label>

            <label className="field" htmlFor="gr-eval-dataset">
              <span className="field-label">Dataset</span>
              <select
                id="gr-eval-dataset"
                value={selectedDatasetId || ""}
                onChange={(e) => {
                  setSelectedDatasetId(e.target.value || null);
                  setSelectedRun(null);
                  setRunItems([]);
                }}
              >
                <option value="">Select dataset…</option>
                {datasets.map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>
                    {d.name} ({d.item_count} items)
                  </option>
                ))}
              </select>
            </label>

            {selectedDatasetId && (
              <button
                type="button"
                className="btn btn-sm btn-ghost gr-eval-delete"
                disabled={busy}
                onClick={() => {
                  const ds = datasets.find((d) => d.dataset_id === selectedDatasetId);
                  if (ds) setPendingDelete(ds);
                }}
              >
                Delete dataset
              </button>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h3 className="panel-title">Chat guardrails config</h3>
          </div>
          <div className="gr-eval-panel-body">
            <label className="field" htmlFor="gr-eval-config">
              <span className="field-label">Saved config from database</span>
              <select
                id="gr-eval-config"
                value={selectedConfigId}
                onChange={(e) => setSelectedConfigId(e.target.value)}
              >
                <option value="">Select config…</option>
                {configs.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>

            {configs.length === 0 && (
              <p className="gr-eval-hint">
                No configs yet. Create one under Guard Config — the same list Chat uses.
              </p>
            )}

            {selectedConfig && (
              <div className="gr-config-summary">
                <span className="gr-summary-label">Runs as</span>
                <span className="gr-tag gr-tag--phase">{selectedConfig.mode}</span>
                {(selectedConfig.guards || []).map((id) => (
                  <span key={id} className={`gr-tag gr-tag--${guardMeta(id).tone}`}>
                    {guardTitle(id)}
                  </span>
                ))}
                {(selectedConfig.guards || []).length === 0 && (
                  <span className="muted">no validators selected</span>
                )}
              </div>
            )}

            <button
              type="button"
              className="btn btn-primary gr-eval-run-btn"
              disabled={busy || !selectedDatasetId || !selectedConfigId}
              onClick={() => void onStartRun()}
            >
              {running && <span className="gr-spinner" aria-hidden />}
              {running ? `Running… ${elapsed}s` : "Start guardrails evaluation"}
            </button>

            {/* The run endpoint is synchronous and returns only when every row is scored, so
                there is no progress to read. An indeterminate bar plus a live second count is
                what tells the operator the request is alive rather than hung. */}
            {running && (
              <div className="gr-eval-progress" role="status" aria-live="polite">
                <div className="gr-progress-track">
                  <span className="gr-progress-bar" />
                </div>
                <p className="gr-eval-hint" style={{ margin: 0 }}>
                  Scoring every row against the config. The judge rows take the longest — a
                  12-row set usually finishes in about twenty seconds.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel gr-eval-panel">
        <div className="panel-header">
          <h3 className="panel-title">Runs</h3>
          <span className="gr-eval-count">
            {runsCount === 1 ? "1 run" : `${runsCount} runs`}
          </span>
        </div>
        <div className="repo-table-wrap">
          <table className="repo-table">
            <thead>
              <tr>
                <th>Created</th>
                <th>Status</th>
                <th>Config</th>
                <th>Accuracy</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="gr-runs-empty">
                    <span>No runs yet for this dataset.</span>
                    <span className="muted">
                      Pick a config above and select Start guardrails evaluation. Each run takes
                      about twenty seconds, because three rows call the LLM judge.
                    </span>
                  </td>
                </tr>
              ) : (
                runs.map((r) => (
                  <tr key={r.run_id} className={selectedRun?.run_id === r.run_id ? "is-selected" : undefined}>
                    <td className="mono">{formatRelativeTime(r.created_at || "")}</td>
                    <td>{r.status}</td>
                    <td>{r.config_snapshot?.name || r.config_id.slice(0, 8)}</td>
                    <td>
                      <div className="gr-run-score">
                        <span className="gr-run-accuracy">
                          {percent(r.aggregate_metrics?.accuracy)}
                        </span>
                        <span className="gr-run-counts">
                          {(r.aggregate_metrics?.false_negatives ?? 0)} missed ·{" "}
                          {(r.aggregate_metrics?.false_positives ?? 0)} false
                        </span>
                      </div>
                    </td>
                    <td>
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => void onSelectRun(r)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedRun && (
        <>
          {hideScores ? (
            <div className="alert alert-error gr-run-warning">
              <div>
                <strong>Every item in this run failed. The scores below are not a real result.</strong>
                <p>
                  {failureMessage ||
                    "The service returned no error message. Check that the guardrails service is running and that the config uses validators that are installed."}
                </p>
              </div>
            </div>
          ) : (
            <div className="panel gr-score-panel">
              <div className="panel-header">
                <h3 className="panel-title">Scores</h3>
                {selectedRun.config_snapshot?.name && (
                  <span className="gr-eval-count">config: {selectedRun.config_snapshot.name}</span>
                )}
              </div>
              <div className="gr-score-hero">
                <div className="gr-hero-figure">
                  <span className="gr-hero-value">{percent(agg?.accuracy)}</span>
                  <span className="gr-hero-label">Accuracy</span>
                </div>
                <div className="gr-hero-aside">
                  <div className="gr-hero-stat">
                    <span className="gr-hero-stat-value">
                      {agg?.items_evaluated ?? "—"}
                      <span className="gr-hero-stat-of">
                        /{agg?.items_total ?? runItems.length}
                      </span>
                    </span>
                    <span className="gr-hero-stat-label">evaluated</span>
                  </div>
                  <div className="gr-hero-stat">
                    <span className="gr-hero-stat-value">{agg?.items_skipped ?? "—"}</span>
                    <span className="gr-hero-stat-label">skipped</span>
                  </div>
                  <div className="gr-hero-stat">
                    <span className="gr-hero-stat-value">{agg?.items_failed ?? "—"}</span>
                    <span className="gr-hero-stat-label">errored</span>
                  </div>
                </div>
              </div>
              <div className="gr-score-grid">
                <ScoreBar label="Precision" value={agg?.precision} />
                <ScoreBar label="Recall" value={agg?.recall} />
                <ScoreBar label="F1" value={agg?.f1} />
                <ScoreBar label="Guard match" value={agg?.guard_match_rate} />
              </div>
              <div className="gr-confusion-grid">
                {confusion.map((tile) => (
                  <div key={tile.key} className={`gr-confusion-tile gr-confusion-tile--${tile.tone}`}>
                    <span className="gr-confusion-key">{tile.key}</span>
                    <span className="gr-confusion-value">
                      {typeof tile.value === "number" ? tile.value : "—"}
                    </span>
                    <span className="gr-confusion-label">{tile.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {agg?.categories && Object.keys(agg.categories).length > 0 && (
            <div className="panel gr-eval-panel">
              <div className="panel-header">
                <h3 className="panel-title">By category</h3>
              </div>
              <div className="repo-table-wrap">
                <table className="repo-table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Items</th>
                      <th>Correct</th>
                      <th>Accuracy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(agg.categories).map(([name, c]) => (
                      <tr key={name}>
                        <td>{formatCategory(name)}</td>
                        <td className="mono">{c.item_count}</td>
                        <td className="mono">{c.correct}</td>
                        <td className="mono">{percent(c.accuracy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="panel">
            <div className="panel-header">
              <h3 className="panel-title">Item results</h3>
              <div className="gr-item-filters">
                <label className="field gr-inline-field" htmlFor="gr-eval-category">
                  <span className="field-label">Category</span>
                  <select
                    id="gr-eval-category"
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                  >
                    <option value="">All categories</option>
                    {categories.map((name) => (
                      <option key={name} value={name}>{formatCategory(name)}</option>
                    ))}
                  </select>
                </label>
                <span className="gr-eval-count">
                  {visibleItems.length} of {runItems.length} rows · config=
                  {selectedRun.config_snapshot?.name || "—"}
                </span>
              </div>
            </div>
            <div className="repo-table-wrap">
              <table className="repo-table">
                <thead>
                  <tr>
                    <th>Text</th>
                    <th>Phase</th>
                    <th>Category</th>
                    <th>Expected</th>
                    <th>Actual</th>
                    <th>Result</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleItems.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="muted">
                        No item rows for this run. Run an evaluation to fill the table.
                      </td>
                    </tr>
                  ) : (
                    visibleItems.map((row) => {
                      const verdict = verdictOf(row);
                      return (
                        <tr key={row.run_item_id} className={`gr-item-row--${verdict}`}>
                          <td className="gr-eval-text-cell" title={row.text}>
                            {row.text.length > 120 ? `${row.text.slice(0, 120)}…` : row.text}
                          </td>
                          <td>{row.phase}</td>
                          <td>{row.category ? formatCategory(row.category) : "—"}</td>
                          <td className="mono">
                            {row.expected_blocked ? `block:${row.expected_guard || "?"}` : "allow"}
                          </td>
                          <td className="mono">
                            {row.skipped
                              ? "skipped"
                              : row.actual_blocked
                                ? `block:${row.actual_guard || "?"}`
                                : "allow"}
                          </td>
                          <td>
                            <span className={`gr-verdict gr-verdict--${verdict}`}>
                              {VERDICT_LABEL[verdict]}
                            </span>
                          </td>
                          <td className="gr-item-note">
                            {verdict === "skipped" && (row.skip_reason || "Excluded by the config mode")}
                            {verdict === "failed" && (row.error_message || "The check raised an error")}
                            {verdict === "false-negative" && "Expected a block, the text passed"}
                            {verdict === "false-positive" && "No block expected, the text was blocked"}
                            {verdict === "guard-miss" &&
                              `Blocked by ${row.actual_guard || "another guard"}, expected ${row.expected_guard || "another guard"}`}
                            {verdict === "ok" && "—"}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {pendingDelete && (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={() => { if (!deleting) setPendingDelete(null); }}
          onKeyDown={(e) => { if (e.key === "Escape" && !deleting) setPendingDelete(null); }}
        >
          <div
            className="modal-panel modal-panel--sm"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="gr-eval-delete-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h3 className="modal-title" id="gr-eval-delete-title">Delete this golden dataset?</h3>
            </div>
            <div className="modal-body">
              <p className="gr-modal-body">
                <strong>{pendingDelete.name}</strong> and every run recorded against it are
                removed. This cannot be undone.
              </p>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setPendingDelete(null)}
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => void runDelete()}
                disabled={deleting}
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
