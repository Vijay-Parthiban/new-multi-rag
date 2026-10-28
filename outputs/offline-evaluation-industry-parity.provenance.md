# Provenance — `offline-evaluation-industry-parity.md`

Every claim in the brief is traced below to the artifact it came from and the method used to read it.
Methods: **read** (file opened and quoted), **grep** (pattern search), **execute** (code run against the
real parser or the installed package), **web** (external page fetched and quoted).

**Environment.** Repo `C:/Users/2782234/omp-projects/new-multi-rag`, branch working tree, accessed
2026-10-20. Python `rag-retrieval-chat-manager/backend/.venv`: `ragas 0.4.3`, `datasets 5.0.1`,
`pandas 3.0.6`. `deepeval` is **not installed**; its behaviour was read from published source.

## 1. Backend implementation claims

| Claim | Evidence | Method |
|---|---|---|
| A run is created at `evaluate.py:590`, refuses `image_vision` at `:605` | `apps/rag-api/src/rag_api/routes/evaluate.py` | read |
| Retrieval settings and session memory are resolved in `create_eval_run` | same file, body of `create_eval_run` | read |
| `GET /evaluate/pipeline-defaults` is at `:570` | same file | grep |
| The worker iterates items sequentially at `tasks.py:230` | `apps/eval-worker/src/eval_worker/tasks.py:193-337` | read |
| `run_evaluation` starts at `tasks.py:140` | same file | read |
| The evaluator goes through `pipeline.chat` (`runner.py:54`) | `libs/eval-core/src/eval_core/runner.py:54-74` | read |
| `_run_conversation` returns only the last turn's result (`:76`) | same file `:76-100` | read |
| `_score` at `:115`; `include_answer_relevancy=False` at `:149` | same file `:115-178` | read |
| Retrieval metrics are formula-only, `k = 5` at `retrieval_metrics.py:55` | `libs/eval-core/src/eval_core/retrieval_metrics.py` | read + execute |
| `k_values` is accepted and unused in both metric modules | `retrieval_metrics.py:50-61`, `rerank_metrics.py:65-88` | read |
| Reranker metrics: `mrr_before`, `mrr_after`, `mrr_delta`, `mrr_before_at_k`, `kendall_tau`, `ndcg` | `rerank_metrics.py:65-88` | read |
| Triad is `ContextRelevance`, `ResponseGroundedness`, `AnswerRelevancy` | `ragas_client.py:282-357`; `TRIAD_METRICS` at `:279` | read |
| Judge budget `JUDGE_MAX_TOKENS = 8192` | `ragas_client.py:26` | grep |
| `ContextPrecision` / `ContextRecall` are implemented at `ragas_client.py:134` | same file | read |
| The offline runner does **not** call them | grep over the backend: only `chat_metrics.py:68`, `ragas_client.py:393/426`, tests | grep |
| The live path calls them | `libs/eval-core/src/eval_core/chat_metrics.py:68` | grep |
| `SKIP_PRECISION_RECALL_CATEGORIES = {"out_of_corpus", "unanswerable"}` | `ragas_client.py:16` | read |
| `PASS_MARK = 0.7`, `RERANK_LOSS_MARGIN = 0.05` | `libs/eval-core/src/eval_core/attribution.py:27,31` | read |
| Aggregation is a plain mean per numeric key, per stage and per category | `evaluation_repository.py:267-341` | read |
| Category comes from `question_type`, then `category` | `evaluation_repository.py:345-352` | read |
| Run-level diagnosis is recomputed on read from stored row metrics | `apps/rag-api/src/rag_api/routes/evaluate.py:792` (`_run_diagnosis`) | read |
| Diagnosis fields: `triad`, `stage_counts`, `dominant_stage`, `dominant_label`, `summary`, `scored_items`, `unscored_items` | same function, return dict | read |
| The diagnosis waterfall and its four named stages | `libs/eval-core/src/eval_core/attribution.py:105-196` (`diagnose`) | read |
| Retrieval vs rerank split requires rerank ran, matched depth, and a 0.05 MRR loss | `attribution.py:70-104` (`_winner`), `:31` | read |
| The triad panel renders first for a selected run | `frontend/src/pages/GoldenEvaluationsPage.tsx:1246` | read |
| The run detail page holds per-question triad and retrieved passages | `frontend/src/pages/EvalRunDetailPage.tsx:185-320`; route in `components/AppLayout.tsx:211` | read |
| Overall KPIs use stage tabs and a chart over `mean_*` keys | `GoldenEvaluationsPage.tsx:1240-1290` (`OverallKpis`, `Metrics by Category`) | read |
| `EvalItemResult` has no latency field | `runner.py:44-50` | read |
| Worker reads `getattr(result, "latency_ms", None)` — always empty | `tasks.py`, run loop body | read |
| `eval_worker_concurrency` and `eval_default_k` are declared and never read | `libs/shared/src/rag_shared/config.py:87-88`; repo-wide grep returns only the definition | grep |
| `ragas_judge_model` default `llama-3.3-70b-versatile`, `ragas_enabled` default True | `config.py:83-84` | grep |

