# 04. Prompts Management Page (`/prompts`)

## 1. Page Purpose & Summary

The **Prompts Management** (`/prompts`) page allows prompt engineers and AI developers to author, version, test, and manage system prompt templates used across all RAG chat pipelines.

---

## 2. Dynamic Variable Injection Engine

Prompt templates support dynamic variable placeholders that are injected at query execution time:
- `{context}`: Retrieved text chunks from hybrid vector search & reranking.
- `{query}`: Original user query string.
- `{history}`: Conversation history context.
- `{current_date}`: Injected runtime timestamp.

---

## 3. Key UI Modules & Features

1. **Prompt Template Library**: List of saved system prompt templates with version tags, descriptions, and active status indicators.
2. **Template Editor**: Syntax-highlighted text editor with live variable validation.
3. **Playground Sandbox**: Split-screen testing drawer allowing engineers to test prompt templates against sample contexts and queries before saving.
4. **Version History Modal**: Compare prompt diffs and roll back to previous prompt revisions.

---

## 4. API Endpoint Reference

- **`listPrompts()`**: `GET /api/rag/prompts`
- **`createPrompt(body)`**: `POST /api/rag/prompts`
- **`updatePrompt(id, body)`**: `PUT /api/rag/prompts/:id`
- **`deletePrompt(id)`**: `DELETE /api/rag/prompts/:id`
