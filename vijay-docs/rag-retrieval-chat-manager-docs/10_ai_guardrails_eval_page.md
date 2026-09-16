# AI Guardrails Evaluation Page

## Route
`/guardrails/evaluation`

## Component
`GuardrailsEvaluationPage.tsx`

## Features

Batch evaluation of guardrail configurations against test datasets.

- **Guard Eval Runs**: Test a guardrail config against a dataset of adversarial or edge-case inputs.
- **Pass/Block Rate**: Aggregate stats on how often each guard triggered across the test set.
- **Per-Row Detail**: View individual input/output pairs and guard decisions.

## Backend APIs Used

- `POST /guardrails/evaluate`
- `GET /guardrails/evaluate/runs`
- `GET /guardrails/evaluate/runs/{run_id}`
