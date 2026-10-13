# 08 — Guard Config Page

**Last updated:** 2026-10-10

**Sidebar label:** Guard Config · **Route:** `/guardrails/config` · **Component:** `frontend/src/pages/GuardrailsConfigPage.tsx` · **In-page `<h1>`:** "Guard Configuration"

(Navigation entry and mount: `components/AppLayout.tsx:32,129,215`; page title `GuardrailsConfigPage.tsx:647`.)

## 1. Executive Summary & Page Purpose
The **Guard Config Page** creates, edits, enables/disables and deletes `GuardrailsConfig` rows (table `guardrails_configs`, `rag_db/models/guardrails.py:13-26`). Each row selects a subset of the guards that `guardrails-service` exposes, the chat phases they apply to (`input`, `retrieval`, `output`; a validator uses `both`), and the parameters of every selected guard. The same rows are what Chat applies when a request carries `guardrails_config_id` (`routes/chat.py:34, 554, 651, 777`) and what the Guard Evaluation page scores against (`routes/guardrails_evaluate.py:253-375`).

The page is **catalog-driven**. The form is generated from `GET /guardrails/guards`, which proxies the catalog of `guardrails-service`. The catalog holds **nine guards**: three validators (`ban_list`, `detect_pii` and `toxic_language`) and six NeMo rails (`self_check_input`, `jailbreak_heuristics`, `pii_retrieval`, `self_check_output` and `self_check_facts`). Only `guardrails-service/config.py` defines that list (`_VALIDATORS`, with `RAIL_SPECS` appended at `config.py:395`), so there is no second copy of it in the repository.

The three validators are Guardrails AI validators. The six rails are implemented by **NeMo Guardrails**, the engine inside `guardrails-service` (`guardrails-service/nemo.py`). A config that names no rail takes the older validator path in `config.run_validators` and behaves exactly as before. A config that names a rail runs the whole phase through the engine.

A failing guard **blocks** the turn: the answer is replaced with fixed copy from `GUARD_BLOCK_COPY` (`routes/chat.py:163-207`) rather than being redacted. A transport or configuration problem does **not** block. The client reports such a problem as `validation_passed: true` plus an `error`, and the trace records it (`rag_shared/guardrails_client.py:104-141`).

---

## 2. Guardrails Architecture & Supported Guards

```
+----------------------------------------------------------------------------------+
|  Chat request carrying guardrails_config_id        (routes/chat.py:34)            |
+-----------------------------------+----------------------------------------------+
                                    v
+----------------------------------------------------------------------------------+
|  _run_guardrails(config_id, phase, text)           (routes/chat.py:384-454)      |
|  1. load the GuardrailsConfig row from guardrails_configs                        |
|  2. mode gate: "input" -> input phase only, "output" -> output phase only,        |
|     "both" -> both phases. The retrieval phase is not gated by mode: a           |
|     configured retrieval rail always runs          (routes/chat.py:410-416)      |
|  3. POST {guardrails_url}/validate                                               |
|     body: {"text": text, "phase": phase, "query": ..., "answer": ...,             |
|            "chunks": [...],                                                      |
|            "validators": [{"id": ..., "params": {...}, "on_fail": ...}, ...]}     |
|                                    (rag_shared/guardrails_client.py:62-149)      |
+-----------------------------------+----------------------------------------------+
                                    v
+----------------------------------------------------------------------------------+
|  guardrails-service runs one phase                                              |
|   no rail in the config -> config.run_validators in config.py (older path)       |
|   one rail or more      -> nemo.run_check, one engine call per phase (nemo.py:798)|
|  results keyed by guard id: {"validation_passed": bool, "error": str|null,        |
|                              "detail": str|null, "ms": int}                       |
|  any validation_passed == false -> turn is blocked (guardrails_client.py:169-174)|
|  a guardrails_traces row is written for every phase that ran; a phase with        |
|  nothing to run is skipped                         (routes/chat.py:429-445)      |
+----------------------------------------------------------------------------------+
```

### Guard catalog (`GET /guardrails/guards`)
The catalog comes from `guardrails-service/config.py` (`_VALIDATORS` for the three validators
and `RAIL_SPECS` for the six rails, merged at `config.py:395`) and is served by
`guardrails-service/server.py` (`GET /catalog`, `server.py:58-61`). Every entry carries
`category`, `phase`, `kind`, the parameter schema and an `available` flag with
`unavailable_reason` when a validator package is missing from the installation.

