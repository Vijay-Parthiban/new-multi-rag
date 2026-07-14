# RAG Monorepo — Retrieval, Rerank, Generation & Evaluation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implement with TDD. Each task should be a small commit.

**Goal:** Standalone monorepo that reads chunks from Qdrant (indexed by web-scraper or file-ingest), runs retrieve → rerank → generate, evaluates with RAGAS + IR metrics, and stores golden-dataset eval results separately from live chat metrics.

**Architecture:** Thin `apps/rag-api` HTTP layer; pipeline logic in `libs/rag-core`; vector/retrieval/rerank/generation/eval as focused libs; Postgres for persistence; Redis/RQ for async eval jobs and post-chat metric calculation. Compatible with existing Qdrant payload (`source_type`, `source_id`, `source_locator`, `type`, `content`, `chunk_index`).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy + Alembic, Redis + RQ, Qdrant, LiteLLM (OpenAI SDK), fastembed (`Qdrant/bm25` + cross-encoder reranker), RAGAS, pytest.

---

## 0. Compatibility with existing ingest (critical)

Your scraper already stores:

```json
{
  "source_type": "web_scrape",
  "source_id": "<scrape_job_uuid>",
  "source_locator": "https://...",
  "type": "text|image",
  "content": "...",
  "chunk_index": 0,
  "title": "...",
  "scrape_job_id": "...",
  "url": "..."
}
```

**This RAG service is read-only against Qdrant.** Use the **same** env models so vectors align:

| Setting | Value (match scraper) |
|---------|------------------------|
| `EMBEDDING_MODEL` | `nvidia-embed-passage` (query: `input_type=query`, passage already indexed) |
| `SPARSE_EMBEDDING_MODEL` | `Qdrant/bm25` |
| `QDRANT_COLLECTION` | `scrape_embeddings` (or shared `knowledge_chunks` later) |
| Dense distance | Cosine |
| Sparse modifier | IDF |
| Hybrid | Prefetch dense + sparse → RRF → optional reranker |

---

## 1. Monorepo layout

```
rag-platform/
├── pyproject.toml                 # uv workspace root
├── docker-compose.yaml
├── .env.example
├── libs/
│   ├── shared/
│   │   └── src/rag_shared/
│   │       ├── config.py
│   │       ├── types.py           # SourceType, SearchMode, ChunkPayload
│   │       └── logging_config.py
│   ├── vector-core/
│   │   └── src/vector_core/
│   │       ├── qdrant_store.py    # copy pattern from web-scrapper
│   │       ├── dense_client.py
│   │       ├── sparse_client.py
│   │       └── filters.py
│   ├── retrieval-core/
│   │   └── src/retrieval_core/
│   │       ├── retriever.py
│   │       └── hit_mapper.py
│   ├── reranker-core/
│   │   └── src/reranker_core/
│   │       ├── base.py            # Protocol
│   │       ├── cross_encoder.py   # fastembed/sentence-transformers
│   │       └── noop.py
│   ├── generation-core/
│   │   └── src/generation_core/
│   │       ├── generator.py       # LiteLLM chat
│   │       └── prompt_builder.py
│   ├── rag-core/
│   │   └── src/rag_core/
│   │       ├── pipeline.py        # retrieve → rerank → generate
│   │       └── schemas.py
│   ├── eval-core/
│   │   └── src/eval_core/
│   │       ├── retrieval_metrics.py   # recall@k, precision@k, MRR, hit@k
│   │       ├── rerank_metrics.py      # NDCG, delta-MRR, rank correlation
│   │       ├── generation_metrics.py  # RAGAS wrappers
│   │       ├── source_match.py        # url/file name in retrieved chunks
│   │       └── runner.py              # orchestrates full eval for one item
│   └── database/
│       └── src/rag_db/
│           ├── models/
│           ├── repositories/
│           └── services/
├── apps/
│   ├── rag-api/
│   │   └── src/rag_api/
│   │       ├── main.py
│   │       └── routes/
│   │           ├── retrieve.py
│   │           ├── rerank.py
│   │           ├── generate.py
│   │           ├── chat.py
│   │           └── evaluate.py
│   └── eval-worker/
│       └── src/eval_worker/
│           ├── main.py
│           └── tasks.py
└── tests/
```

---

## 2. Pipeline flows

### 2.1 Interactive chat (sync response, async metrics)

