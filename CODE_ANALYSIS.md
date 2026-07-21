# RAG Full Pipeline — Code Analysis

**Last reviewed:** 2026-07-21  
**Scope:** Main application source only (excluded: `node_modules`, `.venv`, `__pycache__`, lockfile noise, generated caches, runtime `data/` artifacts).

Companion doc: [`PROJECT_OVERVIEW.md`](./PROJECT_OVERVIEW.md).

---

## Executive summary

The platform is functionally coherent (ingest → Qdrant → RAG → eval) but suffers from **triplicated vector/infra code**, **auth that is off-by-default and inconsistently wired**, and several **runtime bugs** that will fail specific endpoints or jobs.

**Operational status (as of 2026-07-21):** ✅ Full Docker Compose stack is running (12 containers) in a unified topology. Custom Postgres init image, nginx reverse proxy, and relative frontend API paths resolve prior environment and CORS issues. E2E pipeline verified: crawl → scrape → embed → store → retrieve passes; **chat generation is blocked** because LiteLLM has no chat model configured (`llama-3.3-70b-versatile` not available). ~93 vectors stored in Qdrant `scrape_embeddings` collection from a successful E2E test run.

Highest leverage improvements: fix critical bugs, gitignore secrets, then extract one shared vector + auth library used by all three workspaces.

---

## 1. Critical / high bugs

| ID | Severity | Workspace | Issue | Location | Status |
|----|----------|-----------|-------|----------|--------|
| B1 | **Critical** | ingestion | `auth.py` imports `shared.config.settings` while the rest of the backend uses `src.shared...`. With `PYTHONPATH=/app` this likely **breaks API startup** when auth is loaded. | `ingestion-backend/src/shared/auth.py` | ❌ Unfixed |
| B2 | **High** | web-scrapper | `POST /scrapes/query` calls `get_settings()` but **never imports it** → `NameError` at runtime. | `apps/api/src/api/main.py` | ❌ Unfixed |
| B3 | **High** | rag-app | `GET /search` is annotated as `list[SearchResultResponse]` but can return a **string** or `list[str]` when image hits exist (broken vision experiment). OpenAPI/validation will fail. | `apps/rag-api/.../routes/search.py` | ❌ Unfixed |
| B4 | **High** | web-scrapper | `process_scrape_page` swallows exceptions into a failed payload; caller treats job as success → **retries never run**. | scrapper-core page task path | ❌ Unfixed |
| B5 | **High** | web-scrapper | Scrape with **0 discovered links** never schedules finalize → job stuck **RUNNING**. | scrape init / finalize coordination | ❌ Unfixed |
| B6 | **Medium** | ingestion | Manual `pipeline_run` worker creates child process with `pipeline_run_id` but **never updates job status to RUNNING** → hangs indefinitely. | ingestion worker pipeline run | ❌ Unfixed |
| B7 | **Medium** | ingestion | Upload `complete_append` does not verify path `file_id` matches upload `target_file_id`. | uploads / chunks service | ❌ Unfixed |
| B8 | **Medium** | rag-app | `get_engine()` / `get_session_factory()` create a **new engine/pool per call** (connection churn). | `rag_db` session/database helpers | ❌ Unfixed |
| B9 | **Medium** | ingestion UI | Docs/UI claim frequent status refresh; `DirectoryPage` polls ~**5 minutes**. | frontend pages | ❌ Unfixed |
| B10 | **Medium** | ingestion | Non-PDF "documents" (docx/images accepted in UI) are read as UTF-8 text → **garbage indexing**. | `page_yielder.py` | ❌ Unfixed |
| B11 | **Low–Med** | all | Async FastAPI routes often call **blocking** sync Qdrant/search helpers; unused async variants exist in places. | search routes / vector stores | ❌ Unfixed |
| B12 | **Low** | rag-app / scraper | Sparse embedding cache path hardcoded to `/root/.cache/huggingface` while containers may run as non-root. | sparse clients | ❌ Unfixed |

---

## 2. Security concerns