**The catalog holds nine guards.** The Guard Config page renders whatever the catalog
serves, so it shows all eight with no frontend change. Adding an entry to `_VALIDATORS` or to
`RAIL_SPECS` makes it appear on the page.

`kind` has three values:
- `local` — a packaged validator from public PyPI. It runs inside the container with no downloaded model.
- `model` — a validator that loads a model. `detect_pii` and the `pii_retrieval` rail run Presidio with a spaCy pipeline.
- `llm` — a judge that calls the LiteLLM proxy. It needs no package of its own.

A validator declares `phase: both` and runs in the input and the output phase. A rail declares
exactly one phase (`input`, `retrieval` or `output`) and runs only there.

**Content Safety**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `ban_list` | Ban List | `local` | both | `banned_words` (string_list, required, free text), `max_l_dist` (integer, default `0`, range 0–5) | `guardrails-ai-ban-list` |
| `toxic_language` | Toxic Language | `llm` | both | `threshold` (number, default `0.5`, range 0–1), `model` (string, default empty) | `local/toxic_language` |
| `self_check_input` | Self Check Input | `llm` | input | `policy` (text, optional, default empty), `model` (string, optional, default empty) | NeMo engine |
| `template_scope` | Template Scope | `llm` | input | `policy` (text, optional, default empty), `model` (string, optional, default empty) | NeMo engine |
| `jailbreak_heuristics` | Jailbreak Heuristics | `llm` | input | `policy` (text, optional, default empty), `model` (string, optional, default empty) | NeMo engine |
| `self_check_output` | Self Check Output | `llm` | output | `policy` (text, optional, default empty), `model` (string, optional, default empty) | NeMo engine |

**Privacy**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `detect_pii` | PII Detection | `model` | both | `pii_entities` (string_list, required, 18 options, default `EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, IP_ADDRESS`) | `guardrails-ai-detect-pii` |
| `pii_retrieval` | PII in Retrieved Chunks | `model` | retrieval | `pii_entities` (string_list, optional, 18 options, default `EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, IP_ADDRESS`), `score_threshold` (number, optional, default `0.2`, range 0–1) | NeMo engine (Presidio) |

**Grounding**

| id | Label | kind | phase | Parameters | Source |
|---|---|---|---|---|---|
| `self_check_facts` | Fact Check Against Sources | `llm` | output | `policy` (text, optional, default empty), `model` (string, optional, default empty) | NeMo engine |

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

### How the six rails run
Each phase takes the official slot for it, and the phase decides which rails go in that slot,
so one config still has one rail set per phase.

- The **input** phase lists its rails under `rails.input.flows` and checks the user message
  (`$user_message`).
- The **retrieval** phase lists `pii_retrieval` under `rails.input.flows` as well. The library's
  own `rails.retrieval.flows` fire only when the engine computes `$relevant_chunks` itself,
  which a check-only caller never does. The deviations table below records the measurement.
- The **output** phase lists its rails under `rails.output.flows` and hands the answer over as
  an `assistant` message next to the user question, so the runtime sets `$bot_message` from the
  answer under check. A repair rail writes the checked answer back to `$bot_message`, and
  `check_phase` returns it as `text`, which the chat route returns to the user.

The context message (the output and retrieval phases) must come before the user and assistant
messages, or the engine runs no rails at all (`nemo.py:588-605`).

- `self_check_input` and `self_check_output` are the engine's library flows. The engine ships
  no prompt for either task, so `guardrails-service` supplies both prompts and appends the
  configured `policy` to the one that belongs to the rail.
- `jailbreak_heuristics` and `self_check_facts` are flows this service generates, with a judge
  action behind each. Both take a `policy` and a `model`. The fact check scores the answer
  against the retrieved passages (`$relevant_chunks`), so it needs the retrieval phase with
  passages. With no passages it reports `skipped: no retrieval context` and does not block.
- `pii_retrieval` uses the engine's own Presidio rail with the configured `pii_entities` list
  and `score_threshold`. `on_fail: fix` masks the passages before the model reads them.
  `on_fail: noop` blocks the turn.

The four LLM rails (`self_check_input`, `jailbreak_heuristics`, `self_check_output`,
`self_check_facts`) take an optional `model` parameter. Leave it empty to use
`GUARDRAIL_LLM_MODEL` (`Gpt-oss-20b` by default). Each of them spends one model call per turn,
so a config with them costs one call more per rail than the same config without it.
`pii_retrieval` runs Presidio locally and takes no `model`.

