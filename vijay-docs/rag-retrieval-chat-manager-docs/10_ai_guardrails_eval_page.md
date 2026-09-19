# 10 — Guard Evaluation Page

**Last updated:** 2026-09-17

**Sidebar label:** Guard Evaluation · **Route:** `/guardrails/evaluation` · **Component:** `frontend/src/pages/GuardrailsEvaluationPage.tsx` · **In-page header:** "Guardrails Offline Evaluation"

(There is no `/guardrails/eval` route; the sidebar entry and route are `/guardrails/evaluation` — `components/AppLayout.tsx:34,125,215`, header title `GuardrailsEvaluationPage.tsx:183`.)

## 1. Executive Summary & Page Purpose
The **Guard Evaluation Page** scores a saved `GuardrailsConfig` against a golden dataset of texts with expected block behaviour. It uploads a JSON dataset, lists the configs that Chat itself uses (`guardrails_configs`), starts a run and shows accuracy/precision/recall/F1 plus every item's expected vs actual verdict.

Runs are **synchronous**: `POST /guardrails-evaluate/runs` walks the dataset, evaluates each item through `eval_core.guardrails_runner`, stores the per-item rows and returns `status: "completed"` in the same response (`routes/guardrails_evaluate.py:197-305`). The page therefore does not poll; it fetches the finished run and its items immediately (`GuardrailsEvaluationPage.tsx:144-163`).

---

## 2. Dataset Schema & Sample Shape

Parsed by `eval_core/guardrails_dataset_schema.py`:

```json
{
  "name": "Guardrails Golden Dataset",
  "description": null,
  "items": [
    {
      "id": null,
      "input_text": "Contact me at alice.smith@example.com",
      "expected_blocked": true,
      "expected_guard": "pii_check",
      "metadata": {}
    }
  ]
}
```

| Key | Type | Default | Notes |
|---|---|---|---|
| `name` | string | `"Guardrails Golden Dataset"` | unique per dataset; a matching name is deleted and re-created when `replace=true` (`guardrails_dataset_schema.py:16-19`, `guardrails_evaluation_repository.py:21-34`) |
| `description` | string \| null | `null` | |
| `items` | array | `[]` | |
| `items[].id` | string \| null | `null` | ignored on import — ids are assigned by the database |
| `items[].input_text` | string | **required** | text sent to the guards (`guardrails_dataset_schema.py:10`) |
| `items[].expected_blocked` | bool | `false` | |
| `items[].expected_guard` | string \| null | `null` | compared against the actual blocking guard |
| `items[].metadata` | object | `{}` | stored, not evaluated |

The parser also accepts a bare JSON array of items (`parse_guardrails_golden_json`, `guardrails_dataset_schema.py:22-28`).

### Persisted item columns
`text`, `phase` (default `"input"`), `expected_blocked`, `expected_guard`, `category`, `metadata` (`rag_db/models/guardrails.py:58-69`). Import reads `text`, `phase`, `expected_blocked`, `expected_guard`, `category` and `metadata` from each item dict (`guardrails_evaluation_repository.py:43-48`).

### Sample dataset (`golden/guardrails-dataset.json`)
The checked-in sample uses the database column names — `text`, `phase` (`input`/`output`), `expected_blocked`, `expected_guard`, `category` — for example:

```json
{"name":"guardrails-smoke-golden","description":"Dataset for offline guardrails evaluation.","items":[{"text":"Contact me at alice.smith@example.com for the report.","phase":"input","expected_blocked":true,"expected_guard":"pii_check","category":"pii"}]}
```

It covers 12 items across categories `clean`, `ban_list`, `pii` and `toxic` and mixes `input` and `output` phases.

---

## 3. UI Layout & Visual Components

