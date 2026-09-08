/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_SCRAPER_URL?: string;
  readonly VITE_RAG_API_URL?: string;
  readonly VITE_API_KEY?: string;
  readonly VITE_SCRAPER_API_KEY?: string;
  readonly VITE_RAG_API_KEY?: string;
  /** Langfuse traces page URL, e.g. https://cloud.langfuse.com/project/<id>/traces */
  readonly VITE_LANGFUSE_TRACES_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