When a config names a rail, the three validators of that phase run as engine actions beside
the rails, inside the same call. A config with no rail never builds an engine.

### The pipeline's prompt template governs its turns

A pipeline that names a prompt template is checked by `guardrails-service` even when it carries no
guardrails config, or a config that holds no NeMo rail. `rag_shared.guardrails_client.template_guardrails()`
turns the template text into the `policy` of the `template_scope` rail, which decides whether a
message is inside the scope the template declares. A rail the config already names keeps its own
parameters, because that entry is an explicit choice and the template only fills the gap.

The template governs the scope only. Its text does not become the policy of the two self-check
rails: prose written for the model reads badly as a blocking rule, and feeding it to them blocked
valid in-scope answers in testing. Those rails keep their own policy, which is what a config or the
service default supplies.

The route resolves the text once per turn (`routes/chat.py::_template_policy`). The assistant
route puts the pipeline's template into `system_prompt`; a caller that sends `prompt_template_id`
instead, which the Chat page does, gets the same treatment. A turn governed by a template alone
writes its `guardrails_traces` row with a null `config_id`, and the traces page reads that as
"No config".

So the template does two jobs: it is the system message that shapes the answer, and it is the
scope NeMo enforces on the question and on the answer.

### Official NeMo Guardrails patterns, and where this service deviates

The service builds and extends the engine the documented way: `RailsConfig.from_content(
yaml_content=, colang_content=)` builds one engine per config and phase; `colang_version: "1.0"`
loads the shipped Colang 1.0 flows; `models` declares the main model and, for a rail that sets
its own `model`, the task model that rail belongs to; `prompts` carries the task prompts the
library does not ship; every guard runs through an action registered with `register_action`;
the generation options `rails`, `output_vars` and `log.activated_rails` drive the call and
supply the per-rail `ms`.

Nothing is written to disk. There is no `config.yml`, no `.co` file, no `actions.py` and no
`prompts.yml`. `nemo.build_content()` returns the YAML and the Colang of one config row and one
phase as two strings, `nemo._dump_colang()` generates one Colang flow per guard that needs one,
and `nemo._register_actions()` registers the actions that those flows call. The library's own
`.co` files supply the flows this service names instead of writing them (`self check input`,
`self check output`, `mask sensitive data on input`). Prompt tasks live in the `prompts:` key of
the generated YAML, which is where the library keeps them: it ships no `prompts.yml`.

Three deviations are deliberate. Each one has a measurement behind it, taken on the installed
`nemoguardrails 0.24.1`.

| Deviation | Reason |
|---|---|
| The retrieval phase runs the input slot with `sensitive_data_detection.input`, not `rails.retrieval.flows` with `.retrieval`. | With the chunks handed over in a context message, `rails.retrieval.flows` do not fire: `log.activated_rails` stays empty and the passages come back unmasked. The library also exposes no retrieval rail type (`RailType` has `input` and `output` only), so `check()` cannot cover it either. |
| The Guardrails AI validators do not use `rails.config.guardrails_ai.validators` with `guardrailsai check input\|output $validator="…"`. | That integration serves 13 pre-registered names, and it refuses the turn on a failure with no repair path. This project's configs name Hub packages and its own `local/toxic_language`, carry per-guard parameters from the database, and mask PII instead of blocking (`on_fail: fix`). A registered action per guard is the library's own extension point and keeps all three behaviours (`nemo.py::_register_actions`). |
| Output checks run once on the collected answer, not through the streaming rails (`streaming.chunk_size`, `stream_first`). | The application owns generation and streams to the client. A repair rail therefore cannot retract tokens that already left; it changes the persisted answer and the final stream frames. |

### What the catalog used to hold, and why it was cut

The catalog held 16 validators. It now holds three validators and the six NeMo rails. The cut
removed `mentions_drugs`, `restrict_to_topic`, `prompt_injection`, `secrets_present`,
`regex_match`, `valid_length`, `ends_with`, `valid_json`, `one_line`, `lowercase`, `uppercase`,
`reading_time` and `exclude_sql_predicates`, together with the `LlmRestrictToTopic` and
`LlmPromptInjection` judge classes.

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
Exactly three options exist (`config.py`). `on_fail` sits beside the parameters of each selected guard.

| id | Label | `fixes_text` | Meaning |
|---|---|---|---|
| `noop` | Block the request | `false` | Record the failure and stop the chat turn. This is the default. |
| `exception` | Block and raise an error | `false` | Same effect. The validator raises instead of returning. |
| `fix` | Repair the text and continue | `true` | Rewrite the text and continue the turn. Only some guards support this. On the `pii_retrieval` rail, `fix` masks the retrieved passages. |

