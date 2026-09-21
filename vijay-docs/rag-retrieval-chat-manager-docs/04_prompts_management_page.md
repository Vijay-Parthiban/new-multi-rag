# 04 — Prompts Page (Prompt Templates)

**Last updated:** 2026-09-21

## 1. Executive Summary & Page Purpose

The Prompts page (`frontend/src/pages/PromptsPage.tsx`, sidebar label "Prompts", route `/prompts`)
manages **prompt templates**. A prompt template is the system message an assistant pipeline attaches.

The template becomes the system message of the generated answer. The retrieved passages and the user
question are sent separately, in their own user message. There are **no `{context}` or `{question}`
placeholders** to fill in. The old packaged catalog carried such placeholders and no code substituted
them (Section 5).

Generation reads the template here:

| Item | Path |
|---|---|
| Message builder | `backend/libs/generation-core/src/generation_core/prompt_builder.py` |
| Signature | `build_rag_prompt(query, chunks, *, system_prompt=None)` |
| Fallback | `system_prompt or RAG_SYSTEM_PROMPT` |
| Constant | `RAG_SYSTEM_PROMPT`, same file |

The page is full CRUD over a real table in the `rag` database. No create, update or delete goes to a
file. Every route sits behind the shared `verify_api_key` dependency, which is a no-op unless `API_KEY`
is set.

---

## 2. The Prompt Template Store

### `prompt_templates` (`PromptTemplate`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key, default `uuid.uuid4` |
| `name` | text(128) | unique and indexed; a duplicate answers `409` |
| `description` | text, nullable | shown under the name on the card |
| `content` | text, not null | the system message |
| `created_at` | timestamp | `server_default=func.now()` |
| `updated_at` | timestamp | `onupdate=func.now()` |

| Item | Path |
|---|---|
| Model | `backend/libs/database/src/rag_db/models/prompt.py` |
| Repository | `backend/libs/database/src/rag_db/repositories/prompt_repository.py` |
| Migration | `backend/libs/database/alembic/versions/003_prompt_templates.py` |
| Revision | `003`, `down_revision = "002"` |
| Routes | `backend/apps/rag-api/src/rag_api/routes/prompt_templates.py` |

Migration `003` creates the table from `Base.metadata` and seeds **one row** so a fresh install has a
working default:

| Field | Value |
|---|---|
| `name` | `Default RAG` |
| `description` | `The prompt the code shipped with.` |
| `content` | the text of `RAG_SYSTEM_PROMPT` |

The insert is guarded with `WHERE NOT EXISTS (SELECT 1 FROM prompt_templates)`, so a re-run adds
nothing. The migration imports `RAG_SYSTEM_PROMPT` rather than copying the text, so the two cannot
drift.

---

## 3. Backend Endpoints

Prefix `/prompt-templates`, mounted without an `/api` prefix
(`app.include_router(prompt_templates.router)`, `backend/apps/rag-api/src/rag_api/main.py`). Base URL
`http://localhost:8001`. Send `X-API-Key` when `API_KEY` is set.

| Method | Path | Body | Response |
|---|---|---|---|
| `GET` | `/prompt-templates` | — | `{"count": int, "items": [PromptTemplate]}` |
| `POST` | `/prompt-templates` | `PromptTemplateCreate` | `PromptTemplate`, `201` |
| `GET` | `/prompt-templates/{id}` | — | `PromptTemplate` |
| `PUT` | `/prompt-templates/{id}` | `PromptTemplateUpdate` | `PromptTemplate` |
| `DELETE` | `/prompt-templates/{id}` | — | `204`, empty body |

`PromptTemplate` response fields: `id`, `name`, `description`, `content`, `created_at`, `updated_at`.

| Model | Fields |
|---|---|
| `PromptTemplateCreate` | `name` 1–128 chars, required; `description` optional; `content` non-empty, required |
| `PromptTemplateUpdate` | the same three fields, all optional |

`PUT` sends `model_dump(exclude_unset=True)`, so an omitted key keeps its stored value. A rename to a
name another template owns answers `409`.

Error codes:

| Status | Code | Cause |
|---|---|---|
| `409` | `PROMPT_TEMPLATE_NAME_TAKEN` | A template with this name already exists. |
| `404` | `PROMPT_TEMPLATE_NOT_FOUND` | No template has this id. |

```bash
curl -X POST http://localhost:8001/prompt-templates \
  -H 'Content-Type: application/json' \
  -d '{"name": "One Word", "description": "Answers in one word.", "content": "Answer in exactly one word."}'
```

`GET /prompt-templates` orders the rows by name (`PromptRepository.list`).

---

## 4. Page UI Behaviour

