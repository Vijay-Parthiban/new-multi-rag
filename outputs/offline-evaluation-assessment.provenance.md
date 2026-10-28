# Provenance — Offline Evaluation assessment

**Brief:** `outputs/offline-evaluation-assessment.md`
**Date:** 2026-10-16
**Repo:** `C:/Users/2782234/omp-projects/new-multi-rag`, branch `added-nemo-initialdone-Oct13`

## Method

| Phase | What ran | Result |
|---|---|---|
| Recon | `glob` over pages, routes, worker, eval-core, docs; `wc -l`; route grep | module sizes and the file set fixed before slicing |
| Research | 5 read-only `scout` slices in one batch (run lifecycle, metrics per stage, UI, dataset schema, docs) + 1 web pass with 4 query angles | 5 reports, each with `path:line` citations |
| Verify | the author read `attribution.py` (full), `dataset_schema.py` (full), `retrieval_metrics.py`, `rerank_metrics.py`, `generation_metrics.py`, `runner.py` (full), `ragas_client.py:1-30` and its metric index, `custom_metrics.py:55-139`, `tasks.py:100-326`, `evaluate.py:194-335` and `:604-760`, plus a grep over `evaluation_repository.py` | every load-bearing claim re-read at the source, not accepted from a slice |
| Review | two `reviewer` passes over the draft, one on the code citations and one on the docs and the UI | 9 findings, all applied. Verdict: every substantive claim reproduced in the code; 7 citation line numbers were off by 1 to 3 lines, and 2 sentences overstated their evidence |

## Claim → source

