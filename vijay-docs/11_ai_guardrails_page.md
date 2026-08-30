# Page Documentation: AI Guardrails Configuration, Traces & Evaluation (`GuardrailsConfigPage.tsx`, `GuardrailsTracesPage.tsx`, `GuardrailsEvaluationPage.tsx`)

## 1. Overview & Purpose

The **AI Guardrails Suite** (`/guardrails`) provides runtime moderation, safety policy enforcement, entity masking, and violation tracing across input queries and output LLM responses. It guarantees compliance by sanitizing Personally Identifiable Information (PII), detecting toxic text, rejecting prompt injection attacks, enforcing custom banned keyword lists, and auditing violation statistics.

---

## 2. Component Structure & Routes

1. **`GuardrailsConfigPage.tsx` (`/guardrails/config`)**: Policy configuration workspace for defining active guardrail rules, enforcement phases (`input`, `output`, `both`), PII entity types, toxicity sensitivity thresholds, and banned phrase lists.
2. **`GuardrailsTracesPage.tsx` (`/guardrails/traces`)**: Real-time moderation audit log and visual pie charts displaying blocked queries, guardrail trigger breakdowns, and violation timestamps.
3. **`GuardrailsEvaluationPage.tsx` (`/guardrails/evaluation`)**: Offline benchmark evaluation page testing guardrail policy configurations against synthetic red-teaming datasets (toxicity suites, PII leak tests, prompt injection datasets).

---

## 3. Visual Layout & UI Architecture

### 3.1 Policy Configuration View (`GuardrailsConfigPage.tsx`)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: AI Guardrails Configuration | [+ Create Policy Config]              │
├─────────────────────────────────────────────────────────────────────────────┤
│ Active Policy Cards Grid:                                                   │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🛡️ Enterprise Strict Moderation Policy              ● ACTIVE (Input & Out) │ │
│ │  - 🔒 PII Masking: Emails, Phone Numbers, SSN, Credit Cards, API Keys    │ │
│ │  - ⚠️ Toxicity Filter: Threshold 0.75 (Hate, Violence, Harassment)       │ │
│ │  - 🚫 Banned Keywords: 14 phrases configured                           │ │
│ │  - 💉 Injection Defense: Prompt Injection & SQL Keyword Blocking        │ │
│ │ Actions: [✏️ Edit Policy] [📋 Duplicate] [🗑️ Delete]                     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Violation Traces & Audit View (`GuardrailsTracesPage.tsx`)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Guardrails Traces & Analytics | [View: 📋 Table | 📊 Charts]       │
├─────────────────────────────────────────────────────────────────────────────┤
│ Violation Statistics Cards:                                                 │
│ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌───────────┐ │
│ │ Total Interceptions│ │ PII Masking      │ │ Toxic Text       │ │ Banned    │ │
│ │       18         │ │     12           │ │     4            │ │ Keywords:2│ │
│ └──────────────────┘ └──────────────────┘ └──────────────────┘ └───────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ Moderation Audit Table:                                                     │
│ ┌── Timestamp ──┬── Guard Triggered ──┬── Phase ──┬── Content Snippet ──────┐│
│ │ 10:14:22      │ 🔒 pii_check        │ Input │ "Contact john@acme.com" ││
│ │ 10:02:10      │ ⚠️ toxic_language   │ Output│ "[BLOCKED BY POLICY]"   ││
│ │ 09:45:00      │ 🚫 ban_list         │ Input │ "Contains restricted"   ││
│ └───────────────┴─────────────────────┴───────┴─────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Guardrail Capabilities & Moderation Rules

| Guard ID | Name | Phase | Primary Action & Function |
|---|---|---|---|
| `pii_check` | PII Entity Masking | Input & Output | Scans text for emails, phone numbers, SSNs, credit cards, and API keys; masks sensitive substrings (e.g. `[EMAIL_REDACTED]`). |
| `toxic_language` | Toxicity Filter | Input & Output | Scores text for toxicity, hate speech, violence, and harassment using classifier models; blocks responses exceeding threshold. |
| `ban_list` | Banned Keywords | Input & Output | Matches input string against explicit phrase lists; returns standardized refusal cards if matched. |
| `injection_defense` | Prompt Injection | Input | Detects system prompt override attempts, instruction hijacking, and SQL injection syntax patterns. |

---

## 5. API Endpoints & Request Schemas

### 5.1 `GET /api/v1/guardrails/configs`
- **Description**: Returns all configured guardrail policies.
- **Response Schema (`GuardrailsConfig[]`)**:
```json
[
  {
    "id": "gcfg-001",
    "name": "Enterprise Strict Moderation Policy",
    "mode": "both",
    "guards": ["pii_check", "toxic_language", "ban_list", "injection_defense"],
    "pii_entities": ["email", "phone", "ssn", "credit_card", "api_key"],
    "toxicity_threshold": 0.75,
    "banned_keywords": ["confidential_internal_only", "restricted_key"],
    "is_active": true
  }
]
```

### 5.2 `POST /api/v1/guardrails/configs`
- **Description**: Creates a new guardrail policy config.

### 5.3 `GET /api/v1/guardrails/traces` & `GET /api/v1/guardrails/stats`
- **Description**: Returns logged guardrail violation events, execution metrics, and pie-chart aggregation data.

---

## 6. How to Run & Verify

1. **Configure Policy**: Open `http://localhost:5173/guardrails/config` and activate `pii_check` and `ban_list` guards. Add `restricted_key` to banned keywords.
2. **Test Input Block in Chat**: Open `/chat` and submit a query containing PII or banned keyword (e.g., "Here is my secret restricted_key").
3. **Verify Blocked Response**: Confirm the chat UI displays the high-contrast `BlockedCard` banner indicating `Input blocked by Banned keyword policy`.
4. **Inspect Audit Traces**: Open `http://localhost:5173/guardrails/traces` to confirm the interception event is recorded with timestamp and guard trigger details.
