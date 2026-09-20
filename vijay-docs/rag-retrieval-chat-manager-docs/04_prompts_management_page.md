# 04 — Prompts Page (Prompt Templates Registry)

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The Prompts page (`frontend/src/pages/PromptsPage.tsx`, sidebar label "Prompts", link `/prompts`) lists the prompt templates registered by the retrieval & chat backend (`backend/apps/rag-api/src/rag_api/routes/prompts.py`) and applies or clears temporary text overrides for them.

What the implementation actually is:
- A **registry with overrides**, not an authoring/versioning system. There is no create, delete, version-history or test-generation endpoint; the previously documented `POST /prompts`, `DELETE /prompts/{id}` and `POST /prompts/test` do not exist.
- Packaged content is never modified. An edit is written to a file in the OS temp directory and is preferred by `load_prompt` until reset.
- The router is mounted without an `/api` prefix (`app.include_router(prompts.router)`, `apps/rag-api/src/rag_api/main.py:78`; `APIRouter(prefix="/prompts")`, `routes/prompts.py:29`). Effective paths are `/prompts`, `/prompts/{prompt_id}` and `/prompts/reset`, and the frontend client calls exactly those (`frontend/src/api.ts:893-929`).
- All routes require the shared API key dependency (`verify_api_key`, `apps/rag-api/src/rag_api/main.py:62`).

---

## 2. Registered Prompt Catalog (`GET /prompts`)
The catalog is the static `PROMPT_CATALOG` list (`routes/prompts.py:42-85`). Six prompts are exposed:

| ID | Filename | Package | Label | Description |
|---|---|---|---|---|
| `rag_system` | `rag_system.txt` | `generation_core` | RAG System | Main system prompt for text RAG answer generation. |
| `fusion_system` | `fusion_system.txt` | `generation_core` | Fusion System | Merges text and vision partial answers into a final reply. |
| `relevance_judge_system` | `relevance_judge_system.txt` | `generation_core` | Relevance Judge | Self-corrective loop: judges whether an answer is acceptable. |
| `query_rewrite_system` | `query_rewrite_system.txt` | `generation_core` | Query Rewrite | Self-corrective loop: rewrites the search query after a miss. |
| `vision_user` | `vision_user.txt` | `generation_core` | Vision User Template | User-message template for vision / image-based generation. |
| `llm_router_system` | `llm_router_system.txt` | `rag_core` | LLM Router | Classifies queries into greeting / simple RAG / CRAG routes. |

### Packaged vs. resolved content
None of the six entries has a packaged `*.txt` file on disk. `load_packaged_prompt` looks in `<package>/prompts/<filename>` (`libs/generation-core/src/generation_core/prompts.py:24-32`, `libs/rag-core/src/rag_core/prompts.py:21-29`), but neither `generation_core/prompts/` nor `rag_core/prompts/` exists in the tree. Falling back to the module-level `DEFAULT_PROMPTS` also misses, because those maps contain different keys:

- `generation_core.DEFAULT_PROMPTS`: `rag_synthesis`, `system_prompt` (`generation_core/prompts.py:11-17`)
- `rag_core.DEFAULT_PROMPTS`: `rag_retrieval_query`, `rag_context_rerank` (`rag_core/prompts.py:11-14`)

Consequences:
- The four default keys above are **fallback text only** — they are not part of `PROMPT_CATALOG`, never exposed by `GET /prompts`, and reachable only through `load_prompt("<key>")`, which no code calls (Section 5).
- For the five `generation_core` catalog entries the resolved content is the placeholder `"Prompt template '{name}' context:\n{context}\nQuestion:\n{question}"`.
- For `llm_router_system` (`rag_core`) the resolved content is `"RAG prompt template '{name}' query:\n{query}"` (`rag_core/prompts.py:29`).
- So, until an override is written, `preview` / `packaged_content` / `active_content` for every catalog entry are placeholders, not real system prompts.

### Identifier resolution
`_get_meta` accepts a prompt **id**, a **filename** (`rag_system.txt`) or a filename **stem** (`rag_system`); anything else returns HTTP 404 `Unknown prompt: <value>` (`routes/prompts.py:108-114`).

---

## 3. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/prompts` | Lists all catalog entries with active content preview | `PromptListResponse` |
| `PUT` | `/prompts` | Bulk override: writes one override file per item | `BulkUpdateRequest` -> `PromptListResponse` |
| `POST` | `/prompts/reset` | Clears every override for the known catalog | `ResetResponse` |
| `GET` | `/prompts/{prompt_id}` | Packaged content, active content and override flag | `PromptDetail` |
| `PUT` | `/prompts/{prompt_id}` | Writes an override for one prompt | `UpdatePromptRequest` -> `PromptDetail` |
| `POST` | `/prompts/{prompt_id}/reset` | Deletes the override for one prompt | `PromptDetail` |

