import { FormEvent, useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { IconEdit, IconPlus, IconTrash } from "../components/Icons";
import {
  ApiError,
  PromptTemplate,
  createPromptTemplate,
  deletePromptTemplate,
  listPromptTemplates,
  updatePromptTemplate,
} from "../api";

const PREVIEW_CHARS = 160;

const EMPTY_FORM = { name: "", description: "", content: "" };

function describeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

export default function PromptsPage() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listPromptTemplates();
      setTemplates(res.items ?? []);
      setError(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const closeModal = useCallback(() => {
    setIsOpen(false);
    setEditingId(null);
    setFormError(null);
  }, []);

  // Escape closes the modal, matching the close button.
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeModal();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, closeModal]);

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setIsOpen(true);
  }

  function openEdit(template: PromptTemplate) {
    setEditingId(template.id);
    setForm({
      name: template.name,
      description: template.description ?? "",
      content: template.content,
    });
    setFormError(null);
    setIsOpen(true);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const name = form.name.trim();
    const content = form.content.trim();
    if (!name) {
      setFormError("Name is required.");
      return;
    }
    if (!content) {
      setFormError("Content is required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const body = { name, description: form.description.trim() || null, content };
      if (editingId) {
        await updatePromptTemplate(editingId, body);
      } else {
        await createPromptTemplate(body);
      }
      closeModal();
      await load();
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(template: PromptTemplate) {
    if (!window.confirm(`Delete the prompt template "${template.name}"?`)) return;
    try {
      await deletePromptTemplate(template.id);
      await load();
    } catch (err) {
      setError(describeError(err));
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Prompts"
        description="A prompt template becomes an assistant's system message. The retrieved passages and the user question are sent separately."
        actions={
          <button type="button" className="btn btn-primary" onClick={openCreate}>
            <IconPlus /> Create prompt template
          </button>
        }
      />

      {error && <div className="alert alert-error">{error}</div>}

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "1rem",
          marginBottom: "1.5rem",
        }}
      >
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>
            {loading ? "—" : templates.length}
          </div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
            Prompt Templates
          </div>
        </div>
      </section>

      {loading ? (
        <div className="panel-empty">Loading prompt templates…</div>
      ) : templates.length === 0 ? (
        <div className="panel-empty">
          No prompt templates yet. Create one to give a pipeline its own behaviour.
        </div>
      ) : (
        <section style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {templates.map((template) => (
            <div className="panel" key={template.id} style={{ padding: "1.25rem" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "1rem",
                }}
              >
                <div>
                  <strong>{template.name}</strong>
                  {template.description && (
                    <div style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                      {template.description}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => openEdit(template)}
                    aria-label={`Edit ${template.name}`}
                  >
                    <IconEdit /> Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger btn-sm"
                    onClick={() => handleDelete(template)}
                    aria-label={`Delete ${template.name}`}
                  >
                    <IconTrash /> Delete
                  </button>
                </div>
              </div>
              <pre
                style={{
                  marginTop: "0.75rem",
                  padding: "0.75rem",
                  background: "rgba(0,0,0,0.3)",
                  borderRadius: 8,
                  fontFamily: "monospace",
                  fontSize: "0.8rem",
                  whiteSpace: "pre-wrap",
                  overflowX: "auto",
                }}
              >
                {template.content.length > PREVIEW_CHARS
                  ? `${template.content.slice(0, PREVIEW_CHARS)}…`
                  : template.content}
              </pre>
            </div>
          ))}
        </section>
      )}

      {isOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="prompt-template-modal-title"
          onClick={closeModal}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            background: "rgba(0,0,0,0.75)",
            backdropFilter: "blur(12px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "24px",
          }}
        >
          <form
            onSubmit={handleSubmit}
            onClick={(event) => event.stopPropagation()}
            style={{
              background: "#111622",
              border: "1px solid rgba(88,166,253,0.3)",
              borderRadius: 16,
              padding: "24px",
              width: "min(720px, 100%)",
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "0.5rem",
              }}
            >
              <h2 id="prompt-template-modal-title" style={{ margin: 0, fontSize: "1.1rem" }}>
                {editingId ? "Edit prompt template" : "Create prompt template"}
              </h2>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeModal}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <label className="field-label" htmlFor="prompt-template-name">
              Name
            </label>
            <input
              id="prompt-template-name"
              className="input"
              value={form.name}
              maxLength={128}
              autoFocus
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />

            <label className="field-label" htmlFor="prompt-template-description">
              Description (optional)
            </label>
            <input
              id="prompt-template-description"
              className="input"
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />

            <label className="field-label" htmlFor="prompt-template-content">
              Content
            </label>
            <textarea
              id="prompt-template-content"
              className="input"
              style={{ fontFamily: "monospace", minHeight: 220 }}
              value={form.content}
              onChange={(event) => setForm({ ...form, content: event.target.value })}
            />
            <p className="field-hint">
              This text becomes the assistant's system message. The retrieved passages and the user
              question are sent separately.
            </p>

            {formError && <div className="alert alert-error">{formError}</div>}

            <div
              style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "1rem" }}
            >
              <button type="button" className="btn btn-secondary" onClick={closeModal}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
