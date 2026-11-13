# RAG evaluation standards, and what this project should score

Research date: 2026-11-13. Scope: the metric set a complete offline evaluation needs, and
what the current Offline Evaluation page computes today.

## 1. Verdict on the proposed taxonomy

The three-way split is sound: retrieval, generation, end-to-end. It matches the stage
attribution the page already applies, and it matches how RAGAS, TruLens and DeepEval group
their metrics [1, 2, 10].

Two corrections make it usable as a specification.

**Classify each metric by stage and by method.** The list mixes three kinds of metric: a
formula over ranked ids (hit, MRR, NDCG), a judge call (faithfulness, answer relevancy), and
an operational reading (latency, tokens). Each has a different cost, a different failure
mode, and a different "cannot score" case. A metric table without the method column hides
that.

**Some entries are not metrics of their own.** "Hallucination rate" is the complement of
groundedness or faithfulness under a threshold [7, 8]; "context relevancy" in the brief is
RAGAS's `context_precision` under another name [5]; "LLM-as-a-judge" is the method that
produces faithfulness, relevancy and correctness, not a metric beside them [1].

The RAG triad is worth keeping as the end-to-end block. It reads three *pairs* of the three
inputs, so each score names a stage: context relevance reads question + contexts,
groundedness reads answer + contexts, answer relevance reads question + answer [10].

## 2. The metric catalogue

### 2.1 Retrieval (formula, no judge)

| Metric | Definition | Needs |
|---|---|---|
| Hit@k | 1 when at least one relevant id is in the top k | expected source ids |
| Precision@k | relevant ids in the top k / k | expected source ids |
| Recall@k | expected ids found in the top k / expected ids | expected source ids |
| MRR | 1 / rank of the first relevant id | expected source ids |
| MAP | mean of precision at each relevant rank | expected source ids |
| NDCG@k | graded gain over the top k, divided by the ideal gain, with a log2 position discount | expected source ids |

MRR scores only the first relevant result. MAP and NDCG read the whole ranked list, and
NDCG penalises a relevant result that sits low [6]. Report k as a parameter: `hit@5`,
`recall@10`, and so on, because a retriever's score at 5 says nothing about its score at 20.

### 2.2 Context quality (judge or overlap)

| Metric | Question it answers | RAGAS name |
|---|---|---|
| Context precision | Of the retrieved chunks, how many are useful, weighted by rank | `context_precision` |
| Context recall | Which share of the reference answer's claims the context covers | `context_recall` |
| Context entities recall | Which share of the reference's entities appear in the context | `context_entities_recall` |
| Noise sensitivity | How often the answer becomes wrong because of irrelevant retrieved text | `noise_sensitivity` |

The RAGAS documentation lists all four in the retrieval family [5]. Context precision and
recall need a reference answer. Entities recall needs a reference with recognisable entities.
Noise sensitivity needs an answer and its contexts, and an injected-noise variant to compare.

### 2.3 Generation (judge, with a reference where one exists)

| Metric | Question it answers | RAGAS name |
|---|---|---|
| Faithfulness | Is every claim in the answer supported by the contexts | `faithfulness` |
| Response relevancy | Does the answer address the question | `response_relevancy` |
| Answer correctness | Does the answer agree with the reference | `answer_correctness` |
| Factual correctness | Precision and recall of factual claims against the reference | `factual_correctness` |
| Semantic similarity | Embedding distance to the reference | `semantic_similarity` |

Traditional overlap metrics are still useful as a cheap, deterministic second opinion: BLEU,
ROUGE and CHRF are listed as RAGAS's "traditional non-LLM metrics" [5]. They say nothing about
grounding, so they belong beside the judge, not in place of it.

### 2.4 End-to-end and system

| Metric | Reading |
|---|---|
| RAG triad | Context relevance, groundedness, answer relevance, one pair each [10] |
| Abstention correctness | Did the row that expects a refusal get one, and did a normal row avoid one |
| Keypoint coverage | Which listed keypoints the answer covers (the project already scores this) |
| Latency | p50 and p95 of retrieval, rerank, generation and total |
| Cost | Prompt and completion tokens, and the judge calls per run |

### 2.5 Judge hygiene

