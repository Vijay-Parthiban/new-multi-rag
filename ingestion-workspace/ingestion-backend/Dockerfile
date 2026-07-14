FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY alembic.ini .
COPY alembic ./alembic
COPY apps ./apps
COPY src ./src
COPY scripts ./scripts

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app
ENV STORAGE_PATH=/app/storage

RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/*.sh

EXPOSE 8000
