# 01 — RAG Retrieval & Chat Overview Dashboard

**Last updated:** 2026-09-17

## 1. Executive Summary & Page Purpose
The **RAG Retrieval & Chat Overview Dashboard** is `frontend/src/pages/HomePage.tsx`, mounted at route `/` (`frontend/src/components/AppLayout.tsx:164-166`). It is the landing page of the `rag-retrieval-chat-manager` frontend: a page header, four headline stat cards, six quick-launch cards that link to the other workspace pages, and a read-only "Active Retrieval & Synthesis Pipeline Features" panel.

The page is presentation-only apart from a single count: it fetches the number of knowledge profiles once on mount. It performs **no** health checks, no polling, and no other API calls.

---

## 2. UI Layout & Visual Components

```
+-------------------------------------------------------------------------------------------------------------+
| Sidebar (AppLayout.tsx:23-35): Retrieval & Chat | Overview | Knowledge Store | Pipelines | Chat | Prompts |  |
|   Real Time Monitoring | Offline Evaluation | Tracking | Guard Config | Guard Traces | Guard Evaluation       |
+-------------------------------------------------------------------------------------------------------------+
| PageHeader: "Retrieval & Chat Overview"                                                                     |
|   "Manage RAG pipelines, synthesize answers, monitor retrieval latency, and evaluate model performance."    |
+-------------------------------------------------------------------------------------------------------------+
| Stat cards (HomePage.tsx:76-93):                                                                            |
|   [ 4 ]              [ 42 ms ]              [ 96.8% ]              [ {profilesCount} ]                       |
|   Active RAG         Avg Hybrid Retrieval   Ragas Faithfulness     Linked Knowledge Profiles                |
|   Pipelines          Latency                Score                                                            |
+-------------------------------------------------------------------------------------------------------------+
| Quick-launch cards (HomePage.tsx:7-50, rendered HomePage.tsx:95-103):                                       |
|   [ RAG Chat & Synthesis ]  [ Pipeline Management ]  [ Prompt Studio ]                                      |
|   [ Knowledge Store Proxy ] [ Real-Time Monitoring ] [ Guardrail Policy Rules ]                             |
|   Each card: icon, title, description, CTA label → destination route                                        |
+-------------------------------------------------------------------------------------------------------------+
| Panel "Active Retrieval & Synthesis Pipeline Features" (HomePage.tsx:108-142)                               |
|   action link → /pipelines "Configure Pipelines"                                                            |
|   [ Hybrid Reciprocal Rank Fusion ] [ Cross-Encoder Reranker ]                                              |
|   [ Real-Time Moderation ]          [ Ragas Offline Benchmarking ]                                          |
+-------------------------------------------------------------------------------------------------------------+
```

### Stat cards (`HomePage.tsx:76-93`)

| Card label | Value | Source |
|---|---|---|
| Active RAG Pipelines | `4` (hard-coded literal) | `HomePage.tsx:78` |
| Avg Hybrid Retrieval Latency | `42 ms` (hard-coded literal) | `HomePage.tsx:82` |
| Ragas Faithfulness Score | `96.8%` (hard-coded literal) | `HomePage.tsx:86` |
| Linked Knowledge Profiles | `{profilesCount}` state, 0 until the fetch resolves | `HomePage.tsx:53,90` |

### Quick-launch cards (`HomePage.tsx:7-50`)

| Destination | Card title | CTA | Sidebar nav label (`AppLayout.tsx:24-34`) |
|---|---|---|---|
| `/chat` | RAG Chat & Synthesis | Launch Chat | Chat |
| `/pipelines` | Pipeline Management | Manage Pipelines | Pipelines |
| `/prompts` | Prompt Studio | Edit Prompts | Prompts |
| `/knowledge-store` | Knowledge Store Proxy | View Knowledge Store | Knowledge Store |
| `/evaluations` | Real-Time Monitoring | Monitor Quality | Real Time Monitoring |
| `/guardrails/config` | Guardrail Policy Rules | Configure Guardrails | Guard Config |

Every destination exists in the sidebar `NAV` list; the page offers no link to Knowledge Store detail, Tracking, Offline Evaluation, Guard Traces, or Guard Evaluation, which are reachable only from the sidebar.

Card and panel descriptions are static UI copy. The reranker referenced as "Cohere" is implemented as a LiteLLM reranker (`reranker_core/litellm_reranker.py`, model alias `nvidia-rerank`), and the "Ragas & DeepEval" wording covers Ragas metrics only (`eval_core/ragas_client.py`).

---

## 3. Backend APIs & Data Contracts

The page makes exactly one request, triggered by `useEffect(() => { load(); }, [load])` on mount (`HomePage.tsx:64-66`). There is no refresh interval and no interval cleanup, so the value is fetched once per page load; React state persists across navigation because AppLayout keeps pages mounted (`AppLayout.tsx:38-41`).

| Method | Endpoint | Description | Response Model |
|---|---|---|---|
| `GET` | `/api/knowledge-profiles` | Counts knowledge profiles for the "Linked Knowledge Profiles" card; failures resolve to an empty list and the card shows `0` | `KnowledgeProfile[]` |

Call chain:
- `listKnowledgeProfiles()` (`frontend/src/api.ts:378-380`) → `apiFetch("/api/knowledge-profiles")`.
- `apiFetch` targets `API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8007"` (`frontend/src/api.ts:3,56`), i.e. the **rag-ingestion-manager** backend directly, not this service's own API.
- Auth header is `X-API-Key` when `VITE_API_KEY` is set (`frontend/src/api.ts:6,11-13`); errors are caught in the page (`HomePage.tsx:57-61`).

The other three stat cards are literals with no backing endpoint. The retrieval backend does expose a same-path proxy (`rag-retrieval-chat-manager/backend/apps/rag-api/src/rag_api/routes/knowledge.py:22`, base URL default `http://localhost:8007`), but `HomePage.tsx` does not use it; the Knowledge Store page and this card use `API_URL` (`:8007`), while the RAG backend is reached through `RAG_API_URL` (`http://localhost:8001`, `frontend/src/api.ts:5`).

---

## 4. Key Workflows & User Navigation
1. **Interactive session launch**: card → `/chat`, a persistent `ChatPage` (`AppLayout.tsx:187-189`) for hybrid retrieval, reranking, and generation.
2. **Pipeline parameter tuning**: card → `/pipelines` (`AppLayout.tsx:183-185`) for retrieval settings, rerank toggle, top-k, and generator/vision/fusion models.
3. **Prompt editing**: card → `/prompts` (`AppLayout.tsx:191-193`), backed by the retrieval API's prompt registry (`/prompts`).
4. **Knowledge Store**: card → `/knowledge-store` (`AppLayout.tsx:175-177`), which forwards to the ingestion manager on port 8007.
5. **Quality monitoring**: card → `/evaluations` (`AppLayout.tsx:195-197`) reading per-message Ragas metrics via `/chat/stats` and `/chat/messages/{id}/metrics`.
6. **Safety policy auditing**: card → `/guardrails/config` (`AppLayout.tsx:207-209`) for ban lists, PII checks, and toxic-language guards used by the chat guardrail phases.
