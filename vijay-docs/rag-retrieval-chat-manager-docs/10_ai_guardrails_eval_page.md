# 10 — Guard Evaluation Page

**Last updated:** 2026-09-21

**Sidebar label:** Guard Evaluation · **Route:** `/guardrails/evaluation` · **Component:** `frontend/src/pages/GuardrailsEvaluationPage.tsx` · **In-page header:** "Guardrails Offline Evaluation"

(There is no `/guardrails/eval` route. The sidebar entry and route are `/guardrails/evaluation` — `components/AppLayout.tsx:35,130,221`, header title `GuardrailsEvaluationPage.tsx:280`.)

## 1. Executive Summary & Page Purpose
The **Guard Evaluation Page** scores a saved `GuardrailsConfig` against a golden dataset of texts with expected block behaviour. It loads the bundled dataset or uploads a JSON file, lists the configs that Chat itself uses (`guardrails_configs`), starts a run and shows accuracy/precision/recall/F1 plus every item's expected vs actual verdict.

Runs are **synchronous**: `POST /guardrails-evaluate/runs` walks the dataset, evaluates each item through `eval_core.guardrails_runner`, stores the per-item rows and returns `status: "completed"` in the same response (`routes/guardrails_evaluate.py:253-375`). The page therefore does not poll. It fetches the finished run and its items immediately (`GuardrailsEvaluationPage.tsx:214-234`).

---

## 2. Dataset Schema & Sample Shape

Parsed by `eval_core/guardrails_dataset_schema.py:8-29`:

```json
{
  "name": "Guardrails Golden Dataset",
  "description": null,
  "items": [
    {
      "text": "Contact me at alice.smith@example.com",
      "phase": "input",
      "expected_blocked": true,
      "expected_guard": "detect_pii",
      "category": "pii",
      "metadata": {}
    }
  ]
}
```

| Key | Type | Default | Notes |
|---|---|---|---|
| `name` | string | `"Guardrails Golden Dataset"` | unique per dataset. A matching name is deleted and re-created when `replace=true` (`guardrails_dataset_schema.py:20`, `guardrails_evaluation_repository.py:28-37`) |
| `description` | string \| null | `null` | |
| `items` | array | `[]` | |
| `items[].text` | string | **required** | text sent to the validators (`guardrails_dataset_schema.py:11`) |
| `items[].phase` | string | `"input"` | `input` or `output` (`guardrails_dataset_schema.py:12`) |
| `items[].expected_blocked` | bool | `false` | |
| `items[].expected_guard` | string \| null | `null` | compared against the actual blocking validator |
| `items[].category` | string \| null | `null` | used for the per-category scores |
| `items[].metadata` | object | `{}` | stored, not evaluated |

The field names match the stored columns and the bundled dataset, and the parser also accepts a bare JSON array of items (`parse_guardrails_golden_json`, `guardrails_dataset_schema.py:25-29`).

### Persisted item columns
`text`, `phase` (default `"input"`), `expected_blocked`, `expected_guard`, `category`, `metadata` (`rag_db/models/guardrails.py:58-69`). Import reads `text`, `phase`, `expected_blocked`, `expected_guard`, `category` and `metadata` from each item dict (`guardrails_evaluation_repository.py:44-53`).

### `replace` behaviour
`replace=false` (the default of the upload routes) returns **409** when the name already exists. The repository raises `A dataset named '<name>' already exists` and the route turns it into `409` (`guardrails_evaluation_repository.py:26,34-35`, `routes/guardrails_evaluate.py:130-131`). `replace=true` deletes the old dataset and its runs first (cascade, `rag_db/models/guardrails.py:54-55`).

### Sample dataset (`golden/guardrails-dataset.json`)
The checked-in sample lives at the repository root and uses the field names above — `text`, `phase` (`input`/`output`), `expected_blocked`, `expected_guard`, `category`:

```json
{"name":"guardrails-smoke-golden","description":"Dataset for offline guardrails evaluation.","items":[{"text":"Contact me at alice.smith@example.com for the report.","phase":"input","expected_blocked":true,"expected_guard":"detect_pii","category":"pii"}]}
```

