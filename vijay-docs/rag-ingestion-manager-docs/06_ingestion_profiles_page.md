# 06 — Ingestion Profiles (Reusable Destination & Chunking Configuration)

**Last updated:** 2026-10-08

## 1. Executive Summary & Page Purpose

The **Ingestion Profiles** area (`frontend/src/pages/IngestionProfilesPage.tsx`, route `/ingestion-profiles`)
manages saved, reusable ingestion settings. An Ingestion Profile holds a set of destination stores and the
chunking parameters. A Knowledge Product picks one profile and **copies** its destinations into its own rows.

- **List page** (`/ingestion-profiles`): one card per profile, plus create, edit and delete. There is no detail
  route.
- **Editor**: one modal, used for both create and edit.

The sidebar entry sits between `Knowledge Fabric` and `Knowledge Hub`.

Backend API: FastAPI router `apps/api/routes/ingestion_profiles.py`, prefix `/api/ingestion-profiles`
(service `rag-ingestion-manager`, host port `8007`; every route sits behind the shared `verify_api_key`
dependency, a no-op unless `API_KEY` is configured).

Three behaviour notes the UI labels do not make obvious:

- **A product copies a profile, and does not follow it later.** The copy happens in
  `POST /api/knowledge-products`. Editing a profile after that does not touch a product that already exists.
- **Store names stay per product.** A profile carries no store name. The copy assigns `kp_<slug>_<id8>` to every
  destination, and no stored value survives. Two products can therefore share one profile and stay isolated.
- **The profile also carries the chunking.** In the `text` modality the fanout splits every source page with
  the profile's `chunk_size`, `chunk_overlap` and `chunk_strategy` and writes one store document per chunk.
  In the `text_images` modality no chunking runs: the fanout renders each document page to an image and
  writes one store document per page.

---

## 2. What an Ingestion Profile Holds

### `ingestion_profiles` (`IngestionProfile`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `name` | text(128) | unique and indexed; a duplicate answers `400` |
| `description` | text, nullable | shown on the card |
| `enabled` | boolean | default `true`; edited in the modal, the list has no toggle |
| `chunk_size` | integer | default `1000`; bounds `100`–`8000` |
| `chunk_overlap` | integer | default `120`; bounds `0`–`2000` |
| `chunk_strategy` | enum | `recursive` (default), `fixed`, `sentence`, `section`, `layout`, `context_aware`, `parent_child`, `contextual`, `page_level`, `sentence_window`. A native PostgreSQL enum type named `chunk_strategy`, not a text column; migration `016_chunk_config_page_images` adds the last three labels. See §6 |
| `modality_mode` | enum | `text` (default) or `text_images` |
| `text_embedding_model` | text(128) | one text embedding model for every destination; default `nvidia-embed-textonly` |
| `image_embedding_model` | text(128) | default `nvidia-embed-multimodal`; embeds the rendered page image on the `text_images` path |
| `chunk_config` | JSONB | not null, default `{}`; the selected strategy's own settings, keyed by parameter name. One JSON column instead of a column per parameter, so a new strategy adds a key and not a migration |
| `created_at`, `updated_at` | timestamp | `updated_at` carries `onupdate=func.now()` |

### `ingestion_profile_destinations` (`IngestionProfileDestination`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `ingestion_profile_id` | UUID | FK to `ingestion_profiles.id`, `ondelete="CASCADE"` |
| `destination_type` | text(64) | one of the four catalogue ids |
| `enabled` | boolean | default `true` |
| `config` | JSONB | tuning and behaviour fields only, merged over the catalogue defaults. Connection values come from the server environment. |
| `created_at`, `updated_at` | timestamp | — |

Unique on `(ingestion_profile_id, destination_type)`, so one row per destination per profile.

### Destination catalogue

| id | name | product store name |
|---|---|---|
| `vector_qdrant` | Dense Vector Store (Qdrant) | `kp_<slug>_<id8>` |
| `lexical_opensearch` | Sparse Vector Store (OpenSearch) | `kp_<slug>_<id8>` |
| `relational_pgvector` | Relational Chunk Store (Postgres) | `kp_<slug>_<id8>` (table stays `chunks`) |
| `cache_redisvl` | Cache Store (Redis VL) | `kp:<slug>:<id8>` |

`graph_neo4j` is **not** in the catalogue. It has no writer and no purger, so no fanout writes to Neo4j. Migration `010_knowledge_products` deleted the stored rows, and
`backend/scripts/purge_neo4j_legacy.py` removed the graph nodes those rows pointed at. The profile editor shows
four destination cards because the catalogue returns four entries.

### Destination fields

The catalogue exposes **15 fields, down from 43**. Connection values, secrets and store names left the
surface. `.env` supplies every connection value through `src/shared/config/settings.py`.

These keys are **removed** and no longer reachable from the UI or from `fields`:
`url`, `api_key`, `endpoint_url`, `auth_type`, `username`, `password`, `connection_url`, `redis_url`,
`litellm_base_url`, `litellm_api_key`, `vector_size`, `distance`, `quantization`, `on_disk_payload`,
`index_algorithm`, `distance_op`, `collection_name`, `index_name`, `schema_name`, `index_prefix`,
and the per-destination `embedding_model`. `hnsw_m` and `hnsw_ef_construct` survived, and they became visible.

