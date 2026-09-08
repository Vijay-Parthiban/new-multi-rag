import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { listGuardrailsConfigs, type GuardrailsConfig } from "../api";
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

function formatMetric(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

function formatCategory(name: string): string {
  if (name.toLowerCase() === "pii") return "PII";
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function BoolPill({ value, ok }: { value: string; ok?: boolean | null }) {
  const color =
    ok === true ? "var(--success, #10b981)" : ok === false ? "var(--danger, #ef4444)" : "var(--muted)";
  return (
    <span className="mono" style={{ color, fontWeight: 600 }}>
      {value}
    </span>
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

  return (
    <div className="page">
      <PageHeader
        title="Guardrails Offline Evaluation"
        description="Upload a golden dataset, pick one of the Guard Configs already saved in the database (the same ones Chat applies), and score block accuracy against that config."
        breadcrumbs={[
          { label: "Overview", to: "/" },
          { label: "Guardrails Evaluation" },
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
                {(selectedConfig.guards || []).join(", ") || "—"}
                {selectedConfig.settings?.banned_words?.length
                  ? ` · ban=${selectedConfig.settings.banned_words.length} words`
                  : ""}
                {selectedConfig.settings?.pii_entities?.length
                  ? ` · pii=${selectedConfig.settings.pii_entities.length} types`
                  : ""}
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
                    <td className="mono">{formatMetric(r.aggregate_metrics?.accuracy)}</td>
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
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.75rem", marginBottom: "1rem" }}>
            {[
              ["Accuracy", agg?.accuracy],
              ["Precision", agg?.precision],
              ["Recall", agg?.recall],
              ["F1", agg?.f1],
              ["Guard match", agg?.guard_match_rate],
              ["Evaluated", agg?.items_evaluated],
              ["Skipped", agg?.items_skipped],
            ].map(([label, value]) => (
              <div key={String(label)} className="panel" style={{ padding: "0.85rem 1rem" }}>
                <div className="muted" style={{ fontSize: "0.75rem" }}>{label}</div>
                <div className="mono" style={{ fontSize: "1.15rem", fontWeight: 600 }}>
                  {typeof value === "number" ? (label === "Evaluated" || label === "Skipped" ? value : formatMetric(value)) : "—"}
                </div>
              </div>
            ))}
          </div>

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
                        <td className="mono">{formatMetric(c.accuracy)}</td>
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
              <span className="muted" style={{ fontSize: "0.75rem" }}>
                {runItems.length} rows · config={selectedRun.config_snapshot?.name || "—"}
              </span>
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
                    <th>Block OK</th>
                    <th>Guard OK</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {runItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="muted">
                        Select a run to inspect item-level results.
                      </td>
                    </tr>
                  ) : (
                    runItems.map((row) => (
                      <tr key={row.run_item_id}>
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
                          <BoolPill
                            value={row.correct_block == null ? "—" : row.correct_block ? "yes" : "no"}
                            ok={row.correct_block}
                          />
                        </td>
                        <td>
                          <BoolPill
                            value={row.correct_guard == null ? "—" : row.correct_guard ? "yes" : "no"}
                            ok={row.correct_guard}
                          />
                        </td>
                        <td>
                          {row.skipped ? (
                            <span className="muted" title={row.skip_reason || undefined}>
                              skipped
                            </span>
                          ) : (
                            row.status
                          )}
                        </td>
                      </tr>
                    ))
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
