# 13 — Golden Dataset Evaluation Requirements

**Last updated:** 2026-10-19

Implementation contract for offline golden-dataset evaluation in `rag-retrieval-chat-manager`. Every
field below is taken from `eval_core/dataset_schema.py`, `eval_core/runner.py`,
`apps/rag-api/src/rag_api/routes/evaluate.py`, `apps/eval-worker/src/eval_worker/tasks.py` and the
evaluation repository.

## 1. Golden Dataset Schema & Upload

### 1.1 Payload

| Field | Type | Required | Default | Validation |
|---|---|---|---|---|
| `name` | string | yes | — | non-blank after `strip()`; error `name must not be empty` |
| `description` | string \| null | no | `null` | — |
| `kind` | `"single_turn"` \| `"multi_turn"` | no | derived | **never stored from the file.** `kind_from_items` sets it from the rows and overwrites whatever the caller sent |
| `items` | array | yes | — | at least one entry; error `items must contain at least one entry` |

Item object:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `question` | string | yes\* | — | non-blank after `strip()`. \*Not required at the file level when `turns` is present: the loader derives it from the last user turn |
| `ground_truth_answer` | string \| null | no | `null` | the RAGAS `reference`; feeds `faithfulness` and `answer_correctness`/`accuracy` |
| `expected_sources` | array | no | `[]` | normalized into `{name, page?}` objects |
| `turns` | array \| null | no | `null` | `[{role, content}, ...]`. A row with turns is a conversation |
| `metadata` | object | no | `{}` | free-form. `question_type`, `category`, `label`, `expected_behavior`, `keypoints_covered` all live here |

Turn validation, from `GoldenTurnPayload` and the `turns_are_well_formed` validator:

* a `role` outside `{user, assistant}` → `turn role must be user or assistant`
* an empty `content` → `turn content must not be empty`
* `turns` with no `user` turn → `turns must contain at least one user turn`

`record_the_assistant_turns` copies every assistant turn into `metadata["expected_turns"]` as
`[{"content": ...}]` when the row does not carry that key. The assistant turns are what the
conversation aimed at; the run replays the user turns only.

A dataset holds one kind of row. A file that mixes a row with `turns` and a row without fails with
`a dataset cannot mix single-turn and multi-turn rows`. RAGAS and DeepEval both refuse that mixture,
so the rule holds for a file either framework generates.

The dataset `name` is unique in the database; re-uploading an existing name without `replace=true`
fails with `409 Dataset '<name>' already exists`.

### 1.2 Column and field aliases

One alias table serves the CSV, the JSON body and the JSONL path, so a file either framework
generates loads with no renaming. Precedence is left to right, canonical name first.

| Canonical field | Accepted names, in precedence order |
|---|---|
| `question` | `question`, `user_input`, `input`, `query` |
| `ground_truth_answer` | `ground_truth_answer`, `reference`, `expected_output`, `expected_outcome` |
| `reference_context` | `reference_context`, `reference_contexts`, `context` |
| `source_doc_id` | `source_doc_id`, `expected_sources`, `source` |
| `turns` | `turns`, `conversation`, `messages` |

`_COLUMN_ALIASES` in `dataset_schema.py` is the whole declaration. Three consequences:

* **Header order does not matter.** Each canonical field resolves to the first alias present in the
  file's header set.
* **Two spellings of one field must agree.** A file carrying both `question` and `user_input` parses
  while they match and fails with `question and user_input disagree; keep one` when they do not. The
  same rule covers every aliased field.
* **`response` is not an alias.** For RAGAS it is the model's own answer, and reading it as the
  reference would score a run against itself. In a CSV it lands in `metadata`; in a JSON body the
  older paper format still uses it as the answer when no answer field is present.

`retrieved_contexts`, `actual_output`, `retrieval_context`, `rubrics` and `rubric` are not aliased
either. They are a run's outputs, so they fall through to `metadata` and measure nothing.

### 1.3 Accepted JSON Formats

A JSON body and a `.json` file take the same shapes. `_normalize_item` runs as a `before` validator
on `GoldenDatasetPayload`, so `POST /evaluate/datasets` and a file upload accept the same fields.

