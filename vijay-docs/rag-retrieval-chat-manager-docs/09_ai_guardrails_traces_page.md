# 09 — Guard Traces Page

**Last updated:** 2026-09-17

**Sidebar label:** Guard Traces · **Route:** `/guardrails/traces` · **Component:** `frontend/src/pages/GuardrailsTracesPage.tsx` · **In-page `<h1>`:** "Guard Traces & Analytics"

(Navigation entry and mount: `components/AppLayout.tsx:33,124,211`; page title `GuardrailsTracesPage.tsx:81`.)

## 1. Executive Summary & Page Purpose
The **Guard Traces Page** is the audit ledger of guardrail checks. Every time `_run_guardrails()` validates a chat phase it writes one `guardrails_traces` row (table `guardrails_traces`, `rag_db/models/guardrails.py:29-44`) containing the query, the answer (output phase only), the blocked flag, the guard that blocked and the raw per-guard results. The page lists those rows with filters and pagination, and renders aggregate counters and charts from `GET /guardrails/stats`.

Each row is a **phase run**, not a chat turn: an input+output config on one message produces two rows, and a row is written for passed checks as well as blocked ones.

---

## 2. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------+
|  ⛨ Guard Traces & Analytics        [ Table | Charts ] [ ↻ Refresh ]              |
+----------------------------------------------------------------------------------+
|  KPI cards:  Total Requests | Blocked | Passed | Block Rate                      |
|  Analytics:  [ donut: Blocks by Guard ]   [ per-guard block cards -> filter ]    |
+----------------------------------------------------------------------------------+
|  Filters:  Status [ All | Blocked | Passed ]  Guard [ filter by guard name... ]  |
+----------------------------------------------------------------------------------+
|  Traces table                                                                    |
|  Time        | Config           | Query               | Status  | Guard  | Phase |
|  ----------- | ---------------- | ------------------- | ------- | ------ | ------|
|  9/17 10:14  | Prod Safety      | Contact me at a@b.c | Blocked | Ban    | input |
|  9/17 10:11  | Prod Safety      | What is the capital | Passed  | —      | —     |
+----------------------------------------------------------------------------------+
|  [ ← Prev ]   Page 1 of 4   [ Next → ]                                           |
+----------------------------------------------------------------------------------+
```

- Data load: `getGuardrailsStats()` and `listGuardrailsTraces({guard, blocked, limit: 25, offset: page * 25})` in parallel on every filter/page change (`GuardrailsTracesPage.tsx:51-73`); page size is fixed at 25 (`GuardrailsTracesPage.tsx:49`).
- KPI cards render `total_requests`, `blocked_requests`, `passed_requests` and `block_rate` verbatim with a literal `%` appended — the API sends a 0–1 ratio, so a 25% rate displays as `0.25%` (`GuardrailsTracesPage.tsx:97-116`).
- Charts view adds two donuts, "Blocked vs Passed" and "Blocks by Guard"; "Blocks by Guard" filters out guards with a zero count (`GuardrailsTracesPage.tsx:28-36,149-176`).
- Per-guard block cards come from `stats.per_guard` and click through to `filterGuard = guard`, `filterBlocked = "true"`, page 0 (`GuardrailsTracesPage.tsx:128-147`).
- Table columns: Time (`created_at`, localized), Config (`config_name`, `—` when absent), Query (truncated at 80 chars, full text in the cell `title`), Status badge (`Blocked` / `Passed`), Guard (`blocked_by_guard`, mapped to friendlier titles for the three known ids, `—` otherwise) and Phase (`blocked_on`, `—` otherwise) (`GuardrailsTracesPage.tsx:202-242`).
- The free-text "Filter by guard name..." box is passed as the `guard` query parameter, which the API compares for exact equality against `blocked_by_guard` — partial text only matches when it is the full guard id (`GuardrailsTracesPage.tsx:178-200`, `guardrails_repository.py:97-98`).
- There is no trace-detail drawer, no latency column and no per-entity (PII span/confidence) view.

---

## 3. Backend APIs & Contracts

Router: `routes/guardrails.py`, prefix `/guardrails` (`rag_api/main.py:79`; frontend base `http://localhost:8001`, `frontend/src/api.ts:5`). Global API key required.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/traces` | List audit traces, newest first | `TraceListResponse` |
| `GET` | `/guardrails/stats` | Aggregate counters + blocks per guard | `StatsResponse` |

There is **no** `GET /guardrails/traces/{id}` endpoint — the router only defines the list route, so a single trace cannot be fetched (`routes/guardrails.py:321-347`).

