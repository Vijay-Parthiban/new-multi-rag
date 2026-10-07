#!/usr/bin/env bash
# dev.sh — run the app processes on the host, their dependencies in Docker.
#
# The apps hot-reload from source, so an edit to a backend or frontend file takes effect
# without rebuilding an image. The data tier stays in containers, because Postgres, Redis,
# Qdrant, MinIO, OpenSearch and the guardrails service are not things you edit while
# working. The scraper moved here too: it is a host process now, so its code changes the
# same way.
#
# Every subcommand runs ONE foreground process. Open a terminal per subcommand so each log
# stays readable and Ctrl-C stops only that process.
#
#   ./scripts/dev.sh deps              start every dependency container
#   ./scripts/dev.sh deps-stop         stop them again
#   ./scripts/dev.sh status            what is up, and whether the host ports answer
#
#   ./scripts/dev.sh ingestion-api     :8007
#   ./scripts/dev.sh ingestion-worker  source sync and fanout jobs
#   ./scripts/dev.sh ingestion-web     :5173
#
#   ./scripts/dev.sh scraper-api       :8000, runs crawler-db-migrate first
#   ./scripts/dev.sh scraper-worker    crawl, scrape and scrape-page queue consumers
#
#   ./scripts/dev.sh retrieval-api     :8001
#   ./scripts/dev.sh retrieval-worker  RAGAS evaluation jobs
#   ./scripts/dev.sh retrieval-web     :5174
#
# The scraper reads `web-scrapper-workspace/.env` and then `.env.local`, which holds the
# localhost values for a host run. It never reads `docker compose` env.
#
# The backends read `.env.local` after `.env`, so no variables are exported here. See
# vijay-docs/two_project_run.md, section 4.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INGESTION="$ROOT/rag-ingestion-manager"
RETRIEVAL="$ROOT/rag-retrieval-chat-manager"
SCRAPER="$ROOT/web-scrapper-workspace"

# The dependency containers. The ingestion compose owns the data tier, so it is the file
# that declares them. `api`, `worker`, `pathway-worker`, `web` and the three scraper
# services are deliberately absent: those are the host processes this script runs.
DEP_SERVICES=(
  postgres redis qdrant minio opensearch otel-collector guardrails-service
)

# The retrieval project reaches three things inside the ingestion stack (Postgres, Redis,
# Qdrant) and four through host.docker.internal (LiteLLM, OpenSearch, the ingestion API,
# guardrails). On the host all seven are a published port on localhost, so the dependency
# list below is what has to be listening before a host run can work.
HOST_PORTS=(5432 6379 6333 9200 9000 4000 18000 8007)

usage() {
  sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
}

require_dir() {
  [ -d "$1" ] || { echo "missing directory: $1" >&2; exit 1; }
}

cmd_deps() {
  require_dir "$INGESTION"
  echo "Starting dependency containers from rag-ingestion-manager/docker-compose.yaml"
  ( cd "$INGESTION" && docker compose up -d "${DEP_SERVICES[@]}" )
  echo
  echo "LiteLLM is external to this repository. If chat or embeddings fail, start it from"
  echo "its own directory: cd ~/CursorProjects/docker-services/litellm && docker compose up -d"
}

cmd_deps_stop() {
  require_dir "$INGESTION"
  ( cd "$INGESTION" && docker compose stop "${DEP_SERVICES[@]}" )
}

cmd_status() {
  echo "=== containers ==="
  docker ps --format "table {{.Names}}\t{{.Status}}" \
    | grep -E "NAME|rag-ingestion-manager-(postgres|redis|qdrant|minio|opensearch)|guardrails|litellm|^otel" \
    || echo "  none of the dependency containers are running"
  echo
  echo "=== host ports ==="
  for p in "${HOST_PORTS[@]}"; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
      exec 3>&- 3<&- 2>/dev/null || true
      printf "  %-6s up\n" "$p"
    else
      printf "  %-6s DOWN\n" "$p"
    fi
  done
  echo
  echo "=== the app processes (run these in their own terminals) ==="
  for p in 8007 8000 8001 5173 5174; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then
      exec 3>&- 3<&- 2>/dev/null || true
      printf "  %-6s up\n" "$p"
    else
      printf "  %-6s not running\n" "$p"
    fi
  done
}

cmd_ingestion_api() {
  require_dir "$INGESTION/backend"
  cd "$INGESTION/backend"
  # The migration is idempotent and cheap, so a host run always starts from the head.
  uv run ingestion-db-migrate
  exec uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8007 --reload
}

cmd_ingestion_worker() {
  require_dir "$INGESTION/backend"
  cd "$INGESTION/backend"
  # No --reload: this is a queue consumer, so a code change needs a restart. Ctrl-C then
  # run the subcommand again.
  exec uv run python -m apps.worker.main
}

cmd_ingestion_web() {
  require_dir "$INGESTION/frontend"
  cd "$INGESTION/frontend"
  [ -d node_modules ] || npm install
  # `npx vite` cannot spawn on Windows (os error 193). Calling the entry script through
  # node works on every platform.
  exec node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173
}

cmd_scraper_api() {
  require_dir "$SCRAPER"
  cd "$SCRAPER"
  # The crawler DB migration is idempotent and cheap, so a host run starts from the head.
  uv run crawler-db-migrate
  exec uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
}

cmd_scraper_worker() {
  require_dir "$SCRAPER"
  cd "$SCRAPER"
  # SimpleWorker for the same reason as the retrieval worker: the default worker calls
  # os.fork(), which Windows does not have, so it dies on the first job.
  # The working directory matters. SCRAPE_DATA_DIR is relative, and the API reads the
  # page artifacts this worker writes.
  exec uv run rq worker crawl scrape scrape-page \
    --url redis://localhost:6379/0 \
    --worker-class rq.worker.SimpleWorker
}

cmd_retrieval_api() {
  require_dir "$RETRIEVAL/backend"
  cd "$RETRIEVAL/backend"
  uv run rag-db-migrate
  exec uv run uvicorn rag_api.main:app --host 0.0.0.0 --port 8001 --reload
}

cmd_retrieval_worker() {
  require_dir "$RETRIEVAL/backend"
  cd "$RETRIEVAL/backend"
  # `SimpleWorker` is required on Windows: the default worker calls os.fork(), which
  # Windows does not have, and the process dies the moment a job arrives.
  exec uv run rq worker eval \
    --url redis://localhost:6379/0 \
    --worker-class rq.worker.SimpleWorker
}

cmd_retrieval_web() {
  require_dir "$RETRIEVAL/frontend"
  cd "$RETRIEVAL/frontend"
  [ -d node_modules ] || npm install
  exec node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5174
}

case "${1:-}" in
  deps)              cmd_deps ;;
  deps-stop)         cmd_deps_stop ;;
  status)            cmd_status ;;
  ingestion-api)     cmd_ingestion_api ;;
  ingestion-worker)  cmd_ingestion_worker ;;
  ingestion-web)     cmd_ingestion_web ;;
  scraper-api)       cmd_scraper_api ;;
  scraper-worker)    cmd_scraper_worker ;;
  retrieval-api)     cmd_retrieval_api ;;
  retrieval-worker)  cmd_retrieval_worker ;;
  retrieval-web)     cmd_retrieval_web ;;
  *)                 usage ;;
esac
