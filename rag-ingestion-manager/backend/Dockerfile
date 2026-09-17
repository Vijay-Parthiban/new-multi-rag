FROM python:3.11-slim

WORKDIR /app

# Shared RAG/Qdrant helpers (repo root must be the build context).
COPY shared-libs/platform-common /tmp/platform-common
RUN pip install --no-cache-dir /tmp/platform-common && rm -rf /tmp/platform-common

COPY rag-ingestion-manager/backend/pyproject.toml .
COPY rag-ingestion-manager/backend/alembic.ini .
COPY rag-ingestion-manager/backend/alembic ./alembic
COPY rag-ingestion-manager/backend/apps ./apps
COPY rag-ingestion-manager/backend/src ./src
COPY rag-ingestion-manager/backend/scripts ./scripts

RUN pip install --no-cache-dir -e .
ENV PYTHONPATH=/app
ENV STORAGE_PATH=/app/storage

RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/*.sh

EXPOSE 8000
