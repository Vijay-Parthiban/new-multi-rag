# 02 — RAG Pipelines Management Page

**Last updated:** 2026-09-21

## 1. Executive Summary & Page Purpose

The **Pipelines page** (`frontend/src/pages/PipelinesPage.tsx`, route `/pipelines`) creates and inspects
assistant records. The **page** keeps the name **Pipelines**. The **record** is a pipeline. The record is an
**assistant** when its `rag_strategy` is `vector`, `lexical`, `relational` or `hybrid`.

An assistant holds five parts:

| Part | Required | What it does |
|---|---|---|
| One Knowledge Product | yes | The assistant reads the stores of that product. |
| One RAG strategy | yes | The strategy picks the store the assistant searches. |
| One chat model | yes | The model writes the answer. |
| One prompt template | no | The template becomes the assistant's system message. |
| One guardrails config | no | The config checks the question and the answer. |

Key facts:

- The page writes through the ingestion manager: `API_URL = VITE_API_URL ?? "http://localhost:8007"`
  (`frontend/src/api.ts:3`).
- The endpoints the page hands out belong to the retrieval manager:
  `RAG_API_URL = VITE_RAG_API_URL ?? "http://localhost:8001"` (`frontend/src/api.ts:5`).
- An assistant owns no document and no collection. It reads the Knowledge Product's stores, so the page
  carries no source picker, no folder picker, no chunking control and no scraper control (§4).
- The `description` is the record's stored summary. The form hint for the field reads
  `Shown as the assistant's name in chat.` The Chat page's pipeline selector lists `{name} ({rag_strategy})`,
  so the name is what a chat user reads there.
- On load the page reads five lists in parallel: `listPipelines`, `listKnowledgeProducts`,
  `listPromptTemplates`, `listGuardrailsConfigs` and `getLiteLLMModels("chat")`. One failed call does not
  blank the page. The first failure shows in an `.alert-error` above the form.

The page has two header actions: **Create Pipeline** (primary) and **Refresh** (secondary). Creating,
viewing and editing each open a dialog; the saved pipelines render as a card grid. The **Knowledge
Product** select offers only products with at least one enabled retrieval destination.

---

## 2. The Seven Form Fields

One renderer, `PipelineFields` (`PipelinesPage.tsx:106`), serves both the create card and the edit modal.

| Field | Required | What it selects |
|---|---|---|
| `Internal name` | yes, 2 characters or more | The record name. The API derives the `slug` from it. |
| `Description` | yes, 8 characters or more | The pipeline description. The form hint reads `Shown as the assistant's name in chat.` |
| `Knowledge Product` | yes | The product whose stores the assistant reads. |
| `RAG Strategy` | yes | One strategy from the product's enabled destinations. |
| `Prompt Template` | no | `None (default RAG prompt)`, or one saved template. |
| `Guardrails Config` | no | `None`, or one saved config. An inactive config reads `{name} (inactive)`. |
| `Chat Model` | yes | The generator model, from `getLiteLLMModels("chat")` against port `8007`. |

Field notes:

- **Knowledge Product.** The option list holds only products with at least one enabled retrieval destination
  (`vector_qdrant`, `lexical_opensearch` or `relational_pgvector`). Each option reads
  `{name} — {n} destinations`. Below the select the page renders one chip per enabled destination, with the
  store name from `destinationStoreLabel` (`frontend/src/api.ts:356`). While the list loads, the form is
  disabled and the hint reads `Loading knowledge products…`.
- **RAG Strategy.** The page rebuilds this select from the selected product's destinations
  (`frontend/src/api.ts:343-354`). Each option reads `{label} — {description}` from `RAG_STRATEGY_LABELS`
  (`frontend/src/api.ts:317-322`). A new product resets the strategy to the first available option, because
  the old strategy may need a store the new product does not have. When the product serves no strategy, the
  select is disabled and the hint reads
  `This product has no enabled retrieval destination. Enable one in the Ingestion Manager.`
