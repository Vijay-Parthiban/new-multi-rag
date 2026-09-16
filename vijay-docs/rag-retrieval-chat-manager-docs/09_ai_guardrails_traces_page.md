# AI Guardrails Traces Page

## Route
`/guardrails/traces`

## Component
`GuardrailsTracesPage.tsx`

## Features

Audit log of every guardrail evaluation event triggered during chat sessions.

- **Trace List**: All guardrail invocation traces with timestamp, guard name, phase, input snippet, verdict (pass/block), and score.
- **Filter by Guard**: Narrow traces by specific guard type or verdict.

## Backend APIs Used

- `GET /guardrails/traces`
- `GET /guardrails/traces/{trace_id}`