```json
{
  "name": "my-eval-set",
  "description": "optional",
  "items": [
    {
      "query": "What is RAG?",
      "source": [{ "name": "document.pdf", "page": 3 }],
      "response": "RAG stands for Retrieval Augmented Generation...",
      "metadata": { "question_type": "single_hop" }
    },
    {
      "user_input": "What is DSA?",
      "reference": "DSA stands for Data Structures and Algorithms...",
      "reference_contexts": ["A short passage."],
      "source": ["https://geeksforgeeks.org/dsa-tutorial"],
      "metadata": { "category": "Indirect Answer" }
    }
  ]
}
```

Normalization rules:

* `source` may be a single string, a single object, or an array of either. Objects use `name` (or the
  alias `source`) as the locator; `page` is coerced to `int` and dropped when absent, empty or not
  castable. Entries with a blank name are dropped.
* `reference_contexts` may be a list; a list is joined into one string with a blank line between the
  parts, so a RAGAS field round-trips.
* An item-level `category` or `question_type` key is **not** a schema field. Put them under
  `metadata`: the category roll-up reads `metadata.question_type` (falling back to
  `metadata.category`), and the item drill-down returns `metadata.category` as `category`.
* Normalizing an already-normalized payload changes nothing, which is what lets the upload path and
  the model validator both run.

A **multi-turn** JSON item puts the conversation in `turns`, or — for a RAGAS `MultiTurnSample` —
in `user_input` as a list of message objects. A list in `user_input` is read as the turns, and the
question becomes the last user turn. The two shapes are equivalent.

### 1.4 Accepted CSV Format

`POST /evaluate/datasets/upload` accepts `.csv`, `.json` and `.jsonl`. The reference single-turn CSV
is `rag-retrieval-chat-manager/backend/tcs_policies_golden_dataset.csv` (22 rows).

Column mapping (header lookup ignores case and surrounding spaces):

| CSV column | Maps to | Notes |
|---|---|---|
| `question` (or an alias) | `question` | required **unless** the file carries `turns` |
| `ground_truth_answer` (or an alias) | `ground_truth_answer` | the RAGAS `reference` |
| `source_doc_id` (or an alias) | `expected_sources` | `;`- or `,`-separated. `N/A`, `NONE`, `-`, `null` or empty means no source |
| `reference_context` (or an alias) | the gold context, stored in `metadata.reference_context` | a value starting with `NONE` is dropped |
| `turns` (or an alias) | the conversation | a JSON array of `{role, content}` objects in one cell |
| every other column (`id`, `question_type`, `expected_behavior`, `keypoints_covered`, `difficulty`, `notes`) | `metadata` | stored under its own key |

Because any unknown column lands in `metadata` JSONB, adding a CSV column needs **no** migration.

**The `turns` cell.** It is JSON, so the cell must be quoted in the CSV and its inner quotes doubled:

```csv
id,question_type,source_doc_id,turns
M002,coreference,resume3.pdf,"[{""role"": ""user"", ""content"": ""Which company does Rohan Sinha work for now?""},{""role"": ""user"", ""content"": ""What is his title there?""}]"
```

Parsing rules for one multi-turn row:

* A cell that is not a JSON array, or an array holding a non-object, fails with
  `turns must be a JSON array of {role, content} objects`.
* **`question` is derived from the last user turn** when the file has no question column or the cell
  is empty. A file that supplies both must supply a matching value, or
  `question must match the last user turn of turns`. The derived question is what the generation
  metrics score; the earlier turns are replayed to produce the context.
* A row with no resolvable question is skipped, exactly as an empty single-turn row is.

**Two sample datasets** ship in the repository root under `resumes/`, ten rows each:
`resume_single_turn_golden.csv` (4 single-hop, 2 multi-hop, 1 comparative, 1 edge case, 2
out-of-corpus) and `resume_multi_turn_golden.csv` (10 conversations: `follow_up`, `coreference`,
`multi_turn_multi_hop`). Every answer, keypoint and source is traceable to a page of one of the six
PDFs in that folder.

### 1.5 Accepted JSONL

`.jsonl` is one JSON object per line, the shape RAGAS's `EvaluationDataset.to_jsonl()` writes. It is
the only lossless interchange for a list-valued field: a CSV cell is text, so `reference_contexts`
comes back as a string and pydantic rejects it. Each line runs through the same `_normalize_item`.