### guardrails-service endpoints
`guardrails-service/server.py` is a plain FastAPI app (`server.py:27`, version `0.3.0`). It has exactly four endpoints.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/health-check` | Liveness | `{"status": "ok"}` (`server.py:53-55`) |
| `GET` | `/catalog` | The guard catalog and the failure-action options | `{"version": 1, "validators": [...], "on_fail_options": [...]}` (`server.py:58-61`) |
| `POST` | `/validate-config` | Check that a guard list and its parameters can be built. Runs nothing | `{"validators": [{id, params, on_fail}]}` -> `{"valid": bool, "errors": [str]}` (`server.py:64-74`) |
| `POST` | `/validate` | Run one phase of a guard config over the text | `{"text", "phase", "query?", "answer?", "chunks?", "validators": [...]}` -> the per-guard result map plus `blocked`, `blocked_by`, `phase`, `chunks`, `skipped` and `engine_ms` (`server.py:77-108`) |

These four endpoints are the whole surface of the service. `guardrails-service/pyproject.toml` lists `guardrails-ai`, the validator packages, `nemoguardrails` (the rail engine) and `pyyaml`. No LangChain provider package is needed: from NeMo 0.22 the built-in OpenAI-compatible client serves `engine: openai` with `parameters.base_url`, and LangChain is opt-in through `NEMOGUARDRAILS_LLM_FRAMEWORK=langchain`.

`POST /validate` rejects an empty guard list and a bad parameter with HTTP 422 and a readable message (`server.py:87-88, 99-101`). A parameter error comes from `coerce_params` (`config.py:511-534`), for example `Ban List: 'Banned words' is required` or `<id> has unknown parameters: ...`. The reply is keyed by guard id and also carries `blocked`, `blocked_by` and `phase`. On the engine path each result also carries `ms`, the time that rail took (`server.py:81-85`).

`POST /validate-config` accepts a rail entry exactly like a validator entry, and it rejects an unknown rail parameter with the same `has unknown parameters` message. A rail entry whose engine is missing reports `nemoguardrails is not installed: <reason>`, the same way an uninstalled Hub package does.

### Why the validators are real packages now
The old `config.py` imported `BanList`, `DetectPII` and `ToxicLanguage` from `guardrails.hub` inside a `try` / `except ImportError`, with hand-written fallbacks. No Hub validator was ever installed, so the fallbacks always ran. Two of them were wrong:

- The fallback `ToxicLanguage.validate` always returned `PassResult()`. The toxic-language guard could never block anything. A live check before the fix proved it: the old service reported `validation_passed: true` for the sentence "You are an idiot and I hope you fail completely."
- The fallback `DetectPII` was four regular expressions (email, phone, US SSN, IPv4). It missed `4111 1111 1111 1111`, a card number with spaces, and it never found names or locations.

The service now installs the two packaged validators from public PyPI as `guardrails-ai-<name>`. `pyproject.toml` still lists the packages for the removed validators, so the image installs more Hub packages than the catalogue lists. The `guardrails hub install` CLI and its private registry are deprecated, and the `from guardrails.hub import X` shim is scheduled for removal (`config.py`, `pyproject.toml`).

The six rails are not packages at all: `nemoguardrails` implements them, so a rail has no `module` and no `alias` in `RAIL_SPECS`. The catalog marks each of the five unavailable when the `nemoguardrails` import fails at startup (`config.py:48-53, 424-445`).

### Deployment
- `guardrails-service/Dockerfile:22-36` downloads the spaCy model `en_core_web_sm` (12 MB) and rewrites Presidio's `conf/default.yaml` from `en_core_web_lg` (590 MB) to the small model. The build fails if Presidio stops pinning the large model.
- `guardrails-service/Dockerfile:38-61` rewrites two literals in NeMo's own `library/sensitive_data_detection/actions.py` from `en_core_web_lg` to `en_core_web_sm`, because the rail refuses to run without the large model. The build fails if either literal moves.
- `guardrails-service/Dockerfile:66-68` writes `/root/.guardrailsrc`. A missing file makes every `Validator` constructor raise.
- `guardrails-service/Dockerfile:86-88` copies `config.py`, `nemo.py` and `server.py` into the runtime image.
- `rag-ingestion-manager/docker-compose.yaml:285-296` builds the service from `../guardrails-service`, maps port `18000` to `8000`, reads `rag-ingestion-manager/.env.guardrails`, and sets `extra_hosts: host.docker.internal:host-gateway` so the judge reaches LiteLLM on the host.
- `rag-ingestion-manager/.env.guardrails:7-12` sets `LITELLM_BASE_URL`, `LLM_API_KEY`, `GUARDRAIL_LLM_MODEL=Gpt-oss-20b` and `GUARDRAIL_LLM_MAX_TOKENS=512`.

The judge models are reasoning models. At `max_tokens=160` they return an empty body and the judge fails. At 512 they answer correctly in 1–3 s. `Gpt-oss-20b` measured 18/18 correct across six texts. `Gpt-oss-120b` measured 8–105 s and timed out, so do not select it. The code default is `Gpt-oss-20b` (`config.py`) and the deployment sets the same value (`.env.guardrails:10`).

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
|  | Validators            8  |  | Settings                          2          |  |
|  |                          |  |                                              |  |
|  | Content Safety       5   |  | Ban List                [both]     Remove    |  |
|  |  [x] Ban List    [local] |  |  desc: Block a list of words or phrases.      |  |
|  |      Block a list of w…  |  |  Banned words *    (chip picker, free text)   |  |
|  |  [x] Toxic Lang    [llm] |  |  Fuzzy distance    [ 0 ]                      |  |
|  |      Flag abusive, har…  |  |  Action when the text fails [ Block req. v ]  |  |
|  |  [ ] Input Check   [llm] |  |                                              |  |
|  |      Ask a judge whe…    |  | Self Check Output      [output]    Remove    |  |
|  |  Privacy              2  |  |  Policy            (textarea)                 |  |
|  |  [x] PII Detect  [model] |  |  Judge model       [ ]                        |  |
|  |      Detect personal d…  |  |  Action when the text fails [ Block req. v ]  |  |
|  |  [ ] PII Retr.   [model] |  |                                              |  |
|  | Grounding            1   |  | PII Retr.            [retrieval]   Remove    |  |
|  |  [ ] Fact Check   [llm]  |  |  PII types  (chip picker, 18 options)         |  |
|  |      Check that the an…  |  |  Confidence        [ 0.2 ]                    |  |
|  +--------------------------+  +----------------------------------------------+  |
|  Mode:   ( ) Input Only   ( ) Output Only   (o) Both                              |
|                                          [ Cancel ]  [ Create / Update ]         |
+----------------------------------------------------------------------------------+
|  Config cards grid (one card per config):                                        |
|  ┌────────────────────────────────────────────────────────────────────────────┐  |
|  │ Production Safety                                   [ Active ]            │   |
|  │ Mode: both                                                                 │  |
|  │ Guards: [ Ban List ] [ PII Detection ]                                     │  |
|  │   Banned words: drop table, internal_only                                  │  |
|  │   PII types: Email Address, US SSN                                         │  |
|  │                      [ Disable ] [ Edit ] [ Delete ]                       │  |
|  └────────────────────────────────────────────────────────────────────────────┘  |
+----------------------------------------------------------------------------------+
```

