# 14 — Assistant Pipelines & Callable Endpoints

**Last updated:** 2026-09-21

## 1. Executive Summary & What an Assistant Is

An **assistant** is one pipeline record on the ingestion service, exposed as a callable chat endpoint by
the retrieval service. Any future project calls it over HTTP. No adapter code is needed.

One assistant holds:

| Part | Required | Notes |
|---|---|---|
| One pipeline record | yes | `pipelines` table, ingestion service |
| One slug | yes | derived from the name; the external identifier |
| One Knowledge Product | yes | the stores it reads |
| One RAG strategy | yes | `vector`, `lexical`, `relational` or `hybrid` |
| One chat model | yes | the LiteLLM alias that answers |
| One prompt template | no | becomes the system message |
| One guardrails config | no | checks the input and the output |

**An assistant owns no documents.** It writes nothing and holds no collection of its own. The pipeline
record's `qdrant_collection` is nullable for this reason. Every chunk it reads comes from the Knowledge
Product's destination stores.

A pipeline becomes an assistant when its `rag_strategy` is one of `vector`, `lexical`, `relational` or
`hybrid`. The ingestion payload reports this as `is_assistant`.
(`rag-ingestion-manager/backend/apps/api/routes/pipelines.py`)

| Service | Port | Path | Shape |
|---|---|---|---|
| Ingestion manager | `8007` | `/api/pipelines/{uuid}` | the pipeline record |
| Retrieval manager | `8001` | `/api/assistants/{slug}` | the resolved assistant |

The two are different surfaces on purpose. Port `8007` already owns `/api/pipelines/{uuid}`, so the
assistant routes live on `8001` and no caller can mix them up.

---

## 2. Resolution

### The slug

The slug is a URL path segment. The API derives it from the pipeline name: lower case, every run of
non-alphanumeric characters becomes one hyphen, trimmed to 64 characters. An empty result becomes
`assistant`. A slug that a different pipeline already holds gets a numeric suffix, so two assistants can
share a name stem.

The record stays available on the ingestion service:

```bash
curl -X GET http://localhost:8007/api/pipelines/by-slug/resume-assistant
```

A miss answers `404` with code `PIPELINE_NOT_FOUND`. The route is declared **before** `/{pipeline_id}`,
because FastAPI matches in declaration order and a later declaration would parse `by-slug` as a UUID.

The route returns the pipeline plus a nested `knowledge_product` object. That object carries `id`,
`name`, `status`, `chunk_strategy`, `text_embedding_model` and `destinations[]`.

### Store resolution

At every call the retrieval service resolves the assistant in
`backend/apps/rag-api/src/rag_api/routes/assistants.py` (`_resolve_assistant`):

1. `GET {ingestion_service_url}/api/pipelines/by-slug/{slug}` on port `8007`, 10-second timeout.
2. Stop when `is_assistant` is false, with `422 NOT_AN_ASSISTANT`.
3. Read the enabled destinations and take the store names from their config
   (`libs/rag-core/src/rag_core/assistant.py`, `stores_for_product`).
4. Check that every store the chosen strategy needs exists (`resolve_strategy`). A missing store answers
   `422 RAG_STRATEGY_UNAVAILABLE`.

The store names come from the Knowledge Product's destinations:

| Destination type | Config key read | Store field | Derived name |
|---|---|---|---|
| `vector_qdrant` | `config.collection_name` | `qdrant_collection` | `kp_<product-slug>_<id8>` |
| `lexical_opensearch` | `config.index_name` | `opensearch_index` | `kp_<product-slug>_<id8>` |
| `relational_pgvector` | `config.schema_name`, `config.table_name` | `pg_schema`, `pg_table` | schema `kp_<product-slug>_<id8>`, table `chunks` |
| `cache_redisvl` | none | none | serves no strategy |

The fanout derives every store name as `kp_<product-slug>_<id8>`. `cache_redisvl` never contributes a
strategy. It caches answers, so it holds no searchable copy of the chunks.

`stores_for_product` returns a `KpStores` object with four fields: `qdrant_collection`,
`opensearch_index`, `pg_schema`, `pg_table`. `pg_table` falls back to `chunks`.

Only **enabled** destinations count. A product with a disabled Qdrant destination has no
`qdrant_collection`, so the `vector` and `hybrid` strategies are unavailable for it.

---

## 3. Endpoint Reference

All routes live on port `8001` and take the shared API key dependency. Send `X-API-Key` when
`API_KEY` is set. The native routes carry the `/api` prefix. The OpenAI-compatible route carries `/v1`.

