# new-multi-rag — Software Design

| Item | Value |
|---|---|
| Status | As built, with this week's plan at the end |
| Date | 2026-11-03 |
| Repository | `new-multi-rag` |
| Main branch in work | `dataset-fabric-added-Oct28` |
| Scope | Both services, the shared infrastructure, and the two dataset workstreams |

This document describes the system as the code stands today. Section 14 gives the
implementation plan for this week. The plan covers two items only: the Dataset Feedback
feature and the Offline Evaluation page.

---

## 1. Purpose

The product turns documents into a queryable knowledge base and grades the answers it
produces. It does four things:

1. It ingests files of several types into isolated per-product stores.
2. It runs RAG pipelines over those stores with a selectable strategy.
3. It serves chat and assistant endpoints with optional session memory and guardrails.
4. It measures answer quality against golden datasets, and it lets a reviewer turn real
   conversations into new golden rows.

The system has two projects. Each project has its own backend, frontend, and compose file.

| Project | Role | Backend root | API port | Ingestion API port |
|---|---|---|---|---|
| `rag-ingestion-manager` | Files to chunks to stores | `rag-ingestion-manager/backend` | 8007 | (same service) |
| `rag-retrieval-chat-manager` | Retrieval, chat, evaluation | `rag-retrieval-chat-manager/backend` | 8001 | (calls 8007) |

Both frontends run under Vite. The retrieval frontend runs on port 5174.

---

## 2. System Context

### 2.1 Component map

| Component | Technology | Responsibility |
|---|---|---|
| `rag-ingestion-manager` API | FastAPI | Sources, Knowledge Products, pipelines metadata, uploads, connector runs |
| Ingestion worker | RQ | Extract, chunk, embed, write to destinations |
| Pathway worker | Pathway | Streaming ingestion for connectors |
| NiFi | Apache NiFi | Scraper flow orchestration |
| Scraper API and worker | FastAPI + RQ | Web scraping into sources |
| `rag-retrieval-chat-manager` API | FastAPI | Retrieve, rerank, generate, chat, assistants, datasets, evaluation |
| Eval worker | RQ | Golden dataset runs and chat metric jobs |
| Guardrails service | FastAPI | Guard checks, policy evaluation |
| Frontend (rag) | React + Vite + TypeScript | 20 page components, dark and light themes |
| Frontend (ingestion) | React + Vite | Sources, Knowledge Store, uploads |
| PostgreSQL | Postgres 16 | Two databases: ingestion and retrieval |
| Qdrant | Vector database | Dense vectors per Knowledge Product collection |
| OpenSearch | Search engine | BM25 lexical index per Knowledge Product |
| Redis | Redis 7 | RQ queues and assistant session memory |
| MinIO | S3-compatible storage | Source files and the `dataset-fabric` bucket |
| OTEL Collector | OpenTelemetry Collector 0.148.0 | Traces to Phoenix, Langfuse, and rag-api |
| Neo4j, OpenSearch dashboards | Optional | Graph and search exploration |

### 2.2 Request paths

**Chat turn.** The frontend calls `POST /chat` on rag-api. rag-api loads the pipeline
config from the ingestion service, retrieves chunks from Qdrant or OpenSearch, reranks,
generates with LiteLLM, applies guardrails, persists the turn, and emits an OTEL span. A
streaming turn uses `POST /chat/stream` and the same stages.

**Ingestion.** A user uploads a file through the ingestion frontend. The API stores the
file in MinIO and queues a job. The worker extracts text, chunks it, embeds it, and writes
to the product's enabled destinations.

**Evaluation.** The frontend creates a run on rag-api. rag-api queues a job on Redis. The
eval worker replays each row through the same `RAGPipeline.chat` path a live turn uses,
scores the result, and stores per-row metrics. The frontend polls the run.

**Feedback.** rag-api emits a turn span. The collector copies that span to rag-api's OTLP
receiver. rag-api stores the turn in `conversation_turns`. The Dataset Feedback page reads
those turns for one pipeline and appends chosen conversations to a golden dataset.

---

## 3. Data Design

### 3.1 PostgreSQL

The retrieval database holds 17 tables. The migration chain has eight revisions
(`001` to `008`).

