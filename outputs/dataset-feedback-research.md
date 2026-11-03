# Dataset Feedback: how the industry turns production conversations into evaluation datasets

Date: 2026-10-29. Scope: curating golden datasets from production traces, and carrying conversation turns through an OpenTelemetry Collector.

## Findings

1. **Add to dataset is an action on a trace, a thread, or a batch of rows.** Langfuse puts "+ Add to dataset" on every trace and observation, and lets a reviewer batch-add rows from the observations table with a field mapping [1][2]. LangSmith multi-selects runs and clicks "Add to Dataset" [5].
2. **A multi-turn conversation becomes one dataset example.** LangSmith calls a conversation a *thread*. A thread rule or a manual add "adds the full conversation as one example" [5][6]. This matches one `turns` row in this repo's schema.
3. **A human edits the reference before it is stored.** LangSmith reviewers "can optionally modify the inputs/outputs/reference outputs from a trace before it is added", and a run is added with the corrected reference [5][7]. Langfuse says to "let an expert add the expected output" to a selected production trace [2]. So the pipeline's answer is a draft, not the label.
4. **Provenance travels with the row.** Langfuse stores `source_trace_id` on a dataset item [2] and advises an `added` date in item metadata to measure the age of the set [1].
5. **Hygiene rules for the set.** Validate against a schema, deduplicate, and version items; grow the set from fresh production failures; scope each dataset to one behaviour [1].
6. **Sampling and review queues.** LangSmith rules can sample matching runs (rate 0 to 1) and wait for a thread to go idle before adding it [6][8]. Phoenix has labeling and annotation with a `HUMAN` annotator kind and exports annotated traces to datasets [3][4]. This feature stays manual because the request asks for a person to choose each conversation.
7. **PII needs a gate before reuse.** Detect and redact before text is stored or reused, keep an audit record that never holds the raw matched value, and limit who sees unredacted text [9][10]. Here the gate is the human reviewer plus the existing guardrails on the live turn.

## OpenTelemetry Collector facts used

- The `otlp_http` exporter sends traces over HTTP. `encoding` defaults to `proto` and accepts `json`. `compression` defaults to gzip. `traces_endpoint` overrides the path; otherwise `/v1/traces` is appended to `endpoint` [11].
- The `filter` processor drops telemetry that matches any OTTL condition [12]. Its documented form is `traces: span: - <condition>`.
- One receiver can feed several pipelines, and each exporter receives its own copy of every span (this repo's collector config comment, `otel/otel-collector-config.yaml:132`). A failing exporter therefore does not disturb Phoenix or Langfuse.
- The local binary `otel/otelcol.exe` is v0.148.0 and lists the `filter`, `attributes`, `resource`, `span`, `batch` and `memory_limiter` processors; the Docker image is `otel/opentelemetry-collector:0.148.0` (`rag-ingestion-manager/docker-compose.yaml:232`).

## What this repo already emits (verified in code)

Each turn ends one span named `rag.chat` or `rag.chat.stream` with `session.id`, `rag.trace_mode`, `input.value`, `output.value`, `rag.pipeline.slug`, `rag.chunks_used`, `langfuse.observation.metadata.message_id` and `guardrails.<phase>.blocked` (`libs/shared/src/rag_shared/tracing.py:304-329`, `apps/rag-api/src/rag_api/routes/chat.py:615-632,756-794`, `trace_context.py:88-90`). No chat table stores the pipeline, so the span is the only place a turn is tied to a pipeline.

## Design drawn from the findings

| Practice | Dataset Feedback |
|---|---|
| Add from a trace or thread | A conversation list per linked pipeline; one add action per conversation |
| Thread is one example | A multi-turn session becomes one `turns` row |
| Reviewer edits the reference | The pipeline answer pre-fills an editable ground-truth field |
| Provenance in the row | `source_session_id`, `source_trace_id`, `source_span_id`, `trace_mode`, `added_at` in `metadata` |
| Deduplicate | One row per source session per dataset |
| Schema validation | The server builds the row and validates it with `GoldenDatasetItemPayload` |

## Not verified

- The OpenTelemetry `gen_ai.conversation.id` attribute: the search hit a rate limit. The plan uses this repo's own `session.id`.
- Phoenix "Curate a Dataset from Traces" page: only its title and URL were seen [4].

## Sources

1. Golden dataset evaluation: build and maintain LLM test sets. https://langfuse.com/resources/engineering/golden-dataset-evaluation
2. Datasets (Langfuse). https://langfuse.com/docs/evaluation/experiments/datasets
3. Annotations and Evaluation (Phoenix). https://arize.com/docs/phoenix/tracing/tutorial/annotations-and-evaluations
4. Curate a Dataset from Traces (Phoenix). https://phoenix.arize.com/docs/ax/observe/take-action/curate-dataset
5. Create and manage datasets in the UI (LangSmith). https://docs.langchain.com/langsmith/manage-datasets-in-application
6. Set up automation rules (LangSmith). https://docs.langchain.com/langsmith/rules
7. Use annotation queues (LangSmith). https://docs.langchain.com/langsmith/annotation-queues
8. LangSmith: Production Monitoring & Automations. https://www.langchain.com/blog/langsmith-production-logging-automations
9. Handling PII and Sensitive Data with LLMs. https://cborg.lbl.gov/security_pii
10. PII Detection in LLM Outputs: AI Team Guide. https://www.openlayer.com/blog/llm-output-pii-detection
11. otlphttpexporter README, OpenTelemetry Collector v0.162.0. https://github.com/open-telemetry/opentelemetry-collector/blob/v0.162.0/exporter/otlphttpexporter/README.md
12. Transforming telemetry (filter processor). https://opentelemetry.io/docs/collector/transforming-telemetry/index.md
