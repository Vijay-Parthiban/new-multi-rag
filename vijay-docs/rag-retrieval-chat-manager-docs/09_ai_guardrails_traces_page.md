# 09 — Guard Traces Page

**Last updated:** 2026-09-21

**Sidebar label:** Guard Traces · **Route:** `/guardrails/traces` · **Component:** `frontend/src/pages/GuardrailsTracesPage.tsx` · **In-page `<h1>`:** "Guard Traces & Analytics"

(Navigation entry and mount: `components/AppLayout.tsx:34,129,217`; page title `GuardrailsTracesPage.tsx:151`.)

## 1. Executive Summary & Page Purpose
The **Guard Traces Page** is the audit ledger of guardrail checks. Every time `_run_guardrails()` validates a chat phase it writes one `guardrails_traces` row (table `guardrails_traces`, `rag_db/models/guardrails.py:29-44`) containing the query, the answer (output phase only), the blocked flag, the validator that blocked and the raw per-validator results. The page lists those rows with filters and pagination, renders aggregate counters and charts from `GET /guardrails/stats`, breaks failures down per validator, and opens one row in a detail drawer.

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
|  Failures by validator   (counted over the loaded traces)                        |
|    ban_list        3 of 12 checks failed   [============        ]                |
|    detect_pii      1 of 12 checks failed   [====                ]                |
+----------------------------------------------------------------------------------+
|  Filters:  Status [ All | Blocked | Passed ]                                     |
|            Validator [ All validators v ]   [ Search the query text... ] [Clear] |
+----------------------------------------------------------------------------------+
|  Traces table                                                                    |
|  Time        | Config      | Query               | Status     | Guard | Phase    |
|  ----------- | ----------- | ------------------- | ---------- | ----- | -------- |
|  9/17 10:14  | Prod Safety | Contact me at a@b.c | Blocked    | Ban   | input    |
|  ...         |             |                     | ! 1/3      |       |          |
|  9/17 10:11  | Prod Safety | What is the capital | Passed     | —     | —        |
+----------------------------------------------------------------------------------+
|  [ ← Prev ]   Page 1 of 4   [ Next → ]                                           |
+----------------------------------------------------------------------------------+
|  Click a row -> drawer: Trace detail                                             |
|    time · config name · Blocked/Passed · by <validator> on the <phase> phase     |
|    Query  (full text)                                                            |
|    Response  (full text, or "No response. The service stopped the chat turn...") |
|    Validator results (N)                                                         |
|      <validator name>   [ Passed | Failed ]                                      |
|      detail text   ·   Error: <error>                                            |
+----------------------------------------------------------------------------------+
```

- Data load: `getGuardrailsStats()` and `listGuardrailsTraces({guard, blocked, limit: 25, offset: page * 25})` run in parallel on every filter/page change (`GuardrailsTracesPage.tsx:53-64`). The page size is fixed at 25 (`GuardrailsTracesPage.tsx:12`).
- KPI cards render `total_requests`, `blocked_requests`, `passed_requests` and `block_rate`. The card multiplies the 0–1 ratio by 100 and shows one decimal, so a rate of 0.069 displays as `6.9%` (`GuardrailsTracesPage.tsx:175-192`).
- Charts view adds two donuts, "Blocked vs Passed" and "Blocks by Guard". "Blocks by Guard" filters out validators with a zero count (`GuardrailsTracesPage.tsx:31-39,265-289`).
- Per-guard block cards come from `stats.per_guard` and click through to `filterGuard = guard`, `filterBlocked = "true"`, page 0, table view (`GuardrailsTracesPage.tsx:203-222`).
- **Failures by validator** is a horizontal bar list computed from the `guard_results` of the traces that are currently loaded (`countValidatorFailures`, `GuardrailsTracesPage.tsx:63-76`). One bar shows `<failures> of <total> checks failed` for each validator id, sorted by failures (`GuardrailsTracesPage.tsx:227-258`). The panel subtitle states that the counts cover the loaded traces only (`GuardrailsTracesPage.tsx:230-232`).
- Filters (`GuardrailsTracesPage.tsx:294-328`):
  - **Status**: `All Status` / `Blocked` / `Passed`, sent to the API as the `blocked` parameter (`GuardrailsTracesPage.tsx:10,56-60,296-305`).
  - **Validator**: a select, not a free-text box. Its options are the validator ids found in `stats.per_guard` and in the loaded `guard_results`, shown through `guardTitle()`. It is sent to the API as the `guard` parameter, which compares for exact equality against `blocked_by_guard` (`GuardrailsTracesPage.tsx:130-138,306-314`, `guardrails_repository.py:97-98`).
  - **Search the query text**: a client-side filter over the `query` of the loaded rows (`GuardrailsTracesPage.tsx:140-144,315-320`). It does not change the API call.
  - **Clear** resets all three filters and the page (`GuardrailsTracesPage.tsx:321-327`).
- Table columns (`GuardrailsTracesPage.tsx:346-396`): Time (`created_at`, localized), Config (`config_name`, `—` when absent), Query (truncated at 80 chars, full text in the cell `title`), Status badge (`Blocked` / `Passed`) with an `! n/m` failure chip when a loaded row has at least one failed check, Guard (`blocked_by_guard` through `guardTitle()`, `—` otherwise) and Phase (`blocked_on`, `—` otherwise).
- The failure chip reads `checkCounts()` for that row: the number of failed checks over the number of checks in its `guard_results` (`GuardrailsTracesPage.tsx:46-54,373-380`).
- Clicking a row opens the **row detail drawer** (`GuardrailsTracesPage.tsx:364,418-500`). The drawer is built from the already-loaded row. It does not fetch the trace again. It shows the time and `config_name`, the Blocked/Passed badge, "by `<validator>` on the `<phase>` phase", the full Query, the full Response (or "No response. The service stopped the chat turn before the model answered."), and every entry of `guard_results` with a Passed/Failed badge, the `detail` text and an `Error: <error>` line when an error is present (`GuardrailsTracesPage.tsx:427-493`). Clicking the scrim or pressing Escape closes it (`GuardrailsTracesPage.tsx:118-125,419-425`).
- Validator names come from `guardTitle()`, which maps the three original ids to friendly titles and returns the raw id otherwise (`GuardrailsTracesPage.tsx:15-19,41-43`). A validator outside that map shows its id and the default chip style (`GuardrailsTracesPage.tsx:384-388`).
- There is no latency column and no per-entity (PII span / confidence) view.

---

## 3. Backend APIs & Contracts

Router: `routes/guardrails.py`, prefix `/guardrails` (`rag_api/main.py:83`; frontend base `http://127.0.0.1:8001`, `frontend/src/api.ts:8`). Global API key required.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/traces` | List audit traces, newest first | `TraceListResponse` |
| `GET` | `/guardrails/stats` | Aggregate counters + blocks per guard | `StatsResponse` |