| Group | Tables | Notes |
|---|---|---|
| Chat | `chat_sessions`, `chat_messages`, `chat_pipeline_traces`, `chat_message_metrics` | Soft delete on sessions and messages (`deleted_at`) |
| Evaluation | `golden_datasets`, `golden_dataset_items`, `evaluation_runs`, `evaluation_run_items` | `kind` is `single_turn` or `multi_turn`; `profile_id` links to a fabric profile |
| Fabric | `dataset_profiles` | Name, purpose, linked pipeline, Knowledge Product |
| Feedback | `conversation_turns` | One row per collected turn; unique on `(trace_id, span_id)` |
| Guardrails | `guardrails_configs`, `guardrails_traces`, `guardrails_golden_datasets`, `guardrails_golden_dataset_items`, `guardrails_eval_runs`, `guardrails_eval_run_items` | Separate dataset and run tables from RAG evaluation |
| Prompts | `prompt_templates` | Versioned templates |

Design rules:

- A golden row carries `question`, `ground_truth_answer`, `expected_sources`, `turns`, and
  `metadata`. A multi-turn row stores the user turns in `turns`. The assistant turns live
  in `metadata.expected_turns`.
- A dataset belongs to at most one fabric profile. A dataset imported the old way through
  the Offline Evaluation page has a NULL `profile_id`.
- `conversation_turns` has no foreign key to `chat_messages`. A chat row may be deleted and
  the collected turn must outlive it.

### 3.2 Object storage

| Bucket | Contents | Rule |
|---|---|---|
| Knowledge Product buckets | Source files for one product | The ingestion service indexes every object in the bucket |
| `dataset-fabric` | Every golden dataset file | No source points at it, so nothing is chunked or embedded |

A dataset object key is `datasets/<profile_id>/<kind>/<basename>`. The row stores the bucket
and key. Appending rows rewrites the object as JSONL. The JSONL file is the canonical
snapshot, and the database rows are the working copy.

### 3.3 Retrieval stores

Each Knowledge Product owns its data. A product enables some destinations:

| Destination | Store | Serves |
|---|---|---|
| `vector` | Qdrant collection | Dense semantic search |
| `lexical` | OpenSearch index | BM25 keyword search |
| `vision` | Qdrant page-image collection | Image answers through a vision model |
| `graph` | Neo4j | Relationship questions |
| `redis` | Redis | Assistant session memory |

Isolation rule: a pipeline reads only the stores of its own product. A strategy that needs
a store the product does not enable cannot be selected.

---

## 4. Backend Design

### 4.1 Applications

| App | Entry point | Duties |
|---|---|---|
| `rag-api` | `rag_api/main.py` | HTTP surface, routers, auth dependency, lifespan probes |
| `eval-worker` | `eval_worker/main.py` | RQ consumer for the eval queue |

`rag-api` registers 16 routers under one app. A global API key dependency protects every
route. Health probes are open.

### 4.2 Libraries

The backend is a set of libraries with a strict dependency direction. `shared` depends on
nothing internal. Adapters depend on `shared`. `rag-core` composes the adapters. Apps depend
on everything.

| Library | Responsibility |
|---|---|
| `rag_shared` | Settings, types, tracing, chunk utilities, auth |
| `rag_db` | SQLAlchemy models, repositories, migrations, session factory |
| `retrieval_core` | Qdrant and OpenSearch clients, fusion, rewrite |
| `vector_core` | Embedding clients (dense and sparse) |
| `reranker_core` | Cross-encoder rerank and score fusion |
| `generation_core` | LiteLLM client, prompt assembly, streaming |
| `rag_core` | `RAGPipeline`, strategies, session memory, assistants |
| `eval_core` | Schema parsing, runner, metrics, attribution, RAGAS client |

Repositories take a SQLAlchemy session. Routers open a session from the factory and do not
hold it across an `await`.

### 4.3 Configuration

One settings object (`rag_shared.config.Settings`) reads the environment. It groups:

- Infrastructure URLs: database, Redis, Qdrant, OpenSearch, MinIO, LiteLLM, guardrails.
- Model names: chat, vision, embedding, sparse embedding, reranker, judge.
- Retrieval defaults: mode, limit, rerank top k, relevance threshold.
- Evaluation: worker concurrency, default k, RAGAS toggle, async chat metrics.
- Dataset storage: `dataset_fabric_bucket`.

No secret has a default. A missing secret fails startup.