It holds **12 items** across four categories (`clean`, `ban_list`, `pii`, `toxic`) and mixes `input` and `output` phases. The `expected_guard` of the PII rows is `detect_pii`, the current catalog id.

One row is deliberately labelled `expected_blocked: false`: `My SSN is 123-45-6789 and I need help with payroll.` (category `clean`). The real Presidio detector also does not block it with the five entity types the shipped config uses, so the label is correct and the fixture must stay as it is.

---

## 3. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------+
|  Guardrails Offline Evaluation                    [ Load bundled golden dataset ] |
+----------------------------------------------------------------------------------+
|  (when no dataset exists)                                                        |
|  No golden dataset yet                                                           |
|    "This repository ships a golden set at golden/guardrails-dataset.json. It has  |
|     12 items over 4 categories: clean, ban_list, pii and toxic."                 |
|    [ Load bundled golden dataset ]                                               |
+----------------------------------------------------------------------------------+
|  Golden dataset                       |  Chat guardrails config                  |
|  Upload JSON [file] (accept .json)    |  Saved config from database [select v]   |
|  [x] Replace if name already exists   |  id=3695cb61… · mode=both · guards=…     |
|  Dataset [select: name (N items)]     |      · settings for N validator(s)       |
|  [ Delete dataset ]                   |  [ Start guardrails evaluation ]         |
+----------------------------------------------------------------------------------+
|  Runs (N total)   Created | Status | Config | Accuracy |  [ Open ]               |
+----------------------------------------------------------------------------------+
|  Scores:  12 items · 12 evaluated · 0 skipped                                    |
|    Accuracy   [====================] 100%    Precision [===========] 100%         |
|    Recall     [====================] 100%    F1        [===========] 100%         |
|    Guard match[====================] 100%                                        |
|  TP 7 (True positives)   TN 5 (True negatives)                                   |
|  FP 0 (False positives)  FN 0 (False negatives)                                  |
|  By category:  Category | Items | Correct | Accuracy                             |
|  Item results: Text | Phase | Category | Expected | Actual | Result | Note       |
|    Category filter [ All categories v ]                                          |
+----------------------------------------------------------------------------------+
```

- **"Load bundled golden dataset"** calls `POST /guardrails-evaluate/datasets/seed` through a local wrapper (`GuardrailsEvaluationPage.tsx:18-45,168-180`). The button appears in the page header and again in the empty state when no dataset exists (`GuardrailsEvaluationPage.tsx:288-295,310-325`). After the seed it reloads the dataset list and selects the new dataset.
- Upload calls `uploadGuardrailsGoldenDataset(file, replaceOnUpload)`; the "Replace if name already exists" checkbox is **checked by default** (`GuardrailsEvaluationPage.tsx:108,182-194,336-352`).
- The dataset panel lists dataset names with item counts, offers `Delete dataset`, and holds the file input (`GuardrailsEvaluationPage.tsx:332-382`).
- The config dropdown is filled from `listGuardrailsConfigs(false)` — the same `guardrails_configs` rows Chat applies — and shows the id prefix, mode, guard ids and the number of validators with settings (`GuardrailsEvaluationPage.tsx:67-80,387-428`).
- `Start guardrails evaluation` requires both a dataset and a config, calls `POST /runs` then `GET /runs/{id}` and `GET /runs/{id}/items` (`GuardrailsEvaluationPage.tsx:214-234,418-427`).
- Runs table: Created (relative time), Status, Config (`config_snapshot.name`, falling back to the first 8 chars of `config_id`), Accuracy (`percent()`, one decimal) and an `Open` action that reloads the run and its items (`GuardrailsEvaluationPage.tsx:47-50,236-249,433-467`).
- **Score bars**: five `ScoreBar` rows read `accuracy`, `precision`, `recall`, `f1` and `guard_match_rate` from `aggregate_metrics` (`GuardrailsEvaluationPage.tsx:81-94,491-504`). Each bar is a percentage, and a missing key renders as an empty bar with `—` (`percent()`, `GuardrailsEvaluationPage.tsx:47-50`).
- **Confusion tiles**: TP / TN / FP / FN tiles read `true_positives`, `true_negatives`, `false_positives` and `false_negatives`; FP and FN carry the "bad" tone (`GuardrailsEvaluationPage.tsx:270-275,505-518`).
- The Scores header line shows `items_total`, `items_evaluated` and `items_skipped` (`GuardrailsEvaluationPage.tsx:493-496`).
- When **every** item failed, the page hides the zeroed score bars and shows the item error instead, so a total failure is not read as a score of zero (`GuardrailsEvaluationPage.tsx:264-268`).
- **By category** renders `aggregate_metrics.categories` as `Category | Items | Correct | Accuracy` when the key exists (`GuardrailsEvaluationPage.tsx:521-543`). Category names are prettified for display only (`formatCategory`, `GuardrailsEvaluationPage.tsx:52-58`).
- The item table has a **Category filter** built from the categories in the loaded rows (`GuardrailsEvaluationPage.tsx:109,253-262,553-561`).
- Item results columns: Text (truncated at 120 chars, full text in the cell `title`), Phase, Category, Expected (`block:<guard>` / `allow`), Actual, Result (the verdict chip) and Note (`GuardrailsEvaluationPage.tsx:570-625`).

### Verdict chips
`verdictOf()` maps each row to one verdict, and `VERDICT_LABEL` gives the chip text (`GuardrailsEvaluationPage.tsx:60-79`). The chip and the row both take a `gr-verdict--<verdict>` class, and the Note column explains the verdict in words (`GuardrailsEvaluationPage.tsx:592,609-621`).

| Verdict | Chip | Meaning |
|---|---|---|
| `ok` | Correct | Expected and actual agree |
| `false-negative` | Missed block | "Expected a block, the text passed" |
| `false-positive` | False alarm | "No block expected, the text was blocked" |
| `guard-miss` | Wrong guard | "Blocked by X, expected Y" |
| `failed` | Error | The check raised. The error text is shown |
| `skipped` | Skipped | The config mode excluded the row. The skip reason is shown |

The false-negative and false-positive rows are the rows that need a config change, and they are marked in three places: the row and chip colour, the Note text, and the FP / FN count in the tiles (`GuardrailsEvaluationPage.tsx:71-79,270-275,613-618`).

---

## 4. Backend APIs & Contracts

Router: `routes/guardrails_evaluate.py`, prefix `/guardrails-evaluate` (`rag_api/main.py:84`; frontend base `http://127.0.0.1:8001`, `frontend/src/api.ts:8`, client `frontend/src/guardrailsEvalApi.ts`). Global API key required.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/guardrails-evaluate/datasets/seed` | Import the bundled golden dataset from disk | optional `{"path": ..., "replace": true}` -> `CreateDatasetResponse`; `404` naming the paths it tried when the file is missing; `400` on a parse error |
| `POST` | `/guardrails-evaluate/datasets/upload` | Import a JSON dataset from a file | multipart `file`, `?replace=` (default `false`) -> `CreateDatasetResponse`; `400` on parse/validation error |
| `POST` | `/guardrails-evaluate/datasets` | Import a dataset from a JSON body | `GuardrailsGoldenDatasetPayload`, `?replace=` -> `CreateDatasetResponse`; `409` if the name already exists and `replace=false` |
| `GET` | `/guardrails-evaluate/datasets` | List datasets with item counts | `?limit=` (default 50, 1–200) -> `DatasetListResponse` |
| `DELETE` | `/guardrails-evaluate/datasets/{dataset_id}` | Delete a dataset (cascades to its runs/items) | `204 No Content`, `404` if missing |
| `POST` | `/guardrails-evaluate/runs` | Run a dataset against one config, synchronously | `{dataset_id, guardrails_config_id}` -> `{run_id, status}`; `404` for unknown dataset or config, `500` on run failure |
| `GET` | `/guardrails-evaluate/runs/{run_id}` | Fetch a run incl. metrics | `GuardrailsEvalRunResponse`, `404` if missing |
| `GET` | `/guardrails-evaluate/datasets/{dataset_id}/runs` | List runs of a dataset, newest first | `?skip=` (default 0), `?limit=` (default 20, 1–100) -> `GuardrailsEvalRunListResponse` |
| `GET` | `/guardrails-evaluate/runs/{run_id}/items` | Per-item results of a run | `GuardrailsEvalRunItemsResponse` |