There is **no** `GET /guardrails/traces/{id}` endpoint — the router only defines the list route, so a single trace cannot be fetched (`routes/guardrails.py:376-403`).

### `GET /guardrails/traces` parameters (`routes/guardrails.py:376-384`)
| Parameter | Type | Default | Behaviour |
|---|---|---|---|
| `guard` | string | none | exact match on `blocked_by_guard` |
| `blocked` | bool | none | `true` -> only blocked, `false` -> only passed |
| `config_id` | uuid | none | restrict to one guardrails config |
| `limit` | int | 50 | page size (no upper bound) |
| `offset` | int | 0 | rows to skip. Ordering is `created_at DESC` (`guardrails_repository.py:107`) |

The UI sends `guard`, `blocked`, `limit` and `offset`. It never sends `config_id` even though the API supports it (`frontend/src/api.ts:1349-1361`).

### `TraceListResponse`
`total` (count before paging), `limit`, `offset`, `items: list[TraceResponse]` (`routes/guardrails.py:125-129`).

### `TraceResponse` — exact fields (`routes/guardrails.py:109-122,438-452`)
| Field | Type | Meaning |
|---|---|---|
| `id` | uuid | trace id |
| `config_id` | uuid \| null | config that was applied. Null when the trace was written without one |
| `config_name` | string \| null | resolved per row. It is `"No config"` when `config_id` is null, and `"Deleted"` when the config row no longer exists (`routes/guardrails.py:392-402`) |
| `chat_message_id` | uuid \| null | accepted by `record_trace` but never passed by the chat call path, so it is always null for chat writes (`guardrails_repository.py:62-86`, `routes/chat.py:335-344`) |
| `query` | string | the chat query |
| `response` | string \| null | the generated answer. Set only by the output-phase check (`routes/chat.py:430-443`) |
| `blocked` | bool | any validator failed |
| `blocked_by_guard` | string \| null | first failing validator id |
| `blocked_on` | string \| null | `"input"` / `"output"` when blocked, else null (`routes/chat.py:342`) |
| `guard_results` | object | raw per-validator verdicts (below) |
| `created_at` | ISO 8601 string \| null | write time |

