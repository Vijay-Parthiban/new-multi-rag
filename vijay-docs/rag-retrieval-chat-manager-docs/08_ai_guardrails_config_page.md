# 08 — AI Guardrails Policy Configuration Page

## 1. Executive Summary & Page Purpose
The **AI Guardrails Policy Configuration Page** (`GuardrailsConfigPage.tsx`, route: `/guardrails/config`) enables security administrators to define, update, and deploy safety and compliance policies. It supports **Banned Keyword Filters**, **Microsoft Presidio PII/SPI Masking & Redaction**, **Adversarial Prompt Injection & Jailbreak Defense**, **Toxicity Filtering**, **Competitor Mention Blocking**, and **Hallucination Interception**.

---

## 2. Guardrails Architecture & Supported Guards

```
+-----------------------------------------------------------------------------------------------+
|  User Input Prompt                                                                            |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  PHASE 1: INPUT GUARDRAILS EXECUTION                                                          |
|  +------------------------+  +------------------------+  +------------------------+           |
|  | 🚫 Banned Words Filter |  | 🔒 Presidio PII/SPI    |  | 🛡️ Prompt Injection   |           |
|  | - Custom token lists   |  | - Email, Phone, SSN,   |  | - Jailbreaks, system   |           |
|  | - Exact/Fuzzy match    |  |   Credit Card, IP, PAN |  |   prompt leak attempts |           |
|  +------------------------+  +------------------------+  +------------------------+           |
|                                                                                               |
|  Violation Detected? ---> [ YES ] ---> Intercept immediately; return BlockedCard to UI.       |
|                            [ NO  ] ---> Proceed to RAG Retrieval & Synthesis Pipeline.        |
+-----------------------------------------------+-----------------------------------------------+
                                                |
                                                v
+-----------------------------------------------------------------------------------------------+
|  PHASE 2: OUTPUT GUARDRAILS EXECUTION                                                         |
|  +------------------------+  +------------------------+  +------------------------+           |
|  | ⚠️ Toxic Language     |  | 🏢 Competitor Mentions |  | 🔍 Hallucination Check|           |
|  | - Hate speech, vulgarity|  | - Competitive entity   |  | - Claim verification   |           |
|  | - Harassment score     |  |   scrubbing            |  |   against context      |           |
|  +------------------------+  +------------------------+  +------------------------+           |
|                                                                                               |
|  Violation Detected? ---> [ YES ] ---> Redact or replace with generic safe fallback answer.   |
|                            [ NO  ] ---> Stream final response to User.                        |
+-----------------------------------------------------------------------------------------------+
```

### Supported Presidio PII/SPI Entities
- `EMAIL_ADDRESS`, `PHONE_NUMBER`, `PERSON`, `LOCATION`, `ORGANIZATION`
- `CREDIT_CARD`, `CRYPTO`, `IBAN_CODE`, `US_SSN`, `US_BANK_NUMBER`, `IP_ADDRESS`, `US_PASSPORT`

---

## 3. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  AI Guardrails Configuration                                                                  |
|  Manage safety policies, PII anonymization rules, and prompt injection filters.               |
|  [ + New Policy Configuration ]  [ Save Policy ]                                              |
+-----------------------------------------------------------------------------------------------+
|  Active Configuration: Enterprise Production Guardrails (Default)                             |
|                                                                                               |
|  Guardrail Toggles & Thresholds:                                                              |
|  [x] Banned Words Filter: [ Enabled ]                                                         |
|      Configured Keywords: ["drop table", "confidential internal only", "bypass_admin"]        |
|                                                                                               |
|  [x] Presidio PII / SPI Anonymization: [ Enabled - Mask Mode: Redact with <REDACTED>]         |
|      Active Entities: [ EMAIL_ADDRESS ] [ PHONE_NUMBER ] [ CREDIT_CARD ] [ US_SSN ] [ PERSON ]|
|                                                                                               |
|  [x] Adversarial Prompt Injection Guard: [ Enabled - Sensitivity: High (0.85) ]               |
|                                                                                               |
|  [x] Toxic & Harmful Language Detection: [ Enabled - Threshold: 0.70 ]                        |
|                                                                                               |
|  [ ] Competitor Entity Scrubber: [ Disabled ]                                                 |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/configs` | Lists all guardrails policy configs | `ConfigListResponse` |
| `POST` | `/guardrails/configs` | Creates a new policy configuration | `ConfigCreateRequest` -> `ConfigResponse` |
| `GET` | `/guardrails/configs/{id}` | Retrieves full guard configuration | `ConfigResponse` |
| `PUT` | `/guardrails/configs/{id}` | Updates policy rules and thresholds | `ConfigUpdateRequest` -> `ConfigResponse` |
| `DELETE` | `/guardrails/configs/{id}` | Removes configuration | `{"status": "deleted"}` |
| `GET` | `/guardrails/guards` | Lists all available system guards & PII options | `list[GuardOption]` |

### Sample Policy Configuration (`POST /guardrails/configs`)
```json
{
  "name": "Enterprise Production Guardrails",
  "is_default": true,
  "guards": ["ban_list", "pii_check", "prompt_injection", "toxic_language"],
  "settings": {
    "banned_words": ["drop table", "confidential internal only", "bypass_admin"],
    "pii_entities": ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN"]
  }
}
```
