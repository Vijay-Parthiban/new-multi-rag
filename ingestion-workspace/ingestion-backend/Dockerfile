FROM python:3.11-slim

WORKDIR /app

# Shared RAG/Qdrant helpers (repo root must be the build context).
COPY shared-libs/platform-common /tmp/platform-common
RUN pip install --no-cache-dir /tmp/platform-common && rm -rf /tmp/platform-common

COPY ingestion-workspace/ingestion-backend/pyproject.toml .
COPY ingestion-workspace/ingestion-backend/alembic.ini .
COPY ingestion-workspace/ingestion-backend/alembic ./alembic
COPY ingestion-workspace/ingestion-backend/apps ./apps
COPY ingestion-workspace/ingestion-backend/src ./src
COPY ingestion-workspace/ingestion-backend/scripts ./scripts

RUN pip install --no-cache-dir . psycopg[binary]

ENV PYTHONPATH=/app
ENV STORAGE_PATH=/app/storage

RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/*.sh

EXPOSE 8000
