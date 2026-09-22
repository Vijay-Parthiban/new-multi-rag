import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import {
  IconCheckCircle,
  IconClose,
  IconCopy,
  IconDelete,
  IconEdit,
  IconGuardrails,
  IconPipeline,
  IconPlus,
  IconPrompts,
  IconRefresh,
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
  assistantSessionUrl,
  sessionMemoryFor,
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

/**
 * One labelled URL with its own copy control. The pipeline hands out two endpoints, so the
 * label matters more than the URL does.
 */
function EndpointRow({ label, url, hint }: { label: string; url: string; hint?: string }) {
  return (
    <div className="endpoint-row">
      <div className="endpoint-label">
        {label}
        {hint && <span className="endpoint-hint">{hint}</span>}
      </div>
      <div className="endpoint-value">
        <code>{url}</code>
        <CopyEndpointButton url={url} />
      </div>
    </div>
  );
}

/**
 * One dialog shell for create, view and edit. Escape closes it, a click on the scrim closes it,
 * focus moves inside on open, and the background cannot scroll while it is up.
 */
function Modal({
  title,
  onClose,
  children,
  footer,
  size = "md",
  initialFocus,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg" | "sm";
  initialFocus?: { current: HTMLElement | null };
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    (initialFocus?.current ?? panelRef.current)?.focus();
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose, initialFocus]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        ref={panelRef}
        className={`modal-panel modal-panel--${size}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <IconClose size={14} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

/** Delete asks for a second click. It names the pipeline and says what stops working. */
function ConfirmDeleteDialog({
  pipeline,
  busy,
  onCancel,
  onConfirm,
}: {
  pipeline: PipelineRecord;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-panel modal-panel--sm"
        role="alertdialog"
        aria-modal="true"
        aria-label={`Delete ${pipeline.name}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="confirm-body">
          <div className="confirm-icon">
            <IconDelete size={20} />
          </div>
          <h2 className="confirm-title">Delete this pipeline?</h2>
          <p className="confirm-text">
            <strong>{pipeline.description || pipeline.name}</strong> will be removed permanently.
          </p>
          {pipeline.slug && (
            <p className="confirm-text confirm-text--warn">
              Its endpoint <code>{assistantBaseUrl(pipeline.slug)}</code> stops working immediately. Any
              client pointing at it will fail.
            </p>
          )}
          <p className="confirm-text muted">This cannot be undone.</p>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Deleting…" : "Delete pipeline"}
          </button>
        </div>
      </div>
    </div>
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
  const [showCreate, setShowCreate] = useState(false);
  const [viewing, setViewing] = useState<PipelineRecord | null>(null);

  const [editing, setEditing] = useState<PipelineRecord | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(EMPTY_DRAFT);
  const [editShowErrors, setEditShowErrors] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);

  const [deleting, setDeleting] = useState<PipelineRecord | null>(null);
  const [deletingBusy, setDeletingBusy] = useState(false);
  const createNameRef = useRef<HTMLInputElement | null>(null);
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

  // Escape and initial focus are the Modal's job now, so no per-dialog listener lives here.
  const eligibleProducts = useMemo(
    () => products.filter((p) => enabledRetrievalDestinations(p.destinations).size > 0),
    [products],
  );

  /** Newest first, so a pipeline created a moment ago is the first card in the grid. */
  const sortedPipelines = useMemo(
    () =>
      [...pipelines].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [pipelines],
  );

  const viewingStoreDestinations = (viewing?.knowledge_product?.destinations ?? []).filter((d) =>
    enabledRetrievalDestinations([d]).has(d.destination_type),
  );
  const viewingMemory = sessionMemoryFor(viewing?.knowledge_product?.destinations);

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
      await createPipeline(body);
      setDraft(EMPTY_DRAFT);
      setShowErrors(false);
      // The card appears in the grid; the dialog closes. The endpoint is one click away on it.
      setShowCreate(false);
      await load();
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  function openCreate() {
    setDraft(EMPTY_DRAFT);
    setShowErrors(false);
    setFormError(null);
    setShowCreate(true);
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
    setViewing(null);
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
    setDeletingBusy(true);
    try {
      await deletePipeline(pipeline.id);
      setDeleting(null);
      setViewing(null);
      await load();
    } catch (err) {
      setDeleting(null);
      setError(describeError(err));
    } finally {
      setDeletingBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        title="Pipelines"
        description="A pipeline is a chat assistant: one Knowledge Product, one RAG strategy, one chat model, plus an optional prompt template and guardrails config."
        breadcrumbs={[{ label: "Overview", to: "/" }, { label: "Pipelines" }]}
        actions={
          <div className="header-actions">
            <button type="button" className="btn btn-primary" onClick={openCreate}>
              <IconPlus size={14} />
              Create Pipeline
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => load()}
              disabled={loading}
            >
              <IconRefresh size={14} />
              Refresh
            </button>
          </div>
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

      {loading ? (
        <p className="panel-empty muted">Loading pipelines…</p>
      ) : sortedPipelines.length === 0 ? (
        <div className="panel-empty">
          No pipelines yet. Select <strong>Create Pipeline</strong> to build one.
        </div>
      ) : (
        <div className="pipeline-cards">
          {sortedPipelines.map((p) => (
            <article
              key={p.id}
              className="pipeline-card"
              role="button"
              tabIndex={0}
              aria-label={`Open ${p.name}`}
              onClick={() => setViewing(p)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setViewing(p);
                }
              }}
            >
              <div className="pipeline-card-head">
                <h3 className="pipeline-card-name">{p.name}</h3>
                <span className="pipeline-card-strategy">
                  {RAG_STRATEGY_LABELS[p.rag_strategy]?.label ?? p.rag_strategy}
                </span>
              </div>

              <p className="pipeline-card-desc">{p.description}</p>

              <dl className="pipeline-card-meta">
                <div>
                  <dt>Knowledge Product</dt>
                  <dd>{p.knowledge_product?.name ?? "—"}</dd>
                </div>
                <div>
                  <dt>Chat model</dt>
                  <dd className="mono">{p.chat_model ?? "—"}</dd>
                </div>
              </dl>

              <div className="pipeline-card-chips">
                <span className="pipeline-chip">
                  {templates.find((t) => t.id === p.prompt_template_id)?.name ?? "No prompt"}
                </span>
                <span className="pipeline-chip">
                  {guardrails.find((g) => g.id === p.guardrails_config_id)?.name ?? "No guardrails"}
                </span>
                {sessionMemoryFor(p.knowledge_product?.destinations).enabled && (
                  <span className="pipeline-chip pipeline-chip--memory">Memory</span>
                )}
              </div>

              <div className="pipeline-card-endpoint">
                {p.slug ? (
                  <>
                    <span className="pipeline-card-endpoint-label">Endpoint</span>
                    <code>{assistantBaseUrl(p.slug)}</code>
                  </>
                ) : (
                  <span className="muted">No endpoint. This is a legacy ingestion pipeline.</span>
                )}
              </div>

              <div className="pipeline-card-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={(event) => {
                    event.stopPropagation();
                    setViewing(p);
                  }}
                >
                  View
                </button>
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  onClick={(event) => {
                    event.stopPropagation();
                    setDeleting(p);
                  }}
                  aria-label={`Delete ${p.name}`}
                >
                  <IconDelete size={12} />
                  Delete
                </button>
              </div>
            </article>
          ))}
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

      {showCreate && (
        <Modal
          title="Create pipeline"
          size="lg"
          onClose={() => setShowCreate(false)}
          initialFocus={createNameRef}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button
                type="submit"
                form="create-pipeline-form"
                className="btn btn-primary"
                disabled={loading || submitting || !canCreate}
              >
                {submitting ? "Creating…" : "Create Pipeline"}
              </button>
            </>
          }
        >
          <form id="create-pipeline-form" className="pipeline-form" onSubmit={handleCreate}>
            <fieldset
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
                onNameRef={(el) => {
                  createNameRef.current = el;
                }}
              />
            </fieldset>
            {formError && <div className="alert alert-error">{formError}</div>}
          </form>
        </Modal>
      )}

      {viewing && (
        <Modal
          title={viewing.name}
          size="lg"
          onClose={() => setViewing(null)}
          footer={
            <>
              <button type="button" className="btn btn-danger" onClick={() => setDeleting(viewing)}>
                <IconDelete size={12} />
                Delete
              </button>
              <span className="modal-spacer" />
              <Link to="/chat" className="btn btn-secondary">
                Open in Chat
              </Link>
              <button type="button" className="btn btn-secondary" onClick={() => setViewing(null)}>
                Close
              </button>
              <button type="button" className="btn btn-primary" onClick={() => openEdit(viewing)}>
                <IconEdit size={12} />
                Edit configuration
              </button>
            </>
          }
        >
          <p className="view-desc">{viewing.description}</p>

          <section className="view-section">
            <h3 className="view-section-title">Endpoint</h3>
            {viewing.slug ? (
              <>
                <EndpointRow
                  label="OpenAI-compatible base URL"
                  url={assistantBaseUrl(viewing.slug)}
                  hint="Point an OpenAI client's base_url here."
                />
                <EndpointRow label="Native chat URL" url={assistantChatUrl(viewing.slug)} />
              </>
            ) : (
              <p className="muted">
                No endpoint. This is a legacy ingestion pipeline, which the assistant routes do not serve.
              </p>
            )}
          </section>

          <section className="view-section">
            <h3 className="view-section-title">Session memory</h3>
            {viewingMemory.enabled ? (
              <>
                <p className="view-note">
                  This assistant remembers what you send under one <code>session_id</code>. Send the
                  same id on the next turn and it sees the earlier exchange, including a follow-up
                  that only makes sense in context. The memory clears when you call the end endpoint,
                  or after{" "}
                  {viewingMemory.ttlSeconds
                    ? `${Math.round(viewingMemory.ttlSeconds / 3600)} hours`
                    : "its TTL"}{" "}
                  without a turn.
                </p>
                {viewing.slug && (
                  <>
                    <EndpointRow
                      label="Read a session"
                      url={assistantSessionUrl(viewing.slug)}
                      hint="GET, replace {session_id}. Reports the turns this assistant remembers."
                    />
                    <EndpointRow
                      label="End a session"
                      url={assistantSessionUrl(viewing.slug)}
                      hint="DELETE, replace {session_id}. Clears the memory. Safe to retry."
                    />
                  </>
                )}
              </>
            ) : (
              <p className="muted">
                Session memory is off. This Knowledge Product has no enabled Redis destination, so
                each turn is answered on its own. Enable the Redis destination in the Ingestion
                Manager to give the assistant a conversation.
              </p>
            )}
          </section>

          <section className="view-section">
            <h3 className="view-section-title">Configuration</h3>
            <dl className="view-grid">
              <div>
                <dt>Knowledge Product</dt>
                <dd>
                  {viewing.knowledge_product ? (
                    <span className="view-product">
                      {viewing.knowledge_product.name}
                      <StatusBadge status={viewing.knowledge_product.status} />
                    </span>
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
              <div>
                <dt>RAG strategy</dt>
                <dd>{RAG_STRATEGY_LABELS[viewing.rag_strategy]?.label ?? viewing.rag_strategy}</dd>
              </div>
              <div>
                <dt>Chat model</dt>
                <dd className="mono">{viewing.chat_model ?? "—"}</dd>
              </div>
              <div>
                <dt>Prompt template</dt>
                <dd>
                  {templates.find((t) => t.id === viewing.prompt_template_id)?.name ?? "No prompt"}
                </dd>
              </div>
              <div>
                <dt>Guardrails config</dt>
                <dd>
                  {guardrails.find((g) => g.id === viewing.guardrails_config_id)?.name ??
                    "No guardrails"}
                </dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{new Date(viewing.created_at).toLocaleString()}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{new Date(viewing.updated_at).toLocaleString()}</dd>
              </div>
            </dl>
          </section>

          <section className="view-section">
            <h3 className="view-section-title">Stores read</h3>
            {viewingStoreDestinations.length === 0 ? (
              <p className="field-hint">No enabled retrieval destination.</p>
            ) : (
              <ul className="view-stores">
                {viewingStoreDestinations.map((d) => {
                  const store = destinationStoreLabel(d) ?? d.destination_type;
                  const table = d.config?.table_name as string | undefined;
                  return (
                    <li key={d.destination_type}>
                      <span className="view-store-kind">{d.destination_type}</span>
                      <code>
                        {store}
                        {table ? `.${table}` : ""}
                      </code>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </Modal>
      )}

      {editing && (
        <Modal
          title="Edit pipeline"
          size="lg"
          onClose={closeEdit}
          initialFocus={editNameRef}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={closeEdit}>
                Cancel
              </button>
              <button
                type="submit"
                form="edit-pipeline-form"
                className="btn btn-primary"
                disabled={savingEdit}
              >
                {savingEdit ? "Saving…" : "Save changes"}
              </button>
            </>
          }
        >
          <form id="edit-pipeline-form" className="pipeline-form" onSubmit={handleEditSubmit}>
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
          </form>
        </Modal>
      )}

      {deleting && (
        <ConfirmDeleteDialog
          pipeline={deleting}
          busy={deletingBusy}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void handleDelete(deleting)}
        />
      )}
    </div>
  );
}
