# 01 — RAG Retrieval & Chat Overview Dashboard

**Last updated:** 2026-10-02

## 1. Executive Summary & Page Purpose
The **RAG Retrieval & Chat Overview Dashboard** is `frontend/src/pages/HomePage.tsx`, mounted at route `/` (`frontend/src/components/AppLayout.tsx:172`). It is the landing page of the `rag-retrieval-chat-manager` frontend: a page header, four headline stat cards, six quick-launch cards that link to the other workspace pages, and a read-only "Active Retrieval & Synthesis Pipeline Features" panel.

The page loads live values. On mount it sends three requests in parallel: the Knowledge Product count and the pipeline count to the ingestion API on port 8007, and the recent chat stats to the retrieval API on port 8001. It performs **no** health checks and no polling.

---

## 2. UI Layout & Visual Components

```
+-------------------------------------------------------------------------------------------------------------+
| Sidebar (AppLayout.tsx:24-35): Retrieval & Chat | Overview | Knowledge Store | Pipelines | Chat | Prompts |  |
|   Real Time Monitoring | Offline Evaluation | Guard Config | Guard Traces | Guard Evaluation                |
+-------------------------------------------------------------------------------------------------------------+
| PageHeader: "Retrieval & Chat Overview"                                                                     |
|   "Manage RAG pipelines, synthesize answers, monitor retrieval latency, and evaluate model performance."    |
+-------------------------------------------------------------------------------------------------------------+
| Stat cards (HomePage.tsx:94-115):                                                                           |
|   [ {pipelinesCount} ] [ {avgRetrievalMs} ]  [ {faithfulness} ]   [ {productsCount} ]                       |
|   Active RAG         Avg Retrieval          Ragas Faithfulness     Linked Knowledge Products                |
|   Pipelines          Latency                Score                                                            |
+-------------------------------------------------------------------------------------------------------------+
| Quick-launch cards (HomePage.tsx:7-50, rendered HomePage.tsx:117-128):                                      |
|   [ RAG Chat & Synthesis ]  [ Pipeline Management ]  [ Prompt Studio ]                                      |
|   [ Knowledge Store ] [ Real-Time Monitoring ] [ Guardrail Policy Rules ]                                    |
|   Each card: icon, title, description, CTA label → destination route                                        |
+-------------------------------------------------------------------------------------------------------------+
| Panel "Active Retrieval & Synthesis Pipeline Features" (HomePage.tsx:131-167)                              |
|   action link → /pipelines "Configure Pipelines"                                                            |
|   [ Hybrid Reciprocal Rank Fusion ] [ Cross-Encoder Reranker ]                                              |
|   [ Real-Time Moderation ]          [ Ragas Offline Benchmarking ]                                          |
+-------------------------------------------------------------------------------------------------------------+
```

### Stat cards (`HomePage.tsx:94-115`)

All four show live data. `load()` (`HomePage.tsx:58-81`) fetches the three sources in parallel, and each
read is wrapped in `.catch()` so one failing service leaves its own card at `—` instead of blanking the
page.

| Card label | Value | Source |
|---|---|---|
| Active RAG Pipelines | `{pipelinesCount}` | `listPipelines()` → `GET :8007/api/pipelines`, the number of rows |
| Avg Retrieval Latency | `{avgRetrievalMs}` as `N ms`, or `—` | The mean of `latency_ms.retrieve` over the turns `getChatStats(50)` returns. A turn with no timing is skipped |
| Ragas Faithfulness Score | `{faithfulness}` as `N.N%`, or `—` | The mean of the non-null `faithfulness` scores in the same response |
| Linked Knowledge Products | `{productsCount}` | `listKnowledgeProducts()` → `GET :8007/api/knowledge-products`, the number of rows |

The latency and faithfulness cards describe **the most recent 50 chat turns**, not all history, and they
show `—` until a turn has been scored. A turn is scored asynchronously by the RQ evaluation worker, so a
fresh platform shows `—` for both cards until the first metrics job completes.

### Quick-launch cards (`HomePage.tsx:7-50`)