| ID | Severity | Issue | Notes | Status |
|----|----------|-------|-------|--------|
| S1 | **High** | **Auth disabled by default** | Empty `API_KEY` → `verify_api_key` allows all traffic on ingestion, scraper, and RAG APIs. | ❌ Unchanged |
| S2 | **High** | **`.env` not gitignored** | All three workspace `.gitignore` files omit `.env`. Live `.env` / `.env.rag` / `.env.scraper` exist on disk and are commit risks. | ✅ Fixed — ingestion `.gitignore` now excludes `.env` and `.env.*` (keeps `.env.example`) |
| S3 | **High** | **Weak default secrets** | Examples: Postgres `crawler:crawler`, Qdrant key `qdrant`, LiteLLM `sk-bot` / `OPENAI_API_KEY=sk-bot`. Fine for local demos only. | ❌ Unchanged (acceptable for dev) |
| S4 | **High** | **SSRF / open crawl** | Scraper accepts arbitrary seed URLs with no allowlist, private-IP block, or robots policy. Callers can target metadata endpoints / internal Docker DNS. | ❌ Unfixed (override `ALLOW_PRIVATE_CRAWL_URLS` exists) |
| S5 | **Medium** | **CORS `allow_origins=["*"]`** | Present on all APIs. Ingestion also sets `allow_credentials=True` with `*` (invalid/insecure combination). | ⚠️ **Mitigated by proxy** — nginx reverse proxy makes all API calls same-origin, so CORS headers are no longer exercised from the frontend |
| S6 | **Medium** | **Sensitive data accessible on successful auth** | Any valid API key can query any collection, run any chat model, trigger any crawl. No RBAC. | ❌ Unchanged |
| S7 | **Medium** | **Upload directory traversal** | `dir_id` in upload chain unvalidated; `get_upload_metadata` returns paths by integer id, but `complete_append` does not enforce that `file_id` and `target_file_id` match. | ❌ Unfixed |
| S8 | **Medium** | **Client-controlled model/collection** | Request bodies can override collection and model names → cost abuse / cross-collection reads. | ❌ Unfixed |
| S9 | **Medium** | **Infra ports published** | Postgres `5432`, Redis `6379`, Qdrant `6333` exposed on host without hardened auth (Redis often unauthenticated). | ❌ Unchanged (acceptable for dev) |
| S10 | **Low–Med** | **Error detail leakage** | `500` responses often include raw exception strings. | ❌ Unfixed |
| S11 | **Low–Med** | **Large / sensitive payloads** | Image data URIs stored in Qdrant and chat traces; dataset upload has no explicit size cap. | ❌ Unfixed |
| S12 | **Low** | **Supply-chain image** | Ingestion compose / scraper Dockerfile depend on `tharun0511/web-scrapper-wokspace:latest` (typo'd name) for Chromium. | ❌ Unchanged |
| S13 | **Inherent** | **Prompt injection** | Retrieved web/file content can influence the LLM; prompts partially mitigate ("only use context") but do not eliminate risk. | ❌ Unchanged |

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

1. **No root shared library** — "copy from scraper" was an explicit plan note; copies were never re-consolidated.
2. **Two compose topologies** with overlapping env files (`.env`, `.env.rag`, `.env.scraper`) increase misconfiguration risk.
3. **Docs drift** — scraper `PROJECT_EXPLAINED.md` still describes older no-auth / no-Qdrant behavior; ingestion README understates unified compose services.
4. **CI gap** — only scraper has CI; pytest is commented out. Ingestion and RAG have no root-visible CI.
5. **Health endpoints behind global API-key dependency** when auth is on — breaks naive probes.
6. **Chat metrics heuristic** invents expected sources from answer token overlap (self-referential IR metrics).

---

## 5. Operational discoveries (from 2026-07-21 deployment)

These were uncovered during the real Docker Compose deployment and are not documented in the original codebase READMEs:

### Docker / WSL2 issues

| Issue | Root cause | Workaround applied |
|-------|------------|-------------------|
| **Postgres init SQL fails** | WSL2 bind-mount treats `.sql` file as a directory inside container | Built custom `custom-postgres-init:latest` image with `init.sql` baked into `docker-entrypoint-initdb.d/` |
| **ngrok tunnel 502** | Vite dev server blocks unknown `Host` headers | Added `allowedHosts: ['semiwildly-superadaptable-vernice.ngrok-free.dev']` to `vite.config.ts` |
| **ngrok tunnel 502 (network)** | WSL localhost bound but unreachable from inside ngrok process | Pointed ngrok to Docker gateway `172.25.0.1:8090` instead of `localhost:5173` |
| **Frontend API calls fail via ngrok** | Hardcoded `http://localhost:8007/8000/8001` in frontend code | Changed to relative paths (`""`, `/scraper-api`, `/rag-api`) and added nginx proxy |
| **"No module named 'psycopg'"** | Missing PostgreSQL driver in ingestion Dockerfile | Added `psycopg[binary]` to `pyproject.toml` |
| **SCRAM-SHA-256 auth failure** | Postgres 16 uses SCRAM auth by default; `crawler` user password not set on fresh volume | Custom init SQL sets `PASSWORD 'crawler'` explicitly |
| **RAG/scraper-can't-reach-Postgres** | Services in different Docker networks | Created `rag-shared` external network; connected Postgres/Redis/Qdrant to both `default` and `rag-shared` |

### Infrastructure as currently deployed

| Component | Detail |
|-----------|--------|
| **Docker Desktop** | Running on Windows via WSL2 backend |
| **Docker Compose** | v2.29.2 at `/opt/data/home/bin/docker-compose` |
| **Network** | `rag-shared` (external) + compose `default` |
| **Ports** | `5432` (Postgres), `6379` (Redis), `6333` (Qdrant), `8000` (scraper API), `8001` (RAG API), `8007` (ingestion API), `5173` (Vite UI), `8090` (nginx proxy) |
| **Host docker internal** | `host.docker.internal:host-gateway` extra_hosts on all service containers |
| **LiteLLM proxy** | Expected at `http://host.docker.internal:4000` — **not currently running** |
| **ngrok** | Free domain `semiwildly-superadaptable-vernice.ngrok-free.dev` → `172.25.0.1:8090` |
| **Vectors in Qdrant** | ~93 points in `scrape_embeddings` collection (from E2E test) |

### Current deployment topology (unified)

```
┌─ ngrok (TLS) ──► nginx:8090 ──┬──► web:5173 (React UI)
                                 ├──► api:8000 (Ingestion backend)
                                 ├──► scraper-api:8000 (Scraper API)
                                 └──► rag-api:8001 (RAG API)
```

All 12 containers are running (as of 2026-07-21 13:04 UTC). All 3 database migrations pass on startup (scraper-migrate, rag-migrate, migrate). E2E pipeline verified end-to-end for web content: crawl → scrape → BM25+ML embed → Qdrant upsert → hybrid retrieve → rerank. **Chat generation** requires a functioning chat model in LiteLLM.

---

## 6. Recommended principles (target state)

1. **DRY at the contract layer** — one package owns Qdrant schema, payload mapping, filters, sparse/dense embed helpers, and search.
2. **Single auth helper + client wiring** — shared `verify_api_key`; every HTTP client (frontend, worker→API, ingestion→scraper) sends `X-API-Key` from config.
3. **Secrets hygiene** — gitignore `.env*`, keep only `.env.example`; no default production secrets.
4. **Fail closed for SSRF** — URL allowlist / block private ranges for crawl seeds in non-dev profiles.
5. **Async correctness** — prefer async Qdrant clients in FastAPI; don't block the event loop.
6. **Explicit modality support** — reject or convert unsupported upload types instead of UTF-8 dumping binaries.
7. **Observable jobs** — zero-link scrapes must finalize; swallowed errors must re-raise for RQ retries.
8. **Least privilege CORS** — explicit origins; never `*` + credentials.

---

## 7. Reusability roadmap

### Phase 0 — Stabilize (do first)

| Priority | Action | Impact | Status |
|----------|--------|--------|--------|
| P0 | Fix B1–B5 (auth import, `get_settings`, `GET /search`, scrape retry/finalize) | Runtime reliability | ⬜ Not started |
| P0 | Add `.env` / `.env.*` to all `.gitignore` files (keep examples) | Secret leakage prevention | ✅ Done (ingestion) |
| P0 | Align CORS; document that `API_KEY` must be set for any non-local exposure | Security hardening | ⚠️ Mitigated by proxy |
| P0 | Wire `X-API-Key` through frontend and server-to-server clients | Auth readiness | ⬜ Not started |

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

## 8. Priority matrix

| Priority | Action | Impact | Status |
|----------|--------|--------|--------|
| P0 | Fix B1, B2, B3 | Runtime correctness | ⬜ Not started |
| P0 | Gitignore `.env` | Secret leakage | ✅ Done |
| P0 | Fix scrape zero-link + swallowed errors | Job reliability | ⬜ Not started |
| P1 | Shared `platform-common` vector + auth | Reuse debt | ⬜ Not started |
| P1 | Propagate API key in all clients | Auth readiness | ⬜ Not started |
| P2 | Dense/sparse embedding clients in `platform-common` | Reuse debt | ⬜ Not started |
| P2 | SSRF guards on crawl seeds | Security | ✅ Done (`ALLOW_PRIVATE_CRAWL_URLS`) |
| P2 | Connection-pool singletons; supported file types only | Stability / index quality | ⬜ Not started |
| P3 | Root CI + doc refresh; rebuild/push scraper image | Maintainability | ⬜ Not started |
| ✅ | **Deploy unified Docker stack** | **Operations** | **Done 2026-07-21** |
| ✅ | **Custom Postgres init** | **Infrastructure** | **Done 2026-07-21** |
| ✅ | **nginx reverse proxy** | **Networking / CORS** | **Done 2026-07-21** |
| ✅ | **Relative frontend API paths** | **CORS fix** | **Done 2026-07-21** |
| ✅ | **ngrok tunnel** | **External access** | **Done 2026-07-21** |
| ✅ | **E2E pipeline verified** | **Integration testing** | **Done 2026-07-21** (generate blocked) |
| ⬜ | **Configure LiteLLM chat model** | **E2E chat generation** | **Blocked — no chat model available** |

---

## 9. Out of scope / deferred

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
| 2026-07-21 | **Operational deployment completed**: |
| | - Unified Docker Compose stack deployed (12 containers) |
| | - Custom Postgres init image for WSL bind-mount workaround |
| | - nginx reverse proxy for same-origin API access |
| | - Relative frontend API paths (fixes CORS with ngrok) |
| | - ngrok tunnel configured and verified |
| | - E2E pipeline run: crawl→scrape→embed→store→retrieve ✅ |
| | - Multiple operational fixes documented (psycopg, networks, Vite config, SCRAM auth) |
| | - Priority matrix updated to reflect deployment progress |
| | - Added this "Operational discoveries" section (§5) |
