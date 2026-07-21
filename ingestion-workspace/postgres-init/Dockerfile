FROM postgres:16-alpine

COPY init.sql /docker-entrypoint-initdb.d/init.sql
RUN chmod 644 /docker-entrypoint-initdb.d/init.sql

HEALTHCHECK --interval=2s --timeout=5s --retries=15 \
  CMD pg_isready -U ingestion -d ingestion