```
UI → POST /chat
  → RAGPipeline.chat()
      1. retrieve(query, source_type, source_id)     # hybrid/dense/sparse
      2. rerank(query, retrieved_chunks)             # cross-encoder after RRF
      3. generate(query, top_k chunks)               # LiteLLM
  → Return answer + citations to UI immediately
  → Enqueue RQ job: compute_chat_metrics(chat_message_id)
      → RAGAS faithfulness, answer_relevancy, etc.
      → Save to chat_message_metrics table
```

**Why async metrics for chat:** RAGAS is slow/expensive; don't block UI.

### 2.2 Golden dataset evaluation (async via worker)

```
UI/CI → POST /evaluate/runs  { dataset_id, config }
  → Create evaluation_run row (status=queued)
  → Enqueue eval_worker job

Worker per golden item:
  1. Load item: question, ground_truth_answer, expected_sources[]
  2. retrieve(question)
  3. Compute retrieval metrics vs expected_sources
  4. rerank(question, retrieved)
  5. Compute rerank metrics (compare order before/after)
  6. generate(question, reranked_top_k)
  7. Compute generation metrics:
       - vs ground_truth: exact match / BLEU / RAGAS answer_correctness
       - vs contexts: RAGAS faithfulness, context_precision, context_recall
  8. Save evaluation_run_item row with all metric JSON
  → Mark run complete, aggregate run-level metrics
```

### 2.3 Step endpoints (for UI debugging)

| Endpoint | Input | Output |
|----------|-------|--------|
| `POST /retrieve` | query, filters, mode | chunks + retrieval scores |
| `POST /rerank` | query, chunks | reranked chunks + rerank scores |
| `POST /generate` | query, chunks | answer only |
| `POST /chat` | query, filters, pipeline config | answer + chunks used |
| `POST /evaluate/runs` | dataset_id | run_id (poll status) |
| `GET /evaluate/runs/{id}` | — | aggregated metrics |

---

## 3. Database schema (two tables families)

### 3.1 Live chat (production traffic)

```sql
-- chat_sessions
id UUID PK
created_at TIMESTAMPTZ
source_type TEXT NULL
source_id TEXT NULL
metadata JSONB

-- chat_messages
id UUID PK
session_id UUID FK
role TEXT  -- 'user' | 'assistant'
content TEXT
created_at TIMESTAMPTZ

-- chat_pipeline_traces  (one per assistant turn)
id UUID PK
chat_message_id UUID FK UNIQUE
query TEXT
retrieval_mode TEXT          -- hybrid|dense|sparse
retrieve_limit INT
rerank_enabled BOOL
rerank_model TEXT
generation_model TEXT
retrieved_chunks JSONB       -- full chunk list pre-rerank
reranked_chunks JSONB        -- chunks sent to LLM
latency_ms JSONB               -- {retrieve, rerank, generate, total}
created_at TIMESTAMPTZ

-- chat_message_metrics  (filled async after response)
id UUID PK
chat_message_id UUID FK UNIQUE
faithfulness FLOAT NULL
answer_relevancy FLOAT NULL
context_precision FLOAT NULL
context_recall FLOAT NULL
raw_ragas JSONB NULL
status TEXT  -- pending|completed|failed
error_message TEXT NULL
computed_at TIMESTAMPTZ NULL
```

### 3.2 Golden dataset evaluation

```sql
-- golden_datasets
id UUID PK
name TEXT UNIQUE
description TEXT
created_at TIMESTAMPTZ

-- golden_dataset_items
id UUID PK
dataset_id UUID FK
question TEXT
ground_truth_answer TEXT NULL
expected_sources JSONB   -- ["https://arxiv.org/...", "handbook.pdf"]
metadata JSONB
created_at TIMESTAMPTZ

-- evaluation_runs
id UUID PK
dataset_id UUID FK
status TEXT  -- queued|running|completed|failed
config JSONB  -- full pipeline config snapshot
aggregate_metrics JSONB NULL
started_at TIMESTAMPTZ NULL
completed_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ

-- evaluation_run_items
id UUID PK
run_id UUID FK
dataset_item_id UUID FK
status TEXT

-- retrieval
retrieved_chunks JSONB
retrieval_metrics JSONB
  -- recall_at_k, precision_at_k, mrr, hit_at_k, source_match_at_k

-- rerank
reranked_chunks JSONB
rerank_metrics JSONB
  -- ndcg_at_k, mrr_before, mrr_after, mrr_delta, kendall_tau

-- generation
generated_answer TEXT
generation_metrics JSONB
  -- faithfulness, answer_relevancy, context_precision, context_recall
  -- answer_correctness (vs ground_truth)

error_message TEXT NULL
created_at TIMESTAMPTZ
```