- The page loads `listAvailableGuards()`, `listGuardrailsConfigs()` and `listGuardOnFailOptions()` in parallel with `Promise.allSettled` (`GuardrailsConfigPage.tsx:452`). There is no `active_only` filter in the UI. The page renders **two** error panels, each with a Retry button: a catalog failure shows "Could not load the validator catalog." (`:663`), and a config-list failure shows "Could not load the saved configurations." (`:846`).
- The form is **progressive disclosure**. It splits into a validator picker on the left (`gr-form-split` / `gr-form-picker`, `GuardrailsConfigPage.tsx:697`) and a settings pane on the right (`gr-form-settings`, `GuardrailsConfigPage.tsx:747`). Only a **selected** validator gets a settings panel, so a config with two guards shows two panels, not sixteen. The section headers carry live counts: total validators and selected validators (`GuardrailsConfigPage.tsx`).
- Validators are grouped by `category` in the order the catalog returns them (`GuardrailsConfigPage.tsx`). Each category header carries its own count.
- A picker row is a **two-line checkbox chip** (`gr-picker-chip`): the label and a `kind` tag (`local`, `model` or `llm`) on the first line, the validator's own `description` from the catalog on the second (`GuardrailsConfigPage.tsx`). The description used to be a `title` tooltip only, which hid the one line that says what the check does; it is now always visible, and it joins the checkbox's accessible name so a screen reader reads it too. A validator the service reports as unavailable renders with `gr-picker-chip--unavailable`, is disabled, and its description line carries `unavailable_reason` instead. The picker shows no `phase` tag — the phase appears in the settings panel that the validator opens.
- The settings pane lists one `gr-setting-card` per selected validator (`GuardrailsConfigPage.tsx`). The card head carries the label, the `phase` tag and a `Remove` button (`GuardrailsConfigPage.tsx`), which is the same toggle as deselecting the chip.
- With nothing selected the pane shows an empty state that points at the picker ("Pick one on the left. Its options appear here.") rather than rendering a blank column (`GuardrailsConfigPage.tsx`).
- One `ParamField` component renders every parameter. It switches on `param.type` and supports `string`, `text`, `integer`, `number`, `boolean`, `string_list` and `select` (`GuardrailsConfigPage.tsx:319`). No code in the form checks a guard id, so a new catalog entry renders with no frontend change.
- A `text` parameter renders a **textarea** (`GuardrailsConfigPage.tsx:354-363`). That is the control the `policy` parameter of the four LLM rails uses, so a policy runs to several lines.
- A `string_list` parameter with no `options` renders a free-text chip picker. A `string_list` parameter with `options` renders a chip picker with a typed-match list over those options (`ItemPicker`, `GuardrailsConfigPage.tsx:35-210`; the dropdown rows are `gr-combobox-option`, `:190`). That is how the banned words and the PII entity lists are entered. The `pii_retrieval` rail uses the same control with the same 18 options.
- One `on_fail` select sits in every settings panel, labelled "Action when the text fails", filled from `GET /guardrails/on-fail-options` (`GuardrailsConfigPage.tsx`). Three options are in the list, so the control is a select, not a slider. A `FALLBACK_ON_FAIL` list keeps the form usable when that endpoint is down (`:219`).
- Client-side save rules: a name is required, at least one guard must be selected, and every `required` parameter must have a value (`GuardrailsConfigPage.tsx:545-563`). The Create/Update button stays disabled otherwise (`GuardrailsConfigPage.tsx`). A missing required parameter shows `Give "<label>" a value (<guard label>).` (`GuardrailsConfigPage.tsx:554`).
- Selecting a guard seeds its parameters from the catalog defaults and `on_fail: "noop"` (`seedParams`, `GuardrailsConfigPage.tsx:253`). Deselecting removes the entry, so `buildSettings()` never sends stale values (`GuardrailsConfigPage.tsx:271,496`).
- Card actions: `Disable`/`Enable` issues `PUT /configs/{id}` with `{"is_active": !c.is_active}` (`GuardrailsConfigPage.tsx`), `Edit` re-fills the form (`GuardrailsConfigPage.tsx`), `Delete` opens a confirmation dialog then issues `DELETE /configs/{id}`. The dialog reuses the app's shared modal shell (`.modal-overlay` / `.modal-panel` / `.modal-header` / `.modal-body` / `.modal-footer`) with `role="alertdialog"`, names the config being removed, and focuses nothing else. A native `confirm()` came before it: it cannot be themed, it reads as a browser dialog rather than part of the page, and it blocks the whole tab.
- A card shows a parameter row only when the value differs from the catalog default. A guard with all defaults shows "Default settings", and a guard id that is not in the catalog shows "Not in the catalog" (`GuardrailsConfigPage.tsx`).
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

