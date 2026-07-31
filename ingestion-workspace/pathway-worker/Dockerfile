FROM python:3.11-slim

WORKDIR /app

# ── Shared RAG/Qdrant helpers (repo root must be the build context) ──
COPY shared-libs/platform-common /tmp/platform-common
RUN pip install --no-cache-dir /tmp/platform-common && rm -rf /tmp/platform-common

# ── Ingestion backend source (needed for DB models, S3 client, etc.) ──
COPY ingestion-workspace/ingestion-backend/pyproject.toml /tmp/ingestion-backend/
COPY ingestion-workspace/ingestion-backend/src /tmp/ingestion-backend/src
RUN pip install --no-cache-dir /tmp/ingestion-backend && rm -rf /tmp/ingestion-backend

# ── Pathway worker itself ──
COPY ingestion-workspace/pathway-worker/pyproject.toml .
COPY ingestion-workspace/pathway-worker/src ./src
COPY ingestion-workspace/pathway-worker/scripts ./scripts

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app:/app/src

RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/*.sh