| destination | key | group | advanced |
|---|---|---|---|
| `vector_qdrant` | `hnsw_m` | HNSW Tuning | no |
| `vector_qdrant` | `hnsw_ef_construct` | HNSW Tuning | no |
| `lexical_opensearch` | `bm25_k1` | BM25 Tuning | no |
| `lexical_opensearch` | `bm25_b` | BM25 Tuning | no |
| `lexical_opensearch` | `sparse_model` | Lexical | no |
| `lexical_opensearch` | `number_of_shards` | Index | yes |
| `lexical_opensearch` | `number_of_replicas` | Index | yes |
| `lexical_opensearch` | `refresh_interval` | Index | yes |
| `relational_pgvector` | `store_embeddings` | Vectors | no |
| `relational_pgvector` | `table_name` | Table | yes |
| `cache_redisvl` | `ttl_seconds` | Cache | no |
| `cache_redisvl` | `similarity_threshold` | Cache | no |
| `cache_redisvl` | `parent_child_mapping` | Structure | no |
| `cache_redisvl` | `raptor_summaries` | Summaries | yes |
| `cache_redisvl` | `summary_model` | Summaries | yes |

`hnsw_m` and `hnsw_ef_construct` reach the shared Qdrant store and apply at collection creation.
`bm25_k1` and `bm25_b` apply to the lexical index metadata. No field declares a vector dimension any more.

---

## 3. Snapshot, Not Live Reference

### The copy at product creation

`POST /api/knowledge-products` accepts an optional `ingestion_profile_id`. When it is present it is
authoritative, and `req.destinations` is ignored:

1. `_load_profile()` reads the profile with its destinations, or answers `404`.
2. `_destinations_from_profile()` builds one `DestinationConfigInput` per profile destination and passes them to
   `_prepare_destinations()`.
3. `_prepare_destinations()` merges the catalogue defaults, assigns the per-product store names and runs the
   `DESTINATION_STORE_CONFLICT` check. The derived name wins over an input name, so the check cannot fire from
   this path.
4. Each prepared entry becomes a `KnowledgeProductDestination` row on the new product.

A caller that sends `destinations` and no profile keeps the old behaviour, so `scripts/e2e_knowledge_fanout.py`
and the retrieval proxy work unchanged.

`apply_store_namespace()` rewrites the store names during the copy:

| destination | the profile holds | the product gets |
|---|---|---|
| `vector_qdrant` | no store name | `kp_<slug>_<id8>` |
| `lexical_opensearch` | no store name | `kp_<slug>_<id8>` |
| `relational_pgvector` | no store name | `kp_<slug>_<id8>` (table stays `chunks`) |
| `cache_redisvl` | no store name | `kp:<slug>:<id8>` |

`apply_store_namespace()` assigns the derived name unconditionally, so it overwrites a stale stored value. The
profile route never calls it. Only a product carries a store name, and without that rule one profile could not
serve two products.

### No backfill

A product created before this change keeps `ingestion_profile_id = NULL` and keeps its own destination rows. It
keeps ingesting. The list card marks it `Legacy: inline config`. The profile select in the edit dialog is how a
user attaches a profile.

### `POST /api/knowledge-products/{id}/apply-profile`

This route re-copies the linked profile on demand. The body may carry an `ingestion_profile_id`. Without one the
product's current link is used. With no link at all it answers `422`:

```json
{"detail": {"code": "PROFILE_REQUIRED",
            "message": "This Knowledge Product has no Ingestion Profile. Send ingestion_profile_id."}}
```

The route runs these steps in order:

1. Load the product (`404` when it is missing) and resolve the target profile.
2. Re-copy the profile's destinations through `_destinations_from_profile()`.
3. Compare the stored `pipeline_fingerprint` with the profile's current one. The hash covers the chunk size, the
   overlap, the chunk strategy, the `chunk_config`, the modality mode, the text embedding model and the image
   embedding model. A different hash purges **every** destination, because those values change what is written.
   A destination config change alone purges that destination only.
4. Compare the existing rows with the incoming set:
   - `removed` — a row the profile no longer lists,
   - `updated` — a row whose `config` changed,
   - `added` — a row the profile adds.
5. Purge the removed and the updated types **before** the rows change, because the purgers read the old config
   off those rows (`_purge_for_destination_types`).
6. Delete the removed rows, update the changed rows, insert the new rows.
7. Set `product.ingestion_profile_id`, commit, and re-register the product poller. Registration fires one sync,
   so a pipeline change re-writes every file.

The response:

```json
{"status": "applied", "profile_id": "…", "profile_name": "…",
 "added": ["cache_redisvl"], "updated": ["lexical_opensearch"],
 "removed": ["relational_pgvector"], "purged_files": 3}
```

A purge that fails is swallowed: all four purgers catch their own errors and log. The response reports
`purged_files` as the number of purge calls that ran. `updated` names the destinations whose config changed and
`removed` names the destinations the profile no longer lists. A pipeline change puts all four types in the purge
set.

---

## 4. UI Layout & Visual Components

```
+---------------------------------------------------------------------------------+
|  Ingestion Profiles                                                             |
|  Reusable destination and chunking configuration for Knowledge Products.        |
|                                       [ Refresh ]  [ Create Ingestion Profile ] |
+---------------------------------------------------------------------------------+
|  [ Total Profiles ] [ Knowledge Products Using A Profile ] [ Destination         |
|                                                              Catalogue: 4 ]      |
+---------------------------------------------------------------------------------+
|  <profile name>  [N of M destinations]  [Chunk 1000 / 120]  [Chunking: recursive]  [Text only]   |
|                  [DISABLED]                                                                     |
|  <profile name>  [N of M destinations]  [Text + page images]  [Pages: nvidia-embed-multimodal] |
|                  [DISABLED]                                                                     |
|  <description>                                          [ Edit ]  [ Delete ]     |
|  Destination chips:  [ Qdrant ENABLED ]  [ OpenSearch PAUSED ]  [ … ]            |
|  0 Knowledge Product(s) use this profile.                                        |
+---------------------------------------------------------------------------------+
```

Metrics are computed client-side: `Total Profiles`, `Knowledge Products Using A Profile` (the sum of every
`product_count`), and `Destination Catalogue` (`destinationOptions.length`, so always 4).

