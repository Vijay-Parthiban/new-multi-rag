FROM python:3.11-slim

WORKDIR /app

# Shared RAG/Qdrant helpers and the cross-project Pydantic contracts. The repo root
# must be the build context.
#
# Both are path dependencies declared in [tool.uv.sources], which is a uv-only
# extension: pip does not read it. It sees "platform-common" and "shared-contracts"
# in the dependency list and looks for them on PyPI, so each is installed from
# source first and the editable install then finds the requirement satisfied.
COPY shared-libs/platform-common /tmp/platform-common
RUN pip install --no-cache-dir /tmp/platform-common && rm -rf /tmp/platform-common

# shared-contracts declares readme = "README.md", so the whole directory is copied.
COPY shared-contracts /tmp/shared-contracts
RUN pip install --no-cache-dir /tmp/shared-contracts && rm -rf /tmp/shared-contracts

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
