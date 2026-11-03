# Provenance: dataset-feedback-research.md

- Date: 2026-10-29
- Skill: deep-research. The `researcher`, `verifier` and `reviewer` agents are not available in this harness, so `web_search` plus three read-only `scout` agents and direct code reads did the work.
- Search rounds: 2 (8 queries). One query (OpenTelemetry `gen_ai.conversation.id`) failed on a provider rate limit and was not retried.
- Sources consulted: 12 URLs listed in the brief. Findings 1 to 6 and the Collector facts quote or paraphrase the pages named in brackets. Finding 7 and its sources [9][10] are secondary vendor and university guidance, not standards.
- Code claims: each was read in this session. Files: `otel/otel-collector-config.yaml`, `otel/run-local-collector.py`, `otel/.env.example`, `rag-ingestion-manager/docker-compose.yaml`, `libs/shared/src/rag_shared/tracing.py`, `apps/rag-api/src/rag_api/routes/chat.py`, `apps/rag-api/src/rag_api/trace_context.py`, `apps/rag-api/src/rag_api/routes/dataset_profiles.py`, `libs/database/...`, `libs/eval-core/src/eval_core/dataset_schema.py`.
- Local binary check: `./otel/otelcol.exe components` listed the `filter` processor at v0.148.0. The exporter list in that output was filtered by the shell wrapper and did not show `otlp_http`, although the repo's running config uses it.
- Live check: `GET /chat/sessions?limit=100` on 127.0.0.1:8001 returned 100 sessions with message counts {2: 90, 4: 8, 6: 1, 10: 1}, which shows stateless single-turn sessions dominate and multi-turn sessions exist.
- Unverified: Phoenix curate-dataset page content (title and URL only); the version in the `otlp_http` README fetched is v0.162.0 while the repo pins v0.148.0, and `encoding: json` is assumed present in v0.148.0.
