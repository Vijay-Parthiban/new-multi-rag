# 09 — AI Guardrails Traces & Security Audits Page

## 1. Executive Summary & Page Purpose
The **AI Guardrails Traces & Security Audits Page** (`GuardrailsTracesPage.tsx`, route: `/guardrails/traces`) serves as the security compliance ledger. It provides complete audit trails of all incoming user prompts and generated model responses evaluated by guardrail policies, displaying pass/fail statuses, trigger confidence scores, matched PII entities, redacted payloads, and remediation actions.

---

## 2. UI Layout & Visual Components

```
+-----------------------------------------------------------------------------------------------+
|  AI Guardrails Security Traces                                                                |
|  Review real-time guardrail evaluation logs, blocked prompts, and PII redactions.             |
|  [ Filter: All / Blocked Only / PII Redacted ]   [ Search Prompt Text... ]                    |
+-----------------------------------------------------------------------------------------------+
|  Guardrail Traces Table (Showing 150 records)                                                |
|                                                                                               |
|  Timestamp | Prompt Preview           | Policy Name   | Status   | Triggered Guard | Latency  |
|  ----------+--------------------------+---------------+----------+-----------------+--------- |
|  10:14:22  | What is John Doe's SSN?  | Enterprise-v1 | BLOCKED  | pii_check (SSN) | 28ms     |
|  10:13:01  | Ignore previous rules... | Enterprise-v1 | BLOCKED  | prompt_inject   | 42ms     |
|  10:11:45  | Contact alex@chen.ai     | Enterprise-v1 | REDACTED | pii_check(Email)| 31ms     |
|  10:09:12  | Compare PyTorch to TF    | Enterprise-v1 | PASSED   | None (Clean)    | 18ms     |
+-----------------------------------------------------------------------------------------------+
|  Trace Detail Drawer:                                                                         |
|  Trace ID: gt-8fa1c4d9-0b1a-4f6c | Policy: Enterprise-v1 | Status: BLOCKED                     |
|  Guard: pii_check | Entity: US_SSN (Confidence: 0.98)                                         |
|  Original Prompt: "What is John Doe's SSN number?"                                            |
|  Sanitized Action: Intercepted before pipeline execution. Returned BlockedCard to UI.        |
+-----------------------------------------------------------------------------------------------+
```

---

## 3. Backend APIs & Contracts

| Method | Endpoint | Description | Request / Response |
|---|---|---|---|
| `GET` | `/guardrails/traces` | Lists recent guardrail evaluation audit traces | `TraceListResponse` |
| `GET` | `/guardrails/traces/{id}` | Retrieves full audit trace record with raw & redacted payload | `TraceResponse` |
| `GET` | `/guardrails/stats` | Safety metrics: violation breakdown and interception count | `StatsResponse` |

### Sample Trace Response (`GET /guardrails/traces/{id}`)
```json
{
  "id": "c19b48f1-928d-4c31-9f93-bc429188ae01",
  "config_id": "3695cb61-e728-4bf1-91f8-cf249d593c6b",
  "prompt": "What is John Doe's SSN 000-12-3456?",
  "status": "blocked",
  "triggered_guard": "pii_check",
  "details": {
    "matched_entities": [
      {
        "type": "US_SSN",
        "start": 24,
        "end": 35,
        "score": 0.98
      }
    ],
    "action": "blocked"
  },
  "latency_ms": 28,
  "created_at": "2026-09-16T10:14:22.000Z"
}
```
