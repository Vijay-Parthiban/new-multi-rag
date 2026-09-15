# AI Guardrails Traces Page

## Route
`/guardrails/traces`

## Features
Visualizes historical trace interventions where guardrails mutated or blocked traffic entirely. Allows security and ops to investigate "Why was this RAG response denied/redacted?".

## Backend APIs Used
- `GET /api/traces` (Filtered to Guardrail components)
- `GET /api/stats` (Guardrails blocks vs passes)