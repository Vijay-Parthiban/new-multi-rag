import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import {
  IconCheckCircle,
  IconCopy,
  IconGuardrails,
  IconPipeline,
  IconPrompts,
} from "../components/Icons";
import {
  ApiError,
  CreatePipelineRequest,
  GuardrailsConfig,
  KnowledgeProduct,
  PipelinePatchRequest,
  PipelineRecord,
  PromptTemplate,
  RAG_STRATEGY_LABELS,
  assistantBaseUrl,
  assistantChatUrl,
  createPipeline,
  deletePipeline,
  destinationStoreLabel,
  enabledRetrievalDestinations,
  getLiteLLMModels,
  listGuardrailsConfigs,
  listKnowledgeProducts,
  listPipelines,
  listPromptTemplates,
  strategiesForDestinations,
  updatePipeline,
} from "../api";

/** The ingestion manager owns the Knowledge Store UI. Same reason as src/api.ts for 127.0.0.1. */
const INGESTION_KNOWLEDGE_STORE_URL = "http://127.0.0.1:5173/knowledge-store";
/** The ingestion row rejects an empty embedding model, so this is the floor. */
const DEFAULT_EMBEDDING_MODEL = "nvidia-embed-textonly";

const CHIP_STYLE = {
  padding: "0.15rem 0.5rem",
  borderRadius: 999,
  border: "1px solid rgba(88, 166, 253, 0.3)",
  background: "rgba(56, 139, 253, 0.08)",
  fontSize: "0.72rem",
  color: "#8b949e",
  whiteSpace: "nowrap" as const,
};

