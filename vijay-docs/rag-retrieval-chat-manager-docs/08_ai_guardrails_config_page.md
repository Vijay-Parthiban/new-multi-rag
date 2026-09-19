# 08 — Guard Config Page

**Last updated:** 2026-09-17

**Sidebar label:** Guard Config · **Route:** `/guardrails/config` · **Component:** `frontend/src/pages/GuardrailsConfigPage.tsx` · **In-page `<h1>`:** "Guard Configuration"

(Navigation entry and mount: `components/AppLayout.tsx:32,123,207`; page title `GuardrailsConfigPage.tsx:352`.)

## 1. Executive Summary & Page Purpose
The **Guard Config Page** creates, edits, enables/disables and deletes `GuardrailsConfig` rows (table `guardrails_configs`, `rag_db/models/guardrails.py:13-27`). Each row selects a subset of the three guards the backend exposes, the chat phases it applies to (`input`, `output`, `both`), and the per-guard settings (banned keywords, PII entity ids). The same rows are what Chat applies when a request carries `guardrails_config_id` (`routes/chat.py:311-332`) and what the Guard Evaluation page scores against (`routes/guardrails_evaluate.py:216-232`).

Three guards exist in this codebase: **Ban List**, **PII Detection** and **Toxic Language** (`routes/guardrails.py:44-77`). There is no prompt-injection, hallucination, competitor-mention, toxicity-threshold or masking/redaction guard. A failing guard **blocks** the turn: the answer is replaced with fixed copy from `GUARD_BLOCK_COPY` (`routes/chat.py:118-140`) rather than being redacted.

---

## 2. Guardrails Architecture & Supported Guards

```
+----------------------------------------------------------------------------------+
|  Chat request carrying guardrails_config_id   (routes/chat.py:24)                |
+-----------------------------------+----------------------------------------------+
                                    v
+----------------------------------------------------------------------------------+
|  _run_guardrails(config_id, phase, text)            (routes/chat.py:295-353)     |
|  1. load the GuardrailsConfig row from guardrails_configs                        |
|  2. mode gate: "input" -> input phase only, "output" -> output phase only,       |
|     "both" -> both phases                              (routes/chat.py:320-325)  |
|  3. for each guard in cfg.guards POST                                            |
|     {guardrails_url}/parse/{guard}                                               |
|     body: {"llm_output": text, "metadata": cfg.settings}                         |
|                                    (rag_shared/guardrails_client.py:22-31)       |
+-----------------------------------+----------------------------------------------+
                                    v
+----------------------------------------------------------------------------------+
|  per-guard result: {"validation_passed": bool, "error": str|null,                |
|                     "detail": str|null}     (guardrails-service/server.py)       |
|  any validation_passed == false -> turn is blocked (guardrails_client.py:46-51)  |
|  a guardrails_traces row is written for every phase run (chat.py:335-343)        |
+----------------------------------------------------------------------------------+
```

### Available guards (`GET /guardrails/guards`)
| Guard id | Label | Description | `items_key` / `items_label` | `allow_custom` | `options` |
|---|---|---|---|---|---|
| `ban_list` | Ban List | Block specific keywords (case-insensitive) | `banned_words` / Keywords | `true` | `[]` (free text) |
| `pii_check` | PII Detection | Detect personal identifiable information | `pii_entities` / PII types | `false` | 18 entity ids (below) |
| `toxic_language` | Toxic Language | Flag toxic or harmful language | `null` / `null` | `false` | `[]` |

Source: `routes/guardrails.py:44-77` (`AVAILABLE_GUARDS`). `toxic_language` has no per-guard settings.

### PII entity options (`options` of `pii_check`)
`EMAIL_ADDRESS` (Email Address), `PHONE_NUMBER` (Phone Number), `CREDIT_CARD` (Credit Card), `US_SSN` (US SSN), `IP_ADDRESS` (IP Address), `PERSON` (Person Name), `LOCATION` (Location), `DATE_TIME` (Date / Time), `URL` (URL), `DOMAIN_NAME` (Domain Name), `US_PASSPORT` (US Passport), `US_DRIVER_LICENSE` (US Driver License), `US_BANK_NUMBER` (US Bank Number), `US_ITIN` (US ITIN), `IBAN_CODE` (IBAN Code), `CRYPTO` (Crypto Wallet), `MEDICAL_LICENSE` (Medical License), `NRP` (Nationality / Religion / Political group).

Source: `routes/guardrails.py:22-41` (`PII_ENTITY_OPTIONS`).

### guardrails-service side
The validators live in `guardrails-service/config.py` and are served by `guardrails-service/server.py`:

| Service guard id | Validator | Defaults when metadata supplies nothing |
|---|---|---|
| `ban-list` | `ConfigurableBanList(BanList)` | `banned_words = ["codename", "internal_only"]`, `max_l_dist = 0`, `on_fail = "noop"` (`config.py:70,122-131`) |
| `pii-check` | `DetectPII` | `pii_entities = EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, IP_ADDRESS` (`config.py:71-77,133-136`) |
| `toxic-language` | `ToxicLanguage` | `threshold = 0.5`, `validation_method = "sentence"`, `on_fail = "noop"` (`config.py:138-146`) |

- Per-request overrides arrive as `metadata`; `ConfigurableBanList` reads `metadata["banned_words"]` (list or comma-separated string) and restores the previous list afterwards (`config.py:91-119`). `config.py:4-11` documents `banned_words` and `pii_entities` as the override keys.
- `POST /parse/{guard_name}` (called by the RAG API) validates text directly and returns `{"validation_passed", "error", "detail"}`; it 404s for a name that is not in `{"ban-list", "pii-check", "toxic-language"}` (`server.py:20-51`).
- If `guardrails.hub` cannot be imported, `config.py:16-68` registers simplified fallbacks: ban list is a substring match, PII is four regexes (email, phone, US SSN, IPv4) and `ToxicLanguage` always passes.

---

