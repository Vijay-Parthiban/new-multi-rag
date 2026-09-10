# 04. Prompts Management Page (`/prompts`)

## 1. Page Purpose & Summary

The **Prompts Management** (`/prompts`) page provides a complete system prompt engineering playground. Engineers can inspect packaged system prompt templates from `generation_core` and `rag_core`, apply live overrides stored on the filesystem, test prompt variations, and reset templates back to packaged defaults.

---

## 2. Key UI Modules & Features

1. **Prompt Template Catalog**: List of system prompts categorized by module (`generation_core`, `rag_core`):
   - `generation_rag_default.txt` (Default RAG response generator)
   - `generation_rag_strict.txt` (Strict grounded RAG response generator)
   - `rag_hyde.txt` (HyDE hypothetical document generator)
   - `rag_multi_query.txt` (Multi-query decomposition generator)
   - `rag_parent_child.txt` (Parent-child context generator)
   - `rag_graph_rag.txt` (GraphRAG reasoning generator)
2. **Interactive Code & Text Editor**: Code mirror surface allowing real-time editing of system prompt instructions, context tags (`{context}`), and question variables (`{question}`).
3. **Override Status Badges**: Identifies whether a prompt is using default packaged code or a custom filesystem override.
4. **Action Toolbar**: Save live override, test prompt with sample query, and reset prompt override to packaged default.

---

## 3. Data Fetching & API Interactions

- **`listPrompts()`**: `GET /api/prompts` — Returns catalog of prompt summaries, IDs, filenames, packages, and override statuses.
- **`getPrompt(promptId)`**: `GET /api/prompts/{promptId}` — Returns full template details, active content, packaged default content, and override directory path.
- **`updatePrompt(promptId, body)`**: `PUT /api/prompts/{promptId}` — Saves custom prompt template override to filesystem directory (`PROMPT_OVERRIDES_DIR`).
- **`resetPrompt(promptId)`**: `POST /api/prompts/{promptId}/reset` — Removes filesystem override and restores packaged default template.