type Draft = {
  name: string;
  description: string;
  knowledgeProductId: string;
  ragStrategy: string;
  promptTemplateId: string;
  guardrailsConfigId: string;
  chatModel: string;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  description: "",
  knowledgeProductId: "",
  ragStrategy: "",
  promptTemplateId: "",
  guardrailsConfigId: "",
  chatModel: "",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

/** The ingestion API sends the product's embedding model; the shared type predates that field. */
function productEmbeddingModel(product: KnowledgeProduct | null): string {
  const value = (product as { text_embedding_model?: string } | null)?.text_embedding_model;
  return (value ?? "").trim() || DEFAULT_EMBEDDING_MODEL;
}

function CopyEndpointButton({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      type="button"
      className="btn btn-secondary btn-sm"
      onClick={handleCopy}
      aria-label="Copy assistant endpoint"
      title={url}
    >
      {copied ? <IconCheckCircle size={12} /> : <IconCopy size={12} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** The seven assistant fields. One renderer serves both the create card and the edit modal. */
function PipelineFields({
  draft,
  setDraft,
  products,
  templates,
  guardrails,
  chatModels,
  loadingProducts,
  idPrefix,
  onNameRef,
  showErrors,
}: {
  draft: Draft;
  setDraft: (next: Draft) => void;
  products: KnowledgeProduct[];
  templates: PromptTemplate[];
  guardrails: GuardrailsConfig[];
  chatModels: { id: string; label: string }[];
  loadingProducts: boolean;
  idPrefix: string;
  onNameRef?: (el: HTMLInputElement | null) => void;
  showErrors: boolean;
}) {
  const product = products.find((p) => p.id === draft.knowledgeProductId) ?? null;
  const strategies = strategiesForDestinations(product?.destinations);
  const enabledTypes = enabledRetrievalDestinations(product?.destinations);
  const destinations = (product?.destinations ?? []).filter((d) => enabledTypes.has(d.destination_type));

  const nameError = draft.name.trim().length < 2 ? "The internal name needs at least 2 characters." : null;
  const descriptionError =
    draft.description.trim().length < 8 ? "The description needs at least 8 characters." : null;
  const strategyError = !draft.ragStrategy ? "Choose a RAG strategy." : null;
  const chatModelError = !draft.chatModel ? "Choose a chat model." : null;

  function fieldError(message: string | null, touched: boolean) {
    if (!message || !(showErrors || touched)) return null;
    return <p className="field-hint">{message}</p>;
  }

  function selectProduct(id: string) {
    const next = products.find((p) => p.id === id) ?? null;
    setDraft({
      ...draft,
      knowledgeProductId: id,
      // The old strategy may need a store the new product does not have.
      ragStrategy: strategiesForDestinations(next?.destinations)[0] ?? "",
    });
  }

  return (
    <>
      <label className="field-label" htmlFor={`${idPrefix}-name`}>
        Internal name
      </label>
      <input
        id={`${idPrefix}-name`}
        ref={onNameRef}
        className="input"
        value={draft.name}
        minLength={2}
        required
        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        placeholder="resume-screener"
      />
      {fieldError(nameError, draft.name.length > 0)}

      <label className="field-label" htmlFor={`${idPrefix}-description`}>
        Description
      </label>
      <input
        id={`${idPrefix}-description`}
        className="input"
        value={draft.description}
        minLength={8}
        required
        onChange={(e) => setDraft({ ...draft, description: e.target.value })}
        placeholder="Screens candidate resumes from the Knowledge Store"
      />
      <p className="field-hint">Shown as the assistant&apos;s name in chat.</p>
      {fieldError(descriptionError, draft.description.length > 0)}

      <label className="field-label" htmlFor={`${idPrefix}-product`}>
        Knowledge Product
      </label>
      <select
        id={`${idPrefix}-product`}
        className="input"
        value={draft.knowledgeProductId}
        required
        onChange={(e) => selectProduct(e.target.value)}
      >
        <option value="" disabled>
          Select a product…
        </option>
        {products.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} — {enabledRetrievalDestinations(p.destinations).size} destinations
          </option>
        ))}
      </select>
      {loadingProducts && <p className="field-hint">Loading knowledge products…</p>}
      {destinations.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.4rem",
            margin: "0.4rem 0 1rem",
          }}
        >
          {destinations.map((d) => (
            <span key={d.destination_type} style={CHIP_STYLE}>
              {destinationStoreLabel(d) ?? d.destination_type}
            </span>
          ))}
        </div>
      )}

      <label className="field-label" htmlFor={`${idPrefix}-strategy`}>
        RAG Strategy
      </label>
      <select
        id={`${idPrefix}-strategy`}
        className="input"
        value={draft.ragStrategy}
        required
        disabled={strategies.length === 0}
        onChange={(e) => setDraft({ ...draft, ragStrategy: e.target.value })}
      >
        <option value="" disabled>
          Select a strategy…
        </option>
        {strategies.map((id) => (
          <option key={id} value={id}>
            {RAG_STRATEGY_LABELS[id]?.label ?? id} — {RAG_STRATEGY_LABELS[id]?.description ?? ""}
          </option>
        ))}
      </select>
      {strategies.length === 0 && draft.knowledgeProductId ? (
        <p className="field-hint">
          This product has no enabled retrieval destination. Enable one in the Ingestion Manager.
        </p>
      ) : (
        fieldError(strategyError, strategies.length > 0)
      )}

      <label className="field-label" htmlFor={`${idPrefix}-prompt`}>
        Prompt Template
      </label>
      <select
        id={`${idPrefix}-prompt`}
        className="input"
        value={draft.promptTemplateId}
        onChange={(e) => setDraft({ ...draft, promptTemplateId: e.target.value })}
      >
        <option value="">None (default RAG prompt)</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>

      <label className="field-label" htmlFor={`${idPrefix}-guardrails`}>
        Guardrails Config
      </label>
      <select
        id={`${idPrefix}-guardrails`}
        className="input"
        value={draft.guardrailsConfigId}
        onChange={(e) => setDraft({ ...draft, guardrailsConfigId: e.target.value })}
      >
        <option value="">None</option>
        {guardrails.map((g) => (
          <option key={g.id} value={g.id}>
            {g.name}
            {g.is_active ? "" : " (inactive)"}
          </option>
        ))}
      </select>

      <label className="field-label" htmlFor={`${idPrefix}-model`}>
        Chat Model
      </label>
      <select
        id={`${idPrefix}-model`}
        className="input mono"
        value={draft.chatModel}
        required
        onChange={(e) => setDraft({ ...draft, chatModel: e.target.value })}
      >
        <option value="" disabled>
          Select a model…
        </option>
        {chatModels.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label || m.id}
          </option>
        ))}
      </select>
      {fieldError(chatModelError, draft.chatModel.length > 0)}
    </>
  );
}