## 3. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------+
|  ⛨ Guard Configuration                                        [ + New Config ]   |
+----------------------------------------------------------------------------------+
|  Create / Edit Config form (shown after + New Config or Edit):                   |
|  Name [__________________]  Description (optional) [__________________]          |
|  Guards:  [x] Ban List - Block specific keywords (case-insensitive)              |
|                Keywords: (free-text picker - type a keyword, Enter to add)       |
|           [x] PII Detection - Detect personal identifiable information           |
|                PII types: (combobox over the 18 entity ids + labels)             |
|           [ ] Toxic Language - Flag toxic or harmful language                    |
|  Mode:   ( ) Input Only   ( ) Output Only   (o) Both                             |
|                                          [ Cancel ]  [ Create / Update ]         |
+----------------------------------------------------------------------------------+
|  Config cards grid (one card per config):                                        |
|  ┌────────────────────────────────────────────────────────────────────────────┐  |
|  │ Production Safety                                   [ Active ]            │   |
|  │ Mode: both                                                                 │  |
|  │ Guards: [ Ban List ] [ PII Detection ]                                     │  |
|  │ Keywords: [ drop table ] [ internal_only ]                                 │  |
|  │ PII: [ Email Address ] [ US SSN ]                                          │  |
|  │                      [ Disable ] [ Edit ] [ Delete ]                       │  |
|  └────────────────────────────────────────────────────────────────────────────┘  |
+----------------------------------------------------------------------------------+
```

- The page loads `listAvailableGuards()` and `listGuardrailsConfigs()` in parallel (`GuardrailsConfigPage.tsx:226-240`); there is no `active_only` filter in the UI.
- The guard checkbox rows render `label` + `description` straight from `GET /guardrails/guards`; a `ban_list` block adds a free-text keyword picker and a `pii_check` block adds an option-chip/typeahead picker over the returned entities (`GuardrailsConfigPage.tsx:382-419`).
- Client-side save rules mirror the server: name required, at least one guard, at least one keyword when `ban_list` is selected, at least one PII type when `pii_check` is selected (`GuardrailsConfigPage.tsx:275-281`); the Create/Update button stays disabled otherwise.
- Card actions: `Disable`/`Enable` issues `PUT /configs/{id}` with `{"is_active": !c.is_active}` (`GuardrailsConfigPage.tsx:335-343`), `Edit` re-fills the form, `Delete` confirms then `DELETE /configs/{id}` (`GuardrailsConfigPage.tsx:325-333`).
- There is no "Save Policy", no default-policy selector, and no threshold sliders.

---

## 4. Backend APIs & Contracts

Router: `routes/guardrails.py`, prefix `/guardrails` (mounted at the RAG API root, `rag_api/main.py:79`; frontend base `http://localhost:8001`, `frontend/src/api.ts:5`). All routes require the global API key (header `X-API-Key` or `api_key` query parameter).

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/guards` | Available guard types + PII options | `list[GuardOption]` |
| `POST` | `/guardrails/configs` | Create a config | `ConfigCreateRequest` -> `ConfigResponse` (201) |
| `GET` | `/guardrails/configs` | List configs, optional `?active_only=true` | `ConfigListResponse` (`count`, `items`) |
| `GET` | `/guardrails/configs/{config_id}` | Fetch one config | `ConfigResponse` (404 if missing) |
| `PUT` | `/guardrails/configs/{config_id}` | Partial update (`model_dump(exclude_unset=True)`) | `ConfigUpdateRequest` -> `ConfigResponse` |
| `DELETE` | `/guardrails/configs/{config_id}` | Delete config | `204 No Content`, empty body |

Field lines: `routes/guardrails.py:209,215,244,257,271,306`.

### Settings schema and defaults (`routes/guardrails.py:80-100,165-207`)
`GuardSettings` = `banned_words: list[str] = []`, `pii_entities: list[str] = []`. Both keys are always present in responses; the list for a guard that is not selected is stored and returned empty.
- Ban words are stripped and lower-cased, then de-duplicated preserving order.
- PII ids are de-duplicated; an id outside `PII_ENTITY_OPTIONS` is rejected with `422 Unknown PII entity: X`.
- `ConfigCreateRequest`: `name` (required), `description?`, `guards` (required), `mode` (default `"both"`), `settings` (defaults to empty `GuardSettings`). There is no `is_default` field — activation is the separate `is_active` boolean (default `true`, `rag_db/models/guardrails.py:22`).
- Validation (`422`): `mode not in {input, output, both}`; unknown guard id; empty `guards`; `ban_list` selected with no keywords ("Ban List is enabled — add at least one keyword"); `pii_check` selected with no PII types ("PII Detection is enabled — select at least one PII type").
- `ConfigUpdateRequest`: every field optional — `name`, `description`, `guards`, `mode`, `is_active`, `settings`. On update the settings are re-normalized against the resulting guard list (`routes/guardrails.py:294-297`).

### `ConfigResponse`
`id`, `name`, `description`, `guards`, `settings` (`banned_words`, `pii_entities`), `mode`, `is_active`, `created_at`, `updated_at` (`routes/guardrails.py:102-112,362-378`).

### Sample create request (`POST /guardrails/configs`)
```json
{
  "name": "Production Safety",
  "description": "Checks for the support corpus",
  "guards": ["ban_list", "pii_check"],
  "mode": "both",
  "settings": {
    "banned_words": ["drop table", "internal_only"],
    "pii_entities": ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN"]
  }
}
```

---

## 5. Where Guard Configs Apply During Chat

- `ChatRequest.guardrails_config_id` (`uuid | None`) is the only switch; when it is absent no guardrail check runs (`routes/chat.py:24`).
- `_run_guardrails()` loads the config by id, returns immediately if the id does not resolve, skips the phase that `mode` excludes, calls `run_guardrails_check(text, cfg.guards, guardrails_url, timeout_s, settings=cfg.settings)` and writes a `guardrails_traces` row for every phase it does run (`routes/chat.py:295-353`).
- Non-streaming `/chat`: input phase check before the pipeline call (`routes/chat.py:379-386`), output phase check on the generated answer (`routes/chat.py:431-441`).
- Streaming `/chat/stream`: emits `{"type": "status", "message": "Checking guardrails..."}` before the input check and, on a block, a `blocked` SSE payload plus a `session` event with `route: "blocked"` (`routes/chat.py:530-556,151-165`); the output check runs on the final answer (`routes/chat.py:685-698`).
- On a block the answer becomes `GUARD_BLOCK_COPY[guard][phase]` (`routes/chat.py:118-140`), latency is stamped `route="blocked"`, `blocked=True`, `blocked_by_guard`, `blocked_on` (`routes/chat.py:142-148`), the turn is persisted with metrics skipped, and OTEL span attributes `guardrails.config_id`, `guardrails.{phase}.blocked`, `guardrails.{phase}.blocked_by` are set (`routes/chat.py:348-351`).

### Implementation notes (verified in the working tree)
- Config guard ids are underscore-prefixed (`ban_list`, `pii_check`, `toxic_language`) while the service registers hyphenated ids and `/parse/{guard_name}` 404s for anything else (`guardrails-service/server.py:20-38`, `guardrails-service/config.py:122-146`). `run_guardrails_check` turns a non-200 into `{"validation_passed": true, "error": "HTTP <code>"}` (`rag_shared/guardrails_client.py:22-41`), so a name mismatch fails open rather than blocking.
- `routes/chat.py:329-330` and `routes/guardrails_evaluate.py:254-255` read `settings.guardrails_url` / `settings.guardrails_timeout_s`, but `rag_shared.config.Settings` declares neither field (`libs/shared/src/rag_shared/config.py:10-45`, `extra="ignore"`); the only default in code is the client's `guardrails_url="http://localhost:8002"`, `timeout_s=5.0` (`rag_shared/guardrails_client.py:13-14`).