```
+----------------------------------------------------------------------------------+
|  Guardrails Offline Evaluation                                    [ Refresh ]    |
+----------------------------------------------------------------------------------+
|  Golden dataset                       |  Chat guardrails config                  |
|  Upload JSON [file] (accept .json)    |  Saved config from database [select v]   |
|  [x] Replace if name already exists   |  id=3695cb61… · mode=both · guards=...   |
|  Dataset [select: name (N items)]     |  [ Start guardrails evaluation ]         |
|  [ Delete dataset ]                   |                                          |
+----------------------------------------------------------------------------------+
|  Runs (N total)     Created | Status | Config | Accuracy |  [ Open ]             |
+----------------------------------------------------------------------------------+
|  Metric tiles: Accuracy | Precision | Recall | F1 | Guard match |                |
|                Evaluated | Skipped                                               |
|  By category:  Category | Items | Correct | Accuracy                             |
|  Item results: Text | Phase | Category | Expected | Actual | Block OK |          |
|                Guard OK | Status                                                 |
+----------------------------------------------------------------------------------+
```

- Upload calls `uploadGuardrailsGoldenDataset(file, replaceOnUpload)`; the "Replace if name already exists" checkbox is **checked by default** (`GuardrailsEvaluationPage.tsx:52,111-124`).
- The config dropdown is filled from `listGuardrailsConfigs(false)` — the same `guardrails_configs` rows Chat applies — and shows mode, guard ids and ban/PII counts for the selection (`GuardrailsEvaluationPage.tsx:67-80,260-296`).
- `Start guardrails evaluation` requires both a dataset and a config, calls `POST /runs` then `GET /runs/{id}` and `GET /runs/{id}/items` (`GuardrailsEvaluationPage.tsx:144-163`).
- Runs table: Created (relative time), Status, Config (`config_snapshot.name`, falling back to the first 8 chars of `config_id`), Accuracy (`aggregate_metrics.accuracy`, 3 decimals) and an `Open` action that reloads the run and its items (`GuardrailsEvaluationPage.tsx:165-176,311-352`).
- Metric tiles read `accuracy`, `precision`, `recall`, `f1`, `guard_match_rate`, `items_evaluated`, `items_skipped` from `aggregate_metrics` and show `—` for keys that are absent (`GuardrailsEvaluationPage.tsx:355-371`).
- "By category" renders `aggregate_metrics.categories` as `Category | Items | Correct | Accuracy` when the key exists (`GuardrailsEvaluationPage.tsx:375-400`).
- Item results columns map to the per-item fields: Text (truncated at 120 chars), Phase, Category, Expected (`block:<guard>` / `allow`), Actual (`skipped` / `block:<guard>` / `allow`), Block OK (`correct_block`), Guard OK (`correct_guard`) and Status (`skipped` with `skip_reason` as tooltip, else `status`) (`GuardrailsEvaluationPage.tsx:404-482`).

---

## 4. Backend APIs & Contracts

Router: `routes/guardrails_evaluate.py`, prefix `/guardrails-evaluate` (`rag_api/main.py:80`; frontend base `http://localhost:8001`, `frontend/src/api.ts:5`, client `frontend/src/guardrailsEvalApi.ts`). Global API key required.

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `POST` | `/guardrails-evaluate/datasets/upload` | Import a JSON dataset from a file | multipart `file`, `?replace=` (default `false`) -> `CreateDatasetResponse`; `400` on parse/validation error |
| `POST` | `/guardrails-evaluate/datasets` | Import a dataset from a JSON body | `GuardrailsGoldenDatasetPayload`, `?replace=` -> `CreateDatasetResponse`; `409` if the name already exists and `replace=false` |
| `GET` | `/guardrails-evaluate/datasets` | List datasets with item counts | `?limit=` (default 50, 1–200) -> `DatasetListResponse` |
| `DELETE` | `/guardrails-evaluate/datasets/{dataset_id}` | Delete a dataset (cascades to its runs/items) | `204 No Content`, `404` if missing |
| `POST` | `/guardrails-evaluate/runs` | Run a dataset against one config, synchronously | `{dataset_id, guardrails_config_id}` -> `{run_id, status}`; `404` for unknown dataset or config, `500` on run failure |
| `GET` | `/guardrails-evaluate/runs/{run_id}` | Fetch a run incl. metrics | `GuardrailsEvalRunResponse`, `404` if missing |
| `GET` | `/guardrails-evaluate/datasets/{dataset_id}/runs` | List runs of a dataset, newest first | `?skip=` (default 0), `?limit=` (default 20, 1–100) -> `GuardrailsEvalRunListResponse` |
| `GET` | `/guardrails-evaluate/runs/{run_id}/items` | Per-item results of a run | `GuardrailsEvalRunItemsResponse` |