Every turn you send is tagged **`prod`**, because the backend reads the trace mode from an
`X-RAG-Trace-Mode: test` header and **a request without that header is production**. Do not send the
header from an integrating system: it exists so that a turn sent from the Chat page while somebody
tries a pipeline is distinguishable from real traffic. See
[16 — Observability and Tracing](./16_observability_tracing.md).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/assistants/{slug}` | The resolved configuration. No secrets. |
| `POST` | `/api/assistants/{slug}/chat` | Native chat, one JSON answer. |
| `POST` | `/api/assistants/{slug}/chat/stream` | Native chat, server-sent events. |
| `POST` | `/v1/assistants/{slug}/chat/completions` | The OpenAI chat-completions shape. |
| `GET` | `/api/assistants/{slug}/sessions/{session_id}` | What the assistant remembers for one session. |
| `DELETE` | `/api/assistants/{slug}/sessions/{session_id}` | End the session and clear its memory. |

The last two exist only when the product's Redis destination is enabled. See
[15 — Assistant Session Memory](./15_assistant_session_memory.md).

### 3.1 `GET /api/assistants/{slug}`

Response fields:

| Field | Meaning |
|---|---|
| `slug` | the external identifier |
| `name`, `description` | from the pipeline record |
| `chat_model` | the resolved chat model |
| `strategy` | the strategy in force |
| `strategies_available[]` | `{id, label, description}` per strategy the product can serve |
| `knowledge_product` | `{id, name, status, chunk_strategy, text_embedding_model}` |
| `stores` | `{qdrant_collection, opensearch_index, pg_schema, pg_table}` |
| `prompt_template_id`, `guardrails_config_id` | the attached ids, or null |
| `session_memory` | `{enabled, ttl_seconds, reason}`. `enabled` is the product's Redis destination; `reason` explains `false` |
| `endpoints` | `{chat, chat_stream, openai_base_url, session_get, session_end}`, relative paths |

```bash
curl -X GET http://localhost:8001/api/assistants/resume-assistant
```

### 3.2 `POST /api/assistants/{slug}/chat`

Request body:

| Field | Type | Notes |
|---|---|---|
| `query` | string | required, the user question |
| `session_id` | UUID | optional; continues an existing session |
| `guardrails_config_id` | UUID | optional; overrides the pipeline's config |
| `retrieval_mode` | string | optional; `hybrid`, `dense` or `sparse`. Default `dense` |
| `retrieve_limit` | int | optional, 1–50 |
| `rerank_enabled` | boolean | optional |
| `rerank_model` | string | optional |
| `top_k` | int | optional, 1–50 |

Response body, the same shape as `POST /chat`: `message_id`, `session_id`, `answer`, `sources[]`,
`trace_id`, `metrics_status`. Each source is `{source_locator, chunk_index, rerank_score}`.

`retrieval_mode` sets the Qdrant search mode and defaults to `dense`, because the fanout writes no
sparse vectors. A request that asks for `hybrid` while the product has no Qdrant collection falls back
to `dense`. The **strategy**, not this field, decides which stores the retriever reads.

```bash
curl -X POST http://localhost:8001/api/assistants/resume-assistant/chat \
  -H 'Content-Type: application/json' \
  -d '{"query": "What award did Rohan receive at Amazon?"}'