### Per-validator verdicts (`guard_results`)
Keys are the config's validator ids. Values come from the guardrails-service `/validate` response: `validation_passed` (bool), `error` (a transport or configuration problem), `detail` (`null` when passed, otherwise the failure reason) (`guardrails-service/config.py:762-793`). The page reads `validation_passed` (`GuardrailsTracesPage.tsx:51,69,480,484`), `detail` (`:488`) and `error` (`:489-491`). The frontend types are `GuardResult` and `GuardrailsTrace` (`frontend/src/api.ts:1270-1289`).

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
    "ban_list": { "validation_passed": false, "error": null, "detail": "Contains banned word: codename" },
    "detect_pii": { "validation_passed": true, "error": null, "detail": null }
  },
  "created_at": "2026-09-17T10:14:22.000Z"
}
```

Transport and configuration problems are recorded on the same shape with `validation_passed: true` and a non-null `error` (`"HTTP <code>"` plus the response body in `detail`, or the exception message), so they are distinguishable from a real block (`rag_shared/guardrails_client.py:62-121`). A validator that is missing from the service reply is reported as `"validator missing from the response"` in `error` (`rag_shared/guardrails_client.py:113-118`). There are **no** confidence scores, matched-entity spans or offsets in the response.

### `GET /guardrails/stats` -> `StatsResponse` (`routes/guardrails.py:132-137,408-416`, `guardrails_repository.py:111-136`)
| Field | Meaning |
|---|---|
| `total_requests` | all `guardrails_traces` rows |
| `blocked_requests` | rows with `blocked = true` |
| `passed_requests` | `total_requests - blocked_requests` |
| `block_rate` | `blocked_requests / total_requests` as a 0–1 ratio, `0.0` when there are no rows |
| `per_guard` | map of `blocked_by_guard` -> count over blocked rows. Rows with a null guard are bucketed under `"unknown"` |

### How traces are written
`routes/chat.py:295-353` records the trace inside the same session as the config lookup: `config_id`, `query`, `response` (output phase only), `blocked`, `blocked_by_guard`, `blocked_on` (phase when blocked, else null) and the full `guard_results` map. Nothing else in the codebase writes `guardrails_traces`.

### Implementation note (verified in the working tree)
- The service reply is keyed by the validator ids in the request. The client renames a legacy guard id before it builds the request, so an upgraded config and the trace agree on `detect_pii` (`rag_shared/guardrails_client.py:12,91-92`).
- A failed chat turn records `blocked_on` as the phase. A passed turn records `blocked_on: null`, so the table shows `—` in the Phase column (`routes/chat.py:342`, `GuardrailsTracesPage.tsx:391`).