```jsonl
{"user_input": "Who approved the policy?", "reference": "The Board of Directors.", "reference_contexts": ["The board approved it."]}
{"user_input": [{"role": "user", "content": "Which company does Rohan Sinha work for now?"}, {"role": "user", "content": "What is his title there?"}], "reference": "Senior Software Engineer at Google."}
```

A line that is not an object fails with `JSONL line <n> must be an object`. The dataset name comes
from the filename stem or `?name=`.

### 1.6 Framework compatibility

| Framework | Shape | How it loads |
|---|---|---|
| RAGAS `SingleTurnSample` | `user_input`, `reference`, `reference_contexts` | CSV, JSON body or JSONL, through the alias table |
| RAGAS `MultiTurnSample` | `user_input` as a list of `{role, content}` | JSON body or JSONL; CSV via a `turns` cell |
| RAGAS `EvaluationDataset.to_jsonl()` | one sample per line | `.jsonl` upload |
| DeepEval `Golden` | `input`, `expected_output`, `context` | CSV or JSON body, through the alias table |
| DeepEval `ConversationalGolden` | `turns` | CSV `turns` cell, JSON body, or JSONL |

`EvaluationDataset.from_list` accepts the project's single-turn rows after mapping them to the RAGAS
names; the test `test_the_single_turn_dataset_is_valid_for_ragas` proves it on the shipped dataset.
`from_csv` cannot round-trip a list-valued field, so JSONL is the interchange for those.

Neither synthesizer is implemented. Only the schema is compatible.

### 1.7 The `source_doc_id` convention — read this before authoring a dataset

This column is the only reference the retrieval and reranking metrics have. **A value that does not
match an ingested file name makes every reference-based metric read zero**, with no error: `hit`,
`recall`, `precision`, `mrr` and `ndcg` all come back `0.0` while the `generation` block still scores
normally.

Three rules:

1. **Name the ingested file, not a label of your own.** The matcher compares the value against the
   chunk's `source_locator`, `title`, `metadata.file_name`, `metadata.url` and
   `metadata.source_locator`, reduced to a basename, by bidirectional substring. So
   `Resume-1.pdf` matches; a shorthand such as `WB` does not, and never can, because nothing in the
   corpus carries that string.
2. **A `_p<page>` suffix from a CSV does not set a page.** The suffix splits into `{name, page}` only
   for a plain-string source (`parse_expected_sources`). A CSV row reaches the matcher as a dict,
   because `_split_sources` emits `{"name": "<value>"}` and the dict branch keeps the whole name with
   `page=None`. So `Resume-1.pdf_p3` matches the chunk whose file name is `Resume-1.pdf` and the page
   is ignored. The JSON form can send `{name, page}` and that value does apply.
3. **A page, when one is set, is 1-based against `metadata.page_index`.** A chunk at `page_index: 2`
   is page `3`.

Separate multiple sources with a semicolon or a comma.

```
Q003,procedural_howto,...,TCS-Global-Whistle-Blower-Policy.pdf_p3,...
Q019,comparative_cross_document,...,TCS-Global-Whistle-Blower-Policy.pdf_p1;CSV_p7,...
```

**Check the column before running anything.**

```bash
cut -d, -f6 resumes/resume_single_turn_golden.csv | tr ';' '\n' | sort -u
```

Compare that list with the corpus:

```bash
docker exec rag-ingestion-manager-qdrant-1 sh -c \
  'curl -s -H "api-key: qdrant" -X POST http://localhost:6333/collections/<collection>/points/scroll \
   -H "Content-Type: application/json" -d "{\"limit\":100,\"with_payload\":[\"file_name\"]}"' \
  | grep -o '"file_name":"[^"]*"' | sort -u
```

A CSV carries no `name` field. The upload uses the filename stem, and `?name=` overrides it. A JSON
upload uses the file's own `name`, and `?name=` overrides that too.