```

### 3.3 `POST /api/assistants/{slug}/chat/stream`

The same request body. The response is `text/event-stream`. Each frame is one JSON object. Frame types:

| Type | Payload |
|---|---|
| `status` | `message`, for example `Retrieving context` |
| `token` | `content`, one answer fragment |
| `done` | `metadata` with `answer`, `sources`, `route` |
| `session` | `session_id`, `message_id`, `route`, `metrics_status` |
| `blocked` | the block copy, `blocked_by_guard`, `blocked_on` |
| `error` | `content`, the failure text |

```bash
curl -N -X POST http://localhost:8001/api/assistants/resume-assistant/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"query": "What award did Rohan receive at Amazon?"}'
```

### 3.4 `POST /v1/assistants/{slug}/chat/completions`

Request body, the OpenAI subset this route honours:

| Field | Type | Notes |
|---|---|---|
| `model` | string | optional, ignored |
| `messages` | array | required; the last `role=user` message carries the question |
| `stream` | boolean | default `false` |
| `temperature` | float | optional |
| `max_tokens` | int | optional |
| `user` | string | optional |

A body with no user message that carries text answers with the OpenAI error shape and code
`MISSING_USER_MESSAGE`.

```bash
curl -X POST http://localhost:8001/v1/assistants/resume-assistant/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "assistant", "messages": [{"role": "user", "content": "What award did Rohan receive at Amazon?"}]}'
```

| Mode | Response |
|---|---|
| `stream: false` | `{"id": "chatcmpl-…", "object": "chat.completion", "created": <unix>, "model": "<slug>", "choices": [{"index": 0, "message": {"role": "assistant", "content": "<answer>"}, "finish_reason": "stop"}], "usage": {…}}` |
| `stream: true` | `chat.completion.chunk` frames per token, one final chunk with `finish_reason: "stop"`, then `data: [DONE]` |

The `usage` counts are all zero. The route does not tokenise the answer.

### 3.5 Errors

Every assistant error carries a `detail` object with a `code` and a `message`. The `401` row is the
shared auth dependency, whose detail is a plain string instead.

| Status | Code | Cause |
|---|---|---|
| `404` | `ASSISTANT_NOT_FOUND` | No pipeline has this slug. |
| `404` | `PROMPT_TEMPLATE_NOT_FOUND` | The attached template id no longer exists. |
| `422` | `NOT_AN_ASSISTANT` | The slug names a legacy ingestion pipeline. |
| `422` | `RAG_STRATEGY_UNAVAILABLE` | A store the strategy needs is missing. `detail.missing_destinations` names it. |
| `503` | `INGESTION_SERVICE_UNAVAILABLE` | The ingestion service on `8007` is unreachable. |
| `401` | `Invalid or missing API key` | `API_KEY` is set and the header is absent or wrong. Plain string detail. |

A different non-`200` answer from the ingestion service passes through with code
`INGESTION_SERVICE_ERROR` and the first 500 characters of the upstream body.

`503` is the case to handle first in a caller. The retrieval service cannot resolve a slug without the
ingestion service, so an ingestion outage makes every assistant route fail with this code.

```bash
curl -i -X POST http://localhost:8001/api/assistants/does-not-exist/chat \
  -H 'Content-Type: application/json' \
  -d '{"query": "hello"}'
```

---

## 4. OpenAI Compatibility

Point an OpenAI SDK client at the **base URL** `http://localhost:8001/v1/assistants/{slug}`. The SDK
appends `/chat/completions`, which is the route in Section 3.4. The copyable value comes from
`assistantBaseUrl(slug)` in `frontend/src/api.ts`.

The service sets no `API_KEY` by default, so the key value is unused. The SDK still requires a
non-empty string, so pass a placeholder. When the deployment sets `API_KEY`, send it as `X-API-Key`
through the SDK's default headers.

### Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8001/v1/assistants/resume-assistant",
    api_key="unused",  # the SDK requires a value; the service sets no API_KEY
    # default_headers={"X-API-Key": "…"},  # add this when the service sets API_KEY
)

completion = client.chat.completions.create(
    model="assistant",
    messages=[{"role": "user", "content": "What award did Rohan receive at Amazon?"}],
)
print(completion.choices[0].message.content)

stream = client.chat.completions.create(
    model="assistant",
    messages=[{"role": "user", "content": "What award did Rohan receive at Amazon?"}],
    stream=True,
)
for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="")
```

### JavaScript

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8001/v1/assistants/resume-assistant",
  apiKey: "unused", // the SDK requires a value; the service sets no API_KEY
  // defaultHeaders: { "X-API-Key": "…" }, // add this when the service sets API_KEY
});

const completion = await client.chat.completions.create({
  model: "assistant",
  messages: [{ role: "user", content: "What award did Rohan receive at Amazon?" }],
});
console.log(completion.choices[0].message.content);
```

**The route is single-turn.** It reads the last `role=user` message and ignores every earlier turn. Send
one question per call. Multi-turn memory through this route needs a `session_id` extension field, not
`messages` parsing.

---

## 5. Strategies

The strategy decides which store the assistant reads. It is set on the pipeline and editable at any
time. Its allowed values are exactly the strategies the product's enabled destinations can serve
(`strategies_for_product`).

| Strategy | Store read | Needs enabled | Good for |
|---|---|---|---|
| `vector` | Qdrant dense vectors | `vector_qdrant` | Meaning-based questions and paraphrases. |
| `lexical` | OpenSearch BM25 | `lexical_opensearch` | Exact terms, names, codes and rare words. |
| `relational` | PostgreSQL pgvector | `relational_pgvector` | Cosine order over rows a SQL store already holds. |
| `hybrid` | Qdrant dense **and** OpenSearch BM25 | both of the above | The best default when both stores exist. |