Models (`routes/prompts.py:117-161`):
- `PromptSummary`: `id`, `filename`, `package`, `label`, `description`, `is_overridden`, `preview`.
- `PromptListResponse`: `overrides_dir`, `count`, `items[]`.
- `PromptDetail`: `id`, `filename`, `package`, `label`, `description`, `is_overridden`, `packaged_content`, `active_content`, `overrides_dir`.
- `UpdatePromptRequest`: `{ "content": str }`, `min_length=1` (empty body -> 422).
- `BulkUpdateRequest`: `{ "items": [{ "id": str, "content": str }] }`, list `min_length=1`.
- `ResetResponse`: `reset` (list of filenames), `overrides_dir`.

`preview` is the active content truncated to 160 characters (`active[:157] + "..."` when longer; `routes/prompts.py:168`). `packaged_content` comes from `load_packaged_prompt` and `active_content` from `load_prompt` (`routes/prompts.py:91-100`).

Sample `GET /prompts/{prompt_id}` payload (shape only — content fields are placeholders as described above unless an override exists):
```json
{
  "id": "rag_system",
  "filename": "rag_system.txt",
  "package": "generation_core",
  "label": "RAG System",
  "description": "Main system prompt for text RAG answer generation.",
  "is_overridden": false,
  "packaged_content": "Prompt template 'rag_system.txt' context:\n{context}\nQuestion:\n{question}",
  "active_content": "Prompt template 'rag_system.txt' context:\n{context}\nQuestion:\n{question}",
  "overrides_dir": "<tempdir>/rag_prompt_overrides"
}
```

---