### 1.8 Upload & Import API

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| `POST` | `/evaluate/datasets` | JSON body = dataset payload; query `replace` (default false) | `{dataset_id, name, kind, item_count, replaced}` | `409` duplicate without replace; `422` schema errors, including a mixed-kind file |
| `POST` | `/evaluate/datasets/upload` | multipart field `file` (`.csv`, `.json`, `.jsonl`); query `replace`, `name` | same, with `kind` | `422 file must be a .csv, .json or .jsonl file`; `422 uploaded file is empty`; `422 Invalid dataset CSV\|JSON\|JSONL: <detail>`; `409` duplicate |
| `POST` | `/evaluate/datasets/huggingface` | optional `{replace: bool}` | same | `502 DATASET_EMPTY` |
| `GET` | `/evaluate/datasets?limit=N` | `limit` 1–100, default 50 | `{limit, count, items[{dataset_id, name, description, kind, item_count, created_at}]}` | `422 limit must be between 1 and 100` |
| `GET` | `/evaluate/datasets/{dataset_id}` | — | one summary, with `kind` | `404 Dataset not found` |
| `DELETE` | `/evaluate/datasets/{dataset_id}` | — | `204` | `404` |

`kind` is on every dataset response, because the page needs it to decide whether the selected
pipeline may run that dataset.

The Hugging Face import reads `m-ric/huggingface_doc_qa_eval` through the Hub rows API and stores it
as `HF Doc QA`. Its companion corpus is `A-Roucher/huggingface_doc`.

---

## 2. Evaluation Core (`eval-core`)

### 2.1 A run goes through the real pipeline

`GoldenItemEvaluator.evaluate_item(item, config, k_values, *, judge_model=None, session_memory=None)`
calls **`RAGPipeline.chat`**, which is the path a live turn takes:

```python
if item.turns:
    result = self._run_conversation(item, config, session_memory)
else:
    result = self._pipeline.chat(item.question, config=config)
return self._score(result, item, k_values, judge_model)
```

This is what makes the `self_rag` and `corrective` strategies measurable. Their grading and revision
lives inside `RAGPipeline`:

| Step | What it does | Applies to |
|---|---|---|
| `_effective_query` | rewrites a follow-up into a standalone question when `config.history` is present | every strategy, when the run has memory |
| `retrieve` | reads the store the strategy names | every strategy |
| `rerank` | reorders and cuts to `config.effective_top_k()` | every strategy |
| `_grade_passages` | `grade_relevance` drops passages below the threshold, and returns `None` when none survives | `self_rag`, `corrective` |
| `generate` | builds the prompt from the reranked passages and the history | every strategy |
| `_review_answer` | `answer_is_grounded`; a definite ungrounded verdict rewrites the answer once | `self_rag` |

Two consequences a reader must know:

* **A corrective abstention scores a nearly empty generation block.** When `grade_relevance` keeps
  nothing, `ChatResult` carries `NO_RELEVANT_PASSAGES_ANSWER` with an empty `reranked_chunks`. The
  RAGAS metrics and the triad both skip a row with no contexts, so `generation_metrics` holds only
  the two custom metrics. That is the correct reading of a refusal, not a failure.
* The evaluator no longer calls `Retriever`, `build_reranker` or `Generator` itself. Those imports are
  gone from `runner.py`.

### 2.2 A multi-turn run drives the pipeline's own session memory

`_run_conversation(item, config, memory)` replays the user turns, one `pipeline.chat` call each:

```python
session_id = str(uuid.uuid4())
try:
    for turn in item.turns or []:
        if turn.get("role") != "user":
            continue
        if memory is not None:
            config.history = memory.load(session_id)
        last = self._pipeline.chat(turn["content"], config=config)
        if memory is not None:
            memory.append(session_id, [SessionTurn("user", turn["content"]),
                                       SessionTurn("assistant", last.answer)])
finally:
    memory.clear(session_id)   # a failing clear is logged, not raised
```

This is the same protocol a live turn uses (`routes/chat.py`), so the Redis path under test is the
production one. A run **without** memory still replays the turns, but each one is stateless, so only
the truth of the final answer changes. The final turn's `ChatResult` is what `_score` reads.

The session id is fresh per row, so two rows can never share a conversation, and `clear` runs in a
`finally`, so a failed row leaves no key behind. A Redis outage makes the conversation stateless for
the duration; `SessionMemory` fails soft on read and write, and only `clear` can raise, which the
`finally` catches.