- **Chat Model.** The list comes from
  `GET /api/knowledge-products/config/litellm-models?model_kind=chat` on port `8007`.
- **Prompt Template.** The template is the system message. It is not a text pass-through: the retrieved
  passages and the question keep their own user-message shape.
- **Guardrails Config.** The config id travels with the pipeline. The Chat page can override it for one
  request without editing the pipeline.

The page rejects an incomplete create in the browser. `Create assistant` stays disabled until the name has 2
characters, the description has 8 characters, and the product, the strategy and the chat model are all set.
Field errors appear under the field in `.field-hint`. API errors appear in an `.alert-error` as
`{code}: {message}`.

---

## 3. RAG Strategy

| Strategy id | Label in the form | Store it reads | Destination it needs enabled |
|---|---|---|---|
| `vector` | `Vector search` | Qdrant dense vectors | `vector_qdrant` |
| `lexical` | `Keyword search` | OpenSearch BM25 | `lexical_opensearch` |
| `relational` | `SQL search` | PostgreSQL pgvector | `relational_pgvector` |
| `hybrid` | `Hybrid` | Qdrant dense vectors and OpenSearch BM25, fused by reciprocal rank fusion (k = 60) | `vector_qdrant` **and** `lexical_opensearch` |

Three rules decide the option list:

1. `Hybrid` appears only when both the Qdrant and the OpenSearch destination are enabled. It reads both
   rankings, so one destination is not enough.
2. `cache_redisvl` serves no strategy. That store caches answers. It does not hold a searchable copy of the
   chunks.
3. The store names come from the Knowledge Product's destination config: `collection_name` for
   `vector_qdrant`, `index_name` for `lexical_opensearch`, and `schema_name` plus `table_name` for
   `relational_pgvector`. The fanout derives them as `kp_<product-slug>_<id8>`.

On the retrieval side the four strategies live in
`rag-retrieval-chat-manager/backend/libs/rag-core/src/rag_core/assistant.py`, and the dispatch lives in
`rag-retrieval-chat-manager/backend/libs/retrieval-core/src/retrieval_core/kp_retriever.py`.

---

## 4. What the Page Removed

The page no longer creates an ingestion job. An assistant reads the product's stores, so it owns no documents
of its own. Every control below left the form, with the code behind it:

| Removed control | Was for |
|---|---|
| MinIO source picker | Linking source buckets to the pipeline. The `linkSourceToPipeline` loop in `handleSubmit` went with it. |
| Folders to index | The `GET /api/directories` checklist. |
| `Primary Text Engine` | The dense embedding model. The Knowledge Product's `text_embedding_model` decides it now. |
| `Keyword Search Engine` | The sparse embedding model. The fanout writes Qdrant dense-only, so a product store has no sparse vectors. |
| `Content Type` | The modality. The Knowledge Product's modality mode decides it now. |
| `Document processing size` and `Overlap` | Chunk size and chunk overlap. The Ingestion Profile carries both. |
| `Qdrant collection` | The pipeline's own collection. The assistant reads the product's collection. |
| `Enable web scraper` and its sub-fields | `Seed URL`, `Max depth`, `Max pages`, the scraper embedding source and the scraper mode. |
| `Run`, `Recent Activity`, `Pipeline Details & Stats` | Pipeline runs and MinIO sync counters. An assistant runs no ingestion job. |
| `Trigger Sync`, `Refresh stats` | The matching header actions. Only `Create Pipeline` and `Refresh` remain. |

The legacy ingestion table and its routes stay in the backend, because the Tracking page and the web scraper
still read pipeline runs. The Pipelines page is simply no longer the place where they are created.

---

## 5. The Dialog Shell

Four surfaces use one shell: **create**, **view**, **edit** and the **delete warning**. The shell is the
`Modal` component in the page file, so the overlay, the scroll lock, the Escape handler and the focus
rule exist once.