| Label in the UI | Description shown |
|---|---|
| `Vector search` | Qdrant dense vectors |
| `Keyword search` | OpenSearch BM25 |
| `SQL search` | PostgreSQL pgvector |
| `Hybrid` | Vector and keyword, fused with reciprocal rank fusion |

Reader modules:

| Strategy | Reader |
|---|---|
| `vector` | `libs/vector-core/src/vector_core/search.py` |
| `lexical` | `libs/vector-core/src/vector_core/lexical.py` |
| `relational` | `libs/vector-core/src/vector_core/relational.py` |
| dispatch | `libs/retrieval-core/src/retrieval_core/kp_retriever.py` |

### Reciprocal rank fusion

`hybrid` asks each store for the same number of hits, then fuses the two rankings
(`reciprocal_rank_fusion`, `libs/vector-core/src/vector_core/relational.py`). Each list contributes
`1 / (60 + rank)` per chunk. Rank starts at 1 for the best hit. The constant `60` is the value the RRF
paper and OpenSearch's own implementation use.

A chunk is identified across the stores by the key
`(source_id, file_key or source_locator, page_index, chunk_index)`. The fanout writes the same
`file_key` to every destination, so this key identifies one chunk in Qdrant, OpenSearch and pgvector.

A chunk that ranks well in both lists outranks one that ranks well in only one. That is the point: the
two stores measure different kinds of relevance. The surviving record is the one with the highest
single-store score, and its `retrieval_score` becomes the fused value. The fused list is sorted
descending and cut to the request's limit.

The Qdrant store for knowledge products is a **different server** from the scraper's. `Settings` field
`qdrant_kp_url` holds it and falls back to `qdrant_url`. The fanout writes dense vectors only
(`enable_sparse=False`), so for an assistant `hybrid` means Qdrant dense fused with OpenSearch BM25.

**`hybrid` needs both destinations enabled.** `resolve_strategy` answers `422 RAG_STRATEGY_UNAVAILABLE`
when either store name is absent.

---

## 6. Guardrails and Prompt Templates at Call Time

### Guardrails

`guardrails_config_id` on the request **wins over** the pipeline's value
(`body.guardrails_config_id or pipeline["guardrails_config_id"]`). A caller can therefore test a
different config without editing the pipeline.

A block returns `200` with the block copy, not an error status. The native chat response carries the copy
in `answer`, and the source list still holds the retrieved chunks. The stream reports a `blocked` frame
with `blocked_by_guard` and `blocked_on`, and its `session` frame carries `route: "blocked"`. The
non-streaming response has no `route` field. The copy for the `ban_list` guard at the input phase reads:

> This message was blocked because it contains a banned word or phrase.

`GET /guardrails/traces?config_id=…` on `8001` records the blocked turn.

### Prompt templates

`_system_prompt_for` reads `pipeline["prompt_template_id"]` from the `prompt_templates` table through
`PromptRepository`. A template that no longer exists answers `404 PROMPT_TEMPLATE_NOT_FOUND`.

The template content becomes `ChatRequest.system_prompt`, and `build_rag_prompt` uses it as the system
message. The retrieved passages and the user question keep their existing user-message shape. There are
no `{context}` or `{question}` placeholders to fill in. An assistant with no template falls back to
`RAG_SYSTEM_PROMPT`.

The guardrails config and the prompt template are independent. Either, both or neither can be attached.

---

## 7. Worked Example

This path runs live. The check script `rag-retrieval-chat-manager/backend/scripts/e2e_assistant_pipelines.py`
executes it and passes 30 checks.

### Step 1 — Create the product and ingest

Create a Knowledge Product in the ingestion manager with these destinations enabled: `vector_qdrant`,
`lexical_opensearch` and `relational_pgvector`. Then ingest files. The fanout writes one record per
chunk per destination.

The live example is the product `my resumes`, id `e3655bbe-6d34-45df-9c4f-e7742c033a2e`. It holds 30
records in each of its three retrieval stores.

| Store | Name |
|---|---|
| Qdrant collection | `kp_my_resumes_e3655bbe` |
| OpenSearch index | `kp_my_resumes_e3655bbe` |
| pgvector table | `ingestion.kp_my_resumes_e3655bbe.chunks` |

