FROM python:3.12-slim

# The image mirrors the repository layout, and it has to. libs/*/pyproject.toml point
# their path dependencies at ../../../../shared-libs and ../../../../shared-contracts,
# which is four levels up from libs/shared. Those four levels only land inside the image
# if the application sits at the same depth it does in the repo. Flattening it to /app
# makes uv fail with "cannot normalize a relative path beyond the base directory".
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY shared-libs /app/shared-libs
COPY shared-contracts /app/shared-contracts

WORKDIR /app/rag-retrieval-chat-manager/backend

COPY rag-retrieval-chat-manager/backend/pyproject.toml rag-retrieval-chat-manager/backend/uv.lock ./
COPY rag-retrieval-chat-manager/backend/libs ./libs
COPY rag-retrieval-chat-manager/backend/apps ./apps
COPY rag-retrieval-chat-manager/backend/scripts ./scripts

RUN uv sync --all-packages \
    && sed -i 's/\r$//' ./scripts/*.sh \
    && chmod +x ./scripts/*.sh

# Pre-download BM25 sparse model (same as web-scrapper ingest) to avoid runtime HF errors.
RUN uv run python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding(model_name='Qdrant/bm25')"

ENV PATH="/app/rag-retrieval-chat-manager/backend/.venv/bin:$PATH"
ENV PYTHONPATH="/app/shared-libs/platform-common/src:/app/rag-retrieval-chat-manager/backend/libs/shared/src:/app/rag-retrieval-chat-manager/backend/libs/vector-core/src:/app/rag-retrieval-chat-manager/backend/libs/retrieval-core/src:/app/rag-retrieval-chat-manager/backend/libs/reranker-core/src:/app/rag-retrieval-chat-manager/backend/libs/generation-core/src:/app/rag-retrieval-chat-manager/backend/libs/rag-core/src:/app/rag-retrieval-chat-manager/backend/libs/eval-core/src:/app/rag-retrieval-chat-manager/backend/libs/database/src:/app/rag-retrieval-chat-manager/backend/apps/rag-api/src:/app/rag-retrieval-chat-manager/backend/apps/eval-worker/src"

EXPOSE 8001
