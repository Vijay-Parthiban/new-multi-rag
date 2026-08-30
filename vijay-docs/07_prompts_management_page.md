# Page Documentation: Prompts Management & Version Control (`PromptsPage.tsx`)

## 1. Overview & Purpose

The **Prompts Management Page** (`/prompts`) controls system prompt templates, retrieval context injection rules, system instructions, and LLM persona definitions used across the RAG engine. It features an override engine that preserves factory-packaged system prompts while allowing customization, variable validation, diff comparisons, and bulk saving.

---

## 2. UI Layout & Split Editor Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Prompts Management | Overrides Directory: .prompts_overrides/       │
│ Actions: [💾 Save All Dirty] [🔄 Reset All to Packaged]                     │
├──────────────────────────────┬──────────────────────────────────────────────┤
│ System Prompts List          │ Active Prompt Template Editor                │
│ ┌──────────────────────────┐ │ 📄 System Prompt: RAG Synthesis (rag_system)│
│ │ 📝 RAG Synthesis System  │ │ Status: ● CUSTOM OVERRIDE | Version: v3.2   │
│ │    (Overridden)          │ │ ┌──────────────────────────────────────────┐ │
│ │ 📝 Web Scraper Context   │ │ │ You are an enterprise RAG assistant.     │ │
│ │    (Packaged Default)    │ │ │ Synthesize answers using only the given  │ │
│ │ 📝 Summarization System  │ │ │ context below.                           │ │
│ │    (Packaged Default)    │ │ │                                          │ │
│ │ 📝 Guardrails Refusal    │ │ │ Context:                                 │ │
│ │    (Packaged Default)    │ │ │ {{context}}                              │ │
│ └──────────────────────────┘ │ │                                          │ │
│                              │ │ User Query:                              │ │
│                              │ │ {{query}}                                │ │
│                              │ └──────────────────────────────────────────┘ │
│                              │ Template Variables: [{{context}}] [{{query}}]│
│                              │ Actions: [💾 Save Changes] [🔄 Reset One]  │
└──────────────────────────────┴──────────────────────────────────────────────┘
```

---

## 3. Key Prompt Templates & Supported Variables

### 3.1 Packaged System Prompts
1. **`rag_system`**: Core RAG answer synthesis prompt injecting Qdrant context chunks and user questions.
2. **`web_scraper_summary`**: Markdown summarization prompt for web content scraped via Crawl4AI.
3. **`guardrails_refusal`**: Standardized refusal response template for blocked or unsafe queries.
4. **`query_expansion`**: Prompt template for decomposing complex multi-step user queries into sub-questions.

### 3.2 Template Variables Reference
- **`{{context}}`**: Dynamically replaced with the top-K reranked vector chunks retrieved from Qdrant.
- **`{{query}}`**: User query string submitted in chat or API requests.
- **`{{chat_history}}`**: Prior conversation turns formatted for multi-turn conversational context.
- **`{{current_date}}`**: Current system ISO date string (`2026-08-30`).

---

## 4. API Endpoints & Request Contracts

### 4.1 `GET /api/prompts`
- **Description**: Returns all registered system prompts, status tags (packaged vs custom), and overrides directory path.
- **Response Schema (`PromptsListResponse`)**:
```json
{
  "overrides_dir": "ingestion-backend/.prompts_overrides",
  "items": [
    {
      "id": "rag_system",
      "filename": "rag_system.txt",
      "title": "RAG Answer Synthesis System",
      "is_overridden": true,
      "packaged_content": "You are a helpful assistant...",
      "active_content": "You are an enterprise RAG assistant. Synthesize answers using only {{context}}..."
    }
  ]
}
```

### 4.2 `PUT /api/prompts/:id`
- **Description**: Saves a user override for a specific system prompt.
- **Request Body**:
```json
{
  "content": "You are an enterprise RAG assistant. Synthesize answers using {{context}} for question {{query}}."
}
```

### 4.3 `POST /api/prompts/reset-all`
- **Description**: Wipes all user override files and restores factory-packaged prompts.

---

## 5. How to Run & Test

1. **Open Prompts View**: Navigate to `http://localhost:5173/prompts`.
2. **Select System Prompt**: Click `RAG Answer Synthesis System` in the left sidebar.
3. **Edit Template**: Modify system text or add instructions (e.g. "Always append citation footnotes").
4. **Verify Template Variables**: Ensure `{{context}}` and `{{query}}` placeholders are retained.
5. **Save Changes**: Click `Save Changes`. Observe tag update to `CUSTOM OVERRIDE`.
6. **Test in Chat**: Navigate to `/chat` and submit a query to verify the new prompt instructions take effect.
