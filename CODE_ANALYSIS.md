# RAG Full Pipeline — Code Analysis

**Last reviewed:** 2026-07-17  
**Scope:** Main application source only (excluded: `node_modules`, `.venv`, `__pycache__`, lockfile noise, generated caches, runtime `data/` artifacts).

Companion doc: [`PROJECT_OVERVIEW.md`](./PROJECT_OVERVIEW.md).

---

## Executive summary

The platform is functionally coherent (ingest → Qdrant → RAG → eval) but suffers from **triplicated vector/infra code**, **auth that is off-by-default and inconsistently wired**, and several **runtime bugs** that will fail specific endpoints or jobs. Highest leverage improvements: fix critical bugs, gitignore secrets, then extract one shared vector + auth library used by all three workspaces.

---

## 1. Critical / high bugs

| ID | Severity | Workspace | Issue | Location |
|----|----------|-----------|-------|----------|
| B1 | **Critical** | ingestion | `auth.py` imports `shared.config.settings` while the rest of the backend uses `src.shared...`. With `PYTHONPATH=/app` this likely **breaks API startup** when auth is loaded. | `ingestion-backend/src/shared/auth.py` |
| B2 | **High** | web-scrapper | `POST /scrapes/query` calls `get_settings()` but **never imports it** → `NameError` at runtime. | `apps/api/src/api/main.py` |
| B3 | **High** | rag-app | `GET /search` is annotated as `list[SearchResultResponse]` but can return a **string** or `list[str]` when image hits exist (broken vision experiment). OpenAPI/validation will fail. | `apps/rag-api/.../routes/search.py` |
| B4 | **High** | web-scrapper | `process_scrape_page` swallows exceptions into a failed payload; caller treats job as success → **retries never run**. | scrapper-core page task path |
| B5 | **High** | web-scrapper | Scrape with **0 discovered links** never schedules finalize → job stuck **RUNNING**. | scrape init / finalize coordination |
| B6 | **Medium** | ingestion | Manual `pipeline_runner` can insert duplicate `(pipeline_id, content_hash)` and violate unique index when same content appears across selected folders. Sync path handles this better. | `pipeline_runner.py` vs `sync_runner.py` |
| B7 | **Medium** | ingestion | Upload `complete_append` does not verify path `file_id` matches upload `target_file_id`. | uploads / chunks service |
| B8 | **Medium** | rag-app | `get_engine()` / `get_session_factory()` create a **new engine/pool per call** (connection churn). | `rag_db` session/database helpers |
| B9 | **Medium** | ingestion UI | Docs/UI claim frequent status refresh; `DirectoryPage` polls ~**5 minutes**. | frontend pages |
| B10 | **Medium** | ingestion | Non-PDF “documents” (docx/images accepted in UI) are read as UTF-8 text → **garbage indexing**. | `page_yielder.py` |
| B11 | **Low–Med** | all | Async FastAPI routes often call **blocking** sync Qdrant/search helpers; unused async variants exist in places. | search routes / vector stores |
| B12 | **Low** | rag-app / scraper | Sparse embedding cache path hardcoded to `/root/.cache/huggingface` while containers may run as non-root. | sparse clients |

---

## 2. Security concerns