Route definitions: `routes/guardrails_evaluate.py:141,155,188,217,240,253,376,401,434`. Schemas: `:36-107`.

### `POST /guardrails-evaluate/datasets/seed` (new)
Imports the bundled `golden/guardrails-dataset.json`. The body is optional (`SeedDatasetRequest`, `routes/guardrails_evaluate.py:164-169`): `path` overrides the file location and `replace` defaults to `true`. Location resolution tries the override, then `settings.guardrails_golden_dataset_path` (default `../../golden/guardrails-dataset.json`), then `./golden/...`, `../golden/...` and `../../golden/...` relative to the process working directory (`routes/guardrails_evaluate.py:171-185`, `rag_shared/config.py:37-39`). A missing file returns `404` with the exact list of paths it tried (`routes/guardrails_evaluate.py:201-206`). The index (`GET /datasets`) is not part of this call.

### `CreateDatasetResponse`
`dataset_id`, `name`, `item_count`, `replaced` (`routes/guardrails_evaluate.py:44-49`).

### `GuardrailsEvalRunResponse` (`routes/guardrails_evaluate.py:68-79`)
`run_id`, `dataset_id`, `config_id`, `status`, `config_snapshot`, `aggregate_metrics` (dict or `null`), `error_message`, `created_at`, `started_at`, `completed_at`.
`config_snapshot` is frozen at run creation and contains `config_id` (string), `name`, `mode`, `guards`, `settings`, `is_active` (`routes/guardrails_evaluate.py:277-284`). Run status is `running` while executing, then `completed` or `failed` (`guardrails_evaluation_repository.py:134-149`).

