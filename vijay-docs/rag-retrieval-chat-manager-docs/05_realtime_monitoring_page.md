# 05 — Real-Time Monitoring & Telemetry Page

## 1. Executive Summary & Page Purpose
The **Real-Time Monitoring & Telemetry Page** (`TrackingPage.tsx`, route: `/tracking` / `/evaluations`) provides production observability into active RAG pipeline health. It monitors latency distributions (p50, p95, p99), token consumption, request throughput, cache hit ratios, and real-time generation quality scores calculated asynchronously by the evaluation worker.

---

## 2. Key Telemetry Metrics & Dashboards

```
+-----------------------------------------------------------------------------------------------+
|  Real-Time Production Telemetry                                                               |
|  Live request streams, latency percentiles, token usage, and quality score tracking.          |
+-----------------------------------------------------------------------------------------------+
|  Summary Metrics:                                                                             |
|  [ Total Queries: 1,482 ]   [ P95 Latency: 1.12s ]   [ Cache Hit Rate: 88.4% ]   [ Cost: $4.12 ]|
+-----------------------------------------------------------------------------------------------+
|  Latency Breakdown (Waterfall Average):                                                       |
|  - Retrieval (Qdrant + OpenSearch):  ███████████░░░░░░░░░░░░  124ms (11%)                     |
|  - Reranking (Cohere / BGE):         █████████████████░░░░░░  185ms (16%)                     |
|  - Generation (GPT-4o Stream):       ███████████████████████  810ms (69%)                     |
|  - Guardrails & Sanitization:        ████░░░░░░░░░░░░░░░░░░░   45ms (4%)                      |
+-----------------------------------------------------------------------------------------------+
|  Live Request Stream Table:                                                                   |
|  Timestamp | Query Preview      | Pipeline        | Latency | Tokens | Status | Quality Score  |
|  ----------+--------------------+-----------------+---------+--------+--------+--------------- |
|  10:14:02  | Senior AI engineer | Enterprise-RAG  | 1.18s   | 412    | 200 OK | 0.96 (Faith)   |
|  10:13:45  | Qdrant collection  | Enterprise-RAG  | 0.94s   | 318    | 200 OK | 0.92 (Faith)   |
|  10:12:11  | Dropped table...   | Enterprise-RAG  | 0.04s   | 0      | BLOCKED| Guardrail Block|
+-----------------------------------------------------------------------------------------------+
```

---

## 3. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/chat/stats` | System query volume, avg latency, token aggregates | `ChatStatsResponse` |
| `GET` | `/tracking/stream` | Server-Sent Events stream of live incoming RAG traces | `EventStream[TraceEvent]` |
| `GET` | `/tracking/latency-breakdown` | Component-level latency percentiles | `LatencyBreakdownResponse` |
| `GET` | `/guardrails/stats` | Safety interception rates and policy breakdowns | `StatsResponse` |

### Sample Latency Payload (`GET /tracking/latency-breakdown`)
```json
{
  "total_requests": 1482,
  "p50_ms": 890,
  "p95_ms": 1120,
  "p99_ms": 1840,
  "component_averages_ms": {
    "retrieval": 124,
    "reranker": 185,
    "generation": 810,
    "guardrails": 45
  },
  "cache_hit_rate": 0.884
}
```
