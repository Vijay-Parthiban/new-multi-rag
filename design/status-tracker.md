# new-multi-rag — Project Status Tracker

| Item | Value |
|---|---|
| Status | Living document |
| Date | 2026-11-05 |
| Repository | `new-multi-rag` |
| Branch in work | `dataset-fabric-added-Oct28` |
| Last commit | `1896223` — Add synthetic dataset creator with per-kind versions |
| Commit count | 50 |
| Span | 2026-09-19 to 2026-11-05 |
| Scope | Both projects, the shared infrastructure, and the dataset workstreams |

This document records every stage of the project, the substages inside each stage, and
the state of each one. It ends with the work that is in the working tree today and the
plan for the rest of the week.

Evidence comes from three sources: the git history, the page documents in `vijay-docs/`,
and the design document in `design/software-design.md`.

## 0. Status legend

| State | Meaning |
|---|---|
| Complete | Merged to the branch and verified. |
| Complete, uncommitted | Works and is verified, but it is not in a commit yet. |
| In progress | Some substages work; the stage is not finished. |
| Planned | Agreed, not started. |
| Deferred | Deliberately out of scope for the current period. |

---

## 1. Snapshot

| Measure | Value |
|---|---|
| Commits | 50 |
| Retrieval frontend pages | 21 page components |
| Ingestion frontend pages | 6 page components |
| Backend applications | 2 APIs, 1 ingestion worker, 1 eval worker, 1 guardrails service |
| Unit test suite | 295 pass, 6 fail (all known and older than the current stage) |
| Retrieval API port | 8001 |
| Ingestion API port | 8007 |
| Object storage | MinIO: source buckets, one bucket per Knowledge Product, `dataset-fabric` |
| Vector stores | Qdrant (dense and sparse), OpenSearch (BM25), Neo4j (optional) |
| Working tree | 9 modified files, 1 new migration, 3 screenshots, all uncommitted |

The two dataset pages, Dataset Fabric and Offline Evaluation, are complete. Dataset
Feedback is complete end to end but has known hardening gaps. The Synthetic Dataset
Creator is complete and uncommitted.

---

## 2. Stages at a glance

| Stage | Theme | Period | State |
|---|---|---|---|
| 1 | Ingestion foundations | 2026-09-19 | Complete |
| 2 | Knowledge Products and per-product stores | 2026-09-20 | Complete |
| 3 | Retrieval, chat, and assistant endpoints | 2026-09-20 to 09-24 | Complete |
| 4 | Observability and real-time monitoring | 2026-09-21 to 10-13 | Complete |
| 5 | Guardrails | 2026-09-21 to 10-13 | Complete |
| 6 | Evaluation engine | 2026-09-21 to 10-10 | Complete |
| 7 | Platform operations and web scraping | 2026-09-24 to 10-15 | Complete |
| 8 | Dataset Fabric and universal golden datasets | 2026-10-28 | Complete |
| 9 | Dataset Feedback | 2026-11-03 | Complete, with known gaps |
| 10 | Synthetic Dataset Creator | 2026-11-05 | Complete, uncommitted |

The stages overlap in time. Work on guardrails, evaluation, and tracing ran in the same
days. The order in the table is the order of dependency, not the order of the calendar.

---

## 3. Stage 1 — Ingestion foundations

**Period:** 2026-09-19. **State:** Complete.

