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

function ScoreBar({ label, value }: { label: string; value: number | null | undefined }) {
  const ratio = typeof value === "number" && !Number.isNaN(value) ? value : null;
  const width = ratio === null ? 0 : Math.max(0, Math.min(100, Math.round(ratio * 100)));
  return (
    <div className="gr-score">
      <div className="gr-score-head">
        <span className="gr-score-label">{label}</span>
        <span className="gr-score-value">{percent(ratio)}</span>
      </div>
      <div className="gr-bar-track" role="img" aria-label={`${label}: ${percent(ratio)}`}>
        <span className="gr-bar-fill" style={{ width: `${width}%` }} />
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

  async function onDeleteDataset(datasetId: string) {
    if (!window.confirm("Delete this guardrails golden dataset and all related runs?")) return;
    setBusy(true);
    try {
      await deleteGuardrailsGoldenDataset(datasetId);
      if (selectedDatasetId === datasetId) {
        setSelectedDatasetId(null);
        setSelectedRun(null);
        setRunItems([]);
      }
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  async function onStartRun() {
    if (!selectedDatasetId || !selectedConfigId) {
      setError("Select a dataset and guardrails configuration first");
      return;
    }
    setBusy(true);
    setError(null);
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

  const confusion = [
    { key: "TP", label: "True positives", value: agg?.true_positives, tone: "good" },
    { key: "TN", label: "True negatives", value: agg?.true_negatives, tone: "good" },
    { key: "FP", label: "False positives", value: agg?.false_positives, tone: "bad" },
    { key: "FN", label: "False negatives", value: agg?.false_negatives, tone: "bad" },
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
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void onSeedDataset()}
              disabled={busy}
            >
              {busy ? "Working…" : "Load bundled golden dataset"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => void refresh()} disabled={busy}>
              Refresh
            </button>
          </div>
        }
      />

      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1rem" }}>
        <div className="panel">
          <div className="panel-header">
            <h3 className="panel-title">Golden dataset</h3>
          </div>
          <div style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
            <label className="field">
              <span className="field-label">Upload JSON</span>
              <input
                type="file"
                accept="application/json,.json"
                disabled={busy}
                onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                checked={replaceOnUpload}
                onChange={(e) => setReplaceOnUpload(e.target.checked)}
              />
              <span className="muted">Replace if name already exists</span>
            </label>

            <label className="field">
              <span className="field-label">Dataset</span>
              <select
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
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => void onDeleteDataset(selectedDatasetId)}
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
          <div style={{ padding: "1rem", display: "grid", gap: "0.75rem" }}>
            <label className="field">
              <span className="field-label">Saved config from database</span>
              <select
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
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                No configs yet. Create one under Guard Config — the same list Chat uses.
              </p>
            )}

            {selectedConfig && (
              <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                id={selectedConfig.id.slice(0, 8)}… · mode={selectedConfig.mode} · guards=
                {(selectedConfig.guards || []).join(", ") || "—"} · settings for{" "}
                {Object.keys(selectedConfig.settings ?? {}).length} validator(s)
              </p>
            )}

            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !selectedDatasetId || !selectedConfigId}
              onClick={() => void onStartRun()}
            >
              {busy ? "Running…" : "Start guardrails evaluation"}
            </button>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: "1rem" }}>
        <div className="panel-header">
          <h3 className="panel-title">Runs</h3>
          <span className="muted" style={{ fontSize: "0.75rem" }}>
            {runsCount} total
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
                  <td colSpan={5} className="muted">
                    No runs yet for this dataset.
                  </td>
                </tr>
              ) : (
                runs.map((r) => (
                  <tr key={r.run_id} className={selectedRun?.run_id === r.run_id ? "is-selected" : undefined}>
                    <td className="mono">{formatRelativeTime(r.created_at || "")}</td>
                    <td>{r.status}</td>
                    <td>{r.config_snapshot?.name || r.config_id.slice(0, 8)}</td>
                    <td className="mono">{percent(r.aggregate_metrics?.accuracy)}</td>
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
                <span className="muted" style={{ fontSize: "0.75rem" }}>
                  {agg?.items_total ?? runItems.length} items · {agg?.items_evaluated ?? "—"} evaluated ·{" "}
                  {agg?.items_skipped ?? "—"} skipped
                </span>
              </div>
              <div className="gr-score-grid">
                <ScoreBar label="Accuracy" value={agg?.accuracy} />
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
            <div className="panel" style={{ marginBottom: "1rem" }}>
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
                <label className="field gr-inline-field">
                  <span className="field-label">Category</span>
                  <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                    <option value="">All categories</option>
                    {categories.map((name) => (
                      <option key={name} value={name}>{formatCategory(name)}</option>
                    ))}
                  </select>
                </label>
                <span className="muted" style={{ fontSize: "0.75rem" }}>
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
                          <td style={{ maxWidth: 360 }} title={row.text}>
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
    </div>
  );
}
