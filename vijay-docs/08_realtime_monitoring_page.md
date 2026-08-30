# Page Documentation: Real-Time Monitoring & Metrics Dashboard (`EvaluationsPage.tsx`)

## 1. Overview & Purpose

The **Real-Time Monitoring & Metrics Dashboard** (`/evaluations`) provides live operational observability into online RAG chat interactions. It tracks per-turn Ragas metrics (Faithfulness, Answer Relevance, Context Precision, Context Recall), latency breakdowns across pipeline stages (Vector Retrieval, Reranking, LLM Synthesis), token usage, and direct links to OpenTelemetry/Langfuse trace sessions.

---

## 2. Page Layout & Component Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Real Time Monitoring | [↗ Open Langfuse]  [🔄 Refresh]               │
├─────────────────────────────────────────────────────────────────────────────┤
│ View Mode Switcher & Metric Controls:                                       │
│ View Mode: (●) Latency Breakdown  ( ) Ragas Quality Metrics                 │
│ Rows Per Page: [ 50 ▾ ]                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Real-Time Metrics & Latency Table:                                          │
│ ┌── Timestamp ──┬── Query / Session ──┬── Retrieval ──┬── Rerank ──┬── Gen ───┬── Total ──┐│
│ │ 10:15:30      │ What is ARR target? │ 18 ms       │ 24 ms      │ 100 ms  │ 142 ms││
│ │               │ sess-9901-ab42      │ [Faith 0.98]│ [Rel 0.95] │ [Prec 0.92]   ││
│ ├───────────────┼─────────────────────┼─────────────┼────────────┼─────────┼───────┤│
│ │ 10:12:15      │ Summarize S3 docs   │ 22 ms       │ 31 ms      │ 180 ms  │ 233 ms││
│ │               │ sess-9884-cd10      │ [Faith 0.94]│ [Rel 0.91] │ [Prec 0.88]   ││
│ └───────────────┴─────────────────────┴─────────────┴────────────┴─────────┴───────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│ Expanded Turn Details Panel (On Row Click):                                 │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ User Query: "What is the ARR growth target?"                            │ │
│ │ System Context Chunks (3):                                              │ │
│ │  - [annual_report.pdf p.14 - Similarity 0.94] "ARR growth target 24%..." │ │
│ │  - [q3_summary.pdf p.2 - Similarity 0.89] "Sales forecast..."           │ │
│ │ Full LLM Response: "According to the annual report [1], target ARR..."  │ │
│ │ Ragas Scores: Faithfulness: 0.98 | Relevance: 0.95 | Recall: 0.96        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Real-Time Performance & Quality Metrics

### 3.1 Ragas Online Evaluation Metrics
- **Faithfulness Score (0.0 - 1.0)**: Measures factual consistency between the generated LLM response and the retrieved vector context chunks. Prevents hallucinations.
- **Answer Relevance Score (0.0 - 1.0)**: Measures how directly and completely the generated answer addresses the user query.
- **Context Precision Score (0.0 - 1.0)**: Measures the proportion of relevant chunks in the retrieved Top-K list vs noisy chunks.
- **Context Recall Score (0.0 - 1.0)**: Measures whether all ground-truth facts required to answer the query were present in the retrieved chunks.

### 3.2 Stage Latency Breakdown
- **Retrieval Latency (`ms`)**: Time taken by Qdrant vector database to execute dense vector search and BM25 sparse retrieval.
- **Reranker Latency (`ms`)**: Execution time for cross-encoder reranker models to re-score vector results.
- **Generation Latency (`ms`)**: First-token latency (TTFT) and token generation duration from OpenAI/Anthropic/Ollama APIs.
- **Total End-to-End Latency (`ms`)**: Overall duration from user query submission to response completion.

---

## 4. API Endpoints & Response Contracts

### 4.1 `GET /api/v1/chat/stats?limit=50`
- **Description**: Fetches real-time execution statistics and Ragas score evaluations for online chat interactions.
- **Response Schema (`RAGChatStatItem[]`)**:
```json
[
  {
    "id": "stat-1002",
    "created_at": "2026-08-30T10:15:30Z",
    "session_id": "sess-9901-ab42",
    "user_query": "What is the ARR growth target?",
    "retrieval_ms": 18,
    "rerank_ms": 24,
    "generation_ms": 100,
    "total_latency_ms": 142,
    "faithfulness": 0.98,
    "answer_relevance": 0.95,
    "context_precision": 0.92,
    "context_recall": 0.96,
    "langfuse_trace_id": "trace-sf89-9912"
  }
]
```

---

## 5. How to Run & Verify

1. **Submit Chat Queries**: Go to `/chat` and run several search/chat queries.
2. **Open Real-Time Monitoring View**: Navigate to `http://localhost:5173/evaluations`.
3. **Toggle View Modes**: Switch between `Latency Breakdown` and `Ragas Quality Metrics`.
4. **Inspect Turn Details**: Click any row to expand the context chunks, full response text, and granular score visualizers.
5. **Verify Langfuse Integration**: Click `Open Langfuse` button to test external telemetry trace deep-linking.
