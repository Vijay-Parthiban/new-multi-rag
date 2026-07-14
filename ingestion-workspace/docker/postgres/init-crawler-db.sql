-- Second database for web-scrapper (ingestion DB is created via POSTGRES_DB).
CREATE USER crawler WITH PASSWORD 'crawler';
CREATE DATABASE crawler OWNER crawler;
GRANT ALL PRIVILEGES ON DATABASE crawler TO crawler;

-- Third database for RAG chat and evaluations
CREATE DATABASE rag OWNER crawler;
GRANT ALL PRIVILEGES ON DATABASE rag TO crawler;