A card shows the name, a `N of M destinations` badge, a `Chunk <size> / <overlap>` badge, a `DISABLED` badge
when `profile.enabled` is false, the description when present, one chip per destination with an `ENABLED` or
`PAUSED` chip, and the usage line `N Knowledge Product(s) use this profile.`

The badges depend on the modality:

| badge | shown when |
|---|---|
| `Chunk <size> / <overlap>` | only when `modality_mode` is `text` |
| `Chunking: <strategy>` | only when `modality_mode` is `text`; the short label from `formatChunkStrategy()` in `utils/format.ts` |
| `Text + page images` or `Text only` | always; `Text + page images` follows `modality_mode = text_images` |
| `Pages: <image_embedding_model>` | only when `modality_mode` is `text_images` and the model is not empty |

`Edit` and `Delete` live on the card. The list has no per-card enable toggle; `enabled` is edited in the modal.

The empty state shows `IconDatabase`, the heading `No Ingestion Profiles`, one sentence of help, and a
`Create Ingestion Profile` button.

### Delete

`Delete` opens the shared `ConfirmDialog`:

- title `Delete Ingestion Profile?`
- message `Delete '<name>'? Knowledge Products already created keep their own copy of its destinations.`
- details `Destinations: N`, `Chunk size / overlap: S / O`, `Knowledge Products using it: N`

A profile that a product references cannot be deleted. The API answers `409` and the dialog shows that text. The
FK is `SET NULL`, so a delete would leave every referencing product with copied destination rows and no way to
reach the profile again.

---

## 5. Create / Edit Modal

One modal for create (`POST /api/ingestion-profiles`) and edit (`PATCH /api/ingestion-profiles/{id}`).

1. **Profile Name** (required, 1–128 chars, unique → `400`).
2. **Description** textarea.
3. **Profile enabled** checkbox.
4. **Pipeline Stages**: the **Modality** select only, with two options:
   - `Text only (chunks of text and tables)` (`text`),
   - `Text with images (one record per page image)` (`text_images`).

   The hint follows the selection: `Chunking applies, and every chunk is embedded with the text model.` for
   `text`, and `Every document page becomes one record, embedded from the page image, so there is nothing to
   chunk.` for `text_images`. No model of any kind is chosen here.
5. **Chunking**, rendered only when the modality is `text`:
   - the **Chunking Strategy** select, built from `GET /api/ingestion-profiles/chunk-strategies`, so the
     frontend holds no strategy knowledge;
   - the selected strategy's `description` from the catalogue, as the hint below the select;
   - the settings the catalogue declares for that strategy;
   - the **Text Embedding Model** select over the models whose `kind` is `embedding`, with the hint
     `One model for every store. The vector dimension comes from its output.`
6. **Page Images**, rendered only when the modality is `text_images`:
   - the **Multimodal Embedding Model** select over the models whose `kind` is `embedding`, defaulted from the
     deployment's `default_image_embedding_model`;
   - one hint: `Each page is rendered to an image at 150 dpi, stored in the source bucket under _pages/, and
     embedded with this model. The page text rides along for the text stores. A file that renders no page
     image, such as a Word document, keeps text chunks and the text model instead.`
7. **Configure Destination Stores**: one card per catalogue entry, each with an enable checkbox and, when
   enabled, the typed field grid from `components/DestinationConfigFields.tsx`, which delegates the rendering to
   `components/ConfigFields.tsx`. That component is generic over `option.fields` and needed no change. The block
   carries the note
   `Connections come from the server environment. Vector dimensions are derived from the embedding model.`
8. Footer: `Cancel` and a submit reading `Saving Profile...` / `Update Profile` / `Create Ingestion Profile`.

The Chunking block renders the settings the catalogue declares for the selected strategy:

| UI label | stored `chunk_strategy` | settings, in form order |
|---|---|---|
| Recursive Chunking (default) | `recursive` | `chunk_size` 100–8000, default 1000; `chunk_overlap` 0–2000, default 120 |
| Fixed-Size Chunking | `fixed` | the same two |
| Structure-Aware / Document-Aware Chunking | `section` | the same two |
| Semantic Chunking | `context_aware` | `chunk_size` (labelled "Largest Chunk Size"), `chunk_overlap`, `semantic_threshold_type` select over `standard_deviation` (default) / `percentile` / `interquartile`, `semantic_threshold_amount` 0.5–3.0, default 1.0 |
| Parent-Child / Hierarchical Chunking | `parent_child` | `chunk_size` (labelled "Parent Chunk Size (characters)"), `chunk_overlap` (labelled "Parent Chunk Overlap (characters)"), `child_chunk_size` 0–2000, default 0, `child_overlap` 0–500, default 0 |
| Contextual Chunking | `contextual` | `chunk_size`, `chunk_overlap`, `context_model` (a chat model, required), `context_max_tokens` 50–500, default 100 |
| Page-Level Chunking | `page_level` | `max_page_chars` 0–20000, default 0 |
| Sentence-Window Chunking | `sentence_window` | `window_sentences` 1–10, default 2 |

`chunk_size` and `chunk_overlap` are columns of the profile itself. Every other setting travels in
`chunk_config`. Switching strategy keeps what was typed for each strategy, because the form holds one settings
bag per strategy. Switching modality loses nothing.

The retired values `sentence` and `layout` are no longer offered. A sentence-level record comes from
`sentence_window`, and the PDF layout path is what `section` reads. Both stay valid at the API edge, so a
profile that already stores one still reads, still ingests and still renders. The form shows such a value as
`Sentence (retired, use Sentence-Window)` or `Document layout (retired, use Structure-Aware)`, and a save with it
is accepted.

