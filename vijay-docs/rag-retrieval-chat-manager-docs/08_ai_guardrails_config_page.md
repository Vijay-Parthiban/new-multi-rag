# 08 — Guard Config Page

**Last updated:** 2026-09-21

**Sidebar label:** Guard Config · **Route:** `/guardrails/config` · **Component:** `frontend/src/pages/GuardrailsConfigPage.tsx` · **In-page `<h1>`:** "Guard Configuration"

(Navigation entry and mount: `components/AppLayout.tsx:33,128,213`; page title `GuardrailsConfigPage.tsx:633`.)

## 1. Executive Summary & Page Purpose
The **Guard Config Page** creates, edits, enables/disables and deletes `GuardrailsConfig` rows (table `guardrails_configs`, `rag_db/models/guardrails.py:13-26`). Each row selects a subset of the validators that `guardrails-service` exposes, the chat phases it applies to (`input`, `output`, `both`), and the parameters of every selected validator. The same rows are what Chat applies when a request carries `guardrails_config_id` (`routes/chat.py:24,379,431,528,612`) and what the Guard Evaluation page scores against (`routes/guardrails_evaluate.py:253-375`).

The page is **catalog-driven**. The form is generated from `GET /guardrails/guards`, which proxies the catalog of `guardrails-service`. The catalog holds **3 validators**. Only `guardrails-service/config.py` (`_VALIDATORS`) defines that list, so there is no second copy of it in the repository.

A failing validator **blocks** the turn: the answer is replaced with fixed copy from `GUARD_BLOCK_COPY` (`routes/chat.py:118-139`) rather than being redacted. A transport or configuration problem does **not** block. The client reports such a problem as `validation_passed: true` plus an `error`, and the trace records it (`rag_shared/guardrails_client.py:62-121`).

---

## 2. Guardrails Architecture & Supported Guards

```
+----------------------------------------------------------------------------------+
|  Chat request carrying guardrails_config_id        (routes/chat.py:24)            |
+-----------------------------------+----------------------------------------------+
                                    v
+----------------------------------------------------------------------------------+
|  _run_guardrails(config_id, phase, text)           (routes/chat.py:295-353)      |
|  1. load the GuardrailsConfig row from guardrails_configs                        |
|  2. mode gate: "input" -> input phase only, "output" -> output phase only,        |
|     "both" -> both phases                          (routes/chat.py:320-325)      |
|  3. POST {guardrails_url}/validate                                               |
|     body: {"text": text, "phase": phase,                                         |
|            "validators": [{"id": ..., "params": {...}, "on_fail": ...}, ...]}     |
|                                    (rag_shared/guardrails_client.py:62-121)      |
+-----------------------------------+----------------------------------------------+
                                    v
+----------------------------------------------------------------------------------+
|  results keyed by validator id: {"validation_passed": bool,                      |
|                                  "error": str|null, "detail": str|null}           |
|                                    (guardrails-service/config.py)         |
|  any validation_passed == false -> turn is blocked (guardrails_client.py:123-128) |
|  a guardrails_traces row is written for every phase run (routes/chat.py:335-345)  |
+----------------------------------------------------------------------------------+
```

### Validator catalog (`GET /guardrails/guards`)
The catalog comes from `guardrails-service/config.py` (`_VALIDATORS`) and is served by
`guardrails-service/server.py` (`GET /catalog`). Every entry carries `category`, `phase`,
`kind`, the parameter schema and an `available` flag with `unavailable_reason` when a
validator package is missing from the installation.

**The catalog holds exactly three validators.** The Guard Config page renders whatever the
catalog serves, so it shows three with no frontend change. Adding a fourth entry to
`_VALIDATORS` makes it appear on the page.

`kind` has three values:
- `local` — a packaged validator from public PyPI. It runs inside the container with no downloaded model.
- `model` — a packaged validator that loads a model. `detect_pii` runs Presidio with a spaCy pipeline.
- `llm` — a judge that calls the LiteLLM proxy. It needs no package of its own.

