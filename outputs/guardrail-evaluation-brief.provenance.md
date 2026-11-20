# Provenance — guardrail-evaluation-brief.md

Produced 2026-11-20. Every claim in the brief traces to one row below.

## How the evidence was gathered

| Step | Action | Used for |
|---|---|---|
| Read the runner | `read` on `guardrails_runner.py` | row scoring, skip rule, aggregate |
| Read the schema | `read` on `guardrails_dataset_schema.py` | dataset fields |
| Read the route | `read` on `guardrails_evaluate.py:254-360` | synchronous loop |
| Read the model | `grep`/`read` on `rag_db/models/guardrails.py` | run columns |
| Read the page | `grep` on `GuardrailsEvaluationPage.tsx` | cards and tables |
| Confirm unused latency | `sed 116-200 | grep -c '"ms"'` → 0 | no `ms` in the aggregate |
| Web | fetched FalseReject abstract, NeMo overview, Promptfoo red-team guide, OWASP LLM Top 10 | [W1]-[W4] |

## Claim → evidence

| Claim | Evidence | Type |
|---|---|---|
| Dataset fields are text, phase, expected_blocked, expected_guard, category, metadata | `guardrails_dataset_schema.py:8-20` | code |
| A row is skipped when the config mode excludes its phase | `guardrails_runner.py:37-42`, `44-70` | code |
| A row scores `correct_block` as `expected_blocked == actual_blocked` | `guardrails_runner.py:90-100` | code |
| `correct_guard` is set only when both guards are present | `guardrails_runner.py:101-103` | code |
| A service error becomes `error_message` on the row | `guardrails_runner.py:105-112` | code |
| Aggregate emits accuracy, precision, recall, F1, guard_match_rate, TP/TN/FP/FN | `guardrails_runner.py:116-190` | code |
| Per-category bucket carries accuracy only | `guardrails_runner.py:180-195` | code |
| The run loops over rows inside the API request | `guardrails_evaluate.py:254-360` | code |
| The run stores a config snapshot and aggregate | `models/guardrails.py:74-86` | code |
| The page shows accuracy hero, P/R/F1 bars, per-category accuracy, per-row verdicts | `GuardrailsEvaluationPage.tsx:617, 643-645, 683, 720` | code |
| Each rail reports `ms` in its result | `guardrails-service/server.py` `/validate` docstring; client passes `results` through | code |
| The aggregate ignores `ms` | `sed 116-200 | grep -c '"ms"'` = 0 | command |
| Repair (`on_fail: fix`) returns masked chunks/text | `chat.py:560-590` (retrieval filter), `737-760` (output) | code |
| The evaluation does not check masked content | `guardrails_runner.py` records only `actual_blocked`/`actual_guard` | code |
| No generator for adversarial variants | repo search: no mutation helpers on the guardrails path | command |
| Over-refusal is a known failure mode of safety alignment | FalseReject abstract [W1] | web |
| Rails run at configured points; RAG filters content and checks answers | NeMo overview [W2] | web |
| Red teaming generates, runs, quantifies; recommended in CI | Promptfoo guide [W3] | web |
| Indirect injection and RAG-context PII are application-layer threats | Promptfoo guide, "Model vs application layer threats" [W3] | web |
| Prompt injection and sensitive information disclosure are the first two OWASP LLM risks | OWASP LLM Top 10 2025 [W4] | web |

## Not verified

- No run of the Guard Evaluation page was executed in this session; the page description comes
  from its source, not from a rendered screenshot.
- The synchronous route's timeout risk is inferred from the loop in the request handler; no
  large-set run was timed.
- The claim that a masking failure scores as a pass follows from the runner storing only
  `actual_blocked`; it was not demonstrated with a live service call.
- Judge calibration has no data in this repository; the item in the brief is a recommendation.
- The MDPI paper "Evaluation of NeMo Guardrails as a Firewall for User–LLM Interaction" was found
  by search but blocked (HTTP 403); its numbers are not cited.