A create opens with `text`, the strategy set to `recursive`, and each strategy's settings seeded from the
catalogue defaults. The page reads the model list, then defaults the text embedding model to the deployment's
`default_embedding_model` and the multimodal model to `default_image_embedding_model`. Both arrive from
`GET /api/knowledge-products/config/litellm-models`. So the form follows the server configuration rather than
the proxy list order.

An edit shows one notice: `Saving does not change the N Knowledge Product(s) already using this profile. Use
Apply Profile on a product to copy the new values.`

Client-side validation, each setting the error banner and returning:

| Condition | Message |
|---|---|
| name empty | `Profile name is required.` |
| `chunk_overlap >= chunk_size` | `Chunk overlap must be smaller than the chunk size.` |
| `text` with no text embedding model | `Select a text embedding model.` |
| `text_images` with no image embedding model | `Select a multimodal embedding model.` |
| `contextual` with no context model | `Contextual Chunking needs a context model.` |
| no destination enabled | `Enable at least one destination.` |

The submit body carries `name`, `description`, `enabled`, `chunk_size`, `chunk_overlap`, `chunk_strategy`,
`chunk_config`, `modality_mode`, `text_embedding_model`, `image_embedding_model` and the full `destinations`
list. `text_embedding_model` is omitted when the modality is `text_images`, so an edit keeps the stored text
model. `image_embedding_model` is `null` when the modality is `text`. `PATCH` **replaces
the whole destination set** when that field is supplied: types absent from the payload are deleted, present types
are updated in place, new types are inserted.

The server repeats both checks. A duplicate name answers `400 Ingestion Profile '<name>' already exists.` A bad
chunk pair answers `422`:

```json
{"detail": {"code": "CHUNK_OVERLAP_TOO_LARGE",
            "message": "Chunk overlap must be smaller than the chunk size."}}
```

`PATCH` validates the **effective** pair, so a request that sends only one half is still checked against the
other stored value.

The server checks the settings of the selected strategy. A `chunk_config` that names a key the strategy does not
declare, holds a value outside its range, or holds a value that is not one of a select's options answers `422`:

```json
{"detail": {"code": "CHUNK_CONFIG_INVALID",
            "message": "'Window Sentences' must be at most 10."}}
```

The server also checks the image embedding model. A `text_images` profile with an explicitly empty
`image_embedding_model` answers `422`:

```json
{"detail": {"code": "IMAGE_EMBEDDING_MODEL_REQUIRED",
            "message": "modality_mode 'text_images' needs an image_embedding_model."}}
```

An absent `image_embedding_model` resolves to `MULTIMODAL_EMBEDDING_MODEL`, so only an empty string fails.
`PATCH` validates against the effective values, so a request that sends only `modality_mode` is still checked
against the stored image embedding model.

A `PATCH` that changes the strategy and sends no `chunk_config` replaces the stored config with the new
strategy's defaults, because the old settings belong to the old strategy. A stored config is only checked when
the caller sends one, so a row that holds a key this version does not know cannot block an unrelated edit.

---

## 6. Chunking, Modality and the Fanout

The fanout has two shapes, because the modality decides the record shape. The `text` modality runs extraction,
the optional strategy pre-pass, chunking, one shared embedding pass and fanout. The `text_images` modality runs
extraction and render, one record per page, one embedding pass over the page images, and fanout.
`universal_fanout.py` owns every stage after extraction.

```
iter_file_pages(render_pages=<modality == "text_images">, render_dpi=150,
                layout=<strategy in {"section", "layout"}>)
        |                      -> FilePage(page_index=3, text=<one page>, image_png=<a PNG, or None>)
        v
text_images: _page_image_records(pages)
                             -> one record per page: modality="image", record_type="page",
                                image_ref={page_index, bucket, key}
                                the PNG is written to <bucket>/_pages/<file_key>/page-<n>.png
                                a page with no PNG takes the text path below
        |
        v
_resolve_chunking(product)   -> (chunk_size, chunk_overlap)
_resolve_chunk_strategy(product) -> "recursive" | "fixed" | ... | "sentence_window"
_resolve_chunk_config(product)   -> the selected strategy's own settings
        |
        v
context_aware only: _context_similarities(pages) -> one batch embedding call per page
contextual only:    _chunk_contexts(pages, ...)  -> one chat call per chunk
        |
        v
_chunk_pages(pages, size, overlap, strategy, config, similarities, contexts)
                             -> one FilePage per record,
                                page_index=3, chunk_index=0..n-1,
                                record_type="chunk"|"parent"|"child"|"window"|"sentence",
                                parent_ref="<page>:<parent chunk_index>"
        |
        v
one store document per record (Qdrant point, OpenSearch doc, Postgres row, Redis key)
```

### Modality modes

`modality_mode` decides what the fanout reads and which model embeds it:

| mode | what is extracted | embedding model |
|---|---|---|
| `text` (default) | selectable text and tables only | `text_embedding_model` |
| `text_images` | one PNG of each document page at 150 dpi, plus the page text | `image_embedding_model` |

- `text` renders no page image, so chunking runs and the text embedding model embeds every chunk.
- `text_images` renders each page to a PNG with `page.get_pixmap(dpi=150)`, writes it to the source bucket at
  `_pages/{file_key}/page-{page_index:05d}.png` (`page_image_object_key`), and embeds it through
  `EmbeddingClient.embed_image_png`.
- One record per page: `modality="image"`, `record_type="page"`, the page's extracted text as `content` and
  `text`, and `image_ref = {page_index, bucket, key}`. `type` stays `text`, so the retrieval consumers keep
  working.
- No chunking runs on that path.
- A page that renders no image takes the ordinary text path with `text_embedding_model` and `modality="text"`.
  Every text format is in that group, and so is a PDF page PyMuPDF cannot rasterise.
