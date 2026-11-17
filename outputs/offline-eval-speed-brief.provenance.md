# Provenance — offline-eval-speed-brief.md

Produced 2026-11-17. Every claim in the brief traces to one row below.

## How the evidence was gathered

| Step | Command or action | Result used |
|---|---|---|
| Read the eval path | `read`/`grep` on `transport.py`, `evaluate.py`, `tasks.py`, `runner.py`, `ragas_client.py`, `evaluation_repository.py`, `GoldenEvaluationsPage.tsx` | file:line anchors [R1]–[R3], [R7]–[R8] |
| Independent audit | `task` → `scout` agent `AuditEvalPath` | confirm/contradict items 1–11 [R6] |
| Measured a real run | created run `cf749579…` with `sample_size: 3`, judge `cc-deepseek-v4-flash`, rerank off; polled progress; read `aggregate_metrics` and `evaluation_run_items` | [M1] |
| Measured one embedding | `EmbeddingClient.embed_text("What is Tharun's education?")` with `nvidia-embed-textonly`, then Qdrant `query_points` | [M2] |
| Reranker probes | `POST /v1/rerank` for `nvidia-rerank`, `bge-reranker-v2-m3`, `bge-reranker-v2-gemma` | [M3] |
| Models endpoint probe | `GET /api/knowledge-products/config/litellm-models?model_kind=chat`; `GET :4000/v1/models` | [M4] |
| Test suite | `uv run pytest tests/unit -q` | [M5] |
| Installed ragas source | read `ragas/metrics/collections/noise_sensitivity/metric.py` and `context_precision/metric.py` in the venv | [R4], [R5] |
| Web docs | fetched the LiteLLM caching page and the ragas RunConfig page with `read`; ragas metrics list fetched | [W2]–[W4] |
| Cached settings | `grep cache tharun.yaml` | [R9] |

## Claim → evidence

| Claim in the brief | Evidence | Check type |
|---|---|---|
| Rows are scored one at a time | `tasks.py:234` | audit [R6] |
| The sample is drawn before the row loop; progress caps at `sample_size` | `tasks.py:226`; `evaluation_repository.py:240-250` | audit |
| One `asyncio.run` per row holds all judge calls | `ragas_client.py:508-535, 544` | audit |
| `NoiseSensitivity` is not called on the eval path | only a docstring mention at `ragas_client.py:196` | audit |
| Precision verdicts are concurrent, combined by `_average_precision` | `ragas_client.py:171-172, 144-150` | audit |
| Judge client uses `timeout=180`, `max_retries=1` | `ragas_client.py:68-69` | audit |
| MAP divides by `max(len(sources), hits)` | `retrieval_metrics.py:69` | audit |
| Aggregate carries means, coverage, p50/p95, skipped | `evaluation_repository.py:340-430` | audit |
| The page renders the row count and the Not scored line | `GoldenEvaluationsPage.tsx:280, 305-307, 335` | audit (format is `key · N rows`, not `key (n)`) |
| The run stores and uses `judge_model` | `evaluate.py:76, 645`; `tasks.py:264` | audit |
| Latency is stored per row | `runner.py:236-256` | audit |
| The retrieval judge ignored the run's judge | `ragas_client.py:218` before `5b4fdd5` | audit; fixed and unit-tested |
| The trace's latency was always empty | `tasks.py:296` vs `EvalItemResult` before `5b4fdd5` | audit; fixed |
| 3-row run = 2019 s; rows 7.3/9.4/16.6 min | `evaluation_runs.completed_at − started_at`; item `created_at` gaps | [M1] |
| retrieve/generate/total ms values | `aggregate_metrics.retrieval/generation` | [M1] |
| 117 s for one embedding | timed `EmbeddingClient.embed_text` call | [M2] |
| `nvidia-rerank` returns 410 | `/v1/rerank` response body | [M3] |
| The `bge` rerankers cannot reach HF | `/v1/rerank` 500 body: DNS failure | [M3] |
| The model list falls back to one model | response `source: fallback` + `/v1/models` timeout | [M4] |
| A stalled call waited 600 s | worker log gap 11:34:02 → 11:39:53 in run `48ec1802` | log + [W2] for SDK default |
| Truncated judge output at 8192 | worker log: `RAGAS faithfulness failed: The output is incomplete due to a max_tokens length limit` | log |
| The proxy cache is disabled | `tharun.yaml:272` `#  cache_responses: true` | [R9] |
| LiteLLM caches chat, embeddings and rerank | LiteLLM caching page, "with `cache: True` … caching is on for `/chat/completions` … `/embeddings` … `/rerank`" | [W2] |
| Redis is the default cache backend | same page, "LiteLLM defaults to using a redis cache" | [W2] |
| ragas `evaluate()` parallelises with `max_workers` (default 16) | RunConfig page | [W3] |
| Metrics named by ragas as separate entries | metrics list page | [W4] |
| Judge design choices move cost by orders of magnitude | paper abstract and title | [W5] |
| Small judge samples are a weak basis | paper on judge bias | [W1] |

## Not verified

- The expected gains in 4.2 (parallel rows) are arithmetic from the measured row durations, not
  a measured run. The proxy's behaviour at 3 concurrent rows is unmeasured.
- The expected gain in 4.1 (cache) is from the documentation; no cache has been enabled in this
  environment.
- 4.3 assumes `context_entity_recall` and `factual_correctness` are redundant for this product's
  diagnosis; that is a product judgement, not a measurement.
- The reranker's effect on retrieval scores is unmeasured because no reranker works today.
- The 305/5 test result is from this machine; the five failures are the known `test_stats.py`
  fixtures, unchanged across the session.

## Audit source

Agent `AuditEvalPath` (scout, read-only), 2026-11-17, 1m10s. Full result quoted in the session
transcript. Its line numbers refer to the tree at commit `7d1d926`; the two fixes after that
commit (`5b4fdd5`) changed `ragas_client.py` and `runner.py` only.
