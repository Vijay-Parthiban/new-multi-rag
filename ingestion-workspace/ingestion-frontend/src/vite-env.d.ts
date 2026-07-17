/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_SCRAPER_URL?: string;
  readonly VITE_RAG_API_URL?: string;
  readonly VITE_API_KEY?: string;
  readonly VITE_SCRAPER_API_KEY?: string;
  readonly VITE_RAG_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
