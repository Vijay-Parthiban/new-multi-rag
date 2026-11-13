# Provenance — RAG evaluation standards brief

Brief: `outputs/rag-evaluation-standards-2026.md`
Research date: 2026-11-13
Method: web search, then direct reads of the primary Ragas documentation page and the
TruLens triad page. Code claims come from reading the repository, not from the web.

## Claim table

| # | Claim in the brief | Source | Evidence | Confidence |
|---|---|---|---|---|
| 1 | Ragas lists context precision, context recall, context entities recall, noise sensitivity as retrieval metrics | 1 | The "Retrieval Augmented Generation" section of the available-metrics page names all four | High (primary docs) |
| 2 | Ragas lists response relevancy, faithfulness, answer accuracy, context relevance, response groundedness as generation metrics | 1 | Same page, "Retrieval Augmented Generation" and "Nvidia Metrics" sections | High |
| 3 | Ragas lists factual correctness, semantic similarity, aspect critic, and traditional BLEU/CHRF/ROUGE/string metrics | 1 | "Natural Language Comparison", "Traditional non LLM metrics", "General Purpose" sections | High |
| 4 | Context precision and recall need a reference answer; entities recall needs entities; noise sensitivity needs an injected-noise comparison | 1 | The per-metric pages linked from the catalogue | Medium — the catalogue states the requirement, the per-metric page was not read in full |
| 5 | MRR scores only the rank of the first relevant result; MAP and NDCG read the whole list; NDCG discounts low positions | 6 | Definition section of the ranking-metrics article | High |
| 6 | The RAG triad is context relevance, groundedness and answer relevance | 10 | The TruLens page states the three names | High (primary docs) |
| 7 | Each triad metric reads a different pair of the three inputs, which is what names a stage | 10 | The triad page's description of the three checks | Medium — the page says what each measures; the pairing is the standard reading |
| 8 | LLM judges show position bias and verbosity preference, and need calibration against a labelled set | 3, 9 | Both guides describe the biases and calibration as the remedy | High |
| 9 | A judge model should stay fixed across the runs a user compares | 3, 9 | Both guides recommend one judge for a comparison; neither states it as a hard rule | Medium |
| 10 | Hallucination rate is reported as the complement of groundedness or faithfulness under a threshold | 7, 8 | Both guides define hallucination through the groundedness score rather than a separate metric | Medium |
| 11 | The Ragas testset generator builds a knowledge graph and uses query synthesizers | 11 | The synthetic-test-data page's pipeline description | High (primary docs) |
| 12 | The retrieval metrics in this repo are fixed at k = 5 | Repo: `libs/eval-core/src/eval_core/retrieval_metrics.py` | `compute_retrieval_metrics` sets `k = 5` and ignores `k_values` | High (code read) |
| 13 | NDCG and Kendall tau are computed on the reranked list only | Repo: `libs/eval-core/src/eval_core/rerank_metrics.py` | `ndcg_at_k` and `kendall_tau_rank_correlation` are called from `compute_rerank_metrics` | High (code read) |
| 14 | Generation scoring uses faithfulness, answer correctness and the triad | Repo: `libs/eval-core/src/eval_core/ragas_client.py`, `runner.py` | `calculate_generation_ragas_async` and `compute_triad_metrics` calls | High (code read) |
| 15 | Retrieval precision and recall are also scored by Ragas, gated on a reference | Repo: `ragas_client.py` | `calculate_retrieval_ragas_async` skips when no contexts or reference | High (code read) |
| 16 | The run aggregate is a mean per numeric key, with a `categories` block by `question_type` | Repo: `libs/database/src/rag_db/repositories/evaluation_repository.py` | `aggregate_run_metrics` and `_category_by_item_id` | High (code read) |
| 17 | Each row runs through `RAGPipeline.chat`; a multi-turn row replays with Redis session memory | Repo: `libs/eval-core/src/eval_core/runner.py` | `evaluate_item`, `_run_conversation` | High (code read) |
| 18 | Dataset rows carry question, ground-truth answer, expected sources, turns and metadata | Repo: `libs/eval-core/src/eval_core/dataset_schema.py` | `GoldenDatasetItemPayload` fields | High (code read) |
| 19 | `ragas` 0.4.3 ships ContextEntityRecall, NoiseSensitivity, SemanticSimilarity, FactualCorrectness, BleuScore, RougeScore, CHRFScore in `ragas.metrics.collections` | Repo venv | Import of each class succeeded; `dir(ragas.metrics.collections)` lists them | High (runtime check) |

## Queries run

1. RAGAS available metrics context precision context recall noise sensitivity answer correctness 2025
2. RAG evaluation retrieval metrics hit rate MRR MAP NDCG best practices
3. DeepEval RAG metrics contextual precision relevancy hallucination G-Eval
4. LLM as judge evaluation best practices bias position calibration
5. TruLens RAG triad context relevance groundedness answer relevance
6. RAGAS testset generator synthetic evaluation dataset generation documentation

## Pages read in full

1. https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/ — metric names and
   their families (fetched and stripped of markup, not summarised by a search engine).
2. https://www.trulens.org/getting_started/core_concepts/rag_triad/ — the three triad names.

## Not verified

1. The exact scoring of `noise_sensitivity` in ragas 0.4. The brief treats it as "the rate at
   which injected noise flips the answer", which is the standard reading, not a code read.
3. Cost per run. The brief gives no number, because none of the sources publishes one for
   this stack.
4. Judge self-preference for the models this project uses. The literature documents the
   effect for GPT-class judges; the project's default judge was not tested.
5. Whether a run comparison view exists in a later build of the page. The brief describes the
   repository at commit `b4109c8` and the code read on 2026-11-13.
6. Human-evaluation protocol. The brief proposes a 0.5-day calibration subset; it does not
   define the labelling rubric.