### 2.3 Formula-based metrics (retrieval and reranking)

No LLM-as-a-judge is used for these stages. Fixed `k = 5`.

* **`precision`**: relevant chunks within the top 5 divided by the chunks in the top 5.
* **`recall`**: expected sources matched within the top 5 divided by the number of expected sources.
* **`hit`**: `1.0` when any expected source appears in the top 5.
* **`mrr`**: `1 / rank` of the first relevant chunk over the full retrieved list.
* **Reranking**: `mrr_before`, `mrr_after`, `mrr` (alias of `mrr_after`), `mrr_delta`,
  `mrr_before_at_k` (the pre-rerank list cut to the reranker's depth), `kendall_tau` (`None` with
  fewer than two shared chunk ids) and `ndcg`.

The score stores one extra key in the retrieval block: **`effective_query`**, the standalone question
a session turn was rewritten into, or absent when the question was searched as written. It is a
string, so the aggregate means skip it. It is the only record of whether a follow-up reached
retrieval as a pronoun.

### 2.4 Generation metrics

RAGAS, through the LiteLLM judge, merged into one `generation_metrics` block:

* `faithfulness` against the post-rerank contexts.
* `answer_relevancy` from question + answer.
* `answer_correctness` (also stored as `accuracy`) when `ground_truth_answer` is non-empty.
* The triad via `compute_triad_metrics`: `context_relevance`, `response_groundedness` and
  `answer_relevancy`. All three need no reference, so all three run on an unanswerable row.
  `include_answer_relevancy=False` on the generation call, because the triad already scores it from
  the same inputs.

**The judge output budget.** `JUDGE_MAX_TOKENS = 8192` (`ragas_client.py`) is passed to `llm_factory`
for every metric. Every RAGAS metric answers in structured JSON, and a five-passage row with a
three-sentence answer needs about 5,200 tokens for `AnswerCorrectness`; at 4,096 the proxy returns
`finish_reason: "length"` and RAGAS reports the metric as failed. **A failed metric leaves its key
out**, so the aggregate mean silently covers only the rows that scored. That is why a run could store
`faithfulness` for one row and none for the next. `tests/unit/test_ragas_judge_budget.py` pins the
budget at 8192 or above.

### 2.5 Custom metrics (no judge model)

* **`behavior_match`**: `1.0` when the answer behaves as the row's `expected_behavior` says. A
  `refuse_or_abstain` row wants an abstention; every other row wants a real answer.
* **`keypoint_coverage`**: the fraction of `keypoints_covered` present in the answer. A
  `label=value` entry is matched on the value side; a comma-separated value needs every part. A row
  whose keypoints are bare tags is not measurable, so the key is **absent** rather than `0.0`.

The abstention markers cover the plural forms and the pipeline's own two refusal answers, because a
model reading five passages says "the resumes do not contain" far more often than "the resume does
not contain". Without `could not find` in the marker list, `NO_RELEVANT_PASSAGES_ANSWER` scored
`behavior_match = 0` on exactly the rows that abstained correctly.

### 2.6 Judge model

`EvalRunConfig.judge_model` overrides the judge for one run. `null` means
`settings.ragas_judge_model`. The run stores the value. Keep one judge across two runs if you intend
to compare them.

`k_values` is accepted by both metric functions and not used. `rag_mode` and
`self_corrective_max_loops` are no longer read: `strategy` selects the behaviour.

---

## 3. Database Layer (`rag_db`)

* **Schema** (`rag_db/models/evaluation.py`):
  * `GoldenDataset` — `name` (unique), `description`, **`kind`** (`String`, NOT NULL,
    `server_default="single_turn"`).
  * `GoldenDatasetItem` — `question` (NOT NULL), `ground_truth_answer`, `expected_sources` JSONB,
    **`turns`** (JSONB, nullable), `metadata` JSONB.
  * `EvaluationRun` — `dataset_id`, `status`, `config` JSONB, `aggregate_metrics` JSONB, timing.
  * `EvaluationRunItem` — the two chunk lists, the three metric blocks, `generated_answer`,
    `error_message`.