```
+-----------------------------------------------------------------------------------+
|  Prompts                                            [ Create prompt template ]     |
|  A prompt template becomes an assistant's system message. The retrieved passages   |
|  and the user question are sent separately.                                        |
+-----------------------------------------------------------------------------------+
|  [ N Prompt Templates ]                                                            |
+-----------------------------------------------------------------------------------+
|  <name>                                                                 [Edit][Delete]|
|  <description>                                                                     |
|  <pre>: first 160 characters of the content, then an ellipsis when longer          |
+-----------------------------------------------------------------------------------+
```

- The page loads `listPromptTemplates()` once on mount and after every create, edit and delete.
- One stat card shows the template count, or `—` while the list loads.
- `Create prompt template` and `Edit` open the **same modal**. The title reads
  `Create prompt template` or `Edit prompt template`.
- `Delete` asks for confirmation with `window.confirm("Delete the prompt template \"<name>\"?")`.

### The modal

Three fields, in this order:

| Field | Control | Rules |
|---|---|---|
| `Name` | text input, `maxLength=128`, autofocus | required |
| `Description (optional)` | text input | none |
| `Content` | textarea, monospace, `minHeight: 220` | required |

The hint under `Content` reads:

> This text becomes the assistant's system message. The retrieved passages and the user question are
> sent separately.

The footer holds `Cancel` and `Save`. The submit reads `Saving…` while the request runs. Client checks
show `Name is required.` and `Content is required.`. A server error renders as
`{code}: {message}` in an `.alert alert-error` inside the modal.

The modal carries `role="dialog"`, `aria-modal="true"` and
`aria-labelledby="prompt-template-modal-title"`. It closes on `Escape`, on a click outside the panel
and on `Cancel`. The name input takes focus on open.

### Loading, empty and error states

| State | Rendering |
|---|---|
| Loading | `.panel-empty` with `Loading prompt templates…` |
| No template | `.panel-empty` with `No prompt templates yet. Create one to give a pipeline its own behaviour.` |
| Load error | `.alert alert-error` above the list, as `{code}: {message}` |

---

## 5. The Old Packaged Catalog

The page previously edited the **packaged prompt catalog**, not templates. That catalog is still in the
tree and the page no longer touches it.

| Item | Path |
|---|---|
| Catalog routes | `backend/apps/rag-api/src/rag_api/routes/prompts.py` |
| Prefix | `/prompts` |
| Catalog | `PROMPT_CATALOG`, six fixed entries |
| Override storage | `backend/libs/shared/src/rag_shared/prompt_overrides.py` |
| Override directory | `Path(tempfile.gettempdir()) / "rag_prompt_overrides"` |

The `/prompts` routes still exist and still answer. An edit wrote an override file to the OS temporary
directory. **Nothing read those overrides.** `load_prompt` was imported only by the routes module, so an
override changed what `GET /prompts` reported and nothing else. The real system message stayed
hardcoded. The `{context}` and `{question}` strings in the catalog were literals, and no code called
`.format()` or `Template` on them.

That is why prompt templates exist: one table generation actually reads. No frontend code calls
`/prompts` now.

---

## 6. Worked Example — A One-Word Template

The check script `backend/scripts/e2e_assistant_pipelines.py` runs this path. It passes.

1. Create the template.
   ```bash
   curl -X POST http://localhost:8001/prompt-templates \
     -H 'Content-Type: application/json' \
     -d '{"name": "One Word", "description": "Answers in one word.", "content": "Answer in exactly one word."}'
   ```
   The response carries the `id`.
2. Attach it to a pipeline on the ingestion service.
   ```bash
   curl -X PATCH http://localhost:8007/api/pipelines/<pipeline-id> \
     -H 'Content-Type: application/json' \
     -d '{"prompt_template_id": "<template-id>"}'
   ```
3. Ask a question through the assistant.
   ```bash
   curl -X POST http://localhost:8001/api/assistants/<slug>/chat \
     -H 'Content-Type: application/json' \
     -d '{"query": "What award did Rohan receive at Amazon?"}'
   ```
4. Read the answer. With the one-word template in force the answer holds no more than 12 words. The
   check asserts exactly that.

---

## 7. Verification (2026-09-21)

| Check | Result |
|---|---|
| `backend/scripts/e2e_assistant_pipelines.py` | 30 checks, all pass |
| Template CRUD in that script | create, list, duplicate-name `409`, and a template in force |
| `npx tsc --noEmit` | no error |
| `npx vite build` | succeeds |
| Browser, 14 retrieval routes | zero console errors |

The script creates its fixtures with a per-run tag and deletes them in a `finally` block, so a re-run
starts clean.