**Content Safety**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `ban_list` | Ban List | `local` | both | `banned_words` (string_list, required, free text), `max_l_dist` (integer, default `0`, range 0–5) | `guardrails-ai-ban-list` |
| `toxic_language` | Toxic Language | `llm` | both | `threshold` (number, default `0.5`, range 0–1), `model` (string, default empty) | `local/toxic_language` |

**Privacy**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `detect_pii` | PII Detection | `model` | both | `pii_entities` (string_list, required, 18 options, default `EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, IP_ADDRESS`) | `guardrails-ai-detect-pii` |

The `pii_entities` parameter carries 18 options: `EMAIL_ADDRESS` (Email Address),
`PHONE_NUMBER` (Phone Number), `CREDIT_CARD` (Credit Card), `US_SSN` (US SSN),
`IP_ADDRESS` (IP Address), `PERSON` (Person Name), `LOCATION` (Location), `DATE_TIME`
(Date / Time), `URL` (URL), `DOMAIN_NAME` (Domain Name), `US_PASSPORT` (US Passport),
`US_DRIVER_LICENSE` (US Driver License), `US_BANK_NUMBER` (US Bank Number), `US_ITIN`
(US ITIN), `IBAN_CODE` (IBAN Code), `CRYPTO` (Crypto Wallet), `MEDICAL_LICENSE`
(Medical License), `NRP` (Nationality / Religion / Political group).

`toxic_language` is a local implementation of the Guardrails `Validator` interface and has
no package. It sends the text to the LiteLLM proxy with `max_tokens` from
`GUARDRAIL_LLM_MAX_TOKENS`. The upstream package needs PyTorch and several gigabytes of
CUDA libraries, so it is deliberately not installed.

### What the catalog used to hold, and why it was cut

The catalog held 16 validators. It now holds these three. The cut removed `mentions_drugs`,
`restrict_to_topic`, `prompt_injection`, `secrets_present`, `regex_match`, `valid_length`,
`ends_with`, `valid_json`, `one_line`, `lowercase`, `uppercase`, `reading_time` and
`exclude_sql_predicates`, together with the `LlmRestrictToTopic` and `LlmPromptInjection`
judge classes.

Two of the 16 carried a real cost. `restrict_to_topic` and `prompt_injection` were
judge-backed, so a config that selected them paid one extra LLM call per chat turn per
validator. The other 11 were cheap, but they were never the point of the page: the
platform's stated checks are toxic language, personal data and a banned-word list.

`LEGACY_GUARD_IDS` and `_LEGACY_SETTING_KEYS` in `rag_shared/guardrails_client.py` still map
`pii_check` to `detect_pii` and the flat `banned_words` / `pii_entities` settings keys to
their owners. Both mapped validators survive the cut, so the upgrade path for old rows is
unchanged.

A saved config may still name a removed validator. The page renders such an id as a bare
tag with the note "Not in the catalog", so a stale row is visible rather than blank.

### `on_fail` options (`GET /guardrails/on-fail-options`)
Exactly three options exist (`config.py`). `on_fail` sits beside the parameters of each selected validator.

| id | Label | `fixes_text` | Meaning |
|---|---|---|---|
| `noop` | Block the request | `false` | Record the failure and stop the chat turn. This is the default. |
| `exception` | Block and raise an error | `false` | Same effect. The validator raises instead of returning. |
| `fix` | Repair the text and continue | `true` | Rewrite the text, for example to lower case, and continue the turn. Only some validators support this. |