## 2. RAGAS 0.4.3 claims

All from the installed package in the repo venv, not from documentation.

| Claim | Evidence | Method |
|---|---|---|
| `ragas.testset.generator` does not exist in 0.4.3 | `ModuleNotFoundError` on import | execute |
| `ragas.testset.TestsetGenerator` exists | `dir(ragas.testset)` | execute |
| `TestsetSample` = `eval_sample` + `synthesizer_name` | `inspect` of `TestsetSample.model_fields`; `to_list()` source | execute |
| `Testset.to_list()` = `model_dump(exclude_none=True)` + `synthesizer_name` | `Testset.to_list` source read via `inspect.getsource` | execute |
| `SingleTurnSample` field list | `model_fields` | execute |
| `MultiTurnSample.user_input` is `list[HumanMessage | AIMessage | ToolMessage]` | `model_fields` annotation | execute |
| Message objects carry `type` (`human`/`ai`/`tool`), not `role` | `HumanMessage` / `AIMessage` / `ToolMessage` `model_fields` | execute |
| Synthesizers set `reference` and `reference_contexts` only | `testset/synthesizers/single_hop/base.py:134`, `multi_hop/base.py:173` | read |
| No `reference_context_ids` anywhere in `ragas/testset` | file scan of the package directory | execute |
| `collections` API exposes 39 metrics including `ContextPrecision`, `ContextRecall`, `NoiseSensitivity` | `dir(ragas.metrics.collections)` | execute |
| `EvaluationDataset.to_jsonl` / `from_jsonl` are the list-preserving path | `inspect.getsource` | execute |

## 3. DeepEval claims

`deepeval` is not installed; read from the published repository and docs, indexed and searched.

| Claim | Source | Method |
|---|---|---|
| `Golden` fields (`input`, `expected_output`, `context`, `retrieval_context`, `additional_metadata`, `source_file`, …) | `deepeval/dataset/golden.py`, `class Golden` | web (indexed source) |
| `ConversationalGolden` fields (`scenario`, `expected_outcome`, `turns`, `additional_metadata`, …) and **no `input`** | same file, `class ConversationalGolden` | web (indexed source) |
| The `Synthesizer` sets `source_file` from `context_source_files[0]` | `deepeval/synthesizer/synthesizer.py`, `Golden(...)` construction | web (indexed source) |
| A dataset holds single-turn or multi-turn goldens, never both | https://deepeval.com/docs/evaluation-datasets | web |
| CSV joins lists on `|`; `turns` / `additionalMetadata` cells are JSON | https://deepeval.com/docs/evaluation-datasets | web |
| A row with `scenario` becomes a `ConversationalGolden` | https://deepeval.com/docs/evaluation-datasets (JSON/CSV load sections) | web |
| `save_as(file_type=...)` supports `csv`, `json`, `jsonl` | https://deepeval.com/docs/evaluation-datasets | web |
| `generate_goldens_from_docs` → `Golden`; `generate_conversational_goldens_from_docs` → `ConversationalGolden` | https://deepeval.com/docs/synthesizer-generate-from-docs | web |
| `ConversationSimulator` generates turns for conversational test cases | https://deepeval.com/docs/evaluation-datasets | web |
| DeepEval RAG metrics carry `threshold` / `success` | https://deepeval.com/docs/metrics-ragas | web |