| ID | Severity | Issue | Notes |
|----|----------|-------|-------|
| S1 | **High** | **Auth disabled by default** | Empty `API_KEY` → `verify_api_key` allows all traffic on ingestion, scraper, and RAG APIs. |
| S2 | **High** | **`.env` not gitignored** | All three workspace `.gitignore` files omit `.env`. Live `.env` / `.env.rag` / `.env.scraper` exist on disk and are commit risks. |
| S3 | **High** | **Weak default secrets** | Examples: Postgres `crawler:crawler`, Qdrant key `qdrant`, LiteLLM `sk-bot` / `OPENAI_API_KEY=sk-bot`. Fine for local demos only. |
| S4 | **High** | **SSRF / open crawl** | Scraper accepts arbitrary seed URLs with no allowlist, private-IP block, or robots policy. Callers can target metadata endpoints / internal Docker DNS. |
| S5 | **Medium** | **CORS `allow_origins=["*"]`** | Present on all APIs. Ingestion also sets `allow_credentials=True` with `*` (invalid/insecure combination). |
| S6 | **Medium** | **Auth incomplete when enabled** | Frontend `api.ts` does not send `X-API-Key`. Scraper worker link-fetch client and ingestion→scraper client also omit the header. Enabling `API_KEY` breaks the stack. |
| S7 | **Medium** | **No tenant / user isolation** | Chat sessions, eval runs, crawls, scrapes are effectively world-readable if you know UUIDs (or if auth is off). |
| S8 | **Medium** | **Client-controlled model/collection** | Request bodies can override collection and model names → cost abuse / cross-collection reads. |
| S9 | **Medium** | **Infra ports published** | Postgres `5432`, Redis `6379`, Qdrant `6333` exposed on host without hardened auth (Redis often unauthenticated). |
| S10 | **Low–Med** | **Error detail leakage** | `500` responses often include raw exception strings. |
| S11 | **Low–Med** | **Large / sensitive payloads** | Image data URIs stored in Qdrant and chat traces; dataset upload has no explicit size cap. |
| S12 | **Low** | **Supply-chain image** | Ingestion compose / scraper Dockerfile depend on `tharun0511/web-scrapper-wokspace:latest` (typo’d name) for Chromium. |
| S13 | **Inherent** | **Prompt injection** | Retrieved web/file content can influence the LLM; prompts partially mitigate (“only use context”) but do not eliminate risk. |

---

## 3. Duplication inventory (reuse debt)

### 3.1 Cross-workspace (highest cost)

| Concern | Copies | Paths (representative) |
|---------|--------|------------------------|
| Qdrant store | **3** | `ingestion_service/vector/qdrant_store.py`, `web_scrapper/vector/qdrant_store.py`, `vector_core/qdrant_store.py` |
| Filters | **3** | `*/vector/filters.py` in each workspace |
| Hit mapper | **3–4** | scrapper, ingestion, `vector_core`, also `retrieval_core/hit_mapper.py` |
| Sparse BM25 client | **3** | `*/embeddings/sparse_client.py` or `vector_core/sparse_client.py` |
| Dense embed client | **3** | LiteLLM/OpenAI wrappers per workspace |
| API key auth | **3** | Nearly identical `verify_api_key` in each `*/auth.py` |
| DB session factories | **3** | Lazy async/sync engine patterns reinvented |
| Source type constants | **3** | Local `types.py` / shared packages with same literals |

**Drift already visible:** API-key handling (hard fail vs fallback `"qdrant"` vs settings), timeouts (60s vs default), legacy single-vector schema checks, delete APIs, sync vs async search, sparse fallback behavior.

### 3.2 Within-workspace

**rag-app**

- Sync/async search twins (`search_scrape_chunks` / `_async`)
- `GET /search` vs `POST /scrapes/query` vs deprecated `POST /retrieve`
- `SearchResultResponse` ≈ `RAGChunkItem`
- `SourceCitation` duplicated across chat/generate routes
- Vision helpers in both `vector_core` and `generation_core`

**web-scrapper**

- `POST /scrapes/query` and `GET /search` duplicate retrieval
- Direct `client.upsert` in page task bypasses `upsert_batch`

**ingestion**

- Pipeline vs sync runners share indexing concerns with divergent duplicate handling

---

## 4. Design / quality smells

1. **No root shared library** — “copy from scraper” was an explicit plan note; copies were never re-consolidated.
2. **Two compose topologies** with overlapping env files (`.env`, `.env.rag`, `.env.scraper`) increase misconfiguration risk.
3. **Docs drift** — scraper `PROJECT_EXPLAINED.md` still describes older no-auth / no-Qdrant behavior; ingestion README understates unified compose services.
4. **CI gap** — only scraper has CI; pytest is commented out. Ingestion and RAG have no root-visible CI.
5. **Health endpoints behind global API-key dependency** when auth is on — breaks naive probes.
6. **Chat metrics heuristic** invents expected sources from answer token overlap (self-referential IR metrics).

---