### guardrails-service endpoints
`guardrails-service/server.py` is a plain FastAPI app (`server.py:24`). It has exactly four endpoints.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/health-check` | Liveness | `{"status": "ok"}` (`server.py:45-47`) |
| `GET` | `/catalog` | The validator catalog and the failure-action options | `{"version": 1, "validators": [...], "on_fail_options": [...]}` (`server.py`) |
| `POST` | `/validate-config` | Check that a validator list and its parameters can be built. Runs nothing | `{"validators": [{id, params, on_fail}]}` -> `{"valid": bool, "errors": [str]}` (`server.py:56-66`) |
| `POST` | `/validate` | Run every configured validator over one text | `{"text", "phase", "validators": [...]}` -> the per-validator result map (`server.py:69-90`) |

These four endpoints are the whole surface of the service. `guardrails-service/pyproject.toml:6-27` lists `guardrails-ai` and the validator packages.

`POST /validate` rejects an empty validator list and a bad parameter with HTTP 422 and a readable message (`server.py:77-87`). A parameter error comes from `coerce_params` (`config.py`), for example `Ban List: 'Keywords' is required` (`config.py`). The reply is keyed by validator id and also carries `blocked`, `blocked_by` and `phase` (`config.py`).

### Why the validators are real packages now
The old `config.py` imported `BanList`, `DetectPII` and `ToxicLanguage` from `guardrails.hub` inside a `try` / `except ImportError`, with hand-written fallbacks. No Hub validator was ever installed, so the fallbacks always ran. Two of them were wrong:

- The fallback `ToxicLanguage.validate` always returned `PassResult()`. The toxic-language guard could never block anything. A live check before the fix proved it: the old service reported `validation_passed: true` for the sentence "You are an idiot and I hope you fail completely."
- The fallback `DetectPII` was four regular expressions (email, phone, US SSN, IPv4). It missed `4111 1111 1111 1111`, a card number with spaces, and it never found names or locations.

The service now installs the two packaged validators from public PyPI as `guardrails-ai-<name>`. The `guardrails hub install` CLI and its private registry are deprecated, and the `from guardrails.hub import X` shim is scheduled for removal (`config.py`, `pyproject.toml`).

### Deployment
- `guardrails-service/Dockerfile:25-36` downloads the spaCy model `en_core_web_sm` (12 MB) and rewrites Presidio's `conf/default.yaml` from `en_core_web_lg` (590 MB) to the small model. The build fails if Presidio stops pinning the large model.
- `guardrails-service/Dockerfile:41-43` writes `/root/.guardrailsrc`. A missing file makes every `Validator` constructor raise.
- `rag-ingestion-manager/docker-compose.yaml:306-317` builds the service from `../guardrails-service`, maps port `18000` to `8000`, reads `rag-ingestion-manager/.env.guardrails`, and sets `extra_hosts: host.docker.internal:host-gateway` so the judge reaches LiteLLM on the host.
- `rag-ingestion-manager/.env.guardrails:7-12` sets `LITELLM_BASE_URL`, `LLM_API_KEY`, `GUARDRAIL_LLM_MODEL=Gpt-oss-20b` and `GUARDRAIL_LLM_MAX_TOKENS=512`.

The judge models are reasoning models. At `max_tokens=160` they return an empty body and the judge fails. At 512 they answer correctly in 1–3 s. `Gpt-oss-20b` measured 18/18 correct across six texts. `Gpt-oss-120b` measured 8–105 s and timed out, so do not select it. The code default is `Gpt-oss-120b` (`config.py`) and the deployment overrides it to `Gpt-oss-20b` (`.env.guardrails:9`).

---

## 3. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------+
|  [icon] Guard Configuration                                   [ + New Config ]   |
|         Choose the checks that run on every chat turn, and set what happens       |
|         when a check fails.                                                       |
+----------------------------------------------------------------------------------+
|  Create / Edit Config form (shown after + New Config or Edit):                   |
|  Name [__________________]   Description (optional) [__________________]         |
|  The picker and the settings are two panes. Only a selected validator gets a      |
|  settings panel, so the form stays one screen high.                               |
|  +--------------------------+  +----------------------------------------------+  |
|  | Validators            3  |  | Settings                          2          |  |
|  |                          |  |                                              |  |
|  | Content Safety       2   |  | Ban List                [both]     Remove    |  |
|  |  [x] Ban List    [local] |  |  desc: Block a list of words or phrases.      |  |
|  |      Block a list of w…  |  |  Banned words *    (chip picker, free text)   |  |
|  |  [x] Toxic Lang    [llm] |  |  Fuzzy distance    [ 0 ]                      |  |
|  |      Flag abusive, har…  |  |  Action when the text fails [ Block req. v ]  |  |
|  | Privacy              1   |  |                                              |  |
|  |  [x] PII Detect  [model] |  | PII Detection           [both]     Remove    |  |
|  |      Detect personal d…  |  |  PII types *   (chip picker, 18 options)      |  |
|  |                          |  |  Action when the text fails [ Block req. v ]  |  |
|  +--------------------------+  +----------------------------------------------+  |
|  Mode:   ( ) Input Only   ( ) Output Only   (o) Both                              |
|                                          [ Cancel ]  [ Create / Update ]         |
+----------------------------------------------------------------------------------+
|  Config cards grid (one card per config):                                        |
|  ┌────────────────────────────────────────────────────────────────────────────┐  |
|  │ Production Safety                                   [ Active ]            │   |
|  │ Mode: both                                                                 │  |
|  │ Guards: [ Ban List ] [ PII Detection ]                                     │  |
|  │   Keywords: drop table, internal_only                                      │  |
|  │   PII types: Email Address, US SSN                                         │  |
|  │                      [ Disable ] [ Edit ] [ Delete ]                       │  |
|  └────────────────────────────────────────────────────────────────────────────┘  |
+----------------------------------------------------------------------------------+
```

