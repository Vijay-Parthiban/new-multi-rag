FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Build context is the monorepo root so shared-libs is available.
# Path deps in libs/*/pyproject.toml resolve ../../../shared-libs → /shared-libs.
COPY shared-libs /shared-libs
COPY rag-app-workspace/pyproject.toml rag-app-workspace/uv.lock ./
COPY rag-app-workspace/libs ./libs
COPY rag-app-workspace/apps ./apps
COPY rag-app-workspace/scripts ./scripts

RUN uv sync --all-packages \
    && sed -i 's/\r$//' /app/scripts/*.sh \
    && chmod +x /app/scripts/*.sh

# Pre-download BM25 sparse model (same as web-scrapper ingest) to avoid runtime HF errors.
RUN uv run python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name='Qdrant/bm25')"

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/shared-libs/platform-common/src:/app/libs/shared/src:/app/libs/vector-core/src:/app/libs/retrieval-core/src:/app/libs/reranker-core/src:/app/libs/generation-core/src:/app/libs/rag-core/src:/app/libs/eval-core/src:/app/libs/database/src:/app/apps/rag-api/src:/app/apps/eval-worker/src"

EXPOSE 8001
