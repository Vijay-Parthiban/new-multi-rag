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

The page has one header action, `Refresh assistants`. The **Knowledge Product** select offers only products
with at least one enabled retrieval destination. The saved list shows every pipeline.

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
| `Trigger Sync`, `Refresh stats` | The matching header actions. Only `Refresh assistants` remains. |

The legacy ingestion table and its routes stay in the backend, because the Tracking page and the web scraper
still read pipeline runs. The Pipelines page is simply no longer the place where they are created.

---

## 5. After a Successful Create — the `Assistant ready` Panel

`POST /api/pipelines` returns the new record. When the record carries a `slug`, the page renders an
**Assistant ready** panel above the two-column layout, with a close glyph in the panel header.

The panel holds:

| Element | Content |
|---|---|
| Sentence | `<name> is live. Point an OpenAI client at the base URL, and the SDK appends /chat/completions.` |
| OpenAI base URL | `assistantBaseUrl(slug)` in monospace |
| Native chat URL | `assistantChatUrl(slug)`, labelled `Native chat:` |
| Copy button | `CopyEndpointButton`, `aria-label="Copy assistant endpoint"` |
| `Open in Chat` | A `<Link to="/chat">` |
| `Close` | Clears the panel |

The copy button writes the base URL to the clipboard, swaps `IconCopy` for `IconCheckCircle`, and changes its
label to `Copied` for 2000 ms.

The same `CopyEndpointButton` appears in the saved list, on the endpoint row of every pipeline that has a
slug.

---

## 6. The Saved List and the `Assistant summary` Panel

### 6.1 Saved assistants

Each row of `Saved assistants` shows, from top to bottom:

1. The `description`, in bold.
2. `{name} · {strategy label}` from `RAG_STRATEGY_LABELS`, with a raw id fallback.
3. `Knowledge Product: {name}`, when the record carries a product.
4. The `chat_model` in monospace, or `No chat model`.
5. Two chips: the prompt template name, or `No prompt`; the guardrails config name, or `No guardrails`.
6. The endpoint, `assistantBaseUrl(slug)` in monospace, or `No endpoint` for a record with a null slug.
7. The actions `Edit` and `Delete`, plus the copy button when a slug exists.

A row click selects the pipeline for the summary panel. `Delete` asks with `window.confirm` before it sends
`DELETE /api/pipelines/{id}`.

A null slug means a legacy ingestion pipeline. The page shows `No endpoint` and no copy button.

### 6.2 `Assistant summary`

The selected pipeline gets an **Assistant summary** panel in the same column. It shows:

| Line | Content |
|---|---|
| Product | The product name and its `StatusBadge`, or `This pipeline has no Knowledge Product.` |
| `Stores read` | One line per enabled retrieval destination: `{destination_type}: {store}` plus `.{table_name}` when the config carries one. |
| `Strategy` | The strategy label. |
| `Chat model` | The `chat_model`, or `—`. |
| `Prompt template` | The template name, or `No prompt`. |
| `Guardrails` | The config name, or `No guardrails`. |
| `Created`, `Updated` | The two timestamps in local time. |

When the selected record has no enabled retrieval destination, the stores block reads
`No enabled retrieval destination.`

### 6.3 Stat cards

Three cards sit above the layout:

| Card | Value | Subtext |
|---|---|---|
| `Total Pipelines` | The pipeline count | `Every assistant with its own endpoint` |
| `With Guardrails` | The count of records with a `guardrails_config_id` | `Answers pass a guardrails config first` |
| `With Prompt Templates` | The count of records with a `prompt_template_id` | `The template is the system message` |

### 6.4 Empty states

- No product qualifies: `.panel-empty` reads
  `No Knowledge Product has an enabled retrieval destination yet.` and links to the ingestion Knowledge Store
  page at `http://localhost:5173/knowledge-store`.
- No pipelines saved: `No pipelines configured yet.`

---

## 7. The Edit Modal

One modal serves edit. `Edit` opens it with the record's values. The title is `Edit pipeline`.

| Part | Value |
|---|---|
| Overlay | `position: fixed; inset: 0; zIndex: 1000; background: rgba(0,0,0,0.75); backdropFilter: blur(12px)` |
| Panel | `background: #111622`, `border: 1px solid rgba(88,166,253,0.3)`, `borderRadius: 16`, `maxHeight: 90vh`, `overflowY: auto`, width `min(720px, 100%)` |
| Accessibility | `role="dialog"`, `aria-modal="true"`, `aria-labelledby="pipeline-modal-title"` |
| Close on `Escape` | A `keydown` listener on `window`, registered in a `useEffect` while the modal is open |
| Close on a click outside | An `onClick` on the overlay, with `stopPropagation` on the panel |
| Focus on open | A `useEffect` moves focus to the first field, the `Internal name` input |
| Footer | `Cancel` and `Save`. The submit reads `Saving…` while the request runs. |

The modal renders the same seven fields through `PipelineFields`. `Save` sends `PATCH /api/pipelines/{id}` with
the full set, then refreshes the list.

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