- The page loads `listAvailableGuards()`, `listGuardrailsConfigs()` and `listGuardOnFailOptions()` in parallel with `Promise.allSettled` (`GuardrailsConfigPage.tsx:443-477`). There is no `active_only` filter in the UI. A catalog failure shows a "Could not load the validator catalog." panel with a Retry button (`GuardrailsConfigPage.tsx:642-653`).
- The form is **progressive disclosure**. It splits into a validator picker on the left (`gr-form-split` / `gr-form-picker`, `GuardrailsConfigPage.tsx:676-717`) and a settings pane on the right (`gr-form-settings`, `GuardrailsConfigPage.tsx:718-780`). Only a **selected** validator gets a settings panel, so a config with two guards shows two panels, not sixteen. The section headers carry live counts: total validators (`:680-681`) and selected validators (`:720-721`).
- Validators are grouped by `category` in the order the catalog returns them (`GuardrailsConfigPage.tsx:611-621,684-716`). Each category header carries its own count (`:686-689`).
- A picker row is a **two-line checkbox chip** (`gr-picker-chip`): the label and a `kind` tag (`local`, `model` or `llm`) on the first line, the validator's own `description` from the catalog on the second (`GuardrailsConfigPage.tsx`). The description used to be a `title` tooltip only, which hid the one line that says what the check does; it is now always visible, and it joins the checkbox's accessible name so a screen reader reads it too. A validator the service reports as unavailable renders with `gr-picker-chip--unavailable`, is disabled, and its description line carries `unavailable_reason` instead. The picker shows no `phase` tag — the phase appears in the settings panel that the validator opens.
- The settings pane lists one `gr-setting-card` per selected validator (`GuardrailsConfigPage.tsx:733-779`). The card head carries the label, the `phase` tag and a `Remove` button (`:735-750`), which is the same toggle as deselecting the chip.
- With nothing selected the pane shows an empty state that points at the picker ("Pick one on the left. Its options appear here.") rather than rendering a blank column (`GuardrailsConfigPage.tsx:725-731`).
- One `ParamField` component renders every parameter. It switches on `param.type` and supports `string`, `text`, `integer`, `number`, `boolean`, `string_list` and `select` (`GuardrailsConfigPage.tsx:318-424`). No code in the form checks a validator id.
- A `string_list` parameter with no `options` renders a free-text chip picker. A `string_list` parameter with `options` renders a chip picker over those options (`ItemPicker`, `GuardrailsConfigPage.tsx:34-213`; used at `:751-757`). That is how the keywords and the PII types are entered.
- One `on_fail` select sits in every settings panel, labelled "Action when the text fails", filled from `GET /guardrails/on-fail-options` (`GuardrailsConfigPage.tsx:760-775`). Three options are in the list, so the control is a select, not a slider. A `FALLBACK_ON_FAIL` list keeps the form usable when that endpoint is down (`:218-237`).
- Client-side save rules: a name is required, at least one guard must be selected, and every `required` parameter must have a value (`GuardrailsConfigPage.tsx:258-264,533-551`). The Create/Update button stays disabled otherwise (`GuardrailsConfigPage.tsx:804-813`). A missing required parameter shows `Give "<label>" a value (<guard label>).` (`GuardrailsConfigPage.tsx:548-550`).
- Selecting a guard seeds its parameters from the catalog defaults and `on_fail: "noop"` (`seedParams`, `GuardrailsConfigPage.tsx:252-256`). Deselecting removes the entry, so `buildSettings()` never sends stale values (`GuardrailsConfigPage.tsx:270-287,492-506`).
- Card actions: `Disable`/`Enable` issues `PUT /configs/{id}` with `{"is_active": !c.is_active}` (`GuardrailsConfigPage.tsx:602-609,873-881`), `Edit` re-fills the form (`GuardrailsConfigPage.tsx:516-532`), `Delete` opens a confirmation dialog then issues `DELETE /configs/{id}`. The dialog reuses the app's shared modal shell (`.modal-overlay` / `.modal-panel` / `.modal-header` / `.modal-body` / `.modal-footer`) with `role="alertdialog"`, names the config being removed, and focuses nothing else. A native `confirm()` came before it: it cannot be themed, it reads as a browser dialog rather than part of the page, and it blocks the whole tab.
- A card shows a parameter row only when the value differs from the catalog default. A guard with all defaults shows "Default settings", and a guard id that is not in the catalog shows "Not in the catalog" (`GuardrailsConfigPage.tsx:288-316,854-871`).
- The config grid uses **bounded** tracks, `repeat(auto-fill, minmax(340px, 460px))` with `justify-content: start` (`index.css` `.gr-config-grid`). Unbounded `1fr` tracks stretched a short summary into a sparse full-width card; plain `auto-fill` reserved empty tracks and left half the row blank when only one or two configs exist.
- There is no "Save Policy", no default-policy selector and no threshold sliders.

