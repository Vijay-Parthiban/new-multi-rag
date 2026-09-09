# 10. AI Guardrails Benchmark Evaluation Page (`/guard-eval`)

## 1. Page Purpose & Summary

The **AI Guardrails Evaluation** (`/guard-eval`) page enables safety researchers to execute automated adversarial red-teaming benchmarks against configured guardrail policies to measure precision, recall, and false-positive rates.

---

## 2. Key UI Modules & Features

1. **Safety Benchmark Suite Selector**: Select test suites (e.g. `Adversarial Injection Benchmark v2`, `PII Masking Suite`, `Hallucination Challenge Set`).
2. **Evaluation Execution Trigger**: Start batch safety evaluation runs across test datasets.
3. **Safety Accuracy Dashboard**: Visual metrics showing Precision (true blocks vs false blocks), Recall (caught attacks vs missed attacks), and F1 Safety Score.
4. **Adversarial Failure Case Breakdown**: List of prompt attacks that successfully bypassed moderation rules for policy tuning.

---

## 3. API Endpoint Reference

- **`triggerGuardrailsEvaluation(payload)`**: `POST /api/guardrails/evaluate`
- **`getGuardrailsEvalResults(runId)`**: `GET /api/guardrails/evaluate/{runId}`
