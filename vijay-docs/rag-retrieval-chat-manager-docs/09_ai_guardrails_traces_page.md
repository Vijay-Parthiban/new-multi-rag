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
+----------------------------------------------------------------------------------+
|  Blocks by guard                                                                 |
|    Each row is a validator that blocked. Select one to filter the table.          |
|    Banned keyword      13 blocked · 86.7%  [==============================]      |
|    Personal info        2 blocked · 13.3%  [=====                         ]      |
+----------------------------------------------------------------------------------+
|  Failures by validator   (counted over the loaded traces)                        |
|    Banned keyword   3 of 12 checks failed   [============        ]                |
|    Personal info    1 of 12 checks failed   [====                ]                |
+----------------------------------------------------------------------------------+
|  Filters:  Status [ All | Blocked | Passed ]                                     |
|            Validator [ All validators v ]   [ Search the query text... ] [Clear] |
+----------------------------------------------------------------------------------+
|  Traces table   (sticky header; a row is focusable and opens on Enter or Space)   |
|  Time        | Config      | Query               | Status      | Guard  | Phase   |
|  ----------- | ----------- | ------------------- | ----------- | ------ | ------- |
|  10:14       | Prod Safety | Contact me at a@b.c | Blocked     | ● Ban  | input   |
|  Sep 17      |             |                     | ! 1/3 failed|  kw    |         |
|  10:11       | Prod Safety | What is the capital | Passed      | —      | —       |
|  Sep 17      |             |                     |             |        |         |
+----------------------------------------------------------------------------------+
|  Click a row to see the full query, response and validator detail.               |
|  [ ← Prev ]   Page 1 of 4   [ Next → ]                                           |
+----------------------------------------------------------------------------------+
|  Click a row -> drawer: Trace detail                                             |
|    Sep 17 · 10:14 · Prod Safety                         [ ✕ ]                    |
|    Blocked   by <validator name> on the <phase> phase                            |
|    Query  (full text)                                                            |
|    Response  (full text, or "No response. The service stopped the chat turn...") |
|    Validator results (N)                                                         |
|      <validator name>   [ Passed | Failed ]                                      |
|      detail text   ·   Error: <error>                                            |
+----------------------------------------------------------------------------------+
```

The **Charts** view shows one labelled proportion bar for blocked versus passed, then the same ranked "Blocks by guard" list (`GuardrailsTracesPage.tsx:313-350`). It uses a `ProportionBar` component (`:20-56`) instead of the two donuts it used to draw.

- Data load: `getGuardrailsStats()` and `listGuardrailsTraces({guard, blocked, limit: 25, offset: page * 25})` run in parallel on every filter/page change (`GuardrailsTracesPage.tsx:132-150`). The page size is fixed at 25 (`GuardrailsTracesPage.tsx:13`).
- KPI cards render `total_requests`, `blocked_requests`, `passed_requests` and `block_rate`. The card multiplies the 0–1 ratio by 100 and shows one decimal, so a rate of 0.069 displays as `6.9%` (`GuardrailsTracesPage.tsx:204-227`).
- **Charts view** is one `ProportionBar` for blocked versus passed (`GuardrailsTracesPage.tsx:314-326`) plus the same "Blocks by guard" ranked list (`:327-350`). The two donuts were removed: a 13-versus-2 split renders as a circle with a sliver, and the SVG donut component and its ten CSS rules were deleted.
- **Blocks by guard** is one card, always visible above the filters, driven by `stats.per_guard` (`guardBreakdown`, `GuardrailsTracesPage.tsx:152-162`). It sorts largest first, filters out zero counts, and labels each row `<count> blocked · <share>%` (`:229-270`). A row is a button: selecting it sets `filterGuard = guard`, `filterBlocked = "true"`, page 0, and returns to the table view (`:243-249`).
- **Failures by validator** is a horizontal bar list computed from the `guard_results` of the traces that are currently loaded (`countValidatorFailures`, `GuardrailsTracesPage.tsx:86-100`). One bar shows `<failures> of <total> checks failed` for each validator id, sorted by failures (`GuardrailsTracesPage.tsx:273-305`). The panel subtitle states that the counts cover the loaded traces only (`:275-278`).
- Filters (`GuardrailsTracesPage.tsx:364-397`):
  - **Status**: `All Status` / `Blocked` / `Passed`, sent to the API as the `blocked` parameter (`GuardrailsTracesPage.tsx:11,137-145,366-375`).
  - **Validator**: a select, not a free-text box. Its options are the validator ids found in `stats.per_guard` and in the loaded `guard_results`, shown through `guardTitle()` (`GuardrailsTracesPage.tsx:164-172`). It is sent to the API as the `guard` parameter, which compares for exact equality against `blocked_by_guard` (`GuardrailsTracesPage.tsx:376-384`, `guardrails_repository.py:97-98`).
  - **Search the query text**: a client-side filter over the `query` of the loaded rows (`GuardrailsTracesPage.tsx:174-178,385-390`). It does not change the API call.
  - **Clear** resets all three filters and the page (`GuardrailsTracesPage.tsx:391-397`).
- Table columns (`GuardrailsTracesPage.tsx:415-479`): Time, Config (`config_name`, `—` when absent), Query (truncated at 80 chars, full text in the cell `title`), Status badge (`Blocked` / `Passed`) with a failure chip, Guard (`blocked_by_guard` through `guardTitle()`, `—` otherwise) and Phase (`blocked_on`, `—` otherwise).
- The **Time** column is two lines: `formatClock()` gives the time (`10:14`) and `formatDay()` gives the day beneath it (`Sep 17`) (`GuardrailsTracesPage.tsx:58-67,445-448`). The single full locale timestamp on every row made a 25-row list hard to scan.
- The **failure chip** reads `checkCounts()` for that row and states the meaning: `! 1/3 failed`, with `1 of 3 checks failed` in the `title` attribute (`GuardrailsTracesPage.tsx:69-80,458-462`). It renders only when at least one check failed.
- The **Guard** cell is a tone dot plus the validator name (`GuardrailsTracesPage.tsx:465-471`). The name carries the meaning, so colour is never the only signal. The emoji icons that used to sit here were removed.
- A row is **keyboard reachable**: `tabIndex={0}`, `role="button"`, an aria-label that reads the day, time and verdict, and Enter or Space opens the drawer (`GuardrailsTracesPage.tsx:433-444`).
- The table header is **sticky** inside `gr-table-wrapper` (`index.css` `.gr-table thead th`), so the column names stay visible while a long trace list scrolls.
- A hint under the table states the interaction: "Click a row to see the full query, response and validator detail." (`GuardrailsTracesPage.tsx:480`).
- Clicking a row opens the **row detail drawer** (`GuardrailsTracesPage.tsx:435,500-573`). The drawer is built from the already-loaded row. It does not fetch the trace again. It shows the day, time and `config_name`, the Blocked/Passed badge, "by `<validator>` on the `<phase>` phase", the full Query, the full Response (or "No response. The service stopped the chat turn before the model answered."), and every entry of `guard_results` with a Passed/Failed badge, the `detail` text and an `Error: <error>` line when an error is present (`GuardrailsTracesPage.tsx:509-567`). Clicking the scrim or pressing Escape closes it (`GuardrailsTracesPage.tsx:118-125,501-507`). The close control is a labelled 36 px button with a visible border and an `aria-label`, because the previous bare small button read as a dark blob on the dark drawer.
- Validator names come from `guardMeta()` / `guardTitle()` in `frontend/src/utils/guardLabels.ts`. That module maps the seven catalog ids to a friendly title and a tone, and `humanizeGuardId()` falls back to a readable form of any unknown id (`secrets_present` renders as "Secrets present"), so a validator the map does not know never shows as a raw slug. A validator outside the map takes the `other` tone.
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
- A failed chat turn records `blocked_on` as the phase. A passed turn records `blocked_on: null`, so the table shows `—` in the Phase column (`routes/chat.py:342`, `GuardrailsTracesPage.tsx:473`).
- `frontend/src/utils/guardLabels.ts` is the single source of validator display names for the Traces page and the Guard Evaluation page. It exports `guardMeta()` (title plus tone), `guardTitle()` (title only) and `humanizeGuardId()`. The map was a page-local three-entry table that keyed the retired `pii_check` id, so a real PII block rendered the raw id `detect_pii`. Add a new catalog validator to that map to give it a name; without an entry it still renders as a readable slug.