### Polish applied on 2026-09-29

Three defects were fixed on this page.

**A symbol stood in for an icon.** The heading was `<h1>⛨ Guard Configuration</h1>`. A text
glyph depends on the font, cannot be themed or sized with the rest of the icon set, and is
read aloud by some screen readers. It is now `IconGuardrails`, an SVG that already existed in
`components/Icons.tsx` and that the sidebar uses for this page. The icon sits **outside** the
`h1`: `.guardrails-page h1` paints its text with `background-clip: text` and a transparent
fill, which would erase an inline SVG.

**A base button fell back to the browser's own colours.** `.btn` set no `background`, so every
bare `.btn.btn-sm` computed `background: rgb(240, 240, 240)` with `color: rgb(0, 0, 0)` — black
on near-white in a dark theme. This affected `Disable`, `Edit` and the picker's `+ Add items`
on this page, and every bare `.btn` in the application. The `.btn` rule now sets
`background: var(--bg-glass)` with `color: var(--text-primary)` and
`border-color: var(--border-default)`, so it paints itself. `.btn-secondary` is kept as an
explicit alias of the same surface. Measured before and after with `getComputedStyle`.

**A description was reachable only by hover.** The validator description lived in a `title`
attribute. It is now the chip's second line, as described above.

The page also gained a subtitle under the title, and the validator count in the picker header
now reads 3.

---

## 4. Backend APIs & Contracts

