# 09. AI Guardrails Traces Page (`/guard-traces`)

## 1. Page Purpose & Summary

The **AI Guardrails Traces** (`/guard-traces`) page provides security auditing logs of all moderation decisions evaluated by the Guardrails Service (Port 8002).

---

## 2. Key UI Modules & Features

1. **Moderation Trace Log Table**: List of evaluated prompt and answer events displaying:
   - Event Timestamp & Request ID
   - Stage (`Input Prompt` vs `Output Generation`)
   - Outcome Badge (`PASSED`, `BLOCKED`, `REDACTED`)
   - Triggered Rule (`PII_DETECTED`, `PROMPT_INJECTION`, `TOXICITY`, `HALLUCINATION`)
   - Confidence Score (0.0 to 1.0).
2. **Inspection Modal**: View exact raw prompt text, detected PII entities, redacted output comparison, and policy decision metadata.
3. **Filter Bar**: Filter events by outcome status, policy category, or date range.

---

## 3. API Endpoint Reference

- **`listGuardrailsTraces(limit)`**: `GET /api/guardrails/traces?limit=100`