| Claim in the brief | Source | Method |
|---|---|---|
| Run path, queue name, worker entry, row write, run close | `evaluate.py:565-600`, `config.py:36`, `tasks.py:140-318`, `runner.py:56` | slice A + author read of `tasks.py` |
| Row failure continues, run failure aborts | `tasks.py:311-326` | author read |
| Sampling happens before the progress count | `tasks.py:209-212`, `tasks.py:127-136` | author read |
| Five metric blocks and their call sites | `runner.py:80, 88, 103, 119, 132` | author read (full file) |
| k = 5 hard-coded, `k_values` unused | `retrieval_metrics.py:55`, `rerank_metrics.py:71` | author read |
| Skip rule for the RAGAS retrieval metrics | `ragas_client.py:16, 108-111` | author read |
| `accuracy` and `answer_correctness` share one value | `ragas_client.py:255-256` | slice B + a grep of the metric index |
| Diagnostic rules and thresholds | `attribution.py:27, 31, 107-197` | author read (full file) |
| Partial triad is never healthy | `attribution.py:170-185` | author read |
| Equal-depth MRR rule | `rerank_metrics.py:78-85`, `evaluate.py:649-658` | author read of both |
| Diagnosis computed at read time | `evaluate.py:719-734` | author read |
| Run and run-item fields | `models/evaluation.py:40-50, 56-72` | slice A |
| Aggregate `mean_*` keys and the `categories` block | `evaluation_repository.py:265-341` | author grep |
| Duplicate dataset name raises | `evaluation_repository.py:152-154` | author grep |
| No per-stage latency | `tasks.py:276-279`, `runner.py:36-42` | author read |
| UI routing by string compare | `AppLayout.tsx:112-128` | slice C |
| Per-row stage-separated numbers | `EvalRunDetailPage.tsx:333-341` | slice C |
| Missing drill-downs (prompt, raw response, chunk index) | `EvalRunDetailPage.tsx`, no grep match | slice C |
| Three create controls, read-only pipeline summary, unrendered explanation | `GoldenEvaluationsPage.tsx:970-1042, 985-992, 1010-1012` | slice C |
| No schema hint in the UI | `GoldenEvaluationsPage.tsx:888-892, 922-924` | slice C |
| JSON and CSV schema, validators, messages | `dataset_schema.py` | author read (full file) |
| Aliases apply on the upload path only | `dataset_schema.py:66-99`, `evaluate.py:194-196` | slice D + author read of both |
| Upload extensions, empty-file rule, error wrapping | `evaluate.py:219-239` | author read |
| Hugging Face mapping and the corpus trap | `evaluate.py:254-330` | author read |
| Doc-page names and their dates | `vijay-docs/rag-retrieval-chat-manager-docs/06…:3`, `10…:3`, `12…:3`, `13…:3` | docs slice, spot-checked by the review pass |
| Doc-stated limits (progress denominator, shared queue, `k_values`, no self-corrective loop) | `06…:436-437`, `12…:256`, `13…:159` | docs slice, spot-checked by the review pass |
| Doc defect: aliases claimed on `POST /datasets` | `13_golden_dataset_requirements.md` section 1 vs `dataset_schema.py:66-99` | slice D |
| Single-stage metrics cannot detect cross-stage failures | [ACL 2026 taxonomy](https://aclanthology.org/2026.trustnlp-main.27.pdf) | web pass |
| Post-hoc traces mislabel the earliest fault | [arXiv 2608.20627](https://arxiv.org/abs/2608.20627) | web pass |
| RAGAS dataset field names used for comparison | [RAGAS schema](https://docs.ragas.io/en/latest/references/evaluation_schema), [RAGAS test dataset](https://docs.ragas.io/en/v0.1.21/getstarted/prepare_data.html) | web pass |

## Unknowns recorded during research

1. **`route` in `generation_metrics`.** `tasks.py:284` reads `(result.generation_metrics or {}).get("route", "normal")`. No producer was found in eval-core or the worker, so the value is likely always `"normal"`. Unconfirmed.
2. **`EVAL_LABELS`** (`ragas_client.py:15`) has no reader found in the backend. Possibly dead.
3. **A skipped metric versus a failed metric.** The aggregate means over the keys that are present, so both look the same in the mean. The UI prints "not scored" for an absent triad value (`TriadPanel.tsx:76-78`). Whether any surface tells the two apart was not confirmed.
4. **Exact chunk record keys.** The frontend types the chunk lists as `Record<string, any>` and reads only `file_name`, `source_id`, `page_index`, `rerank_score`, `content`, `text` (`api.ts:1186-1187`, `EvalRunDetailPage.tsx:126-130`).
5. **`retrieval_mode` when the form does not post it.** The route fills a default (`evaluate.py:577-583`); the full resolution block through `:600` was not read line by line.
6. **Doc line numbers** for pages 06, 10, 12 and 13 come from the documentation slice, not from the author's own read. The review pass spot-checked them.
7. **`chat_metrics.py` expected-source heuristic.** It invents expected sources from answer/chunk token overlap (`chat_metrics.py:86-101`). It serves the live-chat path, not the offline run. Its false-positive rate is unknown and no test pins it.
8. **Different corpora.** A run without `rag_strategy` and a collection reads the legacy scrape collection (`tasks.py:183-190`), which is a different corpus from any Knowledge Product.

## Review findings applied

Two independent read-only reviews checked the draft against the cited lines. Nine findings, all
applied to the brief.

| # | Finding | Fix |
|---|---|---|
| 1 | Section 3 cited `tasks.py:191` for the worker's `k_values` default. The default is on line 193 | citation corrected |
| 2 | Section 8 cited `dataset_schema.py:110` for the JSON-object error. The message is on line 109 | citation corrected |
| 3 | Section 4 cited `attribution.py:186-197` for the partial-triad guard. The guard is at 170-185, and 186-197 is the healthy return | citation corrected |
| 4 | Section 8 attributed the `_p<page>` split to `dataset_schema.py`. That split runs in `source_match.py`; `dataset_schema.py` only splits on `;` and `,` | citation corrected and split in two |
| 5 | Section 5 cited `tasks.py:277-279` for the no-timing comment. The comment starts on line 276 | citation corrected |
| 6 | Section 5 cited `runner.py:34-41` for `EvalItemResult`. The dataclass spans 36-42 | citation corrected |
| 7 | Section 7 cited `tasks.py:177-180` for the ignored run settings. The assignments are at 174-175 | citation corrected |
| 8 | Section 7 claimed a "two runs a day" throughput limit that doc 06:437 does not state | claim replaced with the documented queue-sharing and the measured backlog |
| 9 | Section 6 said "the only text is the file-type label and the empty-state sentence", which ignores the Hugging Face warning at `GoldenEvaluationsPage.tsx:912-918` | claim narrowed to "no schema hint" and the warning added |

## Verification limits

- The projects were not run. This assessment is a static reading of the code, the docs and the web sources.
- No test was executed. Existing tests were used only as evidence of intended behaviour (`tests/unit/test_attribution.py`, `tests/unit/test_run_diagnosis_summary.py`).
- The UI section describes the code path, not a rendered page.