### 4.4 Chat turn lifecycle

1. Authenticate the request and resolve the pipeline.
2. Load the pipeline config from the ingestion service, or from the assistant record.
3. Load session memory when the pipeline has it.
4. Retrieve, fuse, rerank, and select the context.
5. Build the messages and call the model. Stream when requested.
6. Run guardrails on the input and the output.
7. Persist the user and assistant messages, and the trace row.
8. Emit the turn span with `rag.pipeline.slug`, `session.id`, and `rag.trace_mode`.

---

## 5. RAG Pipeline Design

### 5.1 Stages

A pipeline is `retrieve → fuse → rerank → generate`. Reranking is optional. Fusion is the
reciprocal rank fusion of vector and keyword results.

### 5.2 Strategies

| Strategy | Store read | Extra stage |
|---|---|---|
| `vector` | Qdrant | None |
| `lexical` | OpenSearch | None |
| `hybrid` | Both | Reciprocal rank fusion |
| `image_vision` | Qdrant page images | Vision model reads the page image |
| `self_rag` | Depends on stores | Grade passages, check grounding, revise once |
| `corrective` | Depends on stores | Grade passages, answer only from relevant ones |

The Offline Evaluation page can run the first three strategies and the two grading
strategies. It refuses `image_vision`, because the run report cannot show an image context
as a text source.

### 5.3 Session memory

An assistant pipeline can read a Knowledge Product's Redis destination as memory. The
memory stores the last turns of a session with a TTL. The evaluator drives the same path,
so a multi-turn row measures the production protocol, not a copy of it.

---

## 6. Dataset Lifecycle

The system has three dataset stages. Each stage has one owner page.

### 6.1 Dataset Fabric (authoring store)

A profile is the unit. It has a name, a purpose, a linked pipeline, and a Knowledge Product.
Uploaded files become `golden_datasets` rows that point at the profile. The page shows:

- The profile list, with linked pipeline and dataset count.
- A file list per profile, with kind, rows, and upload time.
- A full-width viewer with a pager (20 rows per page).
- An edit form for the profile.

A profile with no linked pipeline is a real state. The datasets are authored before the
pipeline exists. Such a profile never appears on the Offline Evaluation page.

### 6.2 Dataset Feedback (harvest real conversations)

A reviewer picks a profile that is linked to a pipeline. The page lists the real test and
prod conversations of that pipeline from `conversation_turns`. The reviewer reads a
conversation and adds it as a golden row.

Two cases exist:

| Case | Action | Result |
|---|---|---|
| Profile has no dataset of the kind | Create single-turn or multi-turn dataset | New dataset with the chosen rows |
| Profile already has a dataset of the kind | Append to it | Rows added to the newest dataset, snapshot rewritten |

The server builds each row from stored turns. The client never sends the question text.
Each row records provenance in `metadata`: `source`, `source_session_id`, `source_trace_id`,
`source_span_id`, `trace_mode`, `added_at`. One row per source session per dataset prevents
duplicates. The pipeline answer pre-fills an editable ground truth.

The page also edits a stored row. A partial `PATCH` validates the row, rewrites the
snapshot, and keeps row order. Fields: question, ground-truth answer, expected sources,
question type, expected behavior.

### 6.3 Offline Evaluation (run the dataset)

The page selects a pipeline, then a profile linked to it, then a kind. Today it uses the
newest dataset of that kind. The run samples up to N rows and queues a job.

### 6.4 Format rules

A dataset file is CSV, JSON, or JSONL. The parser maps each accepted column set to
`GoldenDatasetItemPayload`. Required fields are `question` and `ground_truth_answer`.
`expected_sources` accepts a list or a delimiter-separated string. `turns` accepts a list of
objects for multi-turn rows.

The canonical snapshot is JSONL with one row per line. The writer emits the same field set
that the parser reads, so a round trip through MinIO is lossless.

---

## 7. Feedback Subsystem Design

### 7.1 Why the collector

No chat table stores which pipeline a turn belonged to. `chat_sessions` holds only
`source_type` and `source_id`. The only place a turn ties to a pipeline is the span
attribute `rag.pipeline.slug`. The collector is therefore the delivery path, and a new
table is the store.

### 7.2 Collector configuration

`otel/otel-collector-config.yaml` has two trace pipelines:

| Pipeline | Processors | Exporters |
|---|---|---|
| `traces` | `memory_limiter`, `resource`, `batch` | `debug`, `otlp_http/phoenix`, `otlp_http/langfuse` |
| `traces/feedback` | `memory_limiter`, `filter/rag_turns`, `batch` | `otlp_http/feedback` |

The filter keeps only `rag.chat` and `rag.chat.stream` spans, so the receiver sees turns and
nothing else. The feedback exporter uses OTLP/HTTP with JSON encoding to
`<endpoint>/v1/traces`. The Phoenix and Langfuse pipelines are unchanged.

The local collector drops the gRPC receiver. `otel/run-local-collector.py` derives
`otel-collector-local.derived.yaml` from the main file for that case.

### 7.3 Receiver and store

`POST /v1/traces` accepts OTLP JSON. It parses `resourceSpans`, then each span. A span is
kept when it has a session id, an input, an output, and a pipeline slug. The insert uses
`ON CONFLICT (trace_id, span_id) DO NOTHING`, so a collector retry never duplicates a turn.

### 7.4 Conversation listing

`GET /api/dataset-feedback/profiles/{id}/conversations` groups turns into sessions. A
single-turn conversation has exactly one turn. A multi-turn conversation has two or more.
The query excludes blocked turns and turns whose chat message is soft-deleted. Each item
carries the session id, the turn count, the trace mode, the first question, and the time.

### 7.5 Row building and append

`POST /api/dataset-feedback/profiles/{id}/rows` takes session ids and a kind. For each
session it reads the turns in order, builds the row, and appends it. The append path:

1. Resolves the target dataset: the newest of that kind for the profile.
2. Inserts the rows with provenance metadata.
3. Updates `row_count`.
4. Writes the full JSONL snapshot to MinIO.
5. Deletes a superseded CSV, XLSX, or Parquet object after the commit.

A multi-turn row stores user turns only, because the runner replays user turns. The
`question` field is the last included user turn. `graded_turn` records which turn the
ground truth answers.

---

## 8. Offline Evaluation Subsystem Design

### 8.1 Run creation

`POST /evaluate/runs` resolves the dataset, samples the requested rows, writes an
`evaluation_runs` row with status `queued`, and enqueues `run_evaluation` on the eval queue.

The run config records the pipeline, the k values, the judge model, the guardrails config,
and the prompt template.

### 8.2 Runner

`eval_core.runner.GoldenItemEvaluator` runs one row. It calls `RAGPipeline.chat`, which is
the live path. That choice makes the grading strategies measurable, because their grading
and revision branches live there.

A multi-turn row replays its user turns with a temporary session id. Each answer goes into
the session memory before the next turn. The last turn is scored. The session key is
cleared in a `finally` block.

### 8.3 Metrics

| Stage | Metrics | Source |
|---|---|---|
| Retrieval | `hit@k`, `recall@k`, `precision@k`, `mrr`, effective query | Formula, k in {1, 3, 5, 10} |
| Rerank | `ndcg@k`, Kendall tau rank correlation | Formula |
| Generation | RAGAS faithfulness, answer relevancy, context precision, context recall | LLM judge |
| Generation | Triad: grounded, attributed, relevant | LLM judge |
| Generation | Custom row checks from CSV columns | Formula |
| Chat pipeline | Latency, chunk counts, guardrail outcomes | Stored trace |

Retrieval and rerank metrics never use an LLM judge. Generation metrics do, so the run
records the judge model.

### 8.4 Attribution

`eval_core/attribution.py` maps per-row metrics to a failing stage. The run response
computes the breakdown when it is read, not when it is written. A rule change therefore
re-reads old runs under the new rule.

### 8.5 Run lifecycle

| State | Meaning |
|---|---|
| `queued` | Job accepted, worker has not started |
| `running` | Worker is scoring rows |
| `completed` | All rows scored |
| `failed` | The job raised; `error_message` holds the cause |

Per-row records keep the retrieved chunks, the reranked chunks, the answer, and each metric
block. Image payloads are stripped before storage.

---

## 9. Observability

| Concern | Design |
|---|---|
| Trace modes | `test` or `prod`, from the `X-RAG-Trace-Mode` header or the request body |
| Turn span | `rag.chat` or `rag.chat.stream`, with session, pipeline, and model attributes |
| Backends | Phoenix and Langfuse, one exporter each |
| Feedback | A separate collector pipeline, into `conversation_turns` |
| Eval traces | Synthetic spans with the original trace id, so a question is not doubled |