The page also gained a subtitle under the title, and the count in the picker header now reads the
number of guards the catalog serves (eight today).

---

## 4. Backend APIs & Contracts

Router: `routes/guardrails.py`, prefix `/guardrails` (mounted at the RAG API root, `rag_api/main.py:83`; frontend base `http://127.0.0.1:8001`, `frontend/src/api.ts:7`). All routes require the global API key (header `X-API-Key` or `api_key` query parameter).

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/guards` | The guard catalog, read from `guardrails-service` | `list[GuardOption]` |
| `GET` | `/guardrails/on-fail-options` | The failure actions | `list[OnFailOption]` |
| `POST` | `/guardrails/configs` | Create a config | `ConfigCreateRequest` -> `ConfigResponse` (201) |
| `GET` | `/guardrails/configs` | List configs, optional `?active_only=true` | `ConfigListResponse` (`count`, `items`) |
| `GET` | `/guardrails/configs/{config_id}` | Fetch one config | `ConfigResponse` (404 if missing) |
| `PUT` | `/guardrails/configs/{config_id}` | Partial update (`model_dump(exclude_unset=True)`) | `ConfigUpdateRequest` -> `ConfigResponse` |
| `DELETE` | `/guardrails/configs/{config_id}` | Delete config | `204 No Content`, empty body |

Field lines: `routes/guardrails.py:230,256,262,294,307,321,361`.

`GET /guardrails/guards` proxies the service catalog and caches it for 60 s (`routes/guardrails.py:33-59`). If the service is briefly down it serves the stale copy instead of failing. Without a cached copy it returns `503`. Each entry carries `category`, `phase`, `kind`, `available`, `unavailable_reason`, `params` and the legacy fields `items_key`, `items_label`, `allow_custom`, `options` (`routes/guardrails.py:157-172,230-254`). `phase` is `both` for a validator and `input`, `retrieval` or `output` for a rail. `config_name` in a trace resolves to `"No config"` when the trace has no config id and `"Deleted"` when the config row is gone (`routes/guardrails.py:395-403`).

### `GuardOption` and `GuardParam`
`GuardParam` is `name`, `type`, `label`, `help`, `required`, `default`, `options`, `min`, `max` (`routes/guardrails.py:145-155`). `GuardOption` is `id`, `label`, `description`, `category`, `phase`, `kind`, `available`, `unavailable_reason`, `params`, plus the legacy `items_key`, `items_label`, `allow_custom`, `options` (`routes/guardrails.py:157-172`).

### Settings schema and defaults (`routes/guardrails.py:184-228`)
`settings` is **per-guard**: one key per selected guard, holding that guard's parameters plus `on_fail`. A rail stores its parameters the same way: `policy` and `model` for the LLM rails, `pii_entities` and `score_threshold` for `pii_retrieval`.

```json
{
  "ban_list": {"banned_words": ["codename"], "max_l_dist": 0, "on_fail": "noop"},
  "detect_pii": {"pii_entities": ["EMAIL_ADDRESS", "US_SSN"], "on_fail": "noop"},
  "self_check_facts": {"policy": "", "model": "", "on_fail": "noop"},
  "pii_retrieval": {"pii_entities": ["EMAIL_ADDRESS"], "score_threshold": 0.2, "on_fail": "fix"}
}
```

- `upgrade_settings()` accepts the old flat shape (`{"banned_words": [...], "pii_entities": [...]}`) and the current nested shape. The old keys map to their owner: `banned_words` -> `ban_list`, `pii_entities` -> `detect_pii` (`rag_shared/guardrails_client.py:15,18-38`).
- The retired guard id from before the catalog existed is renamed to `detect_pii` on read and on write (`rag_shared/guardrails_client.py:12`, `routes/guardrails.py:424,272,333,347`).
- The upgrade runs on read and on write, so **no database migration was needed**. The column is JSONB (`rag_db/models/guardrails.py:20`).
- Only selected guards keep an entry, and every entry gets an explicit `on_fail` (default `noop`) (`routes/guardrails.py:184-198`).
- Every save is checked by the service through `POST /validate-config` before it is stored (`routes/guardrails.py:200-228`). A bad parameter returns HTTP 422 with the service message, for example `Ban List: 'Banned words' is required`. An unreachable service returns `503`. A rail is accepted exactly like a validator, and a parameter the catalog does not declare for it is rejected with `<id> has unknown parameters: ...` (`config.py:511-517`).
- `ConfigCreateRequest`: `name` (required), `description?`, `guards` (required, catalog ids), `mode` (default `"both"`), `settings` (defaults to `{}`) (`routes/guardrails.py:75-81`). There is no `is_default` field — activation is the separate `is_active` boolean (default `true`, `rag_db/models/guardrails.py:22`).
- Validation (`422`): `mode not in {input, output, both}` (`routes/guardrails.py:267`). An empty `guards` list gives "Select at least one guard" (`:270`). An id outside the catalog gives "Unknown guard: X" (`:274-276`). A missing required parameter or a rejected value is reported by the service (`:200-228`).
- `ConfigUpdateRequest`: every field optional — `name`, `description`, `guards`, `mode`, `is_active`, `settings`. On update the settings are re-normalized against the resulting guard list (`routes/guardrails.py:321-359`).

### `ConfigResponse`
`id`, `name`, `description`, `guards`, `settings` (per-guard), `mode`, `is_active`, `created_at`, `updated_at` (`routes/guardrails.py:92-101,421-436`).

### Sample create request (`POST /guardrails/configs`)
Add a rail by listing its id in `guards` and giving it a `settings` entry, the same way as a validator.

```json
{
  "name": "Production Safety",
  "description": "Checks for the support corpus",
  "guards": ["ban_list", "detect_pii", "toxic_language", "self_check_facts"],
  "mode": "both",
  "settings": {
    "ban_list": {"banned_words": ["drop table", "internal_only"], "max_l_dist": 0, "on_fail": "noop"},
    "detect_pii": {"pii_entities": ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN"], "on_fail": "noop"},
    "toxic_language": {"threshold": 0.5, "on_fail": "noop"},
    "self_check_facts": {"policy": "Only claims stated in the passages.", "model": "", "on_fail": "noop"}
  }
}
```

---

## 5. Where Guard Configs Apply During Chat

- `ChatRequest.guardrails_config_id` (`uuid | None`) is the only switch. When it is absent no guardrail check runs (`routes/chat.py:34`).
- `_run_guardrails()` loads the config by id, returns immediately if the id does not resolve, skips the phase that `mode` excludes, and returns a 5-tuple `(is_blocked, blocking_guard, guard_results, masked_chunks, repaired_answer)` (`routes/chat.py:384-457`). It calls `run_guardrails_phase(...)` with `phase`, `query`, `answer` and `chunks`, and writes a `guardrails_traces` row for every phase that ran. A phase with nothing to run is skipped and writes no row (`routes/chat.py:429-445`). Both output call sites return `repaired_answer` instead of the generated answer when an output rail masked it, so the user and the persisted row carry the repaired text.
- Non-streaming `/chat`: input phase check before the pipeline call (`routes/chat.py:567-603`). The retrieval phase runs inside `pipeline.chat` through the `chunk_filter` argument (`routes/chat.py:616-624`), and a `GuardrailBlocked` from the pipeline becomes the canned answer with `blocked_on: "retrieval"` (`routes/chat.py:625-638`). The output phase check runs on the generated answer (`routes/chat.py:662-674`).
- Streaming `/chat/stream`: emits `{"type": "status", "message": "Checking guardrails..."}` before the input check (`routes/chat.py:794`) and, on a block, a `blocked` SSE payload plus a `session` event with `route: "blocked"` (`routes/chat.py:822-826`). The retrieval phase runs through the same `chunk_filter` (`routes/chat.py:856-863`) and a block emits the same two frames (`routes/chat.py:880-907`). The output check runs on the final answer (`routes/chat.py:922-935`).
- On a block the answer becomes `GUARD_BLOCK_COPY[guard][phase]` (`routes/chat.py:163-207`, `_blocked_answer` at `:210-212`), latency is stamped `route="blocked"`, `blocked=True`, `blocked_by_guard`, `blocked_on` (`routes/chat.py:215-221`), the turn is persisted with metrics skipped, and OTEL span attributes `guardrails.config_id`, `guardrails.{phase}.blocked`, `guardrails.{phase}.blocked_by` are set (`routes/chat.py:448-452`).

### Implementation notes (verified in the working tree)
- Config guard ids are the catalog ids (`ban_list`, `detect_pii`, `toxic_language`, `self_check_input`, ...). The client renames the legacy PII guard id to `detect_pii` before it builds the request (`rag_shared/guardrails_client.py:12,88`), so a config written before the catalog existed keeps working.
- A non-200 from the service becomes `{"validation_passed": true, "error": "HTTP <code>", "detail": <body>}` (`rag_shared/guardrails_client.py:104-141`). A guard with no result in the response gets `"validator missing from the response"` as its `error` (`rag_shared/guardrails_client.py:137-141`). Both fail open rather than blocking every chat turn.
- `GUARD_BLOCK_COPY` is keyed by the eight current guard ids (`ban_list`, `detect_pii`, `toxic_language`, `self_check_input`, `jailbreak_heuristics`, `pii_retrieval`, `self_check_output`, `self_check_facts`) (`routes/chat.py:163-207`). A block by any of them returns its own friendly copy from `_blocked_answer`, and the `pii_retrieval` entry also carries a `retrieval` string (`routes/chat.py:195`). The retired PII id is renamed to `detect_pii` before the lookup, so the block text is correct.
- The retrieval rail masks instead of blocking when its `on_fail` is `fix`: `_retrieval_guardrail` puts the masked passage text back in place, so the citations keep their order (`routes/chat.py:475-504`).
- `settings.guardrails_url` defaults to `http://localhost:18000` and `settings.guardrails_timeout_s` defaults to `15.0` (`rag_shared/config.py:51,54`). The timeout rose from 5.0 s because each LLM judge needs about a second, and a rail adds one more model call.