export default function PipelinesPage() {
  const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [guardrails, setGuardrails] = useState<GuardrailsConfig[]>([]);
  const [chatModels, setChatModels] = useState<{ id: string; label: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [created, setCreated] = useState<PipelineRecord | null>(null);
  const [selectedPipelineId, setSelectedPipelineId] = useState<string | null>(null);

  const [editing, setEditing] = useState<PipelineRecord | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editShowErrors, setEditShowErrors] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const editNameRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    // One failed call must not blank the page, so every call keeps its own fallback.
    let firstError: unknown;
    const capture = <T,>(promise: Promise<T>, fallback: T): Promise<T> =>
      promise.catch((err) => {
        if (firstError === undefined) firstError = err;
        return fallback;
      });

    const [pipes, prods, tpls, grds, models] = await Promise.all([
      capture(listPipelines(), [] as PipelineRecord[]),
      capture(listKnowledgeProducts(), [] as KnowledgeProduct[]),
      capture(listPromptTemplates(), { count: 0, items: [] as PromptTemplate[] }),
      capture(listGuardrailsConfigs(), { count: 0, items: [] as GuardrailsConfig[] }),
      capture(getLiteLLMModels("chat"), [] as { id: string; label: string }[]),
    ]);

    setPipelines(pipes);
    setProducts(prods);
    setTemplates(tpls.items ?? []);
    setGuardrails(grds.items ?? []);
    setChatModels(models);
    setError(firstError === undefined ? null : describeError(firstError));
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Escape closes the edit modal, matching its close glyph.
  useEffect(() => {
    if (!editing) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeEdit();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editing]);

  useEffect(() => {
    if (editing) editNameRef.current?.focus();
  }, [editing]);

  const eligibleProducts = useMemo(
    () => products.filter((p) => enabledRetrievalDestinations(p.destinations).size > 0),
    [products],
  );

  const selectedPipeline = pipelines.find((p) => p.id === selectedPipelineId) ?? null;
  const selectedStoreDestinations = (selectedPipeline?.knowledge_product?.destinations ?? []).filter((d) =>
    enabledRetrievalDestinations([d]).has(d.destination_type),
  );

  const canCreate =
    draft.name.trim().length >= 2 &&
    draft.description.trim().length >= 8 &&
    draft.knowledgeProductId.length > 0 &&
    draft.ragStrategy.length > 0 &&
    draft.chatModel.length > 0;

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setShowErrors(true);
    if (!canCreate) return;
    setSubmitting(true);
    setFormError(null);
    try {
      const product = products.find((p) => p.id === draft.knowledgeProductId) ?? null;
      const body: CreatePipelineRequest = {
        name: draft.name.trim(),
        description: draft.description.trim(),
        knowledge_product_id: draft.knowledgeProductId,
        rag_strategy: draft.ragStrategy,
        chat_model: draft.chatModel,
        prompt_template_id: draft.promptTemplateId || null,
        guardrails_config_id: draft.guardrailsConfigId || null,
        embedding_model: productEmbeddingModel(product),
      };
      const record = await createPipeline(body);
      setCreated(record);
      setDraft(EMPTY_DRAFT);
      setShowErrors(false);
      setSelectedPipelineId(record.id);
      await load();
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  function openEdit(pipeline: PipelineRecord) {
    setEditDraft({
      name: pipeline.name,
      description: pipeline.description,
      knowledgeProductId: pipeline.knowledge_product?.id ?? pipeline.knowledge_product_id ?? "",
      ragStrategy: pipeline.rag_strategy,
      promptTemplateId: pipeline.prompt_template_id ?? "",
      guardrailsConfigId: pipeline.guardrails_config_id ?? "",
      chatModel: pipeline.chat_model ?? "",
    });
    setEditShowErrors(false);
    setFormError(null);
    setEditing(pipeline);
  }

  function closeEdit() {
    setEditing(null);
    setFormError(null);
  }

  async function handleEditSubmit(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditShowErrors(true);
    const product = products.find((p) => p.id === editDraft.knowledgeProductId) ?? null;
    const complete =
      editDraft.name.trim().length >= 2 &&
      editDraft.description.trim().length >= 8 &&
      editDraft.knowledgeProductId.length > 0 &&
      editDraft.ragStrategy.length > 0 &&
      editDraft.chatModel.length > 0;
    if (!complete) return;
    setSavingEdit(true);
    setFormError(null);
    try {
      const body: PipelinePatchRequest = {
        name: editDraft.name.trim(),
        description: editDraft.description.trim(),
        embedding_model: productEmbeddingModel(product),
        rag_strategy: editDraft.ragStrategy,
        chat_model: editDraft.chatModel,
        knowledge_product_id: editDraft.knowledgeProductId,
        // null, not undefined: the backend reads a present null as "detach".
        prompt_template_id: editDraft.promptTemplateId || null,
        guardrails_config_id: editDraft.guardrailsConfigId || null,
      };
      await updatePipeline(editing.id, body);
      closeEdit();
      await load();
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleDelete(pipeline: PipelineRecord) {
    if (!window.confirm(`Delete the assistant "${pipeline.name}"?`)) return;
    try {
      await deletePipeline(pipeline.id);
      if (selectedPipelineId === pipeline.id) setSelectedPipelineId(null);
      if (created?.id === pipeline.id) setCreated(null);
      await load();
    } catch (err) {
      setError(describeError(err));
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Pipelines"
        description="A pipeline is a chat assistant: one Knowledge Product, one RAG strategy, one chat model, plus an optional prompt template and guardrails config."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Pipelines" }]}
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => load()}>
            Refresh assistants
          </button>
        }
      />

      {error && <div className="alert alert-error">{error}</div>}

      <div className="stats-overview-grid" style={{ marginBottom: "1.5rem" }}>
        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">Total Pipelines</div>
            <div className="stats-overview-value">{pipelines.length}</div>
            <div className="stats-overview-subtext">Every assistant with its own endpoint</div>
          </div>
          <div className="stats-overview-icon stats-icon--blue">
            <IconPipeline size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">With Guardrails</div>
            <div className="stats-overview-value">
              {pipelines.filter((p) => p.guardrails_config_id).length}
            </div>
            <div className="stats-overview-subtext">Answers pass a guardrails config first</div>
          </div>
          <div className="stats-overview-icon stats-icon--green">
            <IconGuardrails size={22} />
          </div>
        </div>

        <div className="stats-overview-card">
          <div>
            <div className="stats-overview-label">With Prompt Templates</div>
            <div className="stats-overview-value">
              {pipelines.filter((p) => p.prompt_template_id).length}
            </div>
            <div className="stats-overview-subtext">The template is the system message</div>
          </div>
          <div className="stats-overview-icon stats-icon--purple">
            <IconPrompts size={22} />
          </div>
        </div>
      </div>

      {created?.slug && (
        <section className="panel" style={{ marginBottom: "1.5rem" }}>
          <div className="panel-header">
            <h2 className="panel-title">Assistant ready</h2>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setCreated(null)}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <div className="form-body">
            <p>
              <strong>{created.name}</strong> is live. Point an OpenAI client at the base URL, and the
              SDK appends <span className="mono">/chat/completions</span>.
            </p>
            <p className="mono" style={{ fontSize: "0.8rem" }}>
              {assistantBaseUrl(created.slug)}
            </p>
            <p className="mono muted" style={{ fontSize: "0.8rem" }}>
              Native chat: {assistantChatUrl(created.slug)}
            </p>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <CopyEndpointButton url={assistantBaseUrl(created.slug)} />
              <Link to="/chat" className="btn btn-secondary btn-sm">
                Open in Chat
              </Link>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setCreated(null)}>
                Close
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="pipeline-layout">
        <form className="panel pipeline-form" onSubmit={handleCreate}>
          <div className="panel-header">
            <h2 className="panel-title">New assistant</h2>
          </div>
          <fieldset
            className="form-body"
            disabled={loading || submitting}
            style={{ border: 0, margin: 0, minWidth: 0 }}
          >
            <PipelineFields
              draft={draft}
              setDraft={setDraft}
              products={eligibleProducts}
              templates={templates}
              guardrails={guardrails}
              chatModels={chatModels}
              loadingProducts={loading}
              idPrefix="create"
              showErrors={showErrors}
            />
            {formError && <div className="alert alert-error">{formError}</div>}
            <button type="submit" className="btn btn-primary" disabled={loading || submitting || !canCreate}>
              {submitting ? "Creating…" : "Create assistant"}
            </button>
          </fieldset>
        </form>

        <section className="panel pipeline-list-panel">
          <div className="panel-header">
            <h2 className="panel-title">Saved assistants</h2>
          </div>
          {loading ? (
            <p className="panel-empty muted">Loading assistants…</p>
          ) : pipelines.length === 0 ? (
            <p className="panel-empty muted">No pipelines configured yet.</p>
          ) : (
            <ul className="pipeline-list">
              {pipelines.map((p) => (
                <li
                  key={p.id}
                  className={selectedPipelineId === p.id ? "active" : ""}
                  style={{ alignItems: "flex-start" }}
                >
                  <button
                    type="button"
                    className="pipeline-list-item"
                    style={{ textAlign: "left" }}
                    onClick={() => setSelectedPipelineId(p.id)}
                  >
                    <strong>{p.description}</strong>
                    <span className="muted">
                      {p.name} · {RAG_STRATEGY_LABELS[p.rag_strategy]?.label ?? p.rag_strategy}
                    </span>
                    {p.knowledge_product && (
                      <span className="muted">Knowledge Product: {p.knowledge_product.name}</span>
                    )}
                    <span className="muted mono">{p.chat_model ?? "No chat model"}</span>
                    <span style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", margin: "0.25rem 0" }}>
                      <span style={CHIP_STYLE}>
                        {templates.find((t) => t.id === p.prompt_template_id)?.name ?? "No prompt"}
                      </span>
                      <span style={CHIP_STYLE}>
                        {guardrails.find((g) => g.id === p.guardrails_config_id)?.name ?? "No guardrails"}
                      </span>
                    </span>
                    <span className="muted mono" style={{ fontSize: "0.78rem" }}>
                      {p.slug ? assistantBaseUrl(p.slug) : "No endpoint"}
                    </span>
                  </button>
                  <div style={{ display: "flex", gap: "0.4rem", marginLeft: "0.5rem", flexWrap: "wrap" }}>
                    {p.slug && <CopyEndpointButton url={assistantBaseUrl(p.slug)} />}
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => openEdit(p)}
                      aria-label={`Edit ${p.name}`}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDelete(p)}
                      aria-label={`Delete ${p.name}`}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {selectedPipeline && (
            <div className="runs-section" style={{ marginTop: "2rem" }}>
              <h3 className="runs-title">Assistant summary</h3>
              <div className="panel" style={{ background: "var(--bg-inset)", marginTop: "1rem" }}>
                <div className="form-body">
                  {selectedPipeline.knowledge_product ? (
                    <p style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                      <strong>{selectedPipeline.knowledge_product.name}</strong>
                      <StatusBadge status={selectedPipeline.knowledge_product.status} />
                    </p>
                  ) : (
                    <p className="muted">This pipeline has no Knowledge Product.</p>
                  )}

                  <div style={{ marginTop: "0.75rem" }}>
                    <div className="muted" style={{ fontSize: "0.78rem" }}>
                      Stores read
                    </div>
                    {selectedStoreDestinations.length === 0 ? (
                      <p className="field-hint">No enabled retrieval destination.</p>
                    ) : (
                      selectedStoreDestinations.map((d) => {
                        const store = destinationStoreLabel(d) ?? d.destination_type;
                        const table = d.config?.table_name as string | undefined;
                        return (
                          <div key={d.destination_type} className="mono muted" style={{ fontSize: "0.8rem" }}>
                            {d.destination_type}: {store}
                            {table ? `.${table}` : ""}
                          </div>
                        );
                      })
                    )}
                  </div>

                  <div className="muted" style={{ fontSize: "0.8rem", marginTop: "0.75rem" }}>
                    Strategy:{" "}
                    <span className="mono">
                      {RAG_STRATEGY_LABELS[selectedPipeline.rag_strategy]?.label ??
                        selectedPipeline.rag_strategy}
                    </span>
                    <br />
                    Chat model: <span className="mono">{selectedPipeline.chat_model ?? "—"}</span>
                    <br />
                    Prompt template:{" "}
                    {templates.find((t) => t.id === selectedPipeline.prompt_template_id)?.name ??
                      "No prompt"}
                    <br />
                    Guardrails:{" "}
                    {guardrails.find((g) => g.id === selectedPipeline.guardrails_config_id)?.name ??
                      "No guardrails"}
                    <br />
                    Created: {new Date(selectedPipeline.created_at).toLocaleString()}
                    <br />
                    Updated: {new Date(selectedPipeline.updated_at).toLocaleString()}
                  </div>
                </div>
              </div>
            </div>
          )}

          {!loading && eligibleProducts.length === 0 && (
            <div className="panel-empty">
              No Knowledge Product has an enabled retrieval destination yet.{" "}
              <a href={INGESTION_KNOWLEDGE_STORE_URL} target="_blank" rel="noreferrer">
                Open the Knowledge Store
              </a>
              .
            </div>
          )}
        </section>
      </div>

      {editing && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="pipeline-modal-title"
          onClick={closeEdit}
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
            onSubmit={handleEditSubmit}
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
            <div className="page-header-row">
              <h2 id="pipeline-modal-title">Edit pipeline</h2>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeEdit}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <PipelineFields
              draft={editDraft}
              setDraft={setEditDraft}
              products={eligibleProducts}
              templates={templates}
              guardrails={guardrails}
              chatModels={chatModels}
              loadingProducts={loading}
              idPrefix="edit"
              showErrors={editShowErrors}
              onNameRef={(el) => {
                editNameRef.current = el;
              }}
            />

            {formError && <div className="alert alert-error">{formError}</div>}

            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
              <button type="button" className="btn btn-secondary" onClick={closeEdit}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={savingEdit}>
                {savingEdit ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