### Step 2 — Create the assistant

```bash
curl -X POST http://localhost:8007/api/pipelines \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Resume Assistant",
    "description": "Answers questions about the resumes in the store.",
    "knowledge_product_id": "e3655bbe-6d34-45df-9c4f-e7742c033a2e",
    "rag_strategy": "hybrid",
    "chat_model": "Gpt-oss-120b",
    "embedding_model": "nvidia-embed-textonly",
    "prompt_template_id": null,
    "guardrails_config_id": null
  }'
```

`embedding_model` is required even for an assistant, because the `pipelines` row holds it as a
non-nullable column. Send the product's `text_embedding_model`, which the `Pipelines` page reads from the
loaded product. The retrieval service embeds the question with the product's model, not with this value,
so they must name the same model.

The response carries the `slug`, `chat_model`, `is_assistant: true` and the nested
`knowledge_product.destinations[]`. With all three retrieval destinations enabled the product can serve
four strategies: `vector`, `lexical`, `relational` and `hybrid`.

Validation codes on this call:

| Code | Cause |
|---|---|
| `CHAT_MODEL_REQUIRED` | `chat_model` is empty. |
| `NO_RETRIEVAL_DESTINATION` | The product has no enabled retrieval destination. |
| `RAG_STRATEGY_UNAVAILABLE` | The strategy needs a destination the product disabled. |
| `KNOWLEDGE_PRODUCT_NOT_FOUND` | The product id does not resolve. |
| `PIPELINE_EXISTS` | `409`; a pipeline already holds this name or description. |

### Step 3 — Read the resolved configuration

```bash
curl -X GET http://localhost:8001/api/assistants/resume-assistant
```

The `stores` block reads back the three names from the table above. The `strategies_available` list
holds the four entries.

### Step 4 — Ask a question

```bash
curl -X POST http://localhost:8001/api/assistants/resume-assistant/chat \
  -H 'Content-Type: application/json' \
  -d '{"query": "What award did Rohan receive at Amazon?"}'
```

The stored rows contain `Received employee of the year award in Amazon Prime division`. All three
stores find it, so every strategy returns a non-empty `sources` list. OpenSearch matches the word
`award` with `_score` 4.23.

### Step 5 — Read the sources

Each `sources[]` entry is
`{"source_locator": "<file>", "chunk_index": <n>, "rerank_score": <float>}`. The `source_locator`
identifies the ingested file, so a caller can cite it.

### Step 6 — Change one component and re-call

Every component stays editable. `PATCH /api/pipelines/{id}` on `8007` accepts `name`, `description`,
`slug`, `rag_strategy`, `chat_model`, `prompt_template_id`, `guardrails_config_id`,
`knowledge_product_id` and `embedding_model`. An explicit `null` for `prompt_template_id` or
`guardrails_config_id` detaches it. Omitting the key leaves it.

The check script moves the assistant through `vector`, `lexical` and `relational`, calls the chat route
after each move, and asserts a non-empty `sources` list every time. That is the check that proves the
strategy choice reaches the read path.

---

## 8. Limits

1. **The OpenAI route is single-turn.** It reads the last `role=user` message and ignores earlier ones.
   Multi-turn memory there needs a `session_id` extension field, not `messages` parsing.
2. **A vision answer does not stream.** When image chunks are present, `generate_stream` makes one
   blocking call and yields the whole answer as a single token event.
3. **A pipeline with a null slug is a legacy ingestion pipeline.** The Chat page keeps the old
   `/chat/stream` path for it, and that path reads `scrape_embeddings` on the scraper's Qdrant. The
   legacy ingestion table and its routes stay, because the Tracking page and the web scraper still read
   pipeline runs.
4. **Always set `chat_model` on the pipeline.** `Settings.chat_model` is still
   `llama-3.3-70b-versatile`, which the proxy does not serve. An assistant always carries an explicit
   `chat_model`, so the UI cannot reach that default. A hand-made legacy `/chat` request with no
   `generation_model` gets a `400`.
5. **The LLM query router and self-corrective RAG are not implemented.** The dead code is gone and the
   UI no longer offers their controls.
6. **The retrieval service must reach port `8007`, `6335`, `9200` and `5432`.** A browser needs only
   `8001`. Defaults live in `libs/shared/src/rag_shared/config.py`: `qdrant_kp_url`, `opensearch_url`,
   `ingestion_service_url`, `ingestion_database_url`, `guardrails_url`.