* **Migrations**: head is `007_dataset_profiles`, which adds the Dataset Fabric profile table and
  six columns on `golden_datasets` (`profile_id`, `storage_bucket`, `storage_key`,
  `original_filename`, `source_format`, `row_count`). `006_golden_dataset_kind_and_turns` has
  `down_revision = "005"`. It adds
  `golden_datasets.kind` (server default `single_turn`, which backfills every existing dataset
  correctly) and `golden_dataset_items.turns`, and drops both on downgrade. Revision `005` remains
  `005_soft_delete`. Tested as an upgrade → downgrade → upgrade round trip.
* **Repository** (`evaluation_repository.py`): `import_dataset(..., kind=...)` and
  `add_dataset_item(..., turns=...)` carry the two new values. `create_dataset(name, description,
  *, kind="single_turn")`.
* **Aggregation (`aggregate_run_metrics`)** averages every numeric key of every `completed` item and
  prefixes it with `mean_`:
  * `retrieval`: `mean_precision`, `mean_recall`, `mean_hit`, `mean_mrr`.
  * `reranker`: `mean_mrr_before`, `mean_mrr_after`, `mean_mrr`, `mean_mrr_delta`,
    `mean_mrr_before_at_k`, `mean_ndcg`, `mean_kendall_tau`.
  * `generation`: whichever of `mean_faithfulness`, `mean_answer_relevancy`, `mean_accuracy`,
    `mean_answer_correctness`, `mean_context_relevance`, `mean_response_groundedness`,
    `mean_behavior_match`, `mean_keypoint_coverage` the rows produced.
  * `categories`: keyed by `metadata.question_type`, falling back to `metadata.category`. Rows with
    neither are left out rather than grouped under a made-up label.
  * Runs without completed items return empty stage blocks with `item_count: 0`.
* **Status flow**: item `pending` → `completed` | `failed`; run `queued` → `running` → `completed`
  (with aggregates) or `failed` (`aggregate_metrics = {"error": ...}`).

---

## 4. RAG API (`rag-api`)

| Method | Path | Request | Response |
|---|---|---|---|
| `POST` | `/evaluate/datasets` | dataset payload; `?replace=` | `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/upload` | multipart `file` (`.csv`/`.json`/`.jsonl`); `?replace=`, `?name=` | `CreateDatasetResponse` |
| `POST` | `/evaluate/datasets/huggingface` | `{replace}` | `CreateDatasetResponse` |
| `GET` | `/evaluate/datasets` | `?limit=` | `{limit, count, items[]}` |
| `GET` | `/evaluate/datasets/{id}` | — | `DatasetSummary` |
| `DELETE` | `/evaluate/datasets/{id}` | — | `204` |
| `GET` | `/evaluate/datasets/{id}/runs` | `?skip=`, `?limit=` | `{items, count}` |
| `GET` | `/evaluate/runs/{id}/items` | — | `{run_id, count, items[]}` |
| `POST` | `/evaluate/runs` | `{dataset_id, config: EvalRunConfig}` | `{run_id, status: "queued"}` |
| `GET` | `/evaluate/runs/{id}` | — | `EvalRunResponse` |
| `GET` | `/evaluate/pipeline-defaults` | — | `PipelineDefaultsResponse` |
| `GET` | `/evaluate/stats` | `?limit=` | `{limit, count, items[]}` |

### 4.1 `EvalRunConfig`

| Field | Default | Notes |
|---|---|---|
| `retrieval_mode` | `null` | resolved to `"dense"` |
| `retrieve_limit` | `null` | the pipeline's value, else `settings.retrieve_limit` |
| `rerank_enabled` | `null` | the pipeline's value, else `settings.reranker_enabled` |
| `rerank_model` | `null` | the pipeline's pinned model, else `settings.reranker_model` |
| `top_k` | `null` | the pipeline's `rerank_top_k`, else `settings.rerank_top_k` |
| `generation_model` | `null` | the page sends the pipeline's `chat_model` |
| `judge_model` | `null` | `settings.ragas_judge_model` when empty |
| `pipeline_slug` | `null` | **the pipeline whose session memory this run drives** |
| `session_memory_prefix` | `null` | **written by the route, not the caller** |
| `session_memory_ttl_s` | `null` | **written by the route, not the caller** |
| `rag_strategy` | `null` | the store names travel with the strategy |
| `collection`, `opensearch_index`, `pg_schema`, `pg_table` | `null` | the pipelog's Knowledge Product stores |
| `embedding_model`, `sparse_embedding_model` | `null` | the product's models |
| `k_values` | `[1,3,5,10]` | accepted; unused |
| `sample_size` | `null` | 1–500. A random sample |
| `seed` | `null` | stored with the run; the page sends none |
| `rag_mode` | `"normal"` | accepted; unused since the strategy selects the behaviour |
| `self_corrective_max_loops` | `3` | accepted; unused |
| `router_enabled` | `false` | accepted; unused |

