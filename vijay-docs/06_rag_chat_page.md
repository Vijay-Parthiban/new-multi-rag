# Page Documentation: RAG Chat Assistant & Retrieval Playground (`ChatPage.tsx`)

## 1. Overview & Purpose

The **RAG Chat Assistant & Retrieval Playground** (`/chat`) is the interactive query testing surface of the platform. It enables users to converse with their indexed document corpus, fine-tune hybrid search parameters (dense vector similarity + BM25 keyword matching), adjust cross-encoder reranking, inspect precise citation sources, and monitor per-turn Ragas metrics and guardrail enforcement in real time.

---

## 2. UI Layout & Component Breakdown

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: RAG Chat Playground | 2026 Engine Badge                             │
├──────────────────────────────┬──────────────────────────────────────────────┤
│ Left Control & History Bar   │ Main Chat Interface & Response Area          │
│ ┌──────────────────────────┐ │ ┌──────────────────────────────────────────┐ │
│ │ [+ New Chat Session]     │ │ │ 👤 User: What is the ARR growth target?  │ │
│ ├──────────────────────────┤ │ │                                          │ │
│ │ Chat Sessions:           │ │ │ 🤖 RAG Assistant:                        │ │
│ │  - Q3 Financials (Active)│ │ │ "According to the annual report [1], standard│ │
│ │  - Architecture Q&A      │ │ │  ARR growth target is 24% for FY2026..." │ │
│ ├──────────────────────────┤ │ │                                          │ │
│ │ Vector Pipeline Target:  │ │ │  [📑 Citation 1: annual_report.pdf p.14] │ │
│ │  [ Default Vector Pipeline ▾ ] │  [📊 Metrics: Latency 142ms | Faith 0.98]│ │
│ ├──────────────────────────┤ │ └──────────────────────────────────────────┘ │
│ │ Retrieval Controls:      │ │                                              │
│ │  Top K:               [8]│ │                                              │
│ │  Sim Threshold:    [0.75]│ │                                              │
│ │  Hybrid Weight:    [0.70]│ │                                              │
│ │  [x] Cross-Encoder Rerank│ │                                              │
│ │  LLM Model: [ gpt-4o ▾ ] │ │ [💬 Type query (e.g. 'Summarize Q3 results')... ➔]│
└──────────────────────────────┴──────────────────────────────────────────────┘
```

### 2.1 Key UI Components
- **Chat Session Sidebar**: List of historical conversation threads with session deletion, title editing, and session creation (`+ New Chat`).
- **Retrieval Parameters Drawer**:
  - *Target Vector Pipeline*: Selects the Qdrant collection namespace to query.
  - *Top K*: Number of vector chunks retrieved before reranking (e.g. 5, 8, 15).
  - *Similarity Threshold*: Minimum cosine similarity score cut-off (e.g. 0.70).
  - *Hybrid Dense/Sparse Ratio*: Slider weighting dense vector embeddings (0.0 to 1.0) vs BM25 sparse keyword scores.
  - *Cross-Encoder Reranker Toggle*: Activates secondary reranking model to re-score vector results.
  - *LLM Model Selector*: Model choice (`gpt-4o`, `gpt-4o-mini`, `claude-3-5-sonnet`, `ollama/llama3`).
- **Interactive Chat Area**: Real-time SSE streaming message bubbles with formatted Markdown, code block syntax highlighting, citation footnotes, and latency stats.
- **Citation & Source Preview Popover**: Clickable inline citations `[1]`, `[2]` displaying chunk text, source document filename, MinIO bucket, and similarity score.
- **Blocked Guardrails Card**: Displays structured warning banners if input/output triggers PII, toxicity, or banned keyword filters.

---

## 3. Hybrid Search & Generation Pipeline Sequence

```
[User Query] ────────► RAG API (:8001 /api/v1/chat)
                            │
                            ├── 1. Apply Input Guardrails (PII / Toxicity Check)
                            │
                            ├── 2. Vector Pipeline Lookup in Qdrant (:6333)
                            │       ├── Dense Embedding Vector Search
                            │       └── BM25 Sparse Text Match
                            │
                            ├── 3. Hybrid Fusion & Reciprocal Rank Fusion (RRF)
                            │
                            ├── 4. Cross-Encoder Reranker (Top-K Filtering)
                            │
                            ├── 5. Construct System Prompt with Context
                            │
                            ├── 6. Stream Answer via Server-Sent Events (SSE)
                            │
                            └── 7. Async Ragas Evaluation Worker (Faithfulness, Relevance)
```

---

## 4. API Schemas & Request Contracts

### 4.1 `POST /api/v1/chat` (Streaming SSE)
- **Description**: Submits user query and streams LLM response chunks via SSE.
- **Request Body**:
```json
{
  "session_id": "sess-9901-ab42",
  "pipeline_id": "pipe-001",
  "message": "What is the ARR growth target for 2026?",
  "top_k": 8,
  "similarity_threshold": 0.75,
  "hybrid_alpha": 0.70,
  "rerank_enabled": true,
  "llm_model": "gpt-4o",
  "temperature": 0.2
}
```

- **Server-Sent Event Stream Response (`text/event-stream`)**:
```text
event: metadata
data: {"sources": [{"id": "chunk-101", "file_name": "annual_report.pdf", "score": 0.94, "text": "The Q3 target ARR growth is set to 24%..."}]}

event: delta
data: {"text": "According to the annual report"}

event: delta
data: {"text": " [1], the target ARR growth for 2026 is 24%."}

event: done
data: {"message_id": "msg-8819", "total_tokens": 312, "latency_ms": 142}
```

### 4.2 `GET /api/v1/chat/messages/:id/metrics`
- **Description**: Returns async Ragas evaluation metrics calculated for a completed turn.
- **Response Schema (`RAGMetricsResponse`)**:
```json
{
  "message_id": "msg-8819",
  "faithfulness_score": 0.98,
  "answer_relevance_score": 0.95,
  "context_precision_score": 0.92,
  "context_recall_score": 0.96,
  "latency_ms": 142,
  "metrics_status": "completed"
}
```

---

## 5. How to Run & Test

1. **Launch RAG Query API**: Ensure `rag-app-workspace` API is running on `http://localhost:8001`.
2. **Open Chat View**: Navigate to `http://localhost:5173/chat`.
3. **Select Pipeline**: Pick `Default Vector Pipeline` in the left drawer.
4. **Submit Query**: Type a question regarding your uploaded documents (e.g., "Summarize system architecture").
5. **Verify SSE Streaming**: Confirm text streams smoothly into the message window.
6. **Inspect Citations**: Click the citation badge `[1]` to open source document details and Qdrant chunk score.
7. **Verify Real-Time Metrics**: Observe latency, token count, and Ragas score badges on the assistant message box.