### `GuardrailsEvalRunItemRow` — per-item result fields (`routes/guardrails_evaluate.py:86-103`)
| Field | Type | Meaning |
|---|---|---|
| `run_item_id` | uuid | run-item row id |
| `dataset_item_id` | uuid | source dataset item |
| `text` | string | dataset text, re-joined from the dataset item (`""` if the item is gone) |
| `phase` | string | `input` / `output` from the dataset item |
| `category` | string \| null | dataset category |
| `status` | string | `completed`, `skipped` or `failed` |
| `skipped` | bool | item skipped by the runner |
| `skip_reason` | string \| null | why it was skipped |
| `expected_blocked` / `expected_guard` | bool / string \| null | dataset expectation |
| `actual_blocked` / `actual_guard` | bool / string \| null | observed verdict |
| `correct_block` / `correct_guard` | bool \| null | per-aspect correctness. The scores do not read the stored `correct_block` flag. See the rules below |
| `guard_results` | object | per-validator verdicts (`validation_passed` / `error` / `detail`), the same shape as in doc 09 |
| `error_message` | string \| null | set when the item raised (`status: "failed"`) |

### Metrics `aggregate_metrics` (`eval_core/guardrails_runner.py:102-175`)
`aggregate_guardrails_metrics()` returns exactly these keys:

| Key | Meaning |
|---|---|
| `items_total` | rows handed to the runner |
| `items_evaluated` | rows that ran |
| `items_skipped` | rows excluded by the config mode |
| `items_failed` | evaluated rows that reported an error |
| `accuracy` | correct rows / evaluated rows |
| `precision` | `tp / (tp + fp)`, `1.0` when nothing was predicted as blocked |
| `recall` | `tp / (tp + fn)`, `1.0` when nothing was expected to be blocked |
| `f1` | harmonic mean of precision and recall |
| `guard_match_rate` | correct guard names / rows where both an expected and an actual guard exist |
| `true_positives`, `true_negatives`, `false_positives`, `false_negatives` | the confusion matrix counts |
| `categories` | per category: `item_count`, `correct`, `accuracy` |