### 4.2 `POST /evaluate/runs`

The handler is `async def` and does three things before it enqueues:

1. **Refuses the page-image strategy.** A run whose `rag_strategy` is `image_vision` returns
   `422` with `detail = {"code": "STRATEGY_NOT_EVALUABLE", "message": "Image Vision RAG is not
   supported by offline evaluation."}`. The page freezes its button for the same reason; the route is
   the authority.
2. **Resolves the pipeline's retrieval settings** from the request, then the deployment.
3. **Resolves the session-memory handle.** When `pipeline_slug` is set, the route calls the existing
   `_resolve_assistant(request, slug)` and reads `pipeline["_session_memory"]`, which is the
   `(prefix, ttl)` tuple `session_memory_for_product` returns. Both values go into the stored config.
   An unknown slug propagates the `404 ASSISTANT_NOT_FOUND` that route already raises. A product with
   no enabled Redis destination leaves the run stateless, which is all a single-turn run needs.

The Redis namespace never leaves the server: the page sends a slug, not a prefix.

The API key is enforced globally (`verify_api_key`): `X-API-Key` header or `api_key` query parameter
on every route except `/health`, `/docs`, `/openapi.json`, `/redoc`.

---

## 5. Worker (`eval_worker`)

`run_evaluation(run_id)`:

1. Mark the run `running`.
2. Build one `PipelineConfig` from the stored config: retrieval settings, `generation_model`,
   `vision_model` (a `image_vision` record still maps its generation model to the vision model),
   `collection`, the embedding models, **`strategy=config["rag_strategy"]`** and
   **`stores=KpStores(...)`** built from the collection and index names.
3. Build one `SessionMemory(settings, prefix=config["session_memory_prefix"], ttl_s=...)` when the
   config carries a prefix, and pass it to every item.
4. Read each dataset item, **including `turns`**, and pass `turns=` into `GoldenItem`.
5. Call `evaluator.evaluate_item(golden, config, k_values, judge_model=..., session_memory=...)`.
6. Persist the four per-item values, emit the OTel span, then aggregate and mark the run `completed`.
   A per-item exception is written to that item as `failed` and the loop continues.

`strategy` and `stores` ride the `PipelineConfig` now, exactly as they do for a live turn, so the
evaluator cannot be told two different strategies. The `rag_mode` and `self_corrective_max_loops`
arguments are gone: they were never `PipelineConfig` fields, so pydantic silently dropped them.

`EvalItemResult` carries no `latency_ms`; the worker reads it with
`getattr(result, "latency_ms", None) or {}`.

---

## 6. Frontend (`rag-retrieval-chat-manager/frontend`)

* **API client (`api.ts`)**: `uploadGoldenDataset(file, {replace, name})` returns
  `{dataset_id, name, kind, item_count, replaced}`. `GoldenDatasetSummary` carries `kind`.
  `createEvaluationRun(datasetId, config)` accepts `pipeline_slug`. `getAssistant(slug)` is the
  existing assistant-config call; the page uses it for the memory fact and adds no second helper.
* **Page**: `GoldenEvaluationsPage.tsx` at `/golden-evaluations`, nav label **Offline Evaluation**.
* **Two module constants** carry the strategy policy:

  ```ts
  const EVALUABLE_STRATEGIES = ["vector", "lexical", "hybrid", "self_rag", "corrective"];
  const VISION_STRATEGY = "image_vision";
  ```

* **Memory probe.** An effect keyed on the selected pipeline calls `getAssistant(slug)` when the
  pipeline is an assistant with a slug, and reads `session_memory.enabled`, `.ttl_seconds` and
  `.reason`. Any other pipeline reads as "no memory" with a stated reason. A failed probe also reads
  as "no memory", so a single-turn run is never blocked by it.