| Part | Value |
|---|---|
| Overlay | `.modal-overlay`, `position: fixed; inset: 0; z-index: 1000`, `rgba(0,0,0,0.72)` with a 10 px blur |
| Panel | `.modal-panel`, `var(--bg-default)`, `border: 1px solid var(--border-glow)`, `var(--radius-lg)`, `max-height: 90vh` |
| Sizes | `.modal-panel--sm` 460 px, `--md` 720 px, `--lg` 820 px |
| Accessibility | `role="dialog"`, `aria-modal="true"`, `aria-label={title}` on the panel |
| Close on `Escape` | One `keydown` listener on `window`, registered while the dialog is mounted |
| Close on a click outside | `onClick` on the overlay, with `stopPropagation` on the panel |
| Focus on open | `initialFocus` prop focuses that element, otherwise the panel itself. The panel has `tabIndex={-1}` |
| Background scroll | `document.body.style.overflow = "hidden"` while the dialog is up, restored on unmount |
| Mobile | Below 560 px the overlay padding drops to 12 px and the footer buttons stretch to equal width |

The create dialog passes `initialFocus={createNameRef}`, the edit dialog passes `editNameRef`, and the view
dialog passes nothing.

### 5.1 The create dialog

`Create Pipeline` in the header opens it. It carries the same seven fields as before, through
`PipelineFields`, and the footer is `Cancel` and `Create Pipeline`. The submit button lives in the footer
and reaches the form through `form="create-pipeline-form"`, so the form markup and the footer stay
separate.

`Create Pipeline` stays disabled until the name has 2 characters, the description has 8 characters, and the
product, the strategy and the chat model are all set. The same rules as before.

`POST /api/pipelines` runs on submit. On success the dialog closes and the card grid gains the new
pipeline, sorted first. The dialog does **not** stay open to show the endpoint; one click on the new card
shows it.

### 5.2 `CopyEndpointButton`

One component copies a URL. It writes to the clipboard, swaps `IconCopy` for `IconCheckCircle`, and changes
its label to `Copied` for 2000 ms. `aria-label="Copy assistant endpoint"`.

It appears inside every `EndpointRow` in the view dialog, and on every card that has a slug.

---

## 6. The Pipeline Cards

### 6.1 The card grid

`.pipeline-cards` is a grid, `repeat(auto-fill, minmax(330px, 1fr))`, one card per pipeline. The order is
**newest first**, so a pipeline created a moment ago is the first card. Three columns fit at 1600 px, two
from 1280 down to 900, and one below 640.

Each card shows, from top to bottom:

1. The `name`, with the strategy label from `RAG_STRATEGY_LABELS` as a chip at the right (raw id fallback).
2. The `description`.
3. Two labelled rows: `Knowledge Product` and `Chat model`.
4. Two chips: the prompt template name or `No prompt`; the guardrails config name or `No guardrails`.
   A third `Memory` chip appears when the product's Redis destination is enabled.
5. An `Endpoint` block holding `assistantBaseUrl(slug)` in monospace. A null slug reads
   `No endpoint. This is a legacy ingestion pipeline.`
6. The actions `View` and `Delete`.

The whole card is the click target. It carries `role="button"`, `tabIndex={0}` and an
`aria-label={`Open ${name}`}`, and Enter or Space opens it as well. The two action buttons call
`stopPropagation`, so `Delete` opens the warning without also opening the view.

### 6.2 The view dialog

Clicking a card opens a read-only dialog titled with the pipeline name. It has three sections.

**Endpoint.** One `EndpointRow` per URL, each with its own `CopyEndpointButton`:

| Row | URL |
|---|---|
| `OpenAI-compatible base URL` | `assistantBaseUrl(slug)`, with the hint `Point an OpenAI client's base_url here.` |
| `Native chat URL` | `assistantChatUrl(slug)` |

A record with a null slug reads
`No endpoint. This is a legacy ingestion pipeline, which the assistant routes do not serve.`