The application exports to `OTEL_EXPORTER_OTLP_ENDPOINT`, default `http://otel:4318`. A
collector outage must not fail a chat request. The exporter drops the span and the turn
still completes.

---

## 10. Frontend Design

### 10.1 Structure

| Path | Page |
|---|---|
| `/` | Overview |
| `/knowledge-store`, `/sources`, `/upload` | Ingestion front |
| `/pipelines`, `/prompts` | Configuration |
| `/chat` | Chat and assistant endpoints |
| `/evaluations` | Real Time Monitoring |
| `/dataset-fabric` | Dataset authoring and viewer |
| `/dataset-feedback` | Conversation harvesting |
| `/golden-evaluations` | Offline Evaluation |
| `/guardrails/config`, `/traces`, `/evaluation` | Guardrails |

### 10.2 Conventions

- Pages stay mounted. A wrapper hides the inactive page, so state survives navigation.
- One API module (`api.ts`) holds every client. It is not generated.
- Styling uses CSS classes in `index.css`. Two families: `fabric-*` for dataset pages,
  `chat-*` for chat. Both share the theme tokens.
- Dark and light themes use CSS variables. No page sets a hard-coded color.
- Tables page through a shared `Pager` component.
- Icons are inline SVG components. No icon font, no emoji.

---

## 11. Interfaces

### 11.1 Dataset and evaluation

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/dataset-profiles` | List profiles, optional `pipeline_slug` filter |
| `POST` | `/api/dataset-profiles` | Create a profile |
| `PATCH` | `/api/dataset-profiles/{id}` | Edit name, purpose, pipeline link |
| `DELETE` | `/api/dataset-profiles/{id}` | Delete a profile and its files |
| `POST` | `/api/dataset-profiles/{id}/datasets` | Upload a dataset file |
| `GET` | `/api/dataset-profiles/{id}/datasets/{dataset_id}` | Preview rows |
| `PATCH` | `/api/dataset-profiles/{id}/datasets/{dataset_id}/items/{item_id}` | Edit one row |
| `DELETE` | `/api/dataset-profiles/{id}/datasets/{dataset_id}` | Delete a dataset |
| `GET` | `/api/dataset-feedback/profiles/{id}/conversations` | List collected conversations |
| `GET` | `/api/dataset-feedback/profiles/{id}/conversations/{session_id}` | Read one conversation |
| `POST` | `/api/dataset-feedback/profiles/{id}/rows` | Append conversations as rows |
| `GET` | `/evaluate/datasets` | List datasets |
| `POST` | `/evaluate/datasets/upload` | Import a dataset file |
| `POST` | `/evaluate/runs` | Create a run |
| `GET` | `/evaluate/runs/{id}` | Read a run and its rows |
| `GET` | `/evaluate/datasets/{id}/runs` | List runs of a dataset |
| `GET` | `/evaluate/pipeline-defaults` | Retrieval settings a run uses |

### 11.2 Chat and retrieval

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat`, `/chat/stream` | Single turn or streamed turn |
| `GET` | `/chat/sessions`, `/chat/sessions/{id}/messages` | Read history |
| `POST` | `/retrieve`, `/search`, `/rerank` | Stage checks |
| `POST` | `/v1/traces` | OTLP/JSON turn receiver |
| `GET` | `/health` | Liveness |

### 11.3 Guardrails

| Method | Path | Purpose |
|---|---|---|
| `GET`, `POST`, `PATCH`, `DELETE` | `/guardrails/configs` | Guard configuration |
| `GET` | `/guardrails/traces` | Recent guard outcomes |
| `POST` | `/guardrails-evaluate/runs` | Guard evaluation |

---

## 12. Security and Operations

- Auth: one API key dependency on every router. The key comes from the environment.
- Inputs: the upload path checks the extension and the parse. A bad file returns 422, not a
  half-written dataset.
- Secrets: no secret has a default value.
- Soft delete: chat rows and sessions use `deleted_at`. A collected turn survives a chat
  delete.
- Idempotency: collector retries cannot duplicate a turn. A dataset upload with `replace`
  replaces the dataset by name.