The ingestion project became a working source-to-destination pipeline: it takes files
from a source bucket, extracts them, chunks them, embeds them, and writes them to four
destination types.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 1.1 | MinIO source manager | Create a source bucket, upload files, list and delete them, with a source id that survives a restart of the poller | `d61a968`, doc 03 | Complete |
| 1.2 | Live and scheduled polling | Background poller with a live and a scheduled mode, started at API startup | `9c1169b` | Complete |
| 1.3 | Fanout to four destinations | Qdrant, OpenSearch, Redis, and Neo4j writers behind one fanout service | `dd263ed`, `ab5bd20` | Complete |
| 1.4 | Visualizers | Interactive views of the five sink types, with per-destination status | `dd263ed` | Complete |
| 1.5 | Dynamic vector dimensions | A dimension change on a collection no longer raises a mismatch error | `7ce55b2` | Complete |
| 1.6 | NiFi connector catalogue | Connector cards and the connector types the server accepts | `61fc5fe`, doc 03 | Complete |
| 1.7 | Documentation consolidation | One docs set per project, with an index at `vijay-docs/README.md` | `ab5bd20`, `05e7589` | Complete |

**Verified end state:** a file dropped in a source bucket reaches all configured
destinations, and the Knowledge Store page shows the ledger entry.

---

## 4. Stage 2 — Knowledge Products and per-product stores

**Period:** 2026-09-20. **State:** Complete.

A Knowledge Product replaced the single shared collection. Each product has its own
minIO bucket, Qdrant collection, OpenSearch index, and Redis namespace.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 2.1 | Knowledge Product model | Product record, four destinations, and a per-product document bucket | `24d2551` | Complete |
| 2.2 | Universal fanout | One sync writes every destination of the product | `24d2551` | Complete |
| 2.3 | Live pipeline page | Ingestion progress per file, streamed to the page | `24d2551` | Complete |
| 2.4 | Knowledge Store as a view-only mirror | The retrieval project shows the ingestion product state and never writes to it | `4d0601e`, doc 11 | Complete |
| 2.5 | Ingestion profiles | Saved destination and chunking profiles; environment-only connections; copy-on-create | `a3f8b6d`, doc 06 | Complete |
| 2.6 | Text-with-images modality | A profile can store page images next to the text chunks | `a3f8b6d`, `4249ec2` | Complete |
| 2.7 | Chunk strategy select | A strategy list on the profile form, applied on sync | `127ea72` | Complete |

**Verified end state:** two products have separate stores, and a search in one product
never returns a chunk of the other.

---

## 5. Stage 3 — Retrieval, chat, and assistant endpoints

**Period:** 2026-09-20 to 2026-09-24. **State:** Complete.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 3.1 | End-to-end retrieval | Retrieve, rerank, and generate over the Qdrant and OpenSearch stores, with the five blockers fixed | `2b05b4f` | Complete |
| 3.2 | Chat page | Streaming answers, citations, multimodal input, and guardrail feedback | `2b05b4f`, doc 03 | Complete |
| 3.3 | Prompt templates | Create, edit, and delete the system message a pipeline attaches | doc 04 | Complete |
| 3.4 | Assistant model | A pipeline becomes an assistant with a slug and callable endpoints | `02f82e6`, doc 14 | Complete |
| 3.5 | Pipeline builder | Card grid, create dialog, view dialog with copyable endpoints, and a delete warning | `015b420`, doc 02 | Complete |
| 3.6 | Session memory | Redis-backed conversation memory with a query rewrite and an end-session endpoint | `8fdc908`, doc 15 | Complete |
| 3.7 | Strategy selection | Self-reflective and corrective RAG replaced the plain SQL search | `7be85ce` | Complete |
| 3.8 | Reliability fixes | Proxy field loss, cold-index first query, and build context | `1ae92ff`, `b10dec1` | Complete |

**Verified end state:** a turn sent to an assistant endpoint returns an answer with
citations, and a second turn uses the session memory.

---

## 6. Stage 4 — Observability and real-time monitoring

**Period:** 2026-09-21 to 2026-10-13. **State:** Complete.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 4.1 | Chat metrics | Latency, token, and chunk metrics persisted per message | `a300257` | Complete |
| 4.2 | Trace persistence | Pipeline trace rows in Postgres, visible from the message drawer | `3d01f77`, doc 07 | Complete |
| 4.3 | OTEL export | Fan-out to Phoenix and Langfuse, with test and prod trace modes | `8e8aa17`, `9231d28`, doc 16 | Complete |
| 4.4 | Session traces | One trace per session, derived from the session UUID | `8e8aa17` | Complete |
| 4.5 | Real-time monitoring page | Live latency, tokens, and quality for the running pipelines | `3d01f77`, doc 05 | Complete |
| 4.6 | Feedback pipeline | A second collector pipeline that filters chat spans | `bee4770` | Complete |

