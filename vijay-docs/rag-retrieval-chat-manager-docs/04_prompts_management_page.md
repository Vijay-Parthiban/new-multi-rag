# 04 — Prompt Studio & Management Page

## 1. Executive Summary & Page Purpose
The **Prompt Studio & Management Page** (`PromptsPage.tsx`, route: `/prompts`) provides a dedicated environment for authoring, versioning, testing, and optimizing system prompts, query expansion instructions, and few-shot examples used across the RAG generation pipeline.

---

## 2. Dynamic Variable Injection & Templates
The generator engine (`generation_core/prompt_builder.py`) injects dynamic context variables into prompt templates at runtime:

- `{query}`: The raw sanitized user query text.
- `{context}`: Formatted context blocks combining cited chunk text and source locators.
- `{history}`: Rolling conversation history for multi-turn coherence.
- `{current_date}`: System timestamp for time-relative reasoning.

```
+-----------------------------------------------------------------------------------------------+
|  Prompt Studio                                                                                |
|  Manage system prompt templates, injection variables, and version rollback histories.         |
|  [ + New Prompt Template ]  [ Save Version ]                                                  |
+-----------------------------------------------------------------------------------------------+
|  Template: Enterprise RAG Synthesis Prompt (v3 - Active)                                      |
|  Description: High-precision technical synthesizer with strict groundness invariants.         |
|                                                                                               |
|  Prompt Template Editor:                                                                      |
|  +------------------------------------------------------------------------------------------+ |
|  | You are an expert AI enterprise assistant. Answer the user's question accurately using  | |
|  | strictly the provided context below.                                                     | |
|  |                                                                                          | |
|  | ### Context:                                                                             | |
|  | {context}                                                                                | |
|  |                                                                                          | |
|  | ### User Question:                                                                       | |
|  | {query}                                                                                  | |
|  |                                                                                          | |
|  | ### Instructions:                                                                        | |
|  | 1. Only state facts directly supported by the context.                                   | |
|  | 2. If the context is insufficient, explicitly state what is missing.                     | |
|  | 3. Cite the exact document filename and chunk index for every claim.                     | |
|  +------------------------------------------------------------------------------------------+ |
|                                                                                               |
|  Available Dynamic Variables: [ {query} ] [ {context} ] [ {history} ] [ {current_date} ]     |
+-----------------------------------------------------------------------------------------------+
```

---

## 3. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/prompts` | Lists all prompt templates | `list[PromptRecord]` |
| `POST` | `/prompts` | Creates a new prompt template | `CreatePromptRequest` -> `PromptRecord` |
| `GET` | `/prompts/{id}` | Retrieves prompt details with version history | `PromptDetailRecord` |
| `PUT` | `/prompts/{id}` | Updates prompt and creates new version | `UpdatePromptRequest` -> `PromptRecord` |
| `DELETE` | `/prompts/{id}` | Deletes prompt template | `{"status": "deleted"}` |
| `POST` | `/prompts/test` | Runs test generation with mock variables | `TestPromptResponse` |

### Sample Prompt Record (`GET /prompts/{id}`)
```json
{
  "id": "19b48f10-928d-4c31-9f93-bc429188ae01",
  "name": "Enterprise RAG Synthesis Prompt",
  "version": 3,
  "is_active": true,
  "template": "You are an expert AI enterprise assistant. Answer using strictly the provided context: {context} \n\n Question: {query}",
  "variables": ["query", "context"],
  "updated_at": "2026-09-16T08:30:00.000Z"
}
```
