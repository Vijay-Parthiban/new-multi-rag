# AI Guardrails Config Page

## Route
`/guardrails/config`

## Component
`GuardrailsConfigPage.tsx`

## Features

Configure which guardrail checks run on inputs and outputs of the RAG chat pipeline.

- **Available Guards**: Listed via `GET /guardrails/guards`. Each guard has a name, description, and phase (pre-retrieval input check or post-generation output check).
- **Config Creation**: `POST /guardrails/configs` saves a named configuration binding a set of active guards with their settings (thresholds, blocked response templates).
- **Config Management**: List, get, update, delete configurations.

## Backend APIs Used

- `GET /guardrails/guards`
- `POST /guardrails/configs`
- `GET /guardrails/configs`
- `GET /guardrails/configs/{config_id}`
- `PUT /guardrails/configs/{config_id}`
- `DELETE /guardrails/configs/{config_id}`