**Verified end state:** a chat turn appears in Phoenix and Langfuse, and the monitoring
page shows it within one refresh.

---

## 7. Stage 5 — Guardrails

**Period:** 2026-09-21 to 2026-10-13. **State:** Complete.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 5.1 | Guard configuration | Policy definitions, a validator picker, and per-validator settings | `ca48ddb`, doc 08 | Complete |
| 5.2 | Validators | Three Guardrails AI validators and six NeMo rails | `9979476`, doc 08 | Complete |
| 5.3 | Guard traces | Ranked block breakdown, per-validator failures, trace table, and a detail drawer | doc 09 | Complete |
| 5.4 | Guard evaluation | Golden-dataset runs against configurations, with missed and false counts | `432db93`, `35db265`, doc 10 | Complete |
| 5.5 | NeMo as the rail engine | The guardrails service runs the rails, not a parallel implementation | `0b8e8d0` | Complete |
| 5.6 | Output guardrail phase | The output phase runs in the official NeMo slot and receives the retrieved passages | `5b62778`, `4a389c7` | Complete |
| 5.7 | Prompt governance | The pipeline's prompt template governs its turns | `18f9c11` | Complete |
| 5.8 | Policy defaults and judge choice | A filled template policy, and the judge model picked from the proxy list | `52cdcb8`, `ee41e56` | Complete |

**Verified end state:** a blocked question shows the failing rail, and a guard evaluation
reports per-run missed and false counts.

---

## 8. Stage 6 — Evaluation engine

**Period:** 2026-09-21 to 2026-10-10. **State:** Complete.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 6.1 | RAGAS metrics | Metric calls run, with the two-second API penalty removed | `ceace7d` | Complete |
| 6.2 | Offline Evaluation page | CSV datasets, a judge choice, and a per-category view | `a2d729a`, doc 06 | Complete |
| 6.3 | RAG triad | Grounded, attributed, and relevant, with the failing stage named | `31d6aa9` | Complete |
| 6.4 | Stage attribution | Per-row metrics map to the retrieval, rerank, or generation stage | `31d6aa9`, design 8.4 | Complete |
| 6.5 | Model classification | LiteLLM models are classified by the mode the proxy reports | `a83fe7b` | Complete |
| 6.6 | Pipeline-driven runs | Retrieval settings and the prompt template come from the evaluated pipeline | `f4ce235` | Complete |
| 6.7 | Golden dataset contract | CSV, JSON, and JSONL, with RAGAS and DeepEval aliases, `turns`, and `kind` | `57fa8ed`, doc 13 | Complete |
| 6.8 | Metrics reference | Retrieval, rerank, and generation metric definitions in one document | doc 12 | Complete |

**Verified end state:** a run scores four metric groups, names the failing stage, and
opens per-row rubrics.

---

## 9. Stage 7 — Platform operations and web scraping

**Period:** 2026-09-24 to 2026-10-15. **State:** Complete.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 7.1 | Container stacks | One compose stack per project | `3c810b5` | Complete |
| 7.2 | Host run | The four apps on the host, the dependencies in Docker, with every override documented | `9729c67`, `00af585` | Complete |
| 7.3 | One shared Qdrant | Both projects read the same server, so the ingestion write is visible to retrieval | `c7435c2`, `c326981` | Complete |
| 7.4 | Run guide | Prerequisites, the service matrix, ports, the environment block, start order, and a troubleshooting table | `vijay-docs/two_project_run.md` | Complete |
| 7.5 | Phase one: web scraping | Per-source webscraping, renamed pages, and a docs refresh | `bdff0a4` | Complete |
| 7.6 | Text-with-images answers | A product that indexed page images answers from them | `4249ec2` | Complete |