- The fanout drops keys under `_pages/` from its own source listing (`drop_generated_page_images`), because they
  are output and not input. Without that rule a rendered PNG would be indexed as text on the next tick.
- The sync summary reports the count of pages that fell back under `pages_without_image`, and the fanout
  publishes one `page_image_missing` event per file.
- `EmbeddingClient.embed_image_png` raises when the model cannot answer. It no longer returns a zero vector of a
  guessed length, because a wrong dimension would poison the collection.
- API validation answers `422 IMAGE_EMBEDDING_MODEL_REQUIRED` when `text_images` has no image embedding model.
- A page whose text is empty is embedded from its image but carries empty `text`, and all four writers skip an
  empty-text record. A scanned page therefore stores no document until OCR supplies its text.

The legacy Pipeline path keeps `render_pages=True`, so it behaves as before.

### Chunking

- `_resolve_chunking(product)` reads the linked profile. A product with no profile falls back to
  `DEFAULT_CHUNK_SIZE = 1000` and `DEFAULT_CHUNK_OVERLAP = 120`, so an old product behaves like the old
  default. It clamps the overlap to `chunk_size - 1`, because a stored row could predate the API bound.
- `_resolve_chunk_strategy(product)` reads `chunk_strategy` off the same profile and defaults to
  `DEFAULT_CHUNK_STRATEGY = "recursive"`.
- `_resolve_chunk_config(product)` reads `chunk_config` off the same profile and returns `{}` when it is absent.
  The chunker clamps each value again, because a stored row can predate a bound.
- `_chunk_pages(pages, size, overlap, strategy, config, similarities, contexts)` splits every page.
  `page_index` keeps the source page and `chunk_index` numbers the records from `0` inside each page. A blank
  page yields no chunk.
- `_plans_for()` routes `parent_child` to `chunk_parent_child()`, `page_level` to `chunk_page()`,
  `sentence_window` to `chunk_sentence_window()` and `contextual` to `chunk_textual()`. Every other strategy
  goes through `chunk_text()`.
- The fanout indexes chunks instead of whole pages. `pages_indexed` in the `knowledge_product_files` ledger
  still counts **source pages**, and the `Pages` column in the UI keeps its meaning.
- When every page is blank the fanout records the file without writing a document. This keeps the ledger honest
  and stops a false `synced` on an empty file.

#### Chunk strategies

`chunk_text(text, chunk_size, chunk_overlap, strategy, *, config=None, similarities=None)` in
`src/ingestion_service/utils/text_splitter.py` is the entry point for the strategies whose records are all one
kind. `chunk_parent_child()`, `chunk_page()`, `chunk_sentence_window()` and `chunk_textual()` return
`ChunkPlan` records instead, because their records are not one kind. The strategy picks the **unit stream** and
the **packing rule**:

| `chunk_strategy` | Units | Packing | Notes |
|---|---|---|---|
| `recursive` (default) | headings and blank-line paragraphs | packed to the window | The original algorithm, kept byte-identical so an existing product re-syncs to the same text |
| `fixed` | none | a hard window every `chunk_size` characters | Ignores structure; the cut lands mid-paragraph |
| `sentence` (retired) | sentences | packed to the window | No longer offered. No sentence is split. An abbreviation such as `e.g.` does not end a sentence, because the next word must start with a capital, digit, quote or bracket |
| `section` | headings and blank-line paragraphs | one chunk per unit | A unit larger than `chunk_size` is cut on word boundaries |
| `layout` (retired) | the PDF's own layout blocks, blank-line separated | one chunk per unit | No longer offered, and now what `section` reads. `page_yielder._layout_text()` reads `page.get_text("blocks", sort=True)`, so a two-column page comes out in reading order and a table region stays separate. A non-PDF format has no layout blocks and behaves like `section` |
| `context_aware` | sentences | packed inside a topic group | `_context_similarities()` embeds every sentence of a page in **one batch request**, then a boundary starts a new group when its cosine similarity falls below the threshold. The profile names the measure: `standard_deviation` below the page mean (default), `percentile` of the page similarities, or `interquartile`. All three read `semantic_threshold_amount` the same way, so a larger amount is the stricter test and yields fewer, larger groups. A stored value outside the catalogue falls back to standard deviation 1.0. A group boundary is never crossed. An unreachable embedding model falls back to the size window alone, so the file still ingests |
| `parent_child` | headings and blank-line paragraphs, then sentences | parents at `chunk_size`, children at `child_chunk_size` or about a third of the parent | Both levels are stored. A child carries `record_type: "child"` and `parent_ref: "<page_index>:<parent chunk_index>"`; the parent carries `record_type: "parent"`. Parent records come first, so the ordinal in `parent_ref` addresses the parent's own `chunk_index`. A parent that fits inside one child window is stored alone, because a child identical to its parent doubles the store for nothing. `child_overlap` repeats characters at the start of the next child |
| `contextual` | headings and blank-line paragraphs | packed to the window, each chunk prefixed with a context sentence | The fanout asks a chat model for one sentence per chunk (`_chunk_contexts()`, one call per chunk), then `chunk_textual()` stores `f"{sentence}\n\n{chunk}"`. A failed call stores the plain recursive chunk, so a model outage degrades the file and does not fail it |
| `page_level` | blank-line paragraphs | one page per record, cut only when the page exceeds the limit | `chunk_page(text, max_page_chars)`. `max_page_chars` of 0 never splits a page, except the 8000-character ceiling the page record is held to. A longer page is cut on paragraph boundaries |
| `sentence_window` | sentences | a window of `2 * window_sentences + 1` sentences, then each sentence inside it | `chunk_sentence_window(text, window_sentences)`. Windows do not overlap, so a sentence belongs to exactly one window. A window record carries `record_type: "window"`; a sentence carries `record_type: "sentence"` and `parent_ref: "<page_index>:<window chunk_index>"`. Windows come first. A window of one sentence is stored alone |