**Separation:** `chat_*` = real user queries; `evaluation_*` = benchmark runs. Never mix them.

---

## 4. Metrics definitions

### 4.1 Retrieval metrics (golden dataset)

Given `expected_sources: list[str]` (URLs or file names) and `retrieved_chunks` at rank 1..k:

| Metric | Definition |
|--------|------------|
| **Hit@k** | Any retrieved chunk's `source_locator` or title/file_name matches an expected source |
| **Recall@k** | \|matched expected sources\| / \|all expected sources\| |
| **Precision@k** | \|retrieved chunks from expected sources\| / k |
| **MRR** | 1/rank of first relevant chunk (0 if none) |
| **Source match** | Normalize URL path / filename; substring or exact match |

Implement in `eval_core/retrieval_metrics.py` without RAGAS (deterministic, fast).

```python
def normalize_source(s: str) -> str:
    # strip scheme, www, lowercase, basename for files
    ...

def is_relevant_chunk(chunk: RetrievedChunk, expected: set[str]) -> bool:
    candidates = {chunk.source_locator, chunk.title or "", chunk.metadata.get("file_name", "")}
    return any(normalize_source(c) in normalize_source(e) or normalize_source(e) in normalize_source(c)
               for c in candidates for e in expected)
```

### 4.2 Reranker metrics

Compare ranking before vs after rerank on golden items:

| Metric | Definition |
|--------|------------|
| **MRR before / after** | MRR on pre-rerank vs post-rerank list |
| **MRR delta** | after − before (positive = reranker helped) |
| **NDCG@k** | Graded relevance from source match |
| **Kendall tau** | Rank correlation before vs after |

Also log **which retrieval mode** was used (`hybrid`, `dense`, `sparse`) in `evaluation_runs.config`.

### 4.3 Generation metrics (RAGAS + golden)

| Metric | Tool | Inputs |
|--------|------|--------|
| **Faithfulness** | RAGAS | question, answer, contexts |
| **Answer relevancy** | RAGAS | question, answer |
| **Context precision** | RAGAS | question, contexts, ground_truth (optional) |
| **Context recall** | RAGAS | question, contexts, ground_truth |
| **Answer correctness** | RAGAS | answer, ground_truth |

For **chat endpoint** (no ground truth): compute faithfulness + answer_relevancy + context_precision only.

---

## 5. RAGAS + LiteLLM setup

```python
# libs/eval-core/src/eval_core/ragas_client.py
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall

def build_ragas_llm(settings):
    llm = ChatOpenAI(
        base_url=settings.litellm_base_url,
        api_key=settings.openai_api_key,
        model=settings.ragas_judge_model,  # e.g. gpt-4o-mini via proxy
        temperature=0,
    )
    return LangchainLLMWrapper(llm)

def build_ragas_embeddings(settings):
    emb = OpenAIEmbeddings(
        base_url=settings.litellm_base_url,
        api_key=settings.openai_api_key,
        model=settings.embedding_model,  # same as retrieval
    )
    return LangchainEmbeddingsWrapper(emb)
```

**Important:** RAGAS judge model can differ from chat model. Retrieval embeddings must match ingest (`nvidia-embed-passage`).

---

## 6. Reranker placement (after RRF)

```
Query
  → embed dense + sparse
  → Qdrant hybrid (RRF) with prefetch limit = retrieve_limit * 2
  → get retrieve_limit candidates (e.g. 20)
  → CrossEncoderReranker.rerank(query, 20 chunks)
  → top rerank_top_k (e.g. 5) → LLM
```

```python
# libs/reranker-core/src/reranker_core/cross_encoder.py
from fastembed.rerank.cross_encoder import TextCrossEncoder

class CrossEncoderReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self._model = TextCrossEncoder(model_name=model_name)

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RerankedChunk]:
        passages = [c.content for c in chunks]
        scores = list(self._model.rerank(query, passages))
        # pair scores with chunks, sort desc, return top_k
```

Env flag: `RERANKER_ENABLED=true`. When false, use `NoopReranker` (slice top_k from RRF order).

---

## 7. Environment variables (`.env.example`)