**Verified end state:** `scripts/dev.sh` starts both projects against the Docker
dependencies, and the run guide steps reproduce the stack.

---

## 10. Stage 8 — Dataset Fabric and universal golden datasets

**Period:** 2026-10-28. **State:** Complete. Commit `57fa8ed`.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 8.1 | Dataset profiles | A profile with a purpose and an optional pipeline link | `57fa8ed`, doc 20 | Complete |
| 8.2 | Dataset upload | Single-turn and multi-turn files in five formats, from the page | `57fa8ed` | Complete |
| 8.3 | Storage rule | Datasets live in the `dataset-fabric` bucket of the linked Knowledge Product, not in the ingestion destinations | `57fa8ed` | Complete |
| 8.4 | Dataset Fabric API | Create, edit, delete, upload, preview, and row edit | `57fa8ed`, design 11.1 | Complete |
| 8.5 | Universal schema | One contract for CSV, JSON, and JSONL, with framework aliases | `57fa8ed`, doc 13 | Complete |
| 8.6 | Offline Evaluation on profiles | The page selects a profile and a kind instead of an ad hoc upload | `57fa8ed`, doc 06 | Complete |
| 8.7 | Authoring guide | Field rules, the two formats, the metric map, a pre-upload checker, and two LLM prompts | doc 21 | Complete |

**Verified end state:** an uploaded dataset is visible in the Fabric viewer, and the
Offline Evaluation page runs it.

---

## 11. Stage 9 — Dataset Feedback, and the Dataset Validator

**Period:** 2026-11-03. **State:** Complete, with known gaps. Commit `bee4770`.

The stage harvests real chat turns into golden rows. No chat table stores the pipeline a
turn belongs to, so the OpenTelemetry collector is the delivery path.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 9.1 | Collector pipeline | A `traces/feedback` pipeline with a filter for `rag.chat` and `rag.chat.stream` | `otel/otel-collector-config.yaml` | Complete |
| 9.2 | Turn receiver | `POST /v1/traces` parses OTLP JSON and keeps a turn only with a session id, an input, an output, and a pipeline slug | `bee4770`, design 7.3 | Complete |
| 9.3 | Turn store | `conversation_turns` table, unique on `(trace_id, span_id)` so a retry cannot duplicate a turn | migration 008 | Complete |
| 9.4 | Conversation listing | Sessions grouped into single-turn and multi-turn conversations, blocked turns excluded | `dataset_feedback.py` | Complete |
| 9.5 | Row building | A conversation becomes a golden row with provenance metadata | `dataset_feedback.py` | Complete |
| 9.6 | Append path | The row is appended to the newest dataset of its kind, `row_count` is updated, the JSONL snapshot is rewritten, and a superseded CSV or XLSX object is deleted | design 7.5 | Complete |
| 9.7 | Dataset Feedback page | Conversation list, filters, conversation drawer, row drawer, and append | `DatasetFeedbackPage.tsx` | Superseded by 9.10 |
| 9.8 | Row editing | Edit question, answer, or turns, with a kind-mismatch check | `bee4770` | Complete |
| 9.9 | Design document | `design/software-design.md` and its docx copy, including this week's plan | `bee4770` | Complete |
| 9.10 | Rename to Dataset Validator | The page, the route and the API lose the Feedback name. `/dataset-feedback` redirects | working tree | Complete, uncommitted |
| 9.11 | Product and author first | The page asks for the Knowledge Product, then synthetic or manual profiles | working tree | Complete, uncommitted |
| 9.12 | Profile drawer and pipeline link | A floating window shows the profile contents and links it to a pipeline. The default is "Yet to be linked" | `pipeline_slug`, `pipeline_name` on the profile | Complete, uncommitted |
| 9.13 | Active-version editor | The editor shows only the active version, one kind toggle per dataset present, every row and column, row editing, and trace append | working tree | Complete, uncommitted |