* **Two gates**, computed before the button is pressed:

  ```ts
  const strategyBlocked = !EVALUABLE_STRATEGIES.includes(pipeline.rag_strategy);
  const datasetBlocked = selectedDataset?.kind === "multi_turn" && memoryEnabled === false;
  ```

  The run button is `disabled` on either. One `alert alert-warn` states which one applies: the
  Image Vision copy names the strategies to pick instead, and the memory copy names the Redis
  destination and the single-turn alternative.
* **`PipelineSummary`** gained a **Memory** row, after Modality: `enabled · 86400 s TTL` or
  `none · <reason>`. It is stated before a dataset is picked, because it decides whether a multi-turn
  dataset can run at all.
* **Dataset list** shows the kind beside the count: `(10 items · multi-turn)`.
* **Upload control** accepts `.csv`, `.json` and `.jsonl`.
* **The run carries `pipeline_slug`**, so the route can resolve the memory handle. It also sends the
  pipeline's retrieval settings, its chat model, its stores and the judge.
* Results: `TriadPanel`, then `OverallKpis` with the stage selector, `Metrics by Category`, the
  `Evaluation Rubric` distribution, then `Open full run details` → `/golden-evaluations/runs/:id`
  (`EvalRunDetailPage.tsx`, polls every 5 s).

---

## 7. Seed script

`rag-retrieval-chat-manager/backend/scripts/seed_resume_strategy_pipelines.py` makes the five
pipelines offline evaluation can score, over one Knowledge Product.

* `--product <name-or-id>`, default: the first product whose name contains `resume`.
* Enables the product's `cache_redisvl` destination when it has none, with `ttl_seconds: 86400`. The
  update replaces the whole destination list, so every existing destination travels back with the new
  one. `session_memory_for_product` reads exactly `config["index_prefix"]` and
  `config["ttl_seconds"]`.
* Creates one assistant pipeline per strategy — `vector`, `lexical`, `hybrid`, `self_rag`,
  `corrective` — named `<Product> · <Label>` with slug `<product-slug>-<strategy>`, copying the chat
  and embedding models of a pipeline already over that product.
* Re-runnable: an existing slug or name is `PATCH`ed, not duplicated. It deletes nothing.
* A strategy the product cannot serve is reported as `SKIP <strategy>: <reason>` and the rest are
  created. `lexical` needs OpenSearch and `hybrid` needs both stores.

Run it with `uv run python scripts/seed_resume_strategy_pipelines.py` against the live stack.

---

## 8. Key Files

* **Dataset schema**: `backend/libs/eval-core/src/eval_core/dataset_schema.py` — payload models,
  `_COLUMN_ALIASES`, `_normalize_item`, `parse_golden_dataset_csv`, `parse_golden_dataset_json`,
  `parse_golden_dataset_jsonl`.
* **Evaluation core**: `runner.py` (`GoldenItemEvaluator`, `_run_conversation`, `_score`),
  `source_match.py`, `retrieval_metrics.py`, `rerank_metrics.py`, `ragas_client.py`
  (`JUDGE_MAX_TOKENS`), `custom_metrics.py`, `attribution.py`.
* **Worker**: `apps/eval-worker/src/eval_worker/tasks.py` → `run_evaluation`.
* **Database**: `models/evaluation.py`, `repositories/evaluation_repository.py`,
  `alembic/versions/006_golden_dataset_kind_and_turns.py`.
* **API**: `apps/rag-api/src/rag_api/routes/evaluate.py`.
* **Frontend**: `frontend/src/api.ts`, `frontend/src/pages/GoldenEvaluationsPage.tsx`,
  `frontend/src/pages/EvalRunDetailPage.tsx`, `frontend/src/components/TriadPanel.tsx`.
* **Datasets**: `resumes/resume_single_turn_golden.csv`, `resumes/resume_multi_turn_golden.csv`.
* **Tests**: `tests/unit/test_golden_dataset_universal_schema.py`,
  `tests/unit/test_custom_metrics.py`, `tests/unit/test_ragas_judge_budget.py`.