**Session memory.** The gate is the product's Redis destination, computed by `sessionMemoryFor()` in
`frontend/src/api.ts`, which mirrors `session_memory_for_product()` on the backend.

| Product state | What the dialog shows |
|---|---|
| Redis enabled | One sentence explaining the `session_id`, the TTL in hours, and two `EndpointRow`s: `Read a session` (GET) and `End a session` (DELETE), both built by `assistantSessionUrl(slug)` with a literal `{session_id}` placeholder |
| Redis disabled | `Session memory is off.` plus the reason and where to enable it |

See [15 — Assistant Session Memory](./15_assistant_session_memory.md) for the endpoints themselves.

**Configuration.** A `.view-grid` of `Knowledge Product` (with its `StatusBadge`), `RAG strategy`,
`Chat model`, `Prompt template`, `Guardrails config`, `Created` and `Updated`.

**Stores read.** One row per enabled retrieval destination: `{destination_type}` and
`{store}` plus `.{table_name}` when the config carries one. When there is none, the section reads
`No enabled retrieval destination.`

The footer holds four controls: `Delete` (destructive, at the far left), then `Open in Chat`, `Close` and
`Edit configuration` (primary) pushed right by a `.modal-spacer`.

### 6.3 The delete warning

Both the card's `Delete` and the view dialog's `Delete` open the same warning, a
`ConfirmDeleteDialog` with `role="alertdialog"`. It replaced the `window.confirm` call.

| Part | Content |
|---|---|
| Icon | `IconDelete` in a `.confirm-icon` circle, `var(--danger-subtle)` background |
| Title | `Delete this pipeline?` |
| Body | `<description> will be removed permanently.` |
| Warning box | When a slug exists: `Its endpoint <url> stops working immediately. Any client pointing at it will fail.` |
| Last line | `This cannot be undone.` |
| Footer | `Cancel` and `Delete pipeline`. The confirm reads `Deleting…` while the request runs |

`Delete pipeline` sends `DELETE /api/pipelines/{id}`, closes the warning and the view dialog, and reloads
the grid. A failure closes the warning and shows the error in the header alert.

### 6.4 Stat cards

Three cards sit above the grid:

| Card | Value | Subtext |
|---|---|---|
| `Total Pipelines` | The pipeline count | `Every assistant with its own endpoint` |
| `With Guardrails` | The count of records with a `guardrails_config_id` | `Answers pass a guardrails config first` |
| `With Prompt Templates` | The count of records with a `prompt_template_id` | `The template is the system message` |

The card uses hardcoded dark values, so a `[data-theme="light"]` override for `.stats-overview-card`,
`.stats-overview-label` and `.stats-overview-subtext` lives in `index.css`. Without it the label sat dark
grey on a dark grey card. Dark mode is unchanged.

### 6.5 Empty states

- No product qualifies: `.panel-empty` reads
  `No Knowledge Product has an enabled retrieval destination yet.` and links to the ingestion Knowledge Store
  page at `http://localhost:5173/knowledge-store`.
- No pipelines saved: `No pipelines yet. Select Create Pipeline to build one.`
- Loading: `Loading pipelines…`

---

## 7. The Edit Dialog

`Edit configuration` in the view dialog opens it, prefilled from the record. The title is `Edit pipeline`,
and the footer is `Cancel` and `Save changes`.

It uses the same `Modal` shell as §5, at `--lg` width, with `initialFocus={editNameRef}`. Opening it closes
the view dialog first, so two dialogs never stack.

The dialog renders the same seven fields through `PipelineFields`. `Save changes` sends
`PATCH /api/pipelines/{id}` with the full set, then reloads the grid.

`PATCH` accepts `name`, `description`, `slug`, `rag_strategy`, `chat_model`, `prompt_template_id`,
`guardrails_config_id`, `knowledge_product_id` and `embedding_model`
(`frontend/src/api.ts:300-315`). Every component of an existing assistant stays editable.