```env
# --- Database ---
DATABASE_URL=postgresql+psycopg://crawler:crawler@postgres:5432/rag
REDIS_URL=redis://redis:6379/0
RQ_DEFAULT_TIMEOUT=3600
RQ_EVAL_QUEUE=eval

# --- Qdrant (read from ingest services) ---
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=qdrant
QDRANT_COLLECTION=scrape_embeddings

# --- LiteLLM proxy (same as scraper) ---
LITELLM_BASE_URL=http://host.docker.internal:4000
OPENAI_API_KEY=sk-bot

# --- Retrieval (MUST match ingest) ---
EMBEDDING_MODEL=nvidia-embed-passage
SPARSE_EMBEDDING_MODEL=Qdrant/bm25
DEFAULT_RETRIEVAL_MODE=hybrid
RETRIEVE_LIMIT=20

# --- Reranker ---
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANK_TOP_K=5

# --- Generation ---
CHAT_MODEL=gpt-4o-mini
CHAT_MAX_TOKENS=1024
CHAT_TEMPERATURE=0.2

# --- RAGAS evaluation ---
RAGAS_JUDGE_MODEL=gpt-4o-mini
RAGAS_ENABLED=true
CHAT_METRICS_ASYNC=true

# --- Eval worker ---
EVAL_WORKER_CONCURRENCY=2
EVAL_DEFAULT_K=5
```

---

## 8. API contracts (paste into new repo)

### `POST /chat`

```json
{
  "query": "What is the attention mechanism?",
  "source_type": "web_scrape",
  "source_id": "8b401860-3461-4ec7-88a5-3593e267b8aa",
  "retrieval_mode": "hybrid",
  "retrieve_limit": 20,
  "rerank_enabled": true,
  "top_k": 5
}
```

Response:

```json
{
  "message_id": "uuid",
  "answer": "...",
  "sources": [{ "source_locator": "...", "chunk_index": 2, "rerank_score": 0.91 }],
  "trace_id": "uuid",
  "metrics_status": "pending"
}
```

### `POST /evaluate/runs`

```json
{
  "dataset_id": "uuid",
  "config": {
    "retrieval_mode": "hybrid",
    "retrieve_limit": 20,
    "rerank_enabled": true,
    "rerank_model": "BAAI/bge-reranker-v2-m3",
    "top_k": 5,
    "generation_model": "gpt-4o-mini",
    "k_values": [1, 3, 5, 10]
  }
}
```

---

## 9. Implementation tasks (ordered)

### Phase 1 — Scaffold & vector (Week 1)

- [ ] **Task 1:** uv workspace + `libs/shared` config/types (copy `SourceType`, `SearchMode` from scraper)
- [ ] **Task 2:** `vector-core` — port `qdrant_store.py`, `filters.py`, dense/sparse clients from scraper
- [ ] **Task 3:** `retrieval-core` — `Retriever.retrieve()` + `hit_mapper` (same fields as scraper search results)
- [ ] **Task 4:** `apps/rag-api` `POST /retrieve` + health check
- [ ] **Task 5:** Integration test against real Qdrant (skip if no env)

### Phase 2 — Rerank & generate (Week 1–2)

- [ ] **Task 6:** `reranker-core` cross-encoder + noop
- [ ] **Task 7:** `POST /rerank` endpoint
- [ ] **Task 8:** `generation-core` prompt builder + LiteLLM generator
- [ ] **Task 9:** `POST /generate` endpoint
- [ ] **Task 10:** `rag-core/pipeline.py` wire retrieve → rerank → generate
- [ ] **Task 11:** `POST /chat` with pipeline trace persisted

### Phase 3 — Database (Week 2)

- [ ] **Task 12:** Alembic migrations for all tables above
- [ ] **Task 13:** Repositories: `ChatRepository`, `EvaluationRepository`
- [ ] **Task 14:** Save `chat_pipeline_traces` on every `/chat` call

### Phase 4 — Evaluation (Week 2–3)

- [ ] **Task 15:** `eval-core/retrieval_metrics.py` — recall@k, precision@k, MRR, hit@k
- [ ] **Task 16:** `eval-core/rerank_metrics.py` — NDCG, MRR delta
- [ ] **Task 17:** `eval-core/generation_metrics.py` — RAGAS wrapper
- [ ] **Task 18:** `eval-core/runner.py` — single golden item evaluator
- [ ] **Task 19:** `apps/eval-worker` RQ consumer
- [ ] **Task 20:** `POST /evaluate/runs` enqueue + `GET /evaluate/runs/{id}`

### Phase 5 — Chat metrics async (Week 3)

