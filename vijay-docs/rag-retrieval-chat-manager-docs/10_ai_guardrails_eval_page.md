# 10 — AI Guardrails Evaluation Suite Page

## 1. Executive Summary & Page Purpose
The **AI Guardrails Evaluation Suite Page** (`GuardrailsEvaluationPage.tsx`, route: `/guardrails/eval`) provides an automated red-teaming and security benchmark framework. It runs batches of adversarial prompts (jailbreaks, prompt injections, toxic inputs, sensitive PII extraction attempts) against guardrail policies to quantify defense efficacy, false-positive rates, and false-negative rates.

---

## 2. Benchmark Categories & Efficacy Metrics

```
+-----------------------------------------------------------------------------------------------+
|                             GUARDRAIL RED-TEAM BENCHMARK SUITE                                |
+-----------------------------------+-----------------------------------------------------------+
| Category                          | Attack Vector & Target Invariant                          |
+-----------------------------------+-----------------------------------------------------------+
| 1. Adversarial Jailbreaks         | DAN, roleplay, hypothetical scenarios attempting system   |
|                                   | prompt leaks or policy bypasses.                          |
| 2. PII / SPI Extraction           | Queries engineered to trick the LLM into leaking SSNs,    |
|                                   | credit card numbers, or internal email addresses.         |
| 3. Toxic & Harmful Content        | Hate speech, abusive language, and harassment injection.  |
| 4. Banned Keyword Obfuscation     | Leetspeak, base64 encoding, or delimiter-separated        |
|                                   | forbidden tokens.                                         |
+-----------------------------------+-----------------------------------------------------------+
```

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  AI Guardrails Evaluation Suite                                                               |
|  Execute red-team security suites and evaluate policy defenses.                               |
|  [ + Upload Test Suite ]  [ 🚀 Run Guardrails Benchmark ]                                     |
+-----------------------------------------------------------------------------------------------+
|  Evaluation Benchmark Summary (Policy: Enterprise Production Guardrails)                      |
|  Overall Defense Efficacy: 98.4% | False Positive Rate: 1.2% | Avg Intercept Latency: 29ms    |
|                                                                                               |
|  Category Defense Scorecard:                                                                  |
|  - Prompt Injection Defense:       ██████████████████████░  98.0% (49/50 blocked)             |
|  - PII / SPI Extraction Defense:   ███████████████████████  100.0% (50/50 blocked)            |
|  - Toxic Language Interception:    █████████████████████░░  96.0% (48/50 blocked)             |
|  - Banned Keyword Accuracy:        ███████████████████████  100.0% (50/50 blocked)            |
+-----------------------------------------------------------------------------------------------+
|  Detailed Item Failure Inspector (False Negatives / False Positives):                         |
|  Item #12: "Hypothetical historical analysis of DB deletion" -> Status: PASSED (False Negative) |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/eval/datasets` | Lists red-team security test suites | `list[GuardrailEvalDataset]` |
| `POST` | `/guardrails/eval/runs` | Triggers a guardrail evaluation run | `CreateGuardrailEvalRunRequest` |
| `GET` | `/guardrails/eval/runs/{id}` | Retrieves benchmark scores & category metrics | `GuardrailEvalRunResponse` |

### Sample Benchmark Result (`GET /guardrails/eval/runs/{id}`)
```json
{
  "run_id": "89f1c0d5-5727-4632-9cb9-009c91d4e0e4",
  "policy_name": "Enterprise Production Guardrails",
  "total_test_cases": 200,
  "blocked_count": 196,
  "defense_efficacy": 0.98,
  "false_positive_rate": 0.012,
  "category_scores": {
    "prompt_injection": 0.98,
    "pii_leakage": 1.0,
    "toxic_language": 0.96,
    "ban_list": 1.0
  }
}
```
