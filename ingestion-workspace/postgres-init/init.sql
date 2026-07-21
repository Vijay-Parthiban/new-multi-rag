-- Create crawler user and databases for scraper and RAG services
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'crawler') THEN
    CREATE ROLE crawler WITH LOGIN PASSWORD 'crawler';
  END IF;
END
$$;

SELECT 'CREATE DATABASE crawler OWNER crawler'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'crawler')\gexec

SELECT 'CREATE DATABASE rag OWNER crawler'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag')\gexec

GRANT ALL PRIVILEGES ON DATABASE crawler TO crawler;
GRANT ALL PRIVILEGES ON DATABASE rag TO crawler;