### `GET /guardrails/traces` parameters (`routes/guardrails.py:321-347`)
| Parameter | Type | Default | Behaviour |
|---|---|---|---|
| `guard` | string | none | exact match on `blocked_by_guard` |
| `blocked` | bool | none | `true` -> only blocked, `false` -> only passed |
| `config_id` | uuid | none | restrict to one guardrails config |
| `limit` | int | 50 | page size (no upper bound) |
| `offset` | int | 0 | rows to skip; ordering is `created_at DESC` |

The UI sends `guard`, `blocked`, `limit`, `offset`; it never sends `config_id` even though the API supports it (`frontend/src/api.ts:1032-1045`).

### `TraceListResponse`
`total` (count before paging), `limit`, `offset`, `items: list[TraceResponse]` (`routes/guardrails.py:133-137`).

### `TraceResponse` — exact fields (`routes/guardrails.py:119-127,380-394`)
| Field | Type | Meaning |
|---|---|---|
| `id` | uuid | trace id |
| `config_id` | uuid | config that was applied |
| `config_name` | string \| null | resolved per row; `"Deleted"` when the config row no longer exists (`routes/guardrails.py:337-344`) |
| `chat_message_id` | uuid \| null | accepted by `record_trace` but never passed by the chat call path, so it is always null for chat writes (`guardrails_repository.py:62-86`, `routes/chat.py:335-343`) |
| `query` | string | the chat query |
| `response` | string \| null | the generated answer; set only by the output-phase check (`routes/chat.py:432-440`) |
| `blocked` | bool | any guard failed |
| `blocked_by_guard` | string \| null | first failing guard id |
| `blocked_on` | string \| null | `"input"` / `"output"` when blocked, else null (`routes/chat.py:340`) |
| `guard_results` | object | raw per-guard verdicts (below) |
| `created_at` | ISO 8601 string \| null | write time |

### Per-guard verdicts (`guard_results`)
Keys are the config's guard ids; values are the guardrails-service `/parse/{guard}` response verbatim: `validation_passed` (bool), `error` (null on an evaluated verdict), `detail` (`null` when passed, otherwise the failure reason) (response built at `guardrails-service/server.py:44-51`).

```json
{
  "id": "c19b48f1-928d-4c31-9f93-bc429188ae01",
  "config_id": "3695cb61-e728-4bf1-91f8-cf249d593c6b",
  "config_name": "Production Safety",
  "chat_message_id": null,
  "query": "Please use the codename for this project.",
  "response": null,
  "blocked": true,
  "blocked_by_guard": "ban_list",
  "blocked_on": "input",
  "guard_results": {
    "ban_list": { "validation_passed": false, "error": null, "detail": "Contains banned word: codename" }
  },
  "created_at": "2026-09-17T10:14:22.000Z"
}
```

Transport/HTTP problems are recorded on the same shape with `validation_passed: true` and a non-null `error` (`"HTTP <code>"` plus the response body in `detail`, or the exception message plus `"Guardrails connection error"`), so they are distinguishable from a real block (`rag_shared/guardrails_client.py:22-41`). Because config guard ids and the service's route names differ (see below), that transport form — `{"validation_passed": true, "error": "HTTP 404", "detail": ...}` — is what a trace currently holds for every guard. There are **no** confidence scores, matched-entity spans or offsets in the current response.

### `GET /guardrails/stats` -> `StatsResponse` (`routes/guardrails.py:140-146,349-356`, `guardrails_repository.py:111-136`)
| Field | Meaning |
|---|---|
| `total_requests` | all `guardrails_traces` rows |
| `blocked_requests` | rows with `blocked = true` |
| `passed_requests` | `total_requests - blocked_requests` |
| `block_rate` | `blocked_requests / total_requests` as a 0–1 ratio, `0.0` when there are no rows |
| `per_guard` | map of `blocked_by_guard` -> count over blocked rows; rows with a null guard are bucketed under `"unknown"` |

### How traces are written
`routes/chat.py:295-353` records the trace inside the same session as the config lookup: `config_id`, `query`, `response` (output phase only), `blocked`, `blocked_by_guard`, `blocked_on` (phase when blocked, else null) and the full `guard_results` map. Nothing else in the codebase writes `guardrails_traces`.

### Implementation note (verified in the working tree)
- The service registers hyphenated guard ids (`ban-list`, `pii-check`, `toxic-language`) while configs store underscore ids (`ban_list`, `pii_check`, `toxic_language`); a 404 from `/parse/{guard}` is stored as `validation_passed: true` with `error: "HTTP 404"`, so such rows show as **Passed** and never appear in `per_guard` (`guardrails-service/server.py:20-38`, `guardrails-service/config.py:122-146`, `rag_shared/guardrails_client.py:22-41`).
