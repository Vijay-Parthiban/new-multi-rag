# AI Guardrails Evaluation Page

## Route
`/guardrails/evaluation`

## Features
Specifically runs evaluations on the security and formatting checks implemented in the pipeline. It uploads test datasets mapping inputs specifically meant to break formatting or policies to see if the Guardrail correctly triggers.

## Backend APIs Used
- `POST /api/datasets/upload` (Guardrail route context)
- `GET /api/runs/{run_id}/items`