- Dev run: `scripts/dev.sh` starts the two APIs and the two frontends on the host. Docker
  compose provides Postgres, Redis, Qdrant, OpenSearch, MinIO, the collector, and the
  guardrails service.

---

## 13. Known Limitations

| Area | Limitation | Effect |
|---|---|---|
| Feedback | No turn table row exists for traffic before the exporter was enabled | Older sessions never appear |
| Feedback | The conversation list has a limit and no paging | A busy pipeline hides older sessions |
| Feedback | A blocked turn is dropped | A refusal cannot become a golden row from the page |
| Feedback | The collector must reach rag-api | A Docker collector needs `extra_hosts` |
| Evaluation | The page uses the newest dataset of a kind | An older upload cannot be run |
| Evaluation | No run comparison | A change cannot be read as a delta against a baseline |
| Evaluation | No cancel and no timeout | A dead worker leaves a run in `running` |
| Evaluation | `image_vision` is not evaluable | Vision answers are scored only in chat metrics |
| Tests | Six unit tests fail on stale expectations | A real regression is hard to see in the suite |

---

## 14. Implementation Plan — Week of 2026-11-03

Two workstreams only: Dataset Feedback, and Offline Evaluation. Each task names a change,
an acceptance check, and a day. The order is a proposal, not a dependency chain, except
where a task says so.

### 14.1 Workstream A — Implement and refine Dataset Feedback

Current state: the page, the collector pipeline, the receiver, the table, the row builder,
the append path, and the row editor work end to end. What is missing is hardening,
coverage, and reviewer ergonomics.

#### A1. Cover the write paths with tests (day 1)

Problem: a JSONB serialization bug reached the browser, because no test called the edit
path.

Change:

1. Add unit tests for `PATCH /items/{item_id}`: question-only edit, turns-only edit
   (question follows the last user turn), empty answer with and without
   `refuse_or_abstain`, and a kind mismatch.
2. Add a unit test for `POST /rows`: new dataset of each kind, append to an existing
   dataset, and a duplicate session id.
3. Add an integration test with a real Postgres session for the snapshot rewrite: read the
   MinIO object back and assert the row content and the row count.

Acceptance: the new tests fail on the old code and pass now. The suite adds no new failure
to the six known ones.

#### A2. Make collector delivery verifiable in Docker (day 1)

Problem: delivery is verified only with the local binary. A Docker collector cannot reach a
host rag-api without `extra_hosts`.

Change:

1. Add `extra_hosts: host.docker.internal:host-gateway` to the collector service.
2. Add every feedback variable to `otel/.env.example`, with a one-line comment each.
3. Add `GET /api/dataset-feedback/health`: returns the last turn time, the turn count, and
   whether the receiver key is set.
4. Show the same three values at the top of the page.

Acceptance: after `docker compose up` and one chat turn, the health route reports a turn
from the last minute, and the page shows the same time.

#### A3. Page the conversation list and keep the filters (day 2)

Problem: the list asks for 25 items. A busy pipeline has more.

Change:

1. Add offset paging: `limit` and `offset` on the list route, plus a total count per kind.
2. Reuse the shared `Pager` under the conversation list.
3. Keep the mode filter and the search text in the page state across a page change.

Acceptance: a pipeline with more than 25 sessions shows the true total, and page 2 shows
non-overlapping sessions.

#### A4. Show provenance on a golden row, and allow a row delete (day 3)

Problem: a reviewer cannot tell which conversation a row came from, and a wrong row cannot
be removed.

Change:

1. Show `source_session_id`, `trace_mode`, and `added_at` in the Dataset Fabric viewer row
   detail.
2. Add `DELETE /api/dataset-profiles/{id}/datasets/{dataset_id}/items/{item_id}`. It
   removes the row, updates `row_count`, and rewrites the snapshot.
3. Add the delete control to the Feedback row drawer, with a confirm step.

Acceptance: a deleted row is gone from the viewer after a reload, the object in MinIO has
one row fewer, and `row_count` matches.

#### A5. Fix the drawer accessibility gaps (day 4)

Problem: the audit flags unnamed fields, and the keyboard flow is unknown.

Change:

1. Give every drawer field an `id` and a `label htmlFor`.
2. Move focus to the first field on open. Return focus to the pencil on close.
3. Close on Escape. Keep the save button reachable with Tab.

