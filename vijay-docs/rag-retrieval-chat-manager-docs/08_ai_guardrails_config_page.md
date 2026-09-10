# 08. AI Guardrails Policy Config Page (`/guardrails-config`)

## 1. Page Purpose & Summary

The **AI Guardrails Policy Config** (`/guardrails-config`) page manages safety policies, toxicity filters, PII redaction, topic restrictions, and hallucination checks enforced by the Guardrails Service (Port 8002).

---

## 2. Configurable Safety Policies

1. **Input Moderation**:
   - **Toxicity Filter**: Blocks profanity, hate speech, or harassment prompts.
   - **PII Detection**: Detects and redacts SSNs, credit card numbers, email addresses, and phone numbers.
   - **Prompt Injection Defense**: Identifies adversarial attempts to bypass system prompt instructions.
2. **Output Moderation**:
   - **Hallucination Detection**: Verifies LLM output claims against retrieved context documents.
   - **Topic Enforcement**: Ensures responses stay restricted to allowed domain topics.
   - **Profanity & Sensitivity Filter**: Masks forbidden output terms.

---

## 3. Key UI Modules & Features

1. **Policy Enforcement Switches**: Toggle individual safety guardrails on or off.
2. **Sensitivity Threshold Sliders**: Adjust confidence thresholds (e.g. `0.85` toxicity cutoff).
3. **Redaction Action Selectors**: Choose action on violation (`Block Request`, `Redact Sensitive Text`, `Warn & Log`).

---

## 4. API Endpoint Reference

- **`getGuardrailsConfig()`**: `GET /api/guardrails/config` — Retrieves active guardrails configuration.
- **`updateGuardrailsConfig(body)`**: `POST /api/guardrails/config` — Updates safety rules and threshold settings.
