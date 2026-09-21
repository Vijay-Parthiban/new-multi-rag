-- Databases and the login role that this repository's services need beyond the
-- `ingestion` database, which the postgres image creates from POSTGRES_DB.
--
-- Mounted at /docker-entrypoint-initdb.d/02-crawler.sql, so Docker runs it once,
-- on the first start of an empty data volume. To apply it to a volume that
-- already exists, run the same statements by hand:
--
--   docker exec -i rag-ingestion-manager-postgres-1 \
--     psql -U ingestion -d postgres < rag-ingestion-manager/docker/postgres/init-crawler-db.sql
--
-- `rag`       the retrieval manager's own tables: chat, sessions, guardrails,
--             evaluation and prompt templates.
-- `crawler`   the web scraper's tables.
-- `ingestion` holds the kp_* pgvector schemas the fanout writes.
--
-- The `crawler` role logs in and owns the two databases it uses. It is not a
-- superuser and cannot create databases, so it cannot create the `vector`
-- extension. The fanout creates that extension in `ingestion` as the
-- `ingestion` superuser instead (universal_fanout.py).

CREATE ROLE crawler LOGIN PASSWORD 'crawler';
CREATE DATABASE crawler OWNER crawler;
CREATE DATABASE rag OWNER crawler;