`chunk_overlap` applies to every strategy. It is a parameter, not a strategy: the overlap window carries text
across a boundary, and it does not depend on how the boundary was chosen.

`chunk_strategy` is part of `product.pipeline_fingerprint`, so changing it and pressing **Apply Profile**
purges and re-syncs every destination.

Per-sink effect of chunking:

| Sink | Change |
|---|---|
| Qdrant | one point per chunk; the payload carries the real `chunk_index`, plus `record_type` and `parent_ref` |
| OpenSearch | one document per chunk; the document gained a `chunk_index`, `record_type` and `parent_ref` field |
| PostgreSQL | one row per chunk; the `chunks` table gained `chunk_index INT NOT NULL DEFAULT 0`, `record_type TEXT NOT NULL DEFAULT 'chunk'` and `parent_ref TEXT`, all added on an older table with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| RedisVL | the key became `<prefix>:<source_id>:<file_key>:<page_index>:<chunk_index>`; the JSON value gained `chunk_index`, `record_type` and `parent_ref` |

In the `text_images` modality each sink receives one record per document page instead, with `record_type` of
`page`, the page's extracted text, and `image_ref` carrying `page_index`, `bucket` and `key`.

The store inspector returns `record_type` and `parent_ref` for all four destinations, and the visualizer panels
render them: the lexical list and the Qdrant point panel show a `Record Type` tag (`parent`, or `child -> 0:3`),
the relational row panel and the Redis key panel show the same field. Only the vector and lexical panels tag a
record that is not a plain chunk, so a `recursive` product looks exactly as it did.

Ponytail note on `context_aware`: the topic-shift threshold is a per-page statistic, so no constant has to be
tuned per corpus. The profile picks the measure and the amount. `_CONTEXT_MIN_SENTENCES = 6` in
`text_splitter.py` is the only constant left: below that many sentences a mean and a standard deviation say
nothing, so the strategy uses the size window alone.

**A plain poll does not re-index after a chunking change.** File change detection is etag plus size, so a
chunk-size change does not look like a file change. A store keeps its old documents until the object bytes change
or the user applies the profile. `apply-profile` rebuilds every destination when the pipeline fingerprint
changed (§3).

### One embedding per chunk, and the derived dimension

- The fanout embeds each chunk once per tick and shares the vector with every vector destination.
- The Qdrant writer and the PostgreSQL writer used to embed the same chunk twice.
- The fanout also asserts that every vector in a batch has the same length. The embedding client falls back to a
  local 384-dimension model when the proxy call fails, and that fallback would corrupt a batch.
- **The vector dimension is derived, not configured.** `vector_size` is gone, and no field replaces it. The
  dimension is the length of the embedding-model output.
- One text embedding model per profile (`text_embedding_model`) serves every destination. On the `text_images`
  path `_embed_image_records()` uses `image_embedding_model` for a record with a page PNG, and `_embed_records()`
  uses `text_embedding_model` for a record without one. A batch that holds both logs a
  `fanout_mixed_vector_models` warning, because a collection holds one vector size and one of the two groups
  will fail to store.
- The fanout refuses to recreate an existing Qdrant collection whose dimension disagrees. It raises instead,
  because a recreate would delete every point.

The store inspector returns `modality`, `record_type` and `parent_ref` for Qdrant, OpenSearch, PostgreSQL and
RedisVL. It returns `image_ref` where the store holds it. The RedisVL inspect returns the cached JSON value, so
the stored text and the record type are readable. Qdrant needs no projection, because its payload is returned
whole.

The store inspector projects `chunk_index` for Qdrant, OpenSearch and PostgreSQL. Its OpenSearch window is 200
hits and its Redis window is 200 keys.

---

## 7. Backend APIs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/ingestion-profiles` | list profiles with their destinations and `product_count`, newest first |
| `GET` | `/api/ingestion-profiles/chunk-strategies` | the eight strategies with their settings, as a bare list. Declared before `/{profile_id}` |
| `POST` | `/api/ingestion-profiles` | create a profile; `201` |
| `GET` | `/api/ingestion-profiles/{profile_id}` | one profile with its destinations and `product_count` |
| `PATCH` | `/api/ingestion-profiles/{profile_id}` | partial update; a supplied `destinations` list replaces the whole set |
| `DELETE` | `/api/ingestion-profiles/{profile_id}` | delete an unreferenced profile; returns `{"status": "deleted", "profile_id": "…"}` |
| `POST` | `/api/knowledge-products` | accepts an optional `ingestion_profile_id`; when present it is authoritative |
| `POST` | `/api/knowledge-products/{product_id}/apply-profile` | re-copy the linked profile; returns the applied summary |

`_profile_to_dict()` returns `id`, `name`, `description`, `enabled`, `chunk_size`, `chunk_overlap`,
`chunk_strategy`, `chunk_config`, `modality_mode`, `text_embedding_model`, `image_embedding_model`,
`created_at`, `updated_at`, `product_count` and `destinations`. Each destination entry carries `id`,
`ingestion_profile_id`, `destination_type`, `enabled`, `config`, `created_at` and `updated_at`, sorted by
`destination_type`.

`_product_to_dict()` gained `ingestion_profile_id`, `ingestion_profile_name`, `chunk_size`, `chunk_overlap`,
`chunk_strategy`, `modality_mode`, `text_embedding_model` and `image_embedding_model`. A product with no profile
reports `modality_mode: "text"` and `null` for the rest.

### Errors