Acceptance: a Lighthouse accessibility audit of the page reports no unlabeled field. The
whole edit flow works with the keyboard only.

### 14.2 Workstream B — Refine Offline Evaluation

Current state: the page selects a pipeline, a linked profile, and a kind. It runs the
newest dataset of that kind, scores four metric groups, and shows an aggregate, a stage
breakdown, per-row rubrics, and a chart. What is missing is dataset choice, run control,
and a usable test suite.

#### B1. Reproduce the six failing tests and fix them (day 1)

Problem: the suite reports six failures that predate this work. A new regression cannot be
told apart from the noise.

Change:

1. `test_retrieval_metrics`: the code no longer emits `recall_at_3` for the default k set.
   Fix the test to read the emitted keys.
2. `test_dataset_upload` and `test_golden_dataset_file_structure`: the minimum-row rule
   changed. Fix the fixture to the current rule.
3. `test_stats` (two tests): the `ChatStatItem` schema gained required fields. Fix the
   fixtures.
4. `test_sparse_client_cache`: the client factory moved. Patch the new symbol.

Acceptance: `pytest tests/unit` reports zero failures.

#### B2. Let the user choose the dataset (day 2)

Problem: an older upload of the same kind cannot be run.

Change:

1. Replace the "newest of kind" rule on the page with a select list of all datasets of the
   chosen kind, newest first, with row count and upload time.
2. Keep the newest as the default.
3. Keep the row clamp: the sample size cannot exceed the chosen dataset's row count.

Acceptance: two uploads of the same kind appear in the list. A run on the older one reads
the older rows, and its report names that dataset.

#### B3. Add a run cancel path and stale-run recovery (day 3)

Problem: a stopped worker leaves a run in `running` with no end.

Change:

1. Add `POST /evaluate/runs/{id}/cancel`: sets `cancelling`, and the worker checks the flag
   between rows.
2. In the worker, mark the run `cancelled` and keep the rows already scored.
3. On service start, mark any run still `running` and older than the queue timeout as
   `failed`, with `error_message = "worker stopped"`.

Acceptance: a cancelled run stops within one row, keeps its scored rows, and reports
`cancelled`. A run left by a killed worker reports `failed` after the next API start.

#### B4. Compare a run with a baseline (day 4)

Problem: a change cannot be read as a delta.

Change:

1. Add a baseline selector on the run panel: the previous completed run of the same
   dataset.
2. Show a delta table: aggregate metric, baseline value, current value, difference.
3. Mark a metric as regressed when it drops more than a fixed threshold (start with
   `hit@5` and `faithfulness`).

Acceptance: two runs on one dataset show a delta for each aggregate metric, and the
regressed rows are visible without opening the rows.

#### B5. Export a run (day 4, after B4)

Problem: a run cannot leave the page.

Change:

1. Add `GET /evaluate/runs/{id}/export?format=jsonl|csv`. The JSONL form is the golden
   schema plus `generated_answer` and each metric block.
2. Add an export button beside the run title.

Acceptance: the exported JSONL parses with `parse_golden_dataset_jsonl`, and a CSV opens in
a spreadsheet with one row per dataset row.

### 14.3 Schedule

| Day | Workstream A | Workstream B |
|---|---|---|
| Mon 2026-11-03 | A1 test coverage | B1 fix the six tests |
| Tue 2026-11-04 | A2 collector in Docker | B2 dataset choice |
| Wed 2026-11-05 | A3 list paging | B3 cancel and stale recovery |
| Thu 2026-11-06 | A4 provenance and row delete | B4 baseline comparison |
| Fri 2026-11-07 | A5 accessibility, full browser pass | B5 export, full run pass |

### 14.4 Definition of done for the week

1. `pytest tests/unit` passes with zero failures. The integration suite passes against a
   local Postgres.
2. One live chat turn reaches the page through the Docker collector.
3. A dataset round trip holds: harvest a conversation, edit the row in Dataset Fabric,
   export the run, and read the row back from MinIO.
4. `tsc -b` and `vite build` pass.
5. Screenshots at 1440 and 900 pixels, in dark and light, for both pages.

### 14.5 Out of scope for this week

1. A backfill of turns that predate the exporter.
2. Automatic row generation without a reviewer.
3. A change to the metric formulas.
4. New RAG strategies.
5. The guardrails pages.