Router: `routes/guardrails.py`, prefix `/guardrails` (mounted at the RAG API root, `rag_api/main.py:83`; frontend base `http://127.0.0.1:8001`, `frontend/src/api.ts:8`). All routes require the global API key (header `X-API-Key` or `api_key` query parameter).

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/guards` | The validator catalog, read from `guardrails-service` | `list[GuardOption]` |
| `GET` | `/guardrails/on-fail-options` | The failure actions | `list[OnFailOption]` |
| `POST` | `/guardrails/configs` | Create a config | `ConfigCreateRequest` -> `ConfigResponse` (201) |
| `GET` | `/guardrails/configs` | List configs, optional `?active_only=true` | `ConfigListResponse` (`count`, `items`) |
| `GET` | `/guardrails/configs/{config_id}` | Fetch one config | `ConfigResponse` (404 if missing) |
| `PUT` | `/guardrails/configs/{config_id}` | Partial update (`model_dump(exclude_unset=True)`) | `ConfigUpdateRequest` -> `ConfigResponse` |
| `DELETE` | `/guardrails/configs/{config_id}` | Delete config | `204 No Content`, empty body |

Field lines: `routes/guardrails.py:230,256,262,294,307,321,361`.

`GET /guardrails/guards` proxies the service catalog and caches it for 60 s (`routes/guardrails.py:29-59`). If the service is briefly down it serves the stale copy instead of failing. Without a cached copy it returns `503`. Each entry carries `category`, `phase`, `kind`, `available`, `unavailable_reason`, `params` and the legacy fields `items_key`, `items_label`, `allow_custom`, `options` (`routes/guardrails.py:157-172,230-254`). `config_name` in a trace resolves to `"No config"` when the trace has no config id and `"Deleted"` when the config row is gone (`routes/guardrails.py:392-402`).

### `GuardOption` and `GuardParam`
`GuardParam` is `name`, `type`, `label`, `help`, `required`, `default`, `options`, `min`, `max` (`routes/guardrails.py:145-155`). `GuardOption` is `id`, `label`, `description`, `category`, `phase`, `kind`, `available`, `unavailable_reason`, `params`, plus the legacy `items_key`, `items_label`, `allow_custom`, `options` (`routes/guardrails.py:157-172`).

### Settings schema and defaults (`routes/guardrails.py:184-228`)
`settings` is **per-validator**: one key per selected validator, holding that validator's parameters plus `on_fail`.

```json
{
  "ban_list": {"banned_words": ["codename"], "max_l_dist": 0, "on_fail": "noop"},
  "detect_pii": {"pii_entities": ["EMAIL_ADDRESS", "US_SSN"], "on_fail": "noop"}
}
```

- `upgrade_settings()` accepts the old flat shape (`{"banned_words": [...], "pii_entities": [...]}`) and the current nested shape. The old keys map to their owner: `banned_words` -> `ban_list`, `pii_entities` -> `detect_pii` (`rag_shared/guardrails_client.py:15,18-38`).
- The retired guard id from before the catalog existed is renamed to `detect_pii` on read and on write (`rag_shared/guardrails_client.py:12`, `routes/guardrails.py:424,272,333,347`).
- The upgrade runs on read and on write, so **no database migration was needed**. The column is JSONB (`rag_db/models/guardrails.py:20`).
- Only selected guards keep an entry, and every entry gets an explicit `on_fail` (default `noop`) (`routes/guardrails.py:184-198`).
- Every save is checked by the service through `POST /validate-config` before it is stored (`routes/guardrails.py:200-228`). A bad parameter returns HTTP 422 with the service message, for example `Ban List: 'Keywords' is required`. An unreachable service returns `503`.
- `ConfigCreateRequest`: `name` (required), `description?`, `guards` (required, catalog ids), `mode` (default `"both"`), `settings` (defaults to `{}`) (`routes/guardrails.py:75-81`). There is no `is_default` field — activation is the separate `is_active` boolean (default `true`, `rag_db/models/guardrails.py:22`).
- Validation (`422`): `mode not in {input, output, both}` (`routes/guardrails.py:268`). An empty `guards` list gives "Select at least one guard" (`:270`). An id outside the catalog gives "Unknown guard: X" (`:274-276`). A missing required parameter or a rejected value is reported by the service (`:200-228`).
- `ConfigUpdateRequest`: every field optional — `name`, `description`, `guards`, `mode`, `is_active`, `settings`. On update the settings are re-normalized against the resulting guard list (`routes/guardrails.py:321-359`).

### `ConfigResponse`
`id`, `name`, `description`, `guards`, `settings` (per-validator), `mode`, `is_active`, `created_at`, `updated_at` (`routes/guardrails.py:92-101,421-436`).

### Sample create request (`POST /guardrails/configs`)
```json
{
  "name": "Production Safety",
  "description": "Checks for the support corpus",
  "guards": ["ban_list", "detect_pii", "toxic_language"],
  "mode": "both",
  "settings": {
    "ban_list": {"banned_words": ["drop table", "internal_only"], "max_l_dist": 0, "on_fail": "noop"},
    "detect_pii": {"pii_entities": ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN"], "on_fail": "noop"},
    "toxic_language": {"threshold": 0.5, "on_fail": "noop"}
  }
}
```

---

## 5. Where Guard Configs Apply During Chat

- `ChatRequest.guardrails_config_id` (`uuid | None`) is the only switch. When it is absent no guardrail check runs (`routes/chat.py:24`).
- `_run_guardrails()` loads the config by id, returns immediately if the id does not resolve, skips the phase that `mode` excludes, calls `run_guardrails_check(text, cfg.guards, guardrails_url, timeout_s, settings=cfg.settings)` and writes a `guardrails_traces` row for every phase it does run (`routes/chat.py:295-353`).
- Non-streaming `/chat`: input phase check before the pipeline call (`routes/chat.py:378-389`), output phase check on the generated answer (`routes/chat.py:430-443`).
- Streaming `/chat/stream`: emits `{"type": "status", "message": "Checking guardrails..."}` before the input check and, on a block, a `blocked` SSE payload plus a `session` event with `route: "blocked"` (`routes/chat.py:527-560`). The output check runs on the final answer (`routes/chat.py:611-624,655-659`).
- On a block the answer becomes `GUARD_BLOCK_COPY[guard][phase]` (`routes/chat.py:118-139`), latency is stamped `route="blocked"`, `blocked=True`, `blocked_by_guard`, `blocked_on` (`routes/chat.py:142-148`), the turn is persisted with metrics skipped, and OTEL span attributes `guardrails.config_id`, `guardrails.{phase}.blocked`, `guardrails.{phase}.blocked_by` are set (`routes/chat.py:347-351`).

### Implementation notes (verified in the working tree)
- Config guard ids are the catalog ids (`ban_list`, `detect_pii`, `toxic_language`, ...). The client renames the legacy PII guard id to `detect_pii` before it builds the request (`rag_shared/guardrails_client.py:12,91-92`), so a config written before the catalog existed keeps working.
- A non-200 from the service becomes `{"validation_passed": true, "error": "HTTP <code>", "detail": <body>}` (`rag_shared/guardrails_client.py:62-121`). A validator with no result in the response gets `"validator missing from the response"` as its `error` (`rag_shared/guardrails_client.py:113-118`). Both fail open rather than blocking every chat turn.
- `GUARD_BLOCK_COPY` is keyed by the three original guard ids (`routes/chat.py:118-134`). Its PII entry still carries the id that the catalog retired, so a block by `detect_pii` falls back to the generic sentence `"<Phase> blocked by guardrail: detect_pii."` from `_blocked_answer` (`routes/chat.py:137-139`). The block itself is correct. Only the friendly message is generic.
- `settings.guardrails_url` defaults to `http://localhost:18000` and `settings.guardrails_timeout_s` defaults to `15.0` (`rag_shared/config.py:33-36`). The timeout rose from 5.0 s because each LLM judge needs about a second.