**Known gaps in this stage:** no tests on the write paths (A1), no Docker collector
health check (A2), no paging on the conversation list (A3), no provenance in the Fabric
viewer and no row delete (A4), and unlabeled drawer fields (A5). These are the
workstream A tasks of the week plan.

---

## 12. Stage 10 — Synthetic Dataset Creator (current stage)

**Period:** 2026-11-05. **State:** Complete, uncommitted. Commit `1896223` holds the
first part; the rest is in the working tree.

The stage adds a page that generates single-turn and multi-turn datasets from a
Knowledge Product's documents, using the DeepEval Synthesizer. The output is a normal
Dataset Fabric dataset, so Offline Evaluation runs it without a change.

| ID | Substage | What it delivers | Evidence | State |
|---|---|---|---|---|
| 10.1 | Page and profile list | `/synthetic-datasets` with a profile list and a profile create form | `1896223` | Complete |
| 10.2 | Versions | One version per generation run, with a fixed model, kind set, filtration, and evolution settings | `1896223` | Complete |
| 10.3 | Generation | The eval worker runs `run_synthesis`; each kind becomes one `golden_datasets` row with its own configuration and row count | `tasks.py`, `run_synthesis` | Complete |
| 10.4 | Kind controls | Single-turn only, multi-turn only, or both; regenerate and delete one kind | `1896223` | Complete |
| 10.5 | Row inspection | Read the rows of a kind from the version panel | `1896223` | Complete |
| 10.6 | Fabric output | The datasets are written to the profile's Dataset Fabric storage, not to the ingestion destinations | migration 009 | Complete |
| 10.7 | Product scope | The page asks for the Knowledge Product first and lists only that product's profiles | working tree | Complete, uncommitted |
| 10.8 | Active version | One active version per profile, with an `Active` column in the versions table. A profile itself carries no active flag | working tree, migration 012 | Complete, uncommitted |
| 10.9 | Fabric chooser removed | The version creator inherits the fabric profile of the synthetic profile; the manual chooser is gone | working tree | Complete, uncommitted |

### 12.1 What changed in the working tree

| File | Change |
|---|---|
| `models/synthetic_dataset.py` | `is_active` on versions; `fabric_profile_id` on profiles |
| `alembic/versions/010_synthetic_active_and_fabric.py` | The version active index, the fabric column, and the backfill |
| `alembic/versions/011_profile_source_and_version_link.py` | The `source` column, the per-source name rule, and the version link rename |
| `alembic/versions/012_drop_profile_active.py` | Removes the profile active column and its index |
| `repositories/synthetic_dataset_repository.py` | The version activate method, the source filter, and the fabric inheritance on create |
| `routes/synthetic_datasets.py` | The version activate route; the version create no longer reads a fabric profile |
| `frontend/src/pages/SyntheticDatasetPage.tsx` | Product picker, filtered profile list, active version column |
| `frontend/src/api.ts` | The two activate clients |
| `frontend/src/components/StatusBadge.tsx` | The `active` label |
| `frontend/src/index.css` | Card actions, the active border, the six-column version table |
| `tests/unit/test_synthetic_datasets.py` | The obsolete fabric-mismatch test is deleted |

### 12.2 Verification of this stage

| Check | Result |
|---|---|
| Version activation | v5 became active; v7 became inactive |
| `pytest tests/unit` | 295 pass, 6 known failures |
| `tsc -b` and `vite build` | Clean |
| Screenshots at 1280 px | Product picker, profile cards, versions table, and creator all render as intended |

### 12.3 Open item on this stage

The active version is stored and enforced, but no consumer reads it. Offline Evaluation
still lists every dataset of a kind. This is a design decision to make, not a defect.
A profile carries no active state: it is a folder of versions.