## 5. Recommended principles (target state)

1. **DRY at the contract layer** — one package owns Qdrant schema, payload mapping, filters, sparse/dense embed helpers, and search.
2. **Single auth helper + client wiring** — shared `verify_api_key`; every HTTP client (frontend, worker→API, ingestion→scraper) sends `X-API-Key` from config.
3. **Secrets hygiene** — gitignore `.env*`, keep only `.env.example`; no default production secrets.
4. **Fail closed for SSRF** — URL allowlist / block private ranges for crawl seeds in non-dev profiles.
5. **Async correctness** — prefer async Qdrant clients in FastAPI; don’t block the event loop.
6. **Explicit modality support** — reject or convert unsupported upload types instead of UTF-8 dumping binaries.
7. **Observable jobs** — zero-link scrapes must finalize; swallowed errors must re-raise for RQ retries.
8. **Least privilege CORS** — explicit origins; never `*` + credentials.

---

## 6. Reusability roadmap

### Phase 0 — Stabilize (do first)

- Fix B1–B5 (auth import, `get_settings`, `GET /search`, scrape retry/finalize).
- Add `.env` / `.env.*` to all `.gitignore` files (keep examples).
- Align CORS; document that `API_KEY` must be set for any non-local exposure.
- Wire `X-API-Key` through frontend and server-to-server clients.

### Phase 1 — Extract `shared-libs/platform-common`

Create a root installable package (uv path dependency from all three workspaces):

```text
shared-libs/platform-common/
  src/platform_common/
    auth.py              # verify_api_key(expected_key)
    types.py             # SourceType, SearchMode, payload field names
    vector/
      qdrant_store.py    # ensure/upsert/search/delete (sync+async)
      filters.py
      hit_mapper.py
    embeddings/
      dense.py           # LiteLLM embed
      sparse.py          # FastEmbed BM25
```

Each workspace replaces local copies with thin re-exports or direct imports. Update Dockerfiles to `COPY shared-libs/` and add path deps in `pyproject.toml`.

### Phase 2 — Deduplicate APIs & schemas

- One retrieval response model per service; deprecate duplicate routes.
- Shared Pydantic chunk/citation models or generate OpenAPI clients for the frontend.

### Phase 3 — Hardening

- SSRF guards, upload size limits, health-without-auth, connection-pool singletons, CI with unit tests for shared package.

### Phase 4 (optional) — True monorepo

- Root uv workspace or workspace matrix CI; single compose at root; one README.

---

## 7. Priority matrix

| Priority | Action | Impact |
|----------|--------|--------|
| ~~P0~~ | ~~Fix B1, B2, B3~~ | Done |
| ~~P0~~ | ~~Gitignore `.env`~~ | Done |
| ~~P0~~ | ~~Fix scrape zero-link + swallowed errors~~ | Done |
| ~~P1~~ | ~~Shared `platform-common` vector + auth~~ | Done |
| ~~P1~~ | ~~Propagate API key in all clients~~ | Done |
| ~~P2~~ | ~~Dense/sparse embedding clients in `platform-common`~~ | Done |
| ~~P2~~ | ~~SSRF guards on crawl seeds~~ | Done (`ALLOW_PRIVATE_CRAWL_URLS`) |
| P2 | Connection-pool singletons; supported file types only | Index quality / stability |
| P3 | Root CI + doc refresh; rebuild/push scraper image | Maintainability / deploy |

---

## 8. Out of scope / deferred

- Full Kubernetes / Helm packaging
- Multi-tenant IAM (OAuth/OIDC)
- Replacing LiteLLM or Qdrant
- Large frontend redesign

---

## Change log

| Date | Notes |
|------|-------|
| 2026-07-17 | Initial analysis from full source review of three workspaces |
| 2026-07-17 | Started Phase 0+1: shared `shared-libs/platform-common`, critical bug fixes, `.env` gitignore, API-key client wiring |
| 2026-07-17 | Phase 2: consolidated dense/sparse embedding clients into `platform-common`; SSRF guards on crawl seeds (`ALLOW_PRIVATE_CRAWL_URLS` override) |