## 4. Override Storage, Caching & Invalidation
Storage (`libs/shared/src/rag_shared/prompt_overrides.py`):
- Root directory: `Path(tempfile.gettempdir()) / "rag_prompt_overrides"`, created on demand (`prompt_overrides.py:7-10`).
- File name: `<package>__<name>.txt`; `\` and `/` in either part are replaced with `_`, and `.txt` is appended if missing (`prompt_overrides.py:13-18`). Examples: `generation_core__rag_system.txt`, `rag_core__llm_router_system.txt`.
- Helpers: `has_override(package, name)`, `read_override(package, name)`, `write_override(package, name, content)`, `clear_override(package, name)`, `clear_all_overrides()` (`prompt_overrides.py:21-56`).

Read path in the libraries (`generation_core/prompts.py:35-43`, `rag_core/prompts.py:32-40`): override file first, then a process-local `_CACHE` dict, then packaged content (which caches the result).

Cache invalidation: every mutating route calls `_invalidate_caches()` -> `clear_prompt_cache()` on both libraries (`routes/prompts.py:103-105`). Because the override file is checked before the cache, invalidation matters mainly for re-reading packaged content after a reset. The caches are per-process module globals, so a service restart is not required but a second worker process could hold its own cache.

Reset semantics:
- Per prompt — `POST /prompts/{prompt_id}/reset` deletes only `<package>__<filename>.txt` and returns the refreshed `PromptDetail` (`routes/prompts.py:229-234`).
- Global — `POST /prompts/reset` clears every `*.txt` under the overrides root and returns the list of known filenames plus `overrides_dir` (`routes/prompts.py:196-201`; `prompt_overrides.py:45-56`).

---

## 5. Where Each Prompt Is Used
The registry is **display-only today**. `load_prompt` / `load_packaged_prompt` are imported only by `routes/prompts.py:15-20` and called only from `_packaged` / `_active`; no module in `retrieval_core`, `rag_core`, `generation_core` or the API pipeline imports or calls them. Therefore writing an override changes what `GET /prompts` reports and nothing else.

The runtime generation path uses hard-coded text:
- `RAG_SYSTEM_PROMPT` and `FUSION_SYSTEM_PROMPT` constants, and the message builders `build_rag_prompt` / `build_fusion_prompt` (`libs/generation-core/src/generation_core/prompt_builder.py:10-33`, `:36-51`, `:54-73`).
- `NO_SOURCES_ANSWER` is a constant used by both the text and vision generators (`prompt_builder.py:6-8`).
- Vision generation embeds its instruction and question inline in the request (`generation_core/vision_generator.py:29-45`).
- The catalog's `relevance_judge_system`, `query_rewrite_system` and `llm_router_system` have no runtime consumer either: no self-corrective judge/rewrite prompts and no LLM-router prompt are loaded from `load_prompt` anywhere in the backend.

No template variables are substituted anywhere. The strings contain literal `{context}`, `{question}` / `{query}` placeholders, but no code path calls `.format()`/`Template` on a loaded prompt. The previously documented `{history}` and `{current_date}` variables do not exist in the codebase, and `generation_core/prompt_builder.py` performs no variable injection (it builds `messages` with f-strings).

---

## 6. Resolved Implementation Caveat (2026-09-20)
Every handler in Section 3 previously raised `TypeError`: the route called the override helpers with a filename alone, while the helpers take `(package_name, name)`. Fixed on 2026-09-20; all six call sites now pass `meta.package` as well. The table records what was wrong and the signature each call must satisfy.

| Handler | Was | Helper signature |
|---|---|---|
| `list_prompts` | `has_override(meta.filename)` (`routes/prompts.py:176`) | `has_override(package_name, name)` (`prompt_overrides.py:21`) |
| `get_prompt` | `has_override(meta.filename)` (`routes/prompts.py:214`) | same |
| `update_prompt` | `write_override(meta.filename, body.content)` (`routes/prompts.py:224`) | `write_override(package_name, name, content)` (`prompt_overrides.py:32`) |
| `update_prompts_bulk` | `write_override(meta.filename, item.content)` (`routes/prompts.py:191`) | same |
| `reset_prompt` | `clear_override(meta.filename)` (`routes/prompts.py:232`) | `clear_override(package_name, name)` (`prompt_overrides.py:37`) |
| `reset_all_prompts` | `clear_all_overrides(known_ids=known)` (`routes/prompts.py:199`) | `clear_all_overrides()` — takes no arguments (`prompt_overrides.py:45`) |

Observed before the fix: `list_prompts` -> `TypeError: has_override() missing 1 required positional argument: 'name'`; `reset_all_prompts` -> `TypeError: clear_all_overrides() got an unexpected keyword argument 'known_ids'`. `GET /prompts` returned 500, so the page showed only its error state.

After the fix `GET /prompts` returns 200 with all six catalog entries and the overrides directory. `reset_all_prompts` reports the catalog filenames and `clear_all_overrides()` clears every `*.txt` under the temp overrides directory, which only this route writes.

One caveat remains: an override is keyed by `(package, name)` while `reset_all_prompts` clears the directory wholesale rather than filtering by the catalog, so it also removes an override whose catalog entry was deleted.

---

## 7. Page UI Behaviour
Layout and interactions as implemented in `frontend/src/pages/PromptsPage.tsx`. The backend calls work as of 2026-09-20 (see Section 6), so the populated state below is observable end to end:

```
+------------------------------------------------------------------------------------------------+
|  Prompt Templates                                                            [ Save all edits ]|
|  View packaged system prompts and apply temporary overrides.  [ Reset all ]  [ Refresh ]        |
+------------------------------------------------------------------------------------------------+
|  Overrides dir: <tempdir>\rag_prompt_overrides · using packaged defaults / · N custom            |
+------------------------------------------------------------------------------------------------+
|  Cards (one per catalog entry)                      |  Editor panel (only after "Edit")        |
|  <Label>                            [Custom|Packaged]|  <Label> · <filename> · packaged default |
|  <description>                        [Unsaved]      |  [x] Show packaged original              |
|  <filename> · <package>                              |  Packaged (read-only) <pre>              |
|  <first 160 chars of active content>                 |  Active prompt  <textarea rows=18>       |
|  [ Edit ]  [ Reset ]                                 |  [ Save override ] [ Reset to packaged ] |
|                                                      |  [ Copy packaged into editor ]           |
+------------------------------------------------------------------------------------------------+
```

- Loaded only while the path is `/prompts` (visibility guard `isVisible`, `PromptsPage.tsx:19`, `:48-52`); `listPrompts()` populates items plus `overrides_dir` (`:39-41`).
- Card badges: `Custom` when `is_overridden`, otherwise `Packaged`; an `Unsaved` badge appears for entries with a pending draft (`:258-262`).
- Editor: `getPrompt(id)` loads the detail, the textarea starts from the pending bulk draft or `active_content` (`:68-71`); "Show packaged original" reveals `packaged_content` read-only (`:315`); "Save override" calls `updatePrompt` (`:92`); "Reset to packaged" calls `resetPrompt` (`:113`).
- Header actions: "Save all edits (n)" appears once at least one draft exists and calls `updatePromptsBulk` with the dirty entries (`:161`, `:199`); "Reset all" asks for `window.confirm` then calls `resetAllPrompts` (`:133`, `:139`); "Refresh" re-runs `listPrompts`.
- The overrides directory line shows the count of customised entries, or "using packaged defaults" when none are custom (`:227-228`).
- `frontend/src/api.ts:875-891` mirrors the response shapes; there is no `POST`/`DELETE` client function for prompts.