---

## 13. This week's plan — state

The plan is in `design/software-design.md` section 14. It has two workstreams and ten
tasks.

| Task | Workstream | What it adds | Planned day | State |
|---|---|---|---|---|
| A1 | Dataset Feedback | Unit and integration tests for the edit and append paths | Mon 11-03 | Planned |
| A2 | Dataset Feedback | Docker collector reachability, a health route, and a page header fact | Tue 11-04 | Planned |
| A3 | Dataset Feedback | Offset paging on the conversation list, filters kept across pages | Wed 11-05 | Planned |
| A4 | Dataset Feedback | Provenance on a golden row, and a row delete | Thu 11-06 | Planned |
| A5 | Dataset Feedback | Drawer accessibility: labels, focus, Escape, keyboard save | Fri 11-07 | Planned |
| B1 | Offline Evaluation | Reproduce and fix the six failing tests | Mon 11-03 | Planned |
| B2 | Offline Evaluation | Dataset selector instead of the newest-of-kind rule | Tue 11-04 | Planned |
| B3 | Offline Evaluation | Run cancel and stale-run recovery | Wed 11-05 | Planned |
| B4 | Offline Evaluation | Baseline comparison with a delta table | Thu 11-06 | Planned |
| B5 | Offline Evaluation | Run export in JSONL and CSV | Fri 11-07 | Planned |

State of the week as of 2026-11-05: the ten tasks are not started. The days from Monday
to Wednesday went to the Synthetic Dataset Creator. B1 is the first task to pick up,
because the six failures hide any new regression.

---

## 14. Known issues and risks

| Area | Issue | Effect | Owner task |
|---|---|---|---|
| Tests | Six unit tests fail on stale expectations | A real regression is hard to see | B1 |
| Tests | No test calls the Dataset Feedback edit path | A JSONB bug reached the browser once | A1 |
| Feedback | The conversation list has a limit and no paging | A busy pipeline hides older sessions | A3 |
| Feedback | A blocked turn is dropped | A refusal cannot become a golden row | None, by design |
| Feedback | No row provenance in the Fabric viewer | A reviewer cannot trace a row to its conversation | A4 |
| Feedback | A wrong row cannot be deleted from the page | The dataset must be repaired by a new upload | A4 |
| Feedback | A Docker collector cannot reach a host API without `extra_hosts` | Delivery is verified only with the local binary | A2 |
| Feedback | Drawer fields have no labels | Accessibility audit fails | A5 |
| Evaluation | The page uses the newest dataset of a kind | An older upload cannot be run | B2 |
| Evaluation | No cancel and no timeout | A dead worker leaves a run in `running` | B3 |
| Evaluation | No run comparison | A change cannot be read as a delta | B4 |
| Evaluation | `image_vision` is not evaluable | Vision answers are scored only in chat metrics | Backlog |
| Synthetic | The active version has no consumer | The page shows a marker that changes no behaviour | Decision |
| Synthetic | The stage is uncommitted | Work is not on the remote | Commit |
| Repo | `vision_test.py` and three screenshots are untracked at the root and in `outputs/` | Noise in the status | Cleanup |

---

## 15. Decisions to make

| Decision | Options | Default |
|---|---|---|
| What reads the active profile and version | Offline Evaluation preselects it; the assistant preselects it; both; no consumer | Preselect in Offline Evaluation |
| Dataset Feedback paging size | 25, 50, or a user choice | 25 |
| Run comparison threshold | A fixed drop on `hit@5` and `faithfulness`, or a per-metric threshold | Fixed, 0.05 |
| Row delete authority | Any reviewer, or a role check | Any reviewer, until a role model exists |

---

## 16. How to keep this document current

1. After each commit, add the hash to the substage it completes.
2. When a planned task starts, change its state to In progress.
3. When a stage closes, record the verification command and its result.
4. Keep the snapshot table true: commit count, test counts, and page count.
