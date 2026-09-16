# 01 — RAG Retrieval & Chat Overview Dashboard

## 1. Executive Summary & Page Purpose
The **RAG Retrieval & Chat Overview Dashboard** (`HomePage.tsx`, route: `/`) provides the central control panel for the `rag-retrieval-chat-manager` application. It gives users immediate visibility into active RAG chat sessions, pipeline configurations, prompt studios, live telemetry tracking, guardrail security policies, and Knowledge Store synchronization links.

---

## 2. UI Layout & Visual Components

```
+---------------------------------------------------------------------------------------------------+
|  RAG Retrieval & Chat Manager   |  Overview | Chat | Pipelines | Prompts | Monitoring | Guardrails  |
+---------------------------------------------------------------------------------------------------+
|  System Mission Control                                                                           |
|  Orchestrate hybrid vector retrieval, LiteLLM rerankers, safety guardrails, and real-time evals.  |
+---------------------------------------------------------------------------------------------------+
|  Quick Launch Action Cards:                                                                       |
|                                                                                                   |
|  [ 💬 RAG Chat & Synthesis ]       [ ⚙️ Pipeline Management ]      [ ✍️ Prompt Studio ]            |
|  Hybrid Qdrant retrieval, Cohere   Configure dense/sparse hybrid   Design system prompts, version |
|  reranking, guardrail checks       weights, chunk sizes, LLMs      control, variable testing      |
|                                                                                                   |
|  [ 🗄️ Knowledge Store Proxy ]      [ 📊 Real-Time Monitoring ]     [ 🛡️ Guardrail Policy Rules ]  |
|  Forwarding proxy to Ingestion     Live Ragas & DeepEval scores    Ban lists, Presidio PII/SPI,   |
|  Manager 5-sink fanout (Port 8007) for faithfulness, relevancy     jailbreak & prompt injection   |
+---------------------------------------------------------------------------------------------------+
|  Active System Status & Service Connectivity:                                                     |
|  - Qdrant Vector Engine: [ HEALTHY ] (Collection: documents_vres, 73 vectors)                     |
|  - OpenSearch BM25: [ HEALTHY ] (Index: documents_vres)                                           |
|  - LiteLLM / Ollama LLM Gateway: [ CONNECTED ]                                                    |
|  - PostgreSQL Metadata DB: [ CONNECTED ]                                                          |
|  - RedisVL Cache: [ CONNECTED ] (Hit rate: 88%)                                                   |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Backend APIs & Data Contracts

| Method | Endpoint | Description | Response Model |
|---|---|---|---|
| `GET` | `/health` | Validates API status, database, and vector store readiness | `{"status": "ok", "version": str}` |
| `GET` | `/pipelines` | Lists configured RAG retrieval pipelines | `list[PipelineRecord]` |
| `GET` | `/chat/stats` | Retrieves system-wide query volume, latency, and token totals | `ChatStatsResponse` |
| `GET` | `/guardrails/stats` | Aggregates safety violations and blocked request rates | `GuardrailsStatsResponse` |

---

## 4. Key Workflows & User Navigation
1. **Interactive Session Launch**: Launch `/chat` to test hybrid queries against loaded document collections.
2. **Pipeline Parameter Tuning**: Navigate to `/pipelines` to adjust retrieval limits, dense/sparse weighting (alpha: 0.7 dense / 0.3 sparse), and generator models.
3. **Safety & Policy Auditing**: Direct access to `/guardrails/config` to manage PII masking and prompt injection policies.