| Status | Code | When |
|---|---|---|
| `400` | — (`detail` is a string) | `POST` or `PATCH` with a taken name |
| `404` | — (`detail` is a string) | profile id not found |
| `409` | `PROFILE_IN_USE` | `DELETE` on a profile that a product references |
| `422` | `CHUNK_OVERLAP_TOO_LARGE` | `chunk_overlap >= chunk_size` |
| `422` | `CHUNK_CONFIG_INVALID` | a `chunk_config` key the selected strategy does not declare, a value outside its range, or a value that is not one of a select's options |
| `422` | `IMAGE_EMBEDDING_MODEL_REQUIRED` | `text_images` with an explicitly empty `image_embedding_model` |
| `422` | — (FastAPI validation detail) | `chunk_strategy` is not one of the ten accepted names. The field is a `Literal`, so the request never reaches the column |
| `422` | `PROFILE_REQUIRED` | `apply-profile` with no body and no product link |

The `409` detail carries the usage count:

```json
{"detail": {"code": "PROFILE_IN_USE",
            "message": "Ingestion Profile 'Resume Fanout' is used by 2 Knowledge Product(s). Detach or delete them first.",
            "product_count": 2}}
```

`normalize_destination_payload()` drops unknown `destination_type` values silently, matching the product route.

---

## 8. Data Model & Migration

- New tables: `ingestion_profiles`, `ingestion_profile_destinations`.
- `KnowledgeProduct` gained a nullable `ingestion_profile_id` FK (`ondelete="SET NULL"`) and an
  `ingestion_profile` relationship with `lazy="selectin"`, so every product load also loads its profile at no
  extra round trip.
- The configured-SQLite path adds the new column through the `_ensure_sqlite_columns` list in
  `src/shared/db/session.py`: `("knowledge_products", "ingestion_profile_id VARCHAR(36)")`. Without that entry a
  local run fails with `no such column`. The automatic SQLite fallback is gone; PostgreSQL is the one database.
- The profile columns are SQLite entries too: `modality_mode TEXT DEFAULT 'text'`,
  `text_embedding_model TEXT DEFAULT 'nvidia-embed-textonly'`, `chunk_config TEXT DEFAULT '{}'` and
  `image_embedding_model TEXT DEFAULT 'nvidia-embed-multimodal'`. Without them a local run fails with
  `no such column: ingestion_profiles.modality_mode`. The patcher only adds columns, so the two dropped columns
  stay unused on an old SQLite file.
- The chunk strategy added `chunk_strategy TEXT DEFAULT 'recursive'` in the same list. On PostgreSQL the column
  is a native enum type named `chunk_strategy`, not text. An existing row reads `recursive`, so nothing
  re-indexes and no store changes on the upgrade. The Postgres `chunks` table gained
  `record_type TEXT NOT NULL DEFAULT 'chunk'` and `parent_ref TEXT`, added by `ALTER TABLE ... ADD COLUMN IF NOT
  EXISTS` in the writer, which is the same idempotent path the older columns use.
- Migration `016_chunk_config_page_images` (revision `016_chunk_config_page_images`, down_revision
  `015_source_webscrape`) adds `chunk_config` (`JSONB NOT NULL DEFAULT '{}'::jsonb`) and
  `image_embedding_model` (`VARCHAR(128) DEFAULT 'nvidia-embed-multimodal'`), drops the two columns the old
  figure path used, and runs `ALTER TYPE chunk_strategy ADD VALUE IF NOT EXISTS` for `contextual`,
  `page_level` and `sentence_window`. It is PostgreSQL only. The downgrade restores the two dropped columns and
  drops the two added ones, and leaves the three enum labels in place, because PostgreSQL has no `DROP VALUE`.
- The migration head is `016_chunk_config_page_images`. `init_db()` runs `Base.metadata.create_all`, which
  creates any table that does not exist, so no Alembic revision was needed for the two profile tables
  themselves.
- **The table name `ingestion_profiles` is deliberate.** Migration `008_knowledge_store` spent
  `knowledge_profiles` on the table that migration `010_knowledge_products` renamed to `knowledge_products`, so
  that name would collide with the migration history.
- No data backfill. Products created earlier keep `NULL` and their own destination rows, and they read the
  literal default `text` until the user re-applies the profile.
- An existing profile reads the new `text_embedding_model` column as the literal `nvidia-embed-textonly`, and
  the new `image_embedding_model` column as `nvidia-embed-multimodal`. Its `chunk_config` reads `{}`, and the
  chunker falls back to each setting's declared default. Its products pick the models up on the
  next `apply-profile`. `EMBEDDING_MODEL` and `MULTIMODAL_EMBEDDING_MODEL` in `.env` must name models the proxy
  serves.

---

## 9. Frontend Structure

| File | Role |
|---|---|
| `pages/IngestionProfilesPage.tsx` | the page: cards, metric tiles, create/edit modal, delete dialog |
| `pages/KnowledgeStorePage.tsx` | product list; its create/edit dialog picks the profile |
| `pages/KnowledgeProductPage.tsx` | product detail; profile badges and the `Apply Profile` action |
| `components/ConfigFields.tsx` | generic field renderer over a field spec list, used by the chunk settings and by the destination grid |
| `components/DestinationConfigFields.tsx` | destination field grid; delegates the rendering to `ConfigFields` |
| `components/AppLayout.tsx` | the sidebar entry and the persistent page mount |
| `api.ts` | `IngestionProfile`, `IngestionProfileDestinationConfig`, `IngestionProfileCreateRequest`, `ApplyProfileResult`, `ChunkStrategy`, `ChunkStrategyParam`, `ChunkStrategySpec` |

New functions in `api.ts`: `listIngestionProfiles`, `createIngestionProfile`, `updateIngestionProfile`,
`deleteIngestionProfile`, `getChunkStrategies` and `applyProductProfile`. `parseError` now also maps FastAPI's
`{"detail": ...}` shape into the UI error, for a string detail and for an object with a `message`. API error text
therefore reaches the UI instead of the bare status text.

