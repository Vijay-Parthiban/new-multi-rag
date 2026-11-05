# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Four audiences were confirmed. None is ranked above the others.

- **AI engineer building and grading pipelines.** Owns a Knowledge Product end to end: ingests documents, picks a retrieval strategy, chats with the result, then proves quality with datasets. Spends most time in the retrieval app (`5174`).
- **Data or operations analyst.** Uploads and curates source documents, checks that answers are grounded in them, and runs a comparison when asked. Spends most time in the ingestion app (`5173`).
- **Consultant delivering to a client.** Stands the stack up per client, demonstrates answer quality, and tunes it in front of the client. Uses both apps, one deployment per client.
- **Reviewer approving answer quality.** Reads run results and collected turns and decides whether a pipeline may ship. Does not build pipelines.

## Product Purpose

The product turns a document corpus into a queryable knowledge base, serves answers over it, and grades those answers against golden datasets.

Success means an engineer can take a document set, choose a pipeline, show a measured answer-quality result for it, and repeat that measurement after any change, without leaving the deployment.

## Positioning

Four claims, all confirmed as the reason this product exists rather than a neighbouring tool:

1. **A Knowledge Product owns its whole store set.** One product spans its own Qdrant collection, OpenSearch index, SQL schema and Redis namespace. Chat and evaluation read the same stores, so a grade describes the pipeline a user actually hits.
2. **Real turns become graded golden rows.** Collected conversations are curated into datasets, so the evaluation corpus grows from production traffic instead of being authored blind.
3. **Strategies are measured side by side on one corpus.** Vector, lexical, hybrid, self-RAG, corrective and image-vision pipelines are selectable per product and graded against the same datasets.
4. **Synthetic data comes from the product's own chunks.** Generated datasets are built from the indexed corpus, so coverage tracks the documents a client actually loaded.

## Operating Context

- Two applications, two APIs, one data tier. `rag-ingestion-manager` (frontend `5173`, API `8007`) writes the stores; `rag-retrieval-chat-manager` (frontend `5174`, API `8001`) reads them. The retrieval service resolves pipelines and Knowledge Products through the ingestion API.
- Two containers live outside this repository and must run first: a LiteLLM proxy (`4000`) and its database (`5433`). Without them nothing embeds and nothing answers.
- Everything else runs from compose on one machine: Postgres, Qdrant, OpenSearch, Redis, MinIO, an OpenTelemetry collector, and the scraper when it is enabled.
- On Windows, `127.0.0.1` is required in place of `localhost`. `localhost` resolves to IPv6 first and every API call then waits about two seconds.
- A dataset file is a JSONL snapshot in the `dataset-fabric` bucket. The database rows are the working copy, and the object is rewritten when rows change.
- Work is tracked as a branch per feature, evaluated from the app, and documented under `vijay-docs/`.

## Capabilities and Constraints

Confirmed capability:

- Ingestion of files and web sources into per-product destinations, with four sinks: dense vectors, BM25 lexical, relational chunks, and a Redis cache.
- Pipelines with a selectable RAG strategy, embedding model, chunk settings, and optional session memory.
- Chat over a pipeline, with pipeline traces, per-message metrics and guardrails.
- Golden datasets in single-turn and multi-turn form, plus evaluation runs with per-row and per-stage metrics.
- Dataset Fabric, which groups datasets under a profile linked to one pipeline for Offline Evaluation.
- Dataset Feedback, which turns collected production turns into golden rows.
- Synthetic Dataset Creator, which generates dataset versions from a product's indexed chunks and stores them as datasets the evaluator can select.

Confirmed constraints:

- All model calls go through the LiteLLM proxy. The model list, keys and routing live there; no page or worker calls a provider directly.
- A product's data never crosses into another product. Collections, indexes, schemas and buckets are per product. Cross-product comparison is not a goal.
- The stack runs self-hosted on one machine. No capability may require a managed cloud dependency.
- The two frontends stay one surface per app. Ingestion work happens in `5173`; retrieval and evaluation work in `5174`.

Terminology that later work must keep: **Knowledge Product**, **pipeline**, **RAG strategy**, **destination**, **golden dataset**, **dataset profile**, **run**, **version** (a synthetic dataset generation), **turn**.

Open decision, recorded rather than assumed: no single audience is designated primary. Any future prioritisation between the four is a product decision, not an inference.

## Evidence on Hand

- Real corpora are loaded and used for demonstration: SBI policy documents, TCS and ABC insurance policy documents, and résumé sets. Their Knowledge Products and Qdrant collections exist in the dev deployment.
- Reference datasets live in `golden/` (`dataset.json`, `guardrails-dataset.json`).
- Architecture and operational truth live in `vijay-docs/`, `design/software-design.md`, and `PROJECT_OVERVIEW.md`.

Absent, and future work must not invent: public testimonials, customer logos, published benchmarks, pricing, or licence claims.

## Product Principles

1. A grade must describe the pipeline a user actually hits. Evaluation reads the same stores as chat, or the number is not admissible.
2. Every quality claim carries a dataset behind it. A result with no rows is not a result.
3. Keep the operator's knobs visible. Strategy, model, chunking, filters and dataset settings are named on screen, not hidden behind a default.
4. The client's corpus is the only source of content. Never fill a gap with invented documents, answers or figures.
5. Ship self-hosted. A feature that needs a managed service is out of scope until the deployment changes.