| Destination | Card title | CTA | Sidebar nav label (`AppLayout.tsx:24-34`) |
|---|---|---|---|
| `/chat` | RAG Chat & Synthesis | Launch Chat | Chat |
| `/pipelines` | Pipeline Management | Manage Pipelines | Pipelines |
| `/prompts` | Prompt Studio | Edit Prompts | Prompts |
| `/knowledge-store` | Knowledge Store | View Knowledge Store | Knowledge Store |
| `/evaluations` | Real-Time Monitoring | Monitor Quality | Real Time Monitoring |
| `/guardrails/config` | Guardrail Policy Rules | Configure Guardrails | Guard Config |

Every destination exists in the sidebar `NAV` list; the page offers no link to the Knowledge Store detail page, Offline Evaluation, Guard Traces, or Guard Evaluation, which are reachable only from the sidebar or, for the detail page, from a product card's `View` button.

Card and panel descriptions are static UI copy. The reranker referenced as "Cohere" is implemented as a LiteLLM reranker (`reranker_core/litellm_reranker.py`, model alias `nvidia-rerank`), and the "Ragas & DeepEval" wording covers Ragas metrics only (`eval_core/ragas_client.py`).

---

## 3. Backend APIs & Data Contracts

The page makes three requests in parallel, triggered by `useEffect(() => { load(); }, [load])` on mount (`HomePage.tsx:83-85`). There is no refresh interval, so the values are fetched once per page load; React state persists across navigation because AppLayout keeps pages mounted (`AppLayout.tsx:42`).

| Method | Endpoint | Base | Description | Response Model |
|---|---|---|---|---|
| `GET` | `/api/knowledge-products` | 8007 | Counts Knowledge Products for the "Linked Knowledge Products" card | `KnowledgeProduct[]` |
| `GET` | `/api/pipelines` | 8007 | Counts pipelines for the "Active RAG Pipelines" card | `PipelineRecord[]` |
| `GET` | `/chat/stats?limit=50` | 8001 | Feeds the average retrieval latency and the faithfulness score | `ChatStatsResponse` |

Call chain:
- `listKnowledgeProducts()` and `listPipelines()` in `frontend/src/api.ts` → `apiFetch`; `getChatStats(50)` uses `ragFetch`.
- `apiFetch` targets `API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8007"` (`frontend/src/api.ts:6,64`), i.e. the **rag-ingestion-manager** backend directly, not this service's own API. `ragFetch` targets `RAG_API_URL` (`frontend/src/api.ts:7`).
- Auth header is `X-API-Key` when `VITE_API_KEY` is set (`frontend/src/api.ts:8,13-15`); each call is wrapped in `.catch()` in the page (`HomePage.tsx:60-62`).

Every card renders a fetched or derived value, so a failing service leaves its own card at `—` or `0`. The retrieval backend does expose a same-prefix proxy for `/api/knowledge-products` (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/knowledge.py`, base URL default `http://localhost:8007`), but `HomePage.tsx` does not use it; the Knowledge Store page and this card use `API_URL` (`:8007`), while the RAG backend is reached through `RAG_API_URL` (`http://127.0.0.1:8001`, `frontend/src/api.ts:7`).

---

## 4. Key Workflows & User Navigation
1. **Interactive session launch**: card → `/chat`, a persistent `ChatPage` (`AppLayout.tsx:195`) for hybrid retrieval, reranking, and generation.
2. **Pipeline parameter tuning**: card → `/pipelines` (`AppLayout.tsx:191`) for retrieval settings, rerank toggle, top-k, and generator/vision/fusion models.
3. **Prompt editing**: card → `/prompts` (`AppLayout.tsx:199`), backed by the retrieval API's prompt-template routes (`/prompt-templates`).
4. **Knowledge Store**: card → `/knowledge-store` (`AppLayout.tsx:183`), a view-only list of the Knowledge Products owned by the ingestion manager on port 8007; a product card's `View` button opens the read-only detail page at `/knowledge-store/:id`.
5. **Quality monitoring**: card → `/evaluations` (`AppLayout.tsx:203`) reading per-message Ragas metrics via `/chat/stats` and `/chat/messages/{id}/metrics`.
6. **Safety policy auditing**: card → `/guardrails/config` (`AppLayout.tsx:215`) for ban lists, PII checks, and toxic-language guards used by the chat guardrail phases.