## 4. Industry-practice claims

| Claim | Source |
|---|---|
| RAG metric set (context precision/recall, noise sensitivity, faithfulness, response relevancy) | https://docs.ragas.io/en/v0.4.0/references/metrics · https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/ |
| Faithfulness = supported claims / total claims | https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/ |
| RAG triad = context relevance, groundedness, answer relevance | https://www.trulens.org/getting_started/core_concepts/rag_triad/ |
| Retrieval conventions: Recall@k (1/3/5/10/20), MRR, nDCG, MAP | https://arxiv.org/html/2405.07437v2 · https://arxiv.org/pdf/2604.01733 |
| nDCG/MRR/AP may mispredict RAG performance; UDCG proposed | https://aclanthology.org/2026.eacl-long.391/ |
| Multi-turn benchmark: 110 conversations, 7.7 turns average | https://arxiv.org/html/2501.03468 |
| Later-turn degradation: ELSER R@5 0.89 → 0.47 | https://aclanthology.org/2026.semeval-1.447 |
| Turn-level evaluation of answerable/partially/unanswerable turns | https://aclanthology.org/2026.semeval-1.447 |
| LLM-judge reporting needs calibration and confidence intervals | https://arxiv.org/html/2511.21140v1 |
| ARES uses prediction-powered inference with ~150–300 human annotations | https://aclanthology.org/2024.naacl-long.20.pdf |

## 5. Executed checks

Command script run in `rag-retrieval-chat-manager/backend` with the repo venv:

1. Introspect `ragas` version, `dataset_schema` field lists, `testset` layout — 0.4.3 confirmed,
   `ragas.testset.generator` absent.
2. Introspect `TestsetGenerator.generate` / `generate_with_langchain_docs` / `generate_with_chunks`
   signatures — `testset_size`, `query_distribution`, `transforms`.
3. Scan `ragas/testset` for `reference_context_ids` — zero hits.
4. Feed seven dataset shapes to `parse_golden_dataset_jsonl` / `parse_golden_dataset_csv`:
   RAGAS single-turn, RAGAS multi-turn, RAGAS CSV, DeepEval `Golden`, DeepEval conversational with
   turns, DeepEval scenario-only, DeepEval CSV. Results recorded in §5.3 of the brief.
5. Feed real DeepEval field names (`additional_metadata`, `source_file`) and RAGAS's
   `synthesizer_name` — all three dropped from the parsed payload.
6. Collect exact line anchors for every path cited in §2–§3 of the brief.

## 6. Not verified

- **No end-to-end run.** The API, RQ worker, LiteLLM proxy, and Qdrant were not started. All runtime
  behaviour in the brief is read from the executed code path.
- **No judge measurement.** Judge latency, token cost, and inter-run stability were not measured.
- **RAGAS multi-turn metric semantics** were read from `MultiTurnSample` and the docs, not executed.
- **DeepEval** was never executed; its loader behaviour is stated from source and docs, and the
  compatibility results in §5.3 come from feeding DeepEval-shaped rows to *our* parser, not from
  running DeepEval.
- **RAGAS CSV mangling** was reproduced against our parser on a hand-written `to_csv`-shaped row, not
  on a file produced by `EvaluationDataset.to_csv` in this session.
