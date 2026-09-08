import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import {
  PromptDetail,
  PromptSummary,
  getPrompt,
  listPrompts,
  resetAllPrompts,
  resetPrompt,
  updatePrompt,
  updatePromptsBulk,
} from "../api";

type DraftMap = Record<string, string>;

export default function PromptsPage() {
  const location = useLocation();
  const isVisible = location.pathname === "/prompts";

  const [items, setItems] = useState<PromptSummary[]>([]);
  const [overridesDir, setOverridesDir] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [busyAll, setBusyAll] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PromptDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [showPackaged, setShowPackaged] = useState(false);

  /** Multi-edit drafts keyed by prompt id (for Save all dirty). */
  const [bulkDrafts, setBulkDrafts] = useState<DraftMap>({});

  const loadList = useCallback(async () => {
    try {
      const res = await listPrompts();
      setItems(res.items);
      setOverridesDir(res.overrides_dir);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load prompts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    setLoading(true);
    void loadList();
  }, [isVisible, loadList]);

  const overriddenCount = useMemo(
    () => items.filter((i) => i.is_overridden).length,
    [items],
  );

  const dirtyBulkIds = useMemo(() => Object.keys(bulkDrafts), [bulkDrafts]);

  const openEditor = async (id: string) => {
    setBusyId(id);
    setMessage(null);
    setError(null);
    try {
      const d = await getPrompt(id);
      setDetail(d);
      setDraft(bulkDrafts[id] ?? d.active_content);
      setEditingId(id);
      setShowPackaged(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load prompt");
    } finally {
      setBusyId(null);
    }
  };

  const closeEditor = () => {
    setEditingId(null);
    setDetail(null);
    setDraft("");
    setShowPackaged(false);
  };

  const handleSave = async () => {
    if (!editingId || !draft.trim()) return;
    setBusyId(editingId);
    setMessage(null);
    try {
      const updated = await updatePrompt(editingId, draft);
      setDetail(updated);
      setDraft(updated.active_content);
      setBulkDrafts((prev) => {
        const next = { ...prev };
        delete next[editingId];
        return next;
      });
      setMessage(`Saved override for ${updated.filename}. Runtime will use this until reset.`);
      await loadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save prompt");
    } finally {
      setBusyId(null);
    }
  };

  const handleResetOne = async (id: string) => {
    setBusyId(id);
    setMessage(null);
    try {
      const updated = await resetPrompt(id);
      setBulkDrafts((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      if (editingId === id) {
        setDetail(updated);
        setDraft(updated.active_content);
      }
      setMessage(`Reset ${updated.filename} to the packaged prompt.`);
      await loadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reset prompt");
    } finally {
      setBusyId(null);
    }
  };

  const handleResetAll = async () => {
    if (!window.confirm("Reset all prompt overrides and restore packaged system prompts?")) {
      return;
    }
    setBusyAll(true);
    setMessage(null);
    try {
      await resetAllPrompts();
      setBulkDrafts({});
      if (editingId) {
        const d = await getPrompt(editingId);
        setDetail(d);
        setDraft(d.active_content);
      }
      setMessage("All prompt overrides cleared. Using packaged system prompts.");
      await loadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reset prompts");
    } finally {
      setBusyAll(false);
    }
  };

  const handleSaveAllDirty = async () => {
    const entries = Object.entries(bulkDrafts).filter(([, c]) => c.trim().length > 0);
    if (entries.length === 0) return;
    setBusyAll(true);
    setMessage(null);
    try {
      await updatePromptsBulk(entries.map(([id, content]) => ({ id, content })));
      setBulkDrafts({});
      if (editingId) {
        const d = await getPrompt(editingId);
        setDetail(d);
        setDraft(d.active_content);
      }
      setMessage(`Saved ${entries.length} prompt override(s).`);
      await loadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save prompts");
    } finally {
      setBusyAll(false);
    }
  };

  const onDraftChange = (value: string) => {
    setDraft(value);
    if (editingId) {
      setBulkDrafts((prev) => ({ ...prev, [editingId]: value }));
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Prompt Templates"
        description="View packaged system prompts and apply temporary overrides. Overrides are stored in a temp directory and preferred at runtime until you reset."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Prompts" }]}
        actions={
          <div className="page-actions-row">
            {dirtyBulkIds.length > 0 && (
              <button
                type="button"
                className="btn btn-primary"
                disabled={busyAll}
                onClick={() => void handleSaveAllDirty()}
              >
                Save all edits ({dirtyBulkIds.length})
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary"
              disabled={busyAll || overriddenCount === 0}
              onClick={() => void handleResetAll()}
            >
              Reset all
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={loading || busyAll}
              onClick={() => {
                setLoading(true);
                void loadList();
              }}
            >
              Refresh
            </button>
          </div>
        }
      />

      {overridesDir && (
        <p className="muted prompts-meta">
          Overrides dir: <code>{overridesDir}</code>
          {overriddenCount > 0 ? ` · ${overriddenCount} custom` : " · using packaged defaults"}
        </p>
      )}

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      {loading ? (
        <p className="muted">Loading prompts…</p>
      ) : (
        <div className="prompts-layout">
          <div className="prompts-list">
            {items.map((item) => {
              const selected = editingId === item.id;
              const dirty = item.id in bulkDrafts;
              return (
                <article
                  key={item.id}
                  className={`panel prompts-card${selected ? " prompts-card--active" : ""}`}
                >
                  <div className="prompts-card-head">
                    <div>
                      <h2 className="panel-title">{item.label}</h2>
                      <p className="muted prompts-card-desc">{item.description}</p>
                      <p className="prompts-card-file">
                        <code>{item.filename}</code>
                        <span className="muted"> · {item.package}</span>
                      </p>
                    </div>
                    <div className="prompts-card-badges">
                      {item.is_overridden ? (
                        <span className="prompt-badge prompt-badge--custom">Custom</span>
                      ) : (
                        <span className="prompt-badge">Packaged</span>
                      )}
                      {dirty && <span className="prompt-badge prompt-badge--dirty">Unsaved</span>}
                    </div>
                  </div>
                  <p className="prompts-preview muted">{item.preview}</p>
                  <div className="prompts-card-actions">
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={busyId === item.id}
                      onClick={() => void openEditor(item.id)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      disabled={!item.is_overridden || busyId === item.id}
                      onClick={() => void handleResetOne(item.id)}
                    >
                      Reset
                    </button>
                  </div>
                </article>
              );
            })}
          </div>

          <aside className={`panel prompts-editor${editingId ? "" : " prompts-editor--empty"}`}>
            {!detail || !editingId ? (
              <p className="panel-empty muted">Select a prompt and click Edit to view or change it.</p>
            ) : (
              <>
                <div className="prompts-editor-head">
                  <div>
                    <h2 className="panel-title">{detail.label}</h2>
                    <p className="muted">
                      <code>{detail.filename}</code>
                      {detail.is_overridden ? " · active override" : " · packaged default"}
                    </p>
                  </div>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={closeEditor}>
                    Close
                  </button>
                </div>

                <div className="prompts-editor-toolbar">
                  <label className="prompts-toggle">
                    <input
                      type="checkbox"
                      checked={showPackaged}
                      onChange={(e) => setShowPackaged(e.target.checked)}
                    />
                    Show packaged original
                  </label>
                </div>

                {showPackaged && (
                  <div className="prompts-packaged">
                    <p className="panel-toolbar-label">Packaged (read-only)</p>
                    <pre className="prompts-pre">{detail.packaged_content}</pre>
                  </div>
                )}

                <label className="panel-toolbar-label" htmlFor="prompt-draft">
                  Active prompt (saved to temp override on Save)
                </label>
                <textarea
                  id="prompt-draft"
                  className="input prompts-textarea"
                  value={draft}
                  onChange={(e) => onDraftChange(e.target.value)}
                  rows={18}
                  spellCheck={false}
                />

                <div className="prompts-editor-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busyId === editingId || !draft.trim()}
                    onClick={() => void handleSave()}
                  >
                    Save override
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={!detail.is_overridden || busyId === editingId}
                    onClick={() => void handleResetOne(editingId)}
                  >
                    Reset to packaged
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={busyId === editingId}
                    onClick={() => {
                      setDraft(detail.packaged_content);
                      setBulkDrafts((prev) => ({ ...prev, [editingId]: detail.packaged_content }));
                    }}
                  >
                    Copy packaged into editor
                  </button>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