### Knowledge Hub create/edit dialog

The destination-configuration block was **removed**. The form is now name, description, Ingestion Profile
select, a read-only summary of the chosen profile's enabled destinations and its chunking, Sync Mode, and the
source checkboxes. The schedule stays on the product.

- The select offers every profile. With no profile in the system it shows
  `No Ingestion Profiles yet. Create one first.`
- A `Manage Ingestion Profiles` link opens `/ingestion-profiles`.
- The hint reads `Store names are assigned to this product when it is created.`
- Validation: `Product name is required.`, `Select at least one MinIO bucket source.`,
  `Select an ingestion profile.`
- Create sends `ingestion_profile_id` and no `destinations` key.
- Update sends the same fields minus the profile. When the profile changed it follows with
  `applyProductProfile(productId, profileId)`, because `PATCH` deliberately does not accept the profile.
  Attaching a profile copies rows and purges stores, and that belongs to `apply-profile` alone.
- A product with no profile shows the `Legacy: inline config` badge on its card. A product with one shows the
  profile name as a badge.

### Product detail page

`KnowledgeProductPage.tsx` shows a `Profile: <name>` badge and a `Chunk <size> / <overlap>` badge, both only
when a profile is linked. It also shows a `Modality: Text + images` badge when the profile mode is
`text_images`. An `Apply Profile` button opens `ConfirmDialog` with the title
`Apply Ingestion Profile?` and the body `Destination stores the profile no longer lists are purged and their
files re-synced.` On confirm the page calls `applyProductProfile(productId)` and prints a summary line:

`Applied "<name>": +A added, U updated, R removed, P purged.`

On failure the same line shows the API message.

---

## 10. Verification

- `backend/tests/test_ingestion_profile_chunking.py` — plain pytest with bare asserts, 32 cases.
  `_resolve_chunking` is covered with no profile, with a profile, and with an overlap above the size.
  `_resolve_chunk_strategy` is covered with no profile and with a profile. `_chunk_pages` is covered over one
  long page, over a blank page, and over three pages. `chunk_index` runs from `0` with no gaps and restarts
  inside each page. It also covers `_assign_image_chunk_indexes`, so an image record never collides with a text
  record on the same Redis key.
- The chunk strategies share that file. The default `recursive` path must equal itself, so a stored product
  re-syncs unchanged. `section` keeps every block whole. `fixed` ignores the block boundaries. `sentence` emits
  runs of whole consecutive sentences. `context_aware` starts a chunk at a similarity dip, keeps one topic in
  one chunk, moves the boundary when `semantic_threshold_amount` changes, falls back to standard deviation 1.0
  on a bad stored value, and falls back to the size window when the similarities are absent. `parent_child`
  stores parents and children, gives a short block one parent and no child, honours an explicit
  `child_chunk_size`, and proves that every child's `parent_ref` resolves to a record whose `record_type` is
  `parent`. `page_level` stores one record for a short page and cuts a long page on paragraph boundaries.
  `sentence_window` stores every window before its sentences and points every `parent_ref` at its window.
  `contextual` puts a supplied context sentence in front of its chunk and keeps the plain recursive chunks when
  the context map is empty. `validate_chunk_config` rejects an unknown key, an out-of-range value and a value
  that is not a select option, accepts `{}`, and leaves a retired strategy alone. An unknown strategy name
  raises rather than chunking silently.
- `backend/tests/test_ingestion_modality_resolvers.py` — the modality default from a product with no profile,
  `_resolve_image_embedding_model` with a profile and without one, and the image record's modality and
  reference.
- `backend/tests/test_embedding_image_failure.py` — `embed_image_png` raises when the model cannot answer,
  instead of returning a zero vector of a guessed length.
- `backend/tests/test_page_yielder.py` — `render_pages=True` yields one PNG per PDF page, `render_pages=False`
  leaves the text alone, and `render_dpi` decides the raster size.
- `backend/tests/test_fanout_payload.py` — the payload matches the retrieval contract, and a page record in
  image mode carries `modality == "image"`, `record_type == "page"`, non-empty `text`, and an `image_ref` key
  under `_pages/`.
- `backend/scripts/e2e_ingestion_profiles.py` — the isolation regression proof. It proves that a profile carries
  no store name while the product copy gets `kp_*`, that one source page becomes many documents, that a larger
  `chunk_size` yields one document, that a config change through `apply-profile` moves a store, and that
  `DELETE` answers `409 PROFILE_IN_USE`.
- `backend/scripts/e2e_ingestion_modality.py` — the modality proof. It checks the env-only field surface, the
  derived dimension, a `text` sync, that `text` mode stores no page-image record, and that `text_images` stores
  one object per PDF page under `_pages/` and one record per page whose payload carries `modality == "image"`
  and a non-empty `text`.
- `backend/scripts/e2e_chunk_strategies.py` — the strategy proof. It uploads one structured document and moves
  the same product through `section`, `parent_child`, `fixed`, `context_aware`, `page_level` and
  `sentence_window`, checking after each change that every destination holds the expected record count, that the
  child and sentence records name a parent present in the same store, that a strategy change leaves no stale
  record type behind, and that the four destinations agree on the count. It also proves that an unknown strategy
  name is a `422` and that a profile with no strategy stores `recursive`.

Run them from `rag-ingestion-manager/backend`:

```bash
uv run pytest tests -q
uv run python scripts/e2e_ingestion_profiles.py --source-id <a real source uuid>
uv run python scripts/e2e_ingestion_modality.py --source-id <a real source uuid>
uv run python scripts/e2e_chunk_strategies.py --source-id <a real source uuid>
```