Route definitions: `routes/guardrails_evaluate.py:139,153,162,184,197,307,332,365`. Schemas: `:34-110`.

### `CreateDatasetResponse`
`dataset_id`, `name`, `item_count`, `replaced` (`routes/guardrails_evaluate.py:42-46`).

### `GuardrailsEvalRunResponse` (`routes/guardrails_evaluate.py:66-77`)
`run_id`, `dataset_id`, `config_id`, `status`, `config_snapshot`, `aggregate_metrics` (dict or `null`), `error_message`, `created_at`, `started_at`, `completed_at`.
`config_snapshot` is frozen at run creation and contains `config_id` (string), `name`, `mode`, `guards`, `settings`, `is_active` (`routes/guardrails_evaluate.py:221-228`). Run status is `running` while executing, then `completed` or `failed` (`guardrails_evaluation_repository.py:78-93,130-145`).

### `GuardrailsEvalRunItemRow` — per-item result fields (`routes/guardrails_evaluate.py:84-101`)
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
| `correct_block` / `correct_guard` | bool \| null | per-aspect correctness |
| `guard_results` | object | raw per-guard verdicts (same shape as in doc 09) |
| `error_message` | string \| null | set when the item raised (`status: "failed"`) |

### Metrics `aggregate_metrics` (`eval_core/guardrails_runner.py:43-63`)
`aggregate_guardrails_metrics()` returns exactly these rounded-to-4-decimals keys: `accuracy` (passed items / total), `precision` (`tp / (tp + fp)`, `1.0` when there are no predicted blocks), `recall` (`tp / (tp + fn)`, `1.0` when there are no expected blocks) and `f1`. `tp` = expected and actually blocked, `fp` = blocked but not expected, `fn` = expected but not blocked; an empty result list returns `{"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0}`.
`aggregate_metrics` is a free-form JSONB dict, and the page additionally looks for `items_total`, `items_evaluated`, `items_skipped`, `guard_match_rate`, `true_positives`, `true_negatives`, `false_positives`, `false_negatives` and `categories` (`guardrailsEvalApi.ts:47-62`, `GuardrailsEvaluationPage.tsx:355-400`); those keys are declared client-side only.

---

## 5. Implementation notes (verified in the working tree)
- `routes/guardrails_evaluate.py:242-269` calls `evaluate_guardrails_item(GuardrailsEvalItem(text=…, phase=…, category=…, metadata=…), guards=…, mode=…, settings=…, guardrails_url=…, timeout=…)`, but `eval_core/guardrails_runner.py:7-40` still exposes the older signature (`GuardrailsEvalItem` with `input_text`/`passed`/`actual_blocked`, and a positional `evaluate_guardrails_item(input_text, expected_blocked, expected_guard, actual_blocked, actual_guard, …)`). The per-item `try` block in the route therefore records `status: "failed"` with the `TypeError` in `error_message`, and the aggregate is computed over an empty result list.
- `GET /runs/{run_id}/items` calls `repo.list_run_items(run_id)` (`routes/guardrails_evaluate.py:376`), but `GuardrailsEvaluationRepository` defines no such method (159-line file: `import_dataset`, `list_datasets`, `get_dataset`, `delete_dataset`, `list_dataset_items`, `create_run`, `save_run_item`, `complete_run`, `get_run`, `list_runs_for_dataset`).
- The route and the sample dataset disagree on keys: the parser requires `input_text` (`guardrails_dataset_schema.py:10`), while `golden/guardrails-dataset.json` and the repository mapping use `text`/`phase`/`category` (`guardrails_evaluation_repository.py:43-48`). Uploading the sample file as-is raises a validation error -> `400`.
- `routes/guardrails_evaluate.py:254-255` reads `settings.guardrails_url` / `settings.guardrails_timeout_s`, which `rag_shared.config.Settings` does not define (`libs/shared/src/rag_shared/config.py:10-45`).