---

## 8. The Endpoints the Page Hands Out

| What it is | Value | Builder |
|---|---|---|
| OpenAI base URL | `http://localhost:8001/v1/assistants/{slug}` | `assistantBaseUrl` (`frontend/src/api.ts:1183`) |
| Native chat URL | `http://localhost:8001/api/assistants/{slug}/chat` | `assistantChatUrl` (`frontend/src/api.ts:1188`) |

The host comes from `RAG_API_URL`. The port is `8001`, not `8007`. Port `8007` already owns
`/api/pipelines/{uuid}` with a different payload shape, so the assistant surface lives beside the chat
service.

An OpenAI SDK client points `base_url` at the base URL. The SDK appends `/chat/completions`, which is the
route `POST /v1/assistants/{slug}/chat/completions`
(`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/assistants.py:336`).

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8001/v1/assistants/resume-screener",
    api_key="unused",  # the service needs a key only when API_KEY is set
)

answer = client.chat.completions.create(
    model="assistant",
    messages=[{"role": "user", "content": "Which candidates know Qdrant?"}],
)
print(answer.choices[0].message.content)
```

The route reads the last `role=user` message as the question and ignores earlier turns. It is single-turn.
Multi-turn memory there needs a `session_id` extension field, not `messages` parsing. The native chat route
keeps sessions.

---

## 9. Error Codes the Page Can Show

The page renders `{code}: {message}` for an `ApiError` (`describeError`, `PipelinesPage.tsx:71`).

| Code | HTTP | Cause |
|---|---|---|
| `PIPELINE_EXISTS` | 409 | The name or the description already belongs to another pipeline. |
| `CHAT_MODEL_REQUIRED` | 422 | The request carries no chat model. |
| `NO_RETRIEVAL_DESTINATION` | 422 | The Knowledge Product has no enabled retrieval destination. |
| `RAG_STRATEGY_UNAVAILABLE` | 422 | The strategy needs a destination that is disabled or absent. |
| `KNOWLEDGE_PRODUCT_NOT_FOUND` | 422 | The Knowledge Product is missing, or its id is invalid. |

The validation codes come from `_validate_create` and `_validate_assistant_options` in
`rag-ingestion-manager/backend/apps/api/routes/pipelines.py:204-236`. The status codes come from the shared
error classes: `ValidationError` → 422, `ConflictError` → 409, `NotFoundError` → 404
(`rag-ingestion-manager/backend/src/file_manager/core/errors.py:16-28`).

Other API errors appear in the same shape. `PIPELINE_NOT_FOUND` (404) can arrive from a stale delete, and
the header alert shows it.

---

## 10. Notes and Limits

- **An existing pipeline stays editable.** The modal patches every assistant field, so a user can change the
  product, the strategy, the chat model, the template or the guardrails config later.
- **Clearing a select detaches it.** The edit submit sends `null` for an empty `Prompt Template` or
  `Guardrails Config` (the code comments say `null, not undefined: the backend reads a present null as
  "detach"`). Omitting the key leaves the stored value. On the create form a cleared select also sends
  `null`.
- **The slug follows the name.** The API derives it from the name. A slug that already exists gets a numeric
  suffix, so two assistants can share a name stem. The page never asks for the slug.
- **A pipeline with a null slug is a legacy ingestion pipeline.** The Chat page keeps the old scrape path for
  it. The assistant endpoints do not serve it: they answer `422 NOT_AN_ASSISTANT`.
- **`Settings.chat_model` is still `llama-3.3-70b-versatile`,** which the proxy does not serve. An assistant
  always carries an explicit `chat_model`, so the new form cannot reach that default. A hand-made legacy
  `/chat` request with no `generation_model` gets a 400.
- **The page reads the prompt templates and the guardrails configs from the retrieval manager.** The
  `prompt_template_id` and the `guardrails_config_id` on the pipeline carry no foreign key, because those rows
  live in the retrieval manager's database.
