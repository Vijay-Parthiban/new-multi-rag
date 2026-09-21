# 08 — Guard Config Page

**Last updated:** 2026-09-21

**Sidebar label:** Guard Config · **Route:** `/guardrails/config` · **Component:** `frontend/src/pages/GuardrailsConfigPage.tsx` · **In-page `<h1>`:** "Guard Configuration"

(Navigation entry and mount: `components/AppLayout.tsx:33,128,213`; page title `GuardrailsConfigPage.tsx:633`.)

## 1. Executive Summary & Page Purpose
The **Guard Config Page** creates, edits, enables/disables and deletes `GuardrailsConfig` rows (table `guardrails_configs`, `rag_db/models/guardrails.py:13-26`). Each row selects a subset of the validators that `guardrails-service` exposes, the chat phases it applies to (`input`, `output`, `both`), and the parameters of every selected validator. The same rows are what Chat applies when a request carries `guardrails_config_id` (`routes/chat.py:24,379,431,528,612`) and what the Guard Evaluation page scores against (`routes/guardrails_evaluate.py:253-375`).

The page is **catalog-driven**. The form is generated from `GET /guardrails/guards`, which proxies the catalog of `guardrails-service`. The catalog holds **16 validators** today. Only `guardrails-service/config.py:167-549` defines that list, so there is no second copy of it in the repository.

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
|                                    (guardrails-service/config.py:762-793)         |
|  any validation_passed == false -> turn is blocked (guardrails_client.py:123-128) |
|  a guardrails_traces row is written for every phase run (routes/chat.py:335-345)  |
+----------------------------------------------------------------------------------+
```

### Validator catalog (`GET /guardrails/guards`)
The catalog comes from `guardrails-service/config.py:167-549` (`_VALIDATORS`) and is served by `guardrails-service/server.py:50-53`. Every entry carries `category`, `phase`, `kind`, the parameter schema and an `available` flag with `unavailable_reason` when a validator package is missing from the installation (`config.py:598-608`).

`kind` has three values:
- `local` — a packaged validator from public PyPI. It runs inside the container with no downloaded model.
- `model` — a packaged validator that loads a model. `detect_pii` runs Presidio with a spaCy pipeline.
- `llm` — one of the three judges that call the LiteLLM proxy. They need no package of their own.

**Content Safety**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `ban_list` | Ban List | `local` | both | `banned_words` (string_list, required, free text), `max_l_dist` (integer, default `0`, range 0–5) | `guardrails-ai-ban-list` |
| `toxic_language` | Toxic Language | `llm` | both | `threshold` (number, default `0.5`, range 0–1), `model` (string, default empty) | `local/toxic_language` (`config.py:110-119,240-270`) |
| `mentions_drugs` | Mentions Drugs | `local` | both | none | `guardrails-ai-mentions-drugs` |

**Privacy**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `detect_pii` | PII Detection | `model` | both | `pii_entities` (string_list, required, 18 options, default `EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, IP_ADDRESS`) | `guardrails-ai-detect-pii` |

The `pii_entities` parameter carries 18 options (`config.py:217-236`): `EMAIL_ADDRESS` (Email Address), `PHONE_NUMBER` (Phone Number), `CREDIT_CARD` (Credit Card), `US_SSN` (US SSN), `IP_ADDRESS` (IP Address), `PERSON` (Person Name), `LOCATION` (Location), `DATE_TIME` (Date / Time), `URL` (URL), `DOMAIN_NAME` (Domain Name), `US_PASSPORT` (US Passport), `US_DRIVER_LICENSE` (US Driver License), `US_BANK_NUMBER` (US Bank Number), `US_ITIN` (US ITIN), `IBAN_CODE` (IBAN Code), `CRYPTO` (Crypto Wallet), `MEDICAL_LICENSE` (Medical License), `NRP` (Nationality / Religion / Political group).

**Scope**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `restrict_to_topic` | Restrict To Topic | `llm` | output | `valid_topics` (string_list, required), `invalid_topics` (string_list, optional), `threshold` (number, default `0.5`), `model` (string, default empty) | `local/restrict_to_topic` (`config.py:121-150,271-317`) |

**Security**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `prompt_injection` | Prompt Injection | `llm` | input | `threshold` (number, default `0.5`, range 0–1), `model` (string, default empty) | `local/prompt_injection` (`config.py:152-165,318-348`) |
| `secrets_present` | Secrets Present | `local` | both | none | `guardrails-ai-secrets-present` |

**Format**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `regex_match` | Regex Match | `local` | both | `regex` (string, required), `match_type` (select: `search` default, `fullmatch`) | `guardrails-ai-regex-match` |
| `valid_length` | Valid Length | `local` | both | `min` (integer, optional), `max` (integer, optional) | `guardrails-ai-valid-length` |
| `ends_with` | Ends With | `local` | both | `end` (string, required) | `guardrails-ai-ends-with` |
| `valid_json` | Valid JSON | `local` | output | none | `guardrails-ai-valid-json` |
| `one_line` | One Line | `local` | output | none | `guardrails-ai-one-line` |
| `lowercase` | Lower Case | `local` | output | none | `guardrails-ai-lowercase` |
| `uppercase` | Upper Case | `local` | output | none | `guardrails-ai-uppercase` |
| `reading_time` | Reading Time | `local` | output | `reading_time` (number, required, default `5.0`, min `0.1`) | `guardrails-ai-reading-time` |

**Database**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `exclude_sql_predicates` | Exclude SQL Predicates | `local` | output | `predicates` (string_list, required, default `DROP, DELETE`) | `guardrails-ai-exclude-sql-predicates` |

Sources for the entries without an explicit line range: `config.py:168-198` (`ban_list`), `:199-239` (`detect_pii`), `:349-360` (`secrets_present`), `:361-393` (`regex_match`), `:394-424` (`valid_length`), `:425-445` (`ends_with`), `:446-457` (`valid_json`), `:458-469` (`one_line`), `:470-481` (`lowercase`), `:482-493` (`uppercase`), `:494-515` (`reading_time`), `:516-536` (`exclude_sql_predicates`), `:537-548` (`mentions_drugs`).

Three validators are local implementations of the Guardrails `Validator` interface and have no package (`config.py:75-165`). They send the text to the LiteLLM proxy with `max_tokens` from `GUARDRAIL_LLM_MAX_TOKENS` (`config.py:33-40,46-73`). The upstream packages for these three need PyTorch and several gigabytes of CUDA libraries, so they are deliberately not installed.

### `on_fail` options (`GET /guardrails/on-fail-options`)
Exactly three options exist (`config.py:551-570`). `on_fail` sits beside the parameters of each selected validator.

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
| `GET` | `/catalog` | The validator catalog and the failure-action options | `{"version": 1, "validators": [...], "on_fail_options": [...]}` (`server.py:50-53`, `config.py:598-608`) |
| `POST` | `/validate-config` | Check that a validator list and its parameters can be built. Runs nothing | `{"validators": [{id, params, on_fail}]}` -> `{"valid": bool, "errors": [str]}` (`server.py:56-66`) |
| `POST` | `/validate` | Run every configured validator over one text | `{"text", "phase", "validators": [...]}` -> the per-validator result map (`server.py:69-90`) |

These four endpoints are the whole surface of the service. `guardrails-service/pyproject.toml:6-27` lists `guardrails-ai` and the 13 validator packages.

`POST /validate` rejects an empty validator list and a bad parameter with HTTP 422 and a readable message (`server.py:77-87`). A parameter error comes from `coerce_params` (`config.py:661-685`), for example `Ban List: 'Keywords' is required` (`config.py:674-676`). The reply is keyed by validator id and also carries `blocked`, `blocked_by` and `phase` (`config.py:762-793`).

### Why the validators are real packages now
The old `config.py` imported `BanList`, `DetectPII` and `ToxicLanguage` from `guardrails.hub` inside a `try` / `except ImportError`, with hand-written fallbacks. No Hub validator was ever installed, so the fallbacks always ran. Two of them were wrong:

- The fallback `ToxicLanguage.validate` always returned `PassResult()`. The toxic-language guard could never block anything. A live check before the fix proved it: the old service reported `validation_passed: true` for the sentence "You are an idiot and I hope you fail completely."
- The fallback `DetectPII` was four regular expressions (email, phone, US SSN, IPv4). It missed `4111 1111 1111 1111`, a card number with spaces, and it never found names or locations.

The service now installs 13 real validators from public PyPI as `guardrails-ai-<name>`. The `guardrails hub install` CLI and its private registry are deprecated, and the `from guardrails.hub import X` shim is scheduled for removal (`config.py:1-10`, `pyproject.toml:13-27`).

### Deployment
- `guardrails-service/Dockerfile:25-36` downloads the spaCy model `en_core_web_sm` (12 MB) and rewrites Presidio's `conf/default.yaml` from `en_core_web_lg` (590 MB) to the small model. The build fails if Presidio stops pinning the large model.
- `guardrails-service/Dockerfile:41-43` writes `/root/.guardrailsrc`. A missing file makes every `Validator` constructor raise.
- `rag-ingestion-manager/docker-compose.yaml:306-317` builds the service from `../guardrails-service`, maps port `18000` to `8000`, reads `rag-ingestion-manager/.env.guardrails`, and sets `extra_hosts: host.docker.internal:host-gateway` so the three judges reach LiteLLM on the host.
- `rag-ingestion-manager/.env.guardrails:7-12` sets `LITELLM_BASE_URL`, `LLM_API_KEY`, `GUARDRAIL_LLM_MODEL=Gpt-oss-20b` and `GUARDRAIL_LLM_MAX_TOKENS=512`.

The judge models are reasoning models. At `max_tokens=160` they return an empty body and the judge fails. At 512 they answer correctly in 1–3 s. `Gpt-oss-20b` measured 18/18 correct across six texts. `Gpt-oss-120b` measured 8–105 s and timed out, so do not select it. The code default is `Gpt-oss-120b` (`config.py:35`) and the deployment overrides it to `Gpt-oss-20b` (`.env.guardrails:9`).

---

## 3. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------+
|  ⛨ Guard Configuration                                        [ + New Config ]   |
+----------------------------------------------------------------------------------+
|  Create / Edit Config form (shown after + New Config or Edit):                   |
|  Name [__________________]  Description (optional) [__________________]          |
|  Guards, grouped by category (Content Safety, Privacy, Scope, Security, Format,   |
|  Database). Each row shows label, kind tag, phase tag and description:            |
|    [x] Ban List              [local] [both]                                       |
|          Keywords *: (chip picker, free text)                                     |
|          Fuzzy distance: [ 0 ]                                                    |
|          On fail: [ Block the request v ]                                         |
|    [x] PII Detection         [model] [both]                                       |
|          PII types *: (chip picker over the 18 options)                           |
|          On fail: [ Block the request v ]                                         |
|    [ ] Toxic Language        [llm] [both]                                         |
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

- The page loads `listAvailableGuards()`, `listGuardrailsConfigs()` and `listGuardOnFailOptions()` in parallel with `Promise.allSettled` (`GuardrailsConfigPage.tsx:443-452`). There is no `active_only` filter in the UI. A catalog failure shows a "Could not load the validator catalog." panel with a Retry button (`GuardrailsConfigPage.tsx:642-650`).
- Validators are grouped by `category` in the order the catalog returns them (`GuardrailsConfigPage.tsx:613-620,681-686`).
- Each guard row shows the `kind` and `phase` tags (`GuardrailsConfigPage.tsx:707-708`).
- One `ParamField` component renders every parameter. It switches on `param.type` and supports `string`, `text`, `integer`, `number`, `boolean`, `string_list` and `select` (`GuardrailsConfigPage.tsx:317-424`). No code in the form checks a validator id.
- A `string_list` parameter with no `options` renders a free-text chip picker. A `string_list` parameter with `options` renders a chip picker over those options (`GuardrailsConfigPage.tsx:362-388`). That is how the keywords and the PII types are entered.
- One `on_fail` select sits under every selected guard, filled from `GET /guardrails/on-fail-options` (`GuardrailsConfigPage.tsx:734-742`). Three options are in the list, so the control is a select, not a slider.
- Client-side save rules: a name is required, at least one guard must be selected, and every `required` parameter must have a value (`GuardrailsConfigPage.tsx:258-262,546-559`). The Create/Update button stays disabled otherwise (`GuardrailsConfigPage.tsx:780-783`). A missing required parameter shows `Give "<label>" a value (<guard label>).` (`GuardrailsConfigPage.tsx:548-556`).
- Selecting a guard seeds its parameters from the catalog defaults and `on_fail: "noop"`. Deselecting removes the entry, so `buildSettings()` never sends stale values (`GuardrailsConfigPage.tsx:251-256,270-287,490-497`).
- Card actions: `Disable`/`Enable` issues `PUT /configs/{id}` with `{"is_active": !c.is_active}` (`GuardrailsConfigPage.tsx:602-608,846-848`), `Edit` re-fills the form (`GuardrailsConfigPage.tsx:518-525`), `Delete` confirms then `DELETE /configs/{id}` (`GuardrailsConfigPage.tsx:592-600,850`).
- A card shows a parameter row only when the value differs from the catalog default. A guard with all defaults shows "Default settings", and a guard id that is not in the catalog shows "Not in the catalog" (`GuardrailsConfigPage.tsx:288-308,826-841`).
- There is no "Save Policy", no default-policy selector and no threshold sliders.

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