- [ ] **Task 21:** RQ task `compute_chat_metrics(message_id)`
- [ ] **Task 22:** After `/chat` response, enqueue metrics if `CHAT_METRICS_ASYNC=true`
- [ ] **Task 23:** `GET /chat/messages/{id}/metrics`

### Phase 6 — Docker & polish

- [ ] **Task 24:** `docker-compose.yaml` — postgres, redis, qdrant (external or shared), rag-api, eval-worker
- [ ] **Task 25:** Seed script for sample golden dataset (arxiv attention paper example)
- [ ] **Task 26:** README with env var table and metric definitions

---

## 10. Golden dataset format (CSV import)

```csv
question,ground_truth_answer,expected_sources
"What is scaled dot-product attention?","Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V","https://arxiv.org/html/1706.03762v7"
"Who wrote Attention Is All You Need?","Vaswani et al.","1706.03762v7"
```

`expected_sources` can be URL substring, arxiv id, or filename — matched via `source_match` normalizer.

---

## 11. What to paste in the new repo chat

Use this one-liner prompt:

> Build the `rag-platform` monorepo per the RAG Implementation Plan: libs `vector-core`, `retrieval-core`, `reranker-core`, `generation-core`, `rag-core`, `eval-core`, `database`; apps `rag-api` and `eval-worker`. Read Qdrant collection indexed by web-scraper with payload fields `source_type`, `source_id`, `source_locator`, `type`, `content`, `chunk_index`. Use `EMBEDDING_MODEL=nvidia-embed-passage`, `SPARSE_EMBEDDING_MODEL=Qdrant/bm25`, hybrid RRF then `BAAI/bge-reranker-v2-m3` reranker, LiteLLM proxy for chat and RAGAS. Pipeline: retrieve → rerank → generate. `/chat` returns immediately and enqueues RAGAS metrics to `chat_message_metrics`. `/evaluate/runs` enqueues golden dataset eval to worker; store per-item retrieval/rerank/generation metrics in `evaluation_run_items`. Implement recall@k, precision@k, MRR, hit@k, source match, NDCG, MRR delta, RAGAS faithfulness/answer_relevancy/context metrics.

---

## 12. Design decisions (locked in)

| Decision | Choice | Reason |
|----------|--------|--------|
| Rerank after RRF | Yes | RRF is rank-only; reranker needs text pairs |
| Chat metrics | Async RQ | Don't block UI on RAGAS |
| Golden eval | Sync in worker | Batch, reproducible |
| Two DB table families | chat vs evaluation | Clean separation |
| Same embedding models as ingest | Required | Vector space must align |
| `source_id` filter | Optional on all endpoints | Scope to one scrape/ingest job |

---

## 13. Self-review vs your requirements

| Requirement | Covered in |
|-------------|------------|
| Monorepo like scraper | Section 1 |
| Retrieval + rerank + generation | Sections 2, 6 |
| recall, precision, MRR | Section 4.1 |
| faithfulness | Section 4.3 (RAGAS) |
| Worker for golden eval | Section 2.2, Task 19 |
| Chat metrics after generate | Section 2.1, Phase 5 |
| Two DB tables (eval vs chat) | Section 3 |
| source url/file verification | Section 4.1 source_match |
| hybrid/dense/sparse + models | Sections 0, 6, 7 |
| RAGAS via LiteLLM proxy | Section 5 |
| Same BM25 model | Section 0, 7 |

---

## 14. Scraper port map (fill when scraper repo is available)

When implementing Tasks 1–3, copy/adapt from the web-scraper repo:

| RAG lib | Scraper source (expected) |
|---------|---------------------------|
| `rag_shared/types.py` | `SourceType`, `SearchMode`, chunk payload dataclass |
| `vector_core/qdrant_store.py` | Hybrid query + RRF prefetch pattern |
| `vector_core/dense_client.py` | LiteLLM embeddings with `input_type=query` |
| `vector_core/sparse_client.py` | fastembed `Qdrant/bm25` sparse vectors |
| `vector_core/filters.py` | `source_type` / `source_id` Qdrant filters |
| `retrieval_core/hit_mapper.py` | Qdrant hit → `RetrievedChunk` field mapping |

**Integration smoke test (Task 5):** Query against scrape job `8b401860-3461-4ec7-88a5-3593e267b8aa` with `retrieval_mode=hybrid`, assert non-empty hits with `source_locator` containing `arxiv.org`.