Rules:
- **Skipped rows are excluded from every score.** They are counted in `items_skipped` and appear in no denominator (`eval_core/guardrails_runner.py:106-108`).
- Correctness is derived from `expected_blocked == actual_blocked`, not from the stored `correct_block` flag, because that flag defaults to `False` (`eval_core/guardrails_runner.py:110-113`).
- `tp` = expected and actually blocked, `tn` = not expected and not blocked, `fp` = blocked but not expected, `fn` = expected but not blocked (`eval_core/guardrails_runner.py:136-139`).
- Every score is rounded to 4 decimals in the final update (`eval_core/guardrails_runner.py:160-173`). `categories` accuracy is rounded the same way (`:157-158`). With no evaluated rows the function returns the same keys with zero counts and `0.0` scores (`eval_core/guardrails_runner.py:117-134`).
- `guard_match_rate` only counts rows where both guards are known, so a row with no expected guard does not drag the rate down (`eval_core/guardrails_runner.py:146-149`).

### Defects fixed
The page never produced a real score before these four backend fixes. Each one is now covered by the end-to-end script.

1. `evaluate_guardrails_item` was called with `guards=`, `mode=`, `settings=`, `guardrails_url=` and `timeout=`, but the function took six positional scalars. Every row raised `TypeError`, was stored as `failed`, and the metrics came out all zeros. The function now takes a `GuardrailsEvalItem` plus keyword-only arguments (`eval_core/guardrails_runner.py:44-52`), and a row that still raises is counted in the scores instead of being dropped (`routes/guardrails_evaluate.py:328-359`).
2. `repo.import_dataset(..., replace=...)` — the repository had no `replace` parameter, so every dataset upload raised `TypeError`. `replace=False` now returns **409** when the name exists (`guardrails_evaluation_repository.py:21-35`).
3. `list_guardrails_datasets` did `for ds, count in rows`, but `list_datasets()` returns dataset rows, not pairs. That call returned HTTP 500. It now uses `len(ds.items)` (`routes/guardrails_evaluate.py:231-238`).
4. `repo.list_run_items()` did not exist at all. It was added, so `GET /runs/{run_id}/items` works (`guardrails_evaluation_repository.py:165-172`).

### Verified results
- `scripts/e2e_guardrails.py` (new) runs the whole surface against the live stack and prints its own tally. The measured result is **34/34 checks pass** (`scripts/e2e_guardrails.py:268`).
- `tests/unit/test_guardrails_runner.py` (new) holds **15 tests**: 9 functions plus 6 parametrized cases of the mode/phase matrix. They cover the confusion matrix, the skipped-row rule, the phase/mode rule and the category buckets (`tests/unit/test_guardrails_runner.py:33-150`).
- The retrieved golden evaluation scores **accuracy 1.0, precision 1.0, recall 1.0, f1 1.0, guard_match_rate 1.0, 7 true positives, 5 true negatives, 0 false positives, 0 false negatives**.
- The full retrieval unit suite is unchanged at **7 failed / 60 passed**. The 7 failures are pre-existing and unrelated to guardrails.

---

## 5. Implementation notes (verified in the working tree)
- `GuardrailsEvalItem` and `GuardrailsGoldenItem` carry the same field names: `text`, `phase`, `expected_blocked`, `expected_guard`, `category`, `metadata` (`eval_core/guardrails_runner.py:10-18`, `eval_core/guardrails_dataset_schema.py:8-16`).
- The run route passes `settings.guardrails_url` and `settings.guardrails_timeout_s` to the runner (`routes/guardrails_evaluate.py:309-311`). Both are real fields of `rag_shared.config.Settings` (`rag_shared/config.py:33-36`).
- The TypeScript type for `guard_results` in `guardrailsEvalApi.ts:83` still declares the old `passed` key. The runtime object carries `validation_passed`, `error` and `detail`, and the page does not read that type field.
- The metric keys are produced by the backend now. The client type for `aggregate_metrics` lists the same names, each optional (`guardrailsEvalApi.ts:48-62`).
