# AI Guardrails Config Page

## Route
`/guardrails/config`

## Features
Settings interface mapping directly to the dedicated validation layer (`guardrails-service`). Allows users to define custom PII masks, toxicity thresholds, response formats, and prompt injection protections.

## Backend APIs Used
- `POST /api/configs`
- `GET /api/guards`