A judge score is only comparable across runs when the judge is fixed and its bias is known.
The literature documents position bias, verbosity preference, and self-preference [3, 4, 9].
Practice: record the judge model in the run config, keep it constant across a comparison,
decompose a rubric into discrete checks, and calibrate the judge against a labelled subset
before trusting a delta [3, 9]. The judge is not a measurement device until that check exists.

## 3. What the Offline Evaluation page does today

The page is `GoldenEvaluationsPage`. The flow is: pipeline → the profiles the Dataset
Validator linked to it → single-turn or multi-turn → sample N rows → a queued run.

Each row goes through `RAGPipeline.chat`, the live chat path, so the self-reflective and
corrective strategies are scored as they run. A multi-turn row replays its user turns with
the pipeline's Redis session memory, and the last turn is scored.

| Stage | Keys stored per row | Source |
|---|---|---|
| Retrieval | `precision`, `recall`, `hit`, `mrr` | formula, `k = 5` fixed |
| Reranker | `mrr_before`, `mrr_after`, `mrr_delta`, `mrr_before_at_k`, `kendall_tau`, `ndcg` | formula, `k = 5` |
| Generation | `faithfulness`, `accuracy` / `answer_correctness`, `context_relevance`, `response_groundedness`, `answer_relevancy` | RAGAS judge |
| Generation | `behavior_match`, `keypoint_coverage` | string check, no judge |
| Retrieval RAGAS | `context_precision`, `context_recall` | RAGAS judge, skipped without a reference |

The run aggregate is the mean of every numeric key per stage, plus a `categories` block that
groups the same means by the row's `question_type`. The page adds a stage diagnosis: the
weakest stage, and the rule that names the off-question case when relevance is low but the
answer is grounded.

### Gaps against the catalogue

| Gap | Effect today |
|---|---|
| `k_values` is accepted but ignored; every retrieval metric is at 5 | No `@k` curve, no reading at 10 or 20 |
| MAP is absent; NDCG exists only in the rerank block | The retrieval block under-reports ranking quality |
| Context entities recall and noise sensitivity are absent | Context quality reads only two of the four RAGAS retrieval metrics |
| No semantic similarity, factual correctness, or traditional overlap metric | Generation reads one similarity signal, from the judge only |
| No latency or token block | A run cannot be read as a cost/latency trade |
| No coverage report | A mean silently skips rows a metric could not score |
| No run comparison | A change cannot be read as a delta |
| No judge calibration | A judge delta between two models is unverified |

## 4. Recommended target set for this project

The manual and synthetic datasets already carry the inputs most metrics need: a question, a
ground-truth answer, expected source names, and for multi-turn rows the user turns and the
expected answer per turn. The recommended set uses those, and skips a metric with a reason
when a row lacks its input, rather than scoring zero.

**Retrieval, formula, both datasets:** `hit@k`, `precision@k`, `recall@k`, `mrr`, `map`,
`ndcg@k` for `k ∈ {1, 3, 5, 10}`, all on the retrieved list, and the same set on the reranked
list at the depth that reached the model.

**Context, judge:** `context_precision`, `context_recall`, `context_entities_recall`,
`noise_sensitivity` [5].

**Generation, judge:** `faithfulness`, `response_relevancy`, `answer_correctness`,
`factual_correctness`, `semantic_similarity` [5]; plus BLEU and ROUGE as deterministic
checks; plus the project's `behavior_match` and `keypoint_coverage`.

**End-to-end:** the triad [10], latency p50/p95, tokens, and a per-run cost estimate.

**Reporting:** every metric carries its sample count; a run records its judge model and a
digest of the dataset; two runs can be compared side by side.

## 5. Implementation plan (proposed)

Assumptions: no new framework beyond RAGAS, which is already installed; the metric names stay
backward-compatible where the page reads them; each phase ends with a check that proves it.

### Phase 0 — make the existing formulas honest (0.5 day)

1. `compute_retrieval_metrics` uses its `k_values` argument and emits `precision@1`,
   `precision@5`, `recall@5`, `hit@5`, `mrr`, `map`, `ndcg@5`. Keep the old bare names as
   aliases at k=5 so the page and old runs still read. Verify: a unit test with k=1, 3, 10.
2. Add `map` and retrieval-side `ndcg@k`. Verify: a hand-computed ranked list test.
3. `compute_rerank_metrics` uses `k_values` and emits the same names for the reranked list.
   Verify: the existing rerank tests plus one k=10 case.

### Phase 1 — complete the context block (1 day)

The installed `ragas` 0.4.3 exposes `ContextEntityRecall`, `NoiseSensitivity`,
`SemanticSimilarity`, `FactualCorrectness`, `BleuScore`, `RougeScore` and `CHRFScore` in
`ragas.metrics.collections` (checked in the project venv on 2026-11-13). No new dependency is
needed for phases 1 and 2.

4. Add `context_entities_recall` and `noise_sensitivity` to the RAGAS retrieval call, gated
   the same way as precision and recall (needs a reference; skip with a reason otherwise).
5. Store a `skipped` reason per metric on the row, and count it in the aggregate. Verify: a
   row without a reference stores `skipped: {"context_precision": "no_reference"}` and the
   aggregate reports `scored: n / total`.

### Phase 2 — complete the generation block (1 day)

6. Add `semantic_similarity` and `factual_correctness` to the RAGAS generation call.
7. Add BLEU and ROUGE against the reference as non-judge metrics (deterministic, near-zero
   cost). Verify: a fixed answer/reference pair returns fixed scores.
8. Keep `accuracy` as an alias of `answer_correctness` for old runs.

### Phase 3 — system metrics (1 day)

9. Time retrieval, rerank and generation inside the runner, and store `retrieval_ms`,
   `rerank_ms`, `generation_ms`, `total_ms`, `prompt_tokens`, `completion_tokens`.
   Verify: a single-row run stores all six and `total_ms` covers the parts.
10. The aggregate adds p50 and p95 alongside the means.

### Phase 4 — reporting (1–2 days)

11. The page shows each stage's metric table with its sample count and skipped reasons.
12. Run comparison: select a baseline run, show the delta per metric and per category.
13. A dataset coverage pre-check before a run: which metrics this dataset can score, from the
    rows' inputs. Verify: a dataset with no `ground_truth_answer` lists the judge metrics as
    unavailable before the run starts.

### Phase 5 — judge trust (optional, 0.5 day + a labelled set)

14. Record the judge model and dataset digest in the run config.
15. A small labelled subset with human scores; report judge agreement. This is what makes a
   judge delta between two runs meaningful [9].

### Out of scope for this plan

- Human evaluation UI. The plan keeps a labelled-subset check, not a review queue.
- Synthetic test-set generation. The Synthetic Datasets page already generates rows with
  evolutions; the plan consumes datasets, it does not create them.
- Reranking a second model or an A/B harness.

## Sources

1. Ragas docs, "List of available metrics" — https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/
2. Redis, "Get better RAG responses with Ragas" — https://redis.io/blog/get-better-rag-responses-with-ragas/
3. FutureAGI, "LLM-as-Judge Best Practices 2026" — https://futureagi.com/blog/llm-as-judge-best-practices-2026/
4. Confident AI, "LLM-as-a-Judge Simply Explained" — https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method
5. Ragas docs, metric catalogue (retrieval, generation, traditional NLP) — https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/
6. FutureAGI, "MRR vs MAP vs NDCG: Retrieval Ranking Metrics in 2026" — https://futureagi.com/blog/what-is-mrr-map-ndcg-2026/
7. FutureAGI, "RAG Evaluation Metrics 2026: The Complete Guide" — https://futureagi.com/blog/rag-evaluation-metrics-2025/
8. Atlan, "RAG Evaluation: Metrics, Tools, and the Context Gap (2026)" — https://atlan.com/know/how-to-evaluate-rag-systems-explained/
9. Openlayer, "LLM-as-judge: a complete guide to evaluation best practices" — https://www.openlayer.com/blog/llm-as-judge-evaluation-guide
10. TruLens docs, "RAG Triad" — https://www.trulens.org/getting_started/core_concepts/rag_triad/
11. Ragas docs, "Synthetic Test Data generation" — https://docs.ragas.io/en/v0.1.21/concepts/testset_generation.html
