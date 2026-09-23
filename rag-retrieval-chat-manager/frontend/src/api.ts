import { computeFileHash } from "./hash";

// Use 127.0.0.1, not localhost. On Windows "localhost" resolves to ::1 first, and the
// backend binds IPv4 only, so every request first waits for a connection that never
// answers. The penalty is about 2 seconds per call, on a call that otherwise takes 3 ms.
export const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8007";
export const RAG_API_URL = import.meta.env.VITE_RAG_API_URL ?? "http://127.0.0.1:8001";
export const API_KEY = import.meta.env.VITE_API_KEY ?? "";
export const RAG_API_KEY = import.meta.env.VITE_RAG_API_KEY ?? API_KEY;

export const CHUNK_SIZE = 5 * 1024 * 1024;

export function authHeaders(apiKey: string = API_KEY): HeadersInit {
  return apiKey ? { "X-API-Key": apiKey } : {};
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.code = body.error.code;
    this.status = status;
    this.details = body.error.details;
  }
}

async function parseError(res: Response): Promise<never> {
  try {
    const body = await res.json();
    if (body?.error) {
      throw new ApiError(res.status, body as ApiErrorBody);
    }
    // FastAPI render: {"detail": "text"} or {"detail": {"code": ..., "message": ...}}
    const detail = body?.detail;
    if (typeof detail === "string") {
      throw new ApiError(res.status, {
        error: { code: `HTTP_${res.status}`, message: detail },
      });
    }
    if (detail && typeof detail === "object" && detail.message) {
      throw new ApiError(res.status, {
        error: { code: detail.code ?? `HTTP_${res.status}`, message: detail.message },
      });
    }
  } catch (e) {
    if (e instanceof ApiError) throw e;
  }
  throw new ApiError(res.status, {
    error: { code: "HTTP_ERROR", message: res.statusText || "Request failed" },
  });
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = {
    ...authHeaders(API_KEY),
    ...(init?.headers ?? {}),
  };
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) await parseError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface InitUploadResponse {
  upload_id: string;
  directory_name: string;
  file_name: string;
}

export interface CompleteUploadResponse {
  file_id: string;
  job_id: string | null;
  status: string;
  content_hash?: string;
  client_content_hash?: string;
  hash_verified?: boolean;
  duplicate_of_file_id?: string;
  duplicate_of_file_name?: string;
}

export async function uploadFileChunked(
  directoryName: string,
  file: File,
): Promise<CompleteUploadResponse> {
  const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));
  const clientContentHash = await computeFileHash(file);

  const init = await apiFetch<InitUploadResponse>("/api/uploads/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      directory_name: directoryName,
      file_name: file.name,
      total_chunks: totalChunks,
      total_size: file.size,
      mime_type: file.type || null,
      client_content_hash: clientContentHash,
    }),
  });

  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, file.size);
    const blob = file.slice(start, end);
    const form = new FormData();
    form.append("chunk", blob, file.name);

    const res = await fetch(`${API_URL}/api/uploads/${init.upload_id}/chunks/${i}`, {
      method: "PUT",
      body: form,
    });
    if (!res.ok) await parseError(res);
  }

  return apiFetch<CompleteUploadResponse>(`/api/uploads/${init.upload_id}/complete`, {
    method: "POST",
  });
}

export interface FileRecord {
  id: string;
  original_name: string;
  mime_type: string | null;
  size_bytes: number;
  status: string;
  error_message: string | null;
  duplicate_of_file_id: string | null;
  duplicate_of_file_name: string | null;
  content_hash: string | null;
  client_content_hash: string | null;
  hash_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface FileDetail extends FileRecord {
  directory_name: string;
}

export interface DirectorySummary {
  id: string;
  name: string;
  created_at: string;
}

export async function listDirectories(): Promise<DirectorySummary[]> {
  return apiFetch<DirectorySummary[]>("/api/directories");
}

export async function getFile(fileId: string): Promise<FileDetail> {
  return apiFetch<FileDetail>(`/api/files/${fileId}`);
}

export async function listDirectoryFiles(name: string): Promise<FileRecord[]> {
  return apiFetch<FileRecord[]>(`/api/directories/${encodeURIComponent(name)}/files`);
}

export async function renameFile(fileId: string, newName: string): Promise<void> {
  await apiFetch(`/api/files/${fileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_name: newName }),
  });
}

export async function deleteFile(fileId: string): Promise<void> {
  await apiFetch(`/api/files/${fileId}`, { method: "DELETE" });
}

// --- Pipelines ---

export interface RagStrategyOption {
  id: string;
  label: string;
  description: string;
}

export interface ModalityOption {
  id: string;
  label: string;
  description: string;
}

export interface PipelineOptions {
  rag_strategies: RagStrategyOption[];
  modalities: ModalityOption[];
  suggested_embedding_models: string[];
  suggested_sparse_models: string[];
  scraper_modes: string[];
  collection_naming_hint: string;
}

export interface PipelineCatalogEntry {
  description: string;
  name: string;
  rag_strategy: string;
  qdrant_collection: string;
  embedding_model: string;
  id: string;
}

/** One of the knowledge product's ingestion destinations, flattened by the API. */
export interface PipelineDestinationSummary {
  destination_type: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

/** The knowledge product a pipeline reads. Null for a legacy ingestion pipeline. */
export interface PipelineKnowledgeProduct {
  id: string;
  name: string;
  status: string;
  chunk_strategy: string;
  text_embedding_model: string;
  /** The BM25 model the lexical destination embeds with. */
  sparse_embedding_model?: string | null;
  destinations: PipelineDestinationSummary[];
}

/**
 * Sampling settings for an assistant's model call.
 *
 * Unset means the service default applies. The Chat page sends these to try a
 * value without saving it; the Pipelines page saves them on the pipeline.
 */
export interface ModelSettings {
  temperature?: number | null;
  top_p?: number | null;
  /** The sampler's cutoff. Not the count of chunks that reach the prompt. */
  top_k?: number | null;
  max_tokens?: number | null;
}

/**
 * What a new pipeline starts with: tuned for grounded answers, not for creative
 * writing.
 *
 * `temperature` is low because a RAG answer should stay close to the retrieved
 * passages. `top_p` stays neutral so temperature is the only knob in play, which
 * is what the model providers recommend — changing both at once makes the result
 * hard to reason about. `top_k` is 0, meaning off: it is not an OpenAI parameter
 * and many providers ignore it.
 */
export const DEFAULT_MODEL_SETTINGS: Required<ModelSettings> = {
  temperature: 0.1,
  top_p: 1.0,
  top_k: 0,
  max_tokens: 1024,
};

/** One knob, described once so both pages render it the same way. */
export interface ModelSettingField {
  key: keyof ModelSettings;
  label: string;
  min: number;
  max: number;
  step: number;
  /** Shown under the input, so the control explains itself. */
  hint: string;
}

/** The sampling knobs the UI exposes, in display order. */
export const MODEL_SETTING_FIELDS: readonly ModelSettingField[] = [
  {
    key: "temperature",
    label: "Temperature",
    min: 0,
    max: 2,
    step: 0.05,
    hint: "Lower keeps the answer close to the passages. 0.1 suits factual work.",
  },
  {
    key: "top_p",
    label: "Top P",
    min: 0.01,
    max: 1,
    step: 0.01,
    hint: "Nucleus sampling. Leave at 1 so temperature is the only knob.",
  },
  {
    key: "top_k",
    label: "Top K (sampler)",
    min: 0,
    max: 200,
    step: 1,
    hint: "0 turns it off. Not an OpenAI parameter, so some models ignore it.",
  },
  {
    key: "max_tokens",
    label: "Max tokens",
    min: 1,
    max: 32768,
    step: 1,
    hint: "Ceiling on the answer length.",
  },
];

export interface PipelineRecord {
  id: string;
  knowledge_product_id?: string | null;
  name: string;
  description: string;
  rag_strategy: string;
  embedding_model: string;
  sparse_embedding_model: string | null;
  modality: string | null;
  directory_names: string[];
  chunk_size: number;
  chunk_overlap: number;
  qdrant_collection: string | null;
  web_scraper_enabled: boolean;
  scraper_seed_url: string | null;
  scraper_max_depth: number;
  scraper_max_pages: number;
  scraper_mode: string;
  /** External name the chat endpoints address this pipeline by. */
  slug: string | null;
  chat_model: string | null;
  /** Sampling settings saved on the pipeline. Null means service defaults. */
  model_settings: ModelSettings | null;
  prompt_template_id: string | null;
  guardrails_config_id: string | null;
  /** True when the strategy names a knowledge-product store. */
  is_assistant: boolean;
  knowledge_product: PipelineKnowledgeProduct | null;
  created_at: string;
  updated_at: string;
}

export interface CreatePipelineRequest {
  name: string;
  description: string;
  rag_strategy: string;
  embedding_model: string;
  sparse_embedding_model?: string | null;
  modality?: string | null;
  directory_names?: string[];
  chunk_size?: number;
  chunk_overlap?: number;
  qdrant_collection?: string | null;
  web_scraper_enabled?: boolean;
  scraper_seed_url?: string | null;
  scraper_max_depth?: number;
  scraper_max_pages?: number;
  scraper_mode?: string;
  knowledge_product_id?: string;
  slug?: string | null;
  chat_model?: string | null;
  prompt_template_id?: string | null;
  guardrails_config_id?: string | null;
  model_settings?: ModelSettings | null;
}

export interface PipelinePatchRequest {
  directory_names?: string[];
  web_scraper_enabled?: boolean;
  scraper_seed_url?: string;
  scraper_max_depth?: number;
  scraper_max_pages?: number;
  name?: string;
  description?: string;
  slug?: string;
  rag_strategy?: string;
  chat_model?: string;
  prompt_template_id?: string | null;
  guardrails_config_id?: string | null;
  knowledge_product_id?: string;
  embedding_model?: string;
  model_settings?: ModelSettings | null;
}

/** The strategies an assistant may run, in the order the form shows them. */
export const RAG_STRATEGY_LABELS: Record<string, { label: string; description: string }> = {
  vector: { label: "Vector search", description: "Qdrant dense vectors" },
  lexical: { label: "Keyword search", description: "OpenSearch BM25" },
  relational: { label: "SQL search", description: "PostgreSQL pgvector" },
  hybrid: { label: "Hybrid", description: "Vector and keyword, fused with reciprocal rank fusion" },
};

const RETRIEVAL_DESTINATIONS = ["vector_qdrant", "lexical_opensearch", "relational_pgvector"];

/** The enabled destination types an assistant can read. */
export function enabledRetrievalDestinations(
  destinations: PipelineDestinationSummary[] | undefined,
): Set<string> {
  return new Set(
    (destinations ?? [])
      .filter((d) => d.enabled && RETRIEVAL_DESTINATIONS.includes(d.destination_type))
      .map((d) => d.destination_type),
  );
}

/**
 * The strategies a product's enabled destinations can serve. Hybrid fuses the
 * vector and the keyword ranking, so it needs both. A product with only
 * cache_redisvl enabled serves nothing: that store caches answers, it does not
 * hold a searchable copy of the chunks.
 */
export function strategiesForDestinations(
  destinations: PipelineDestinationSummary[] | undefined,
): string[] {
  const enabled = enabledRetrievalDestinations(destinations);
  const strategies: string[] = [];
  if (enabled.has("vector_qdrant")) strategies.push("vector");
  if (enabled.has("lexical_opensearch")) strategies.push("lexical");
  if (enabled.has("relational_pgvector")) strategies.push("relational");
  if (enabled.has("vector_qdrant") && enabled.has("lexical_opensearch")) strategies.push("hybrid");
  return strategies;
}

/** A destination's store name, as the chat endpoint reports it. */
export function destinationStoreLabel(destination: PipelineDestinationSummary): string | null {
  const config = destination.config ?? {};
  const name =
    (config.collection_name as string) ??
    (config.index_name as string) ??
    (config.schema_name as string) ??
    (config.index_prefix as string);
  return name ? String(name) : null;
}

export interface PipelineStats {
  pipeline_id: string;
  indexed_files_count: number;
  scraped_pages_count: number;
}

export async function getPipelineOptions(): Promise<PipelineOptions> {
  return apiFetch<PipelineOptions>("/api/pipelines/options");
}

export async function listPipelines(): Promise<PipelineRecord[]> {
  return apiFetch<PipelineRecord[]>("/api/pipelines");
}

export async function createPipeline(body: CreatePipelineRequest): Promise<PipelineRecord> {
  return apiFetch<PipelineRecord>("/api/pipelines", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updatePipeline(pipelineId: string, body: PipelinePatchRequest): Promise<PipelineRecord> {
  return apiFetch<PipelineRecord>(`/api/pipelines/${pipelineId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
export async function deletePipeline(pipelineId: string): Promise<void> {
  return apiFetch<void>(`/api/pipelines/${pipelineId}`, {
    method: "DELETE",
  });
}

export async function getPipelineStats(pipelineId: string): Promise<PipelineStats> {
  return apiFetch<PipelineStats>(`/api/pipelines/${pipelineId}/stats`);
}

export async function triggerPipelineSync(pipelineId: string): Promise<{ status: string, pipeline_id: string }> {
  return apiFetch<{ status: string, pipeline_id: string }>(`/api/pipelines/${pipelineId}/sync`, { method: "POST" });
}
export interface KnowledgeDestinationOption {
  id: string;
  name: string;
  category: string;
  description: string;
  namespace_fields?: string[];
  default_config: Record<string, unknown>;
}

export interface KnowledgeDestinationConfig {
  id?: string;
  destination_type: string;
  enabled: boolean;
  config: Record<string, unknown>;
  status?: string;
  last_sync_at?: string | null;
  error_message?: string | null;
}

export interface KnowledgeProductSource {
  source_id: string;
  name: string;
  connector_type?: string | null;
  minio_bucket: string;
  status?: string;
}

export interface KnowledgeProduct {
  id: string;
  name: string;
  description?: string | null;
  enabled: boolean;
  monitor_mode: "live" | "scheduled";
  sync_interval_seconds?: number | null;
  sync_interval_minutes?: number | null;
  status: string;
  error_message?: string | null;
  last_sync_at?: string | null;
  created_at?: string;
  updated_at?: string;
  sources: KnowledgeProductSource[];
  destinations: KnowledgeDestinationConfig[];
  pipelines?: PipelineRecord[];
  files_total: number;
  files_synced: number;
  files_pending: number;
  files_failed: number;
  pages_indexed: number;
}
export interface TestConnectionResponse {
  status: "success" | "error";
  destination_type: string;
  message: string;
  details?: Record<string, unknown>;
}

export async function getDestinationOptions(): Promise<KnowledgeDestinationOption[]> {
  return apiFetch<KnowledgeDestinationOption[]>("/api/knowledge-products/destinations/options");
}

export async function listKnowledgeProducts(): Promise<KnowledgeProduct[]> {
  return apiFetch<KnowledgeProduct[]>("/api/knowledge-products");
}

export async function getKnowledgeProduct(productId: string): Promise<KnowledgeProduct> {
  return apiFetch<KnowledgeProduct>(`/api/knowledge-products/${productId}`);
}

export async function testDestinationConnection(
  productId: string,
  destinationType: string,
  config: Record<string, any>
): Promise<TestConnectionResponse> {
  return apiFetch<TestConnectionResponse>(`/api/knowledge-products/${productId}/test-connection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ destination_type: destinationType, config }),
  });
}

/* ── Read-only support for the view-only Knowledge Store ─────────────────────
   This page never writes. It reads the Knowledge Products that the ingestion
   manager owns, plus their file ledger, their live event stream and the
   contents of each destination store. */

export interface ProductFileEntry {
  id: string;
  file_key: string;
  source_id: string;
  source_name: string;
  status: string;
  pages_indexed: number;
  size_bytes: number | null;
  etag: string | null;
  destinations_synced: string[];
  error_message: string | null;
  last_synced_at: string | null;
  updated_at: string | null;
}

export interface ProductFilesResponse {
  files: ProductFileEntry[];
  total: number;
}

export async function listProductFiles(
  productId: string,
  params: { status?: string; limit?: number; offset?: number } = {}
): Promise<ProductFilesResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const suffix = search.toString() ? `?${search}` : "";
  return apiFetch<ProductFilesResponse>(`/api/knowledge-products/${productId}/files${suffix}`);
}

export function productEventsPath(productId: string): string {
  return `/api/knowledge-products/${productId}/events`;
}

export interface DestinationInspectData {
  destination_type: string;
  error?: string;
  // Vector Qdrant
  collection_name?: string;
  total_points?: number;
  status?: string;
  points?: Array<{
    id: string;
    x: number;
    y: number;
    z: number;
    payload: Record<string, any>;
    vector_len: number;
  }>;
  // OpenSearch
  index_name?: string;
  total_docs?: number;
  terms?: Array<{ text: string; value: number }>;
  documents?: Array<{
    id: string;
    file_key?: string;
    page_index?: number;
    content?: string;
    score?: number;
  }>;
  // PGVector Relational
  table_name?: string;
  schema_name?: string;
  total_rows?: number;
  rows?: Array<{
    id: number;
    file_key: string;
    page_index: number;
    content: string;
    created_at: string;
  }>;
  // Redis Cache
  prefix?: string;
  total_cached_keys?: number;
  used_memory_human?: string;
  keys?: Array<{
    key: string;
    ttl: number;
    type: string;
  }>;
}

export async function inspectDestinationStore(
  productId: string,
  destinationType: string
): Promise<DestinationInspectData> {
  return apiFetch<DestinationInspectData>(
    `/api/knowledge-products/${productId}/inspect/${destinationType}`
  );
}

/**
 * Nudge an immediate fanout for one product.
 *
 * The ingestion API exposes no sync route by design: the product poller owns the
 * schedule. `PATCH` re-registers that poller, and `register_knowledge_poller`
 * fires one immediate sync every time it runs, so an empty body is the way to ask
 * for a run now without changing any ingestion code.
 */
export async function refreshKnowledgeProduct(productId: string): Promise<void> {
  await apiFetch<KnowledgeProduct>(`/api/knowledge-products/${productId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

export async function getPipelineCatalog(): Promise<PipelineCatalogEntry[]> {
  return apiFetch<PipelineCatalogEntry[]>("/api/pipelines/catalog");
}

export async function getPipelineByDescription(description: string): Promise<PipelineRecord> {
  const params = new URLSearchParams({ description });
  return apiFetch<PipelineRecord>(`/api/pipelines/by-description?${params}`);
}

// --- RAG API Endpoints ---

async function ragFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const baseHeaders = { ...authHeaders(RAG_API_KEY) };
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: HeadersInit = isFormData
    ? { ...baseHeaders, ...(init?.headers ?? {}) }
    : { ...baseHeaders, ...(init?.headers ?? {}) };

  // For FormData uploads, never force Content-Type — browser sets multipart boundary.
  if (isFormData && headers && typeof headers === "object" && !Array.isArray(headers)) {
    const h = headers as Record<string, string>;
    delete h["Content-Type"];
    delete h["content-type"];
  }

  const res = await fetch(`${RAG_API_URL}${path}`, { ...init, headers });
  if (!res.ok) await parseError(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface ChatSession {
  session_id: string;
  created_at: string | null;
  last_message_at: string | null;
  preview: string | null;
  message_count: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string | null;
  trace?: {
    retrieval_mode: string | null;
    rerank_enabled: boolean | null;
    generation_model: string | null;
    route: string | null;
  } | null;
  sources: {
    source_locator: string;
    chunk_index: number;
    rerank_score: number;
  }[];
  metrics_status?: string | null;
  blocked?: boolean;
  blocked_by_guard?: string | null;
  blocked_on?: string | null;
}

export interface RAGChatResponse {
  message_id: string;
  session_id: string;
  answer: string;
  sources: {
    source_locator: string;
    chunk_index: number;
    rerank_score: number;
  }[];
  trace_id: string;
  metrics_status: string;
}

export interface RAGMetricsResponse {
  message_id: string;
  status: string;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  kendall_tau: number | null;
  mrr: number | null;
  ndcg: number | null;
  metrics: {
    retrieval?: Record<string, any>;
    reranker?: Record<string, any>;
    generation?: Record<string, any>;
  } | null;
  error_message: string | null;
}

export interface RAGChatStatItem {
  message_id: string;
  session_id: string;
  query: string | null;
  answer: string;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  kendall_tau: number | null;
  mrr: number | null;
  ndcg: number | null;
  metrics: {
    retrieval?: Record<string, any>;
    reranker?: Record<string, any>;
    generation?: Record<string, any>;
  } | null;
  metrics_status: string;
  latency_ms: Record<string, number> | null;
  /** "test" for a turn from this page, "prod" for the callable endpoint. Null before migration 004. */
  trace_mode?: string | null;
  /** The OTEL trace id of the turn, for deep-linking into Langfuse or Phoenix. */
  otel_trace_id?: string | null;
  retrieval_mode: string | null;
  rerank_enabled: boolean | null;
  generation_model: string | null;
  created_at: string | null;
}

export interface RAGChatStatsResponse {
  limit: number;
  count: number;
  items: RAGChatStatItem[];
}

export interface GoldenDatasetSummary {
  dataset_id: string;
  name: string;
  description: string | null;
  item_count: number;
  created_at: string | null;
}

export interface EvalRunResponse {
  run_id: string;
  dataset_id: string;
  status: string;
  config: Record<string, any>;
  aggregate_metrics: Record<string, any> | null;
  error_message: string | null;
  progress: {
    items_total: number;
    items_completed: number;
    items_failed: number;
  };
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export async function listChatSessions(limit = 50): Promise<ChatSession[]> {
  const res = await ragFetch<{ items: ChatSession[] }>(`/chat/sessions?limit=${limit}`);
  return res.items || [];
}

export async function getChatSessionMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await ragFetch<{ items: ChatMessage[] }>(`/chat/sessions/${sessionId}/messages`);
  return res.items || [];
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await ragFetch<void>(`/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export interface CloseChatSessionResponse {
  session_id: string;
  turns: number;
  memory: { enabled: boolean; cleared: boolean };
  trace: { emitted: boolean; trace_id: string | null; tags: string[] };
}

/**
 * End a conversation on the server.
 *
 * A pipeline with session memory exports the whole conversation as one trace and drops what
 * it remembered. A stateless pipeline kept nothing, so `memory.enabled` is false and no
 * session trace is written: its turns were already traced one by one.
 */
export async function closeChatSession(
  sessionId: string,
  pipelineId?: string | null,
): Promise<CloseChatSessionResponse> {
  return ragFetch<CloseChatSessionResponse>(`/chat/sessions/${sessionId}/close`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // A conversation from this page is a test conversation, the same as its turns.
      [TRACE_MODE_HEADER]: "test",
    },
    body: JSON.stringify({ pipeline_id: pipelineId ?? null }),
  });
}

export async function deleteChatMessage(
  messageId: string
): Promise<{ session_id: string; deleted_message_ids: string[] }> {
  return ragFetch<{ session_id: string; deleted_message_ids: string[] }>(
    `/chat/messages/${messageId}`,
    { method: "DELETE" }
  );
}

export async function chatWithPipeline(payload: {
  query: string;
  session_id?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  retrieval_mode?: string;
  retrieve_limit?: number;
  rerank_enabled?: boolean;
  rerank_model?: string | null;
  top_k?: number;
  generation_model?: string | null;
  collection?: string | null;
  embedding_model?: string | null;
  sparse_embedding_model?: string | null;
  rag_mode?: string;
  self_corrective_max_loops?: number;
  router_enabled?: boolean;
  router_mode?: string | null;
}): Promise<RAGChatResponse> {
  return ragFetch<RAGChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export type ChatEventType = "status" | "token" | "done" | "error" | "session" | "blocked";

export interface ChatStreamEvent {
  type: ChatEventType;
  message?: string;
  content?: string;
  // session event fields (sent after DB save with real IDs)
  session_id?: string;
  message_id?: string;
  route?: string;
  metrics_status?: string;
  blocked_by_guard?: string;
  blocked_on?: string;
  blocked_title?: string;
  metadata?: {
    message_id?: string;
    session_id?: string;
    sources?: any[];
    route?: string;
  };
}

/**
 * The header the backend reads to tag a turn. The Chat page and an external caller hit the
 * same route, so this is the only thing that separates a test turn from a production one.
 * Omitting it means production.
 */
export const TRACE_MODE_HEADER = "X-RAG-Trace-Mode";
export type TraceMode = "test" | "prod";

export async function* streamChat(
  payload: any,
  opts: { path?: string; traceMode?: TraceMode } = {},
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${RAG_API_URL}${opts.path ?? "/chat/stream"}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(RAG_API_KEY),
      ...(opts.traceMode ? { [TRACE_MODE_HEADER]: opts.traceMode } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    await parseError(res);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    // Keep the last partial chunk in the buffer
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim().startsWith("data: ")) {
        const jsonStr = line.replace(/^data:\s*/, "").trim();
        if (jsonStr) {
          yield JSON.parse(jsonStr) as ChatStreamEvent;
        }
      }
    }
  }
}


export async function getMessageMetrics(messageId: string): Promise<RAGMetricsResponse> {
  return ragFetch<RAGMetricsResponse>(`/chat/messages/${messageId}/metrics`);
}

export async function getChatStats(limit = 20): Promise<RAGChatStatsResponse> {
  return ragFetch<RAGChatStatsResponse>(`/chat/stats?limit=${limit}`);
}

export async function listGoldenDatasets(limit = 50): Promise<GoldenDatasetSummary[]> {
  const res = await ragFetch<{ items: GoldenDatasetSummary[] }>(`/evaluate/datasets?limit=${limit}`);
  return res.items || [];
}

export async function uploadGoldenDataset(
  file: File,
  replace = false,
): Promise<{ dataset_id: string; name: string; item_count: number; replaced: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const qs = replace ? "?replace=true" : "";
  return ragFetch(`/evaluate/datasets/upload${qs}`, {
    method: "POST",
    body: form,
  });
}

export async function deleteGoldenDataset(datasetId: string): Promise<void> {
  await ragFetch(`/evaluate/datasets/${datasetId}`, { method: "DELETE" });
}

/** The built-in evaluation set: question and answer pairs from the Hugging Face documentation. */
export const HF_EVAL_DATASET = "m-ric/huggingface_doc_qa_eval";
/** The corpus those questions are drawn from. A pipeline can only answer them if it holds this. */
export const HF_EVAL_CORPUS = "A-Roucher/huggingface_doc";

/**
 * Import the built-in evaluation set from the Hugging Face Hub.
 *
 * The rows are stored as an ordinary golden dataset, so a run against them is an ordinary run.
 */
export async function importHuggingFaceDataset(replace = true): Promise<{
  dataset_id: string;
  name: string;
  item_count: number;
  replaced: boolean;
}> {
  return ragFetch<{
    dataset_id: string;
    name: string;
    item_count: number;
    replaced: boolean;
  }>("/evaluate/datasets/huggingface", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ replace }),
  });
}

export interface DatasetRunsResponse {
  items: EvalRunResponse[];
  count: number;
}

export async function listDatasetRuns(
  datasetId: string,
  opts: { skip?: number; limit?: number } = {},
): Promise<DatasetRunsResponse> {
  const skip = opts.skip ?? 0;
  const limit = opts.limit ?? 10;
  return ragFetch<DatasetRunsResponse>(
    `/evaluate/datasets/${datasetId}/runs?skip=${skip}&limit=${limit}`,
  );
}

export interface EvalRunItemRow {
  item_id: string;
  dataset_item_id: string;
  status: string;
  question: string | null;
  expected_sources: Array<string | { name: string; page?: number }>;
  ground_truth_answer: string | null;
  generated_answer: string | null;
  retrieval_metrics: Record<string, any> | null;
  rerank_metrics: Record<string, any> | null;
  generation_metrics: Record<string, any> | null;
  category: string | null;
  error_message: string | null;
}

export async function listEvaluationRunItems(runId: string): Promise<EvalRunItemRow[]> {
  const res = await ragFetch<{ items: EvalRunItemRow[] }>(`/evaluate/runs/${runId}/items`);
  return res.items || [];
}

export async function createEvaluationRun(
  datasetId: string,
  config: {
    retrieval_mode?: string;
    retrieve_limit?: number;
    rerank_enabled?: boolean;
    rerank_model?: string | null;
    top_k?: number;
    generation_model?: string | null;
    collection?: string | null;
    embedding_model?: string | null;
    sparse_embedding_model?: string | null;
    /** With a strategy, the evaluator reads the pipeline's knowledge-product stores. */
    rag_strategy?: string | null;
    opensearch_index?: string | null;
    pg_schema?: string | null;
    pg_table?: string | null;
    k_values?: number[];
    /** Evaluate a random sample of this many rows instead of the whole set. */
    sample_size?: number | null;
    /** Makes a sample reproducible. Omit for a fresh sample on every run. */
    seed?: number | null;
    rag_mode?: string;
    self_corrective_max_loops?: number;
    router_enabled?: boolean;
    router_mode?: string | null;
  }
): Promise<{ run_id: string; status: string }> {
  return ragFetch<{ run_id: string; status: string }>("/evaluate/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, config }),
  });
}

export async function getEvaluationRun(runId: string): Promise<EvalRunResponse> {
  return ragFetch<EvalRunResponse>(`/evaluate/runs/${runId}`);
}

// --- Prompt Templates Registry ---

export interface PromptSummary {
  id: string;
  filename: string;
  package: "generation_core" | "rag_core";
  label: string;
  description: string;
  is_overridden: boolean;
  preview: string;
}

export interface PromptDetail {
  id: string;
  filename: string;
  package: "generation_core" | "rag_core";
  label: string;
  description: string;
  is_overridden: boolean;
  packaged_content: string;
  active_content: string;
  overrides_dir: string;
}

export interface PromptListResponse {
  overrides_dir: string;
  count: number;
  items: PromptSummary[];
}

export async function listPrompts(): Promise<PromptListResponse> {
  return ragFetch<PromptListResponse>("/prompts");
}

export async function getPrompt(promptId: string): Promise<PromptDetail> {
  return ragFetch<PromptDetail>(`/prompts/${encodeURIComponent(promptId)}`);
}

export async function updatePrompt(promptId: string, content: string): Promise<PromptDetail> {
  return ragFetch<PromptDetail>(`/prompts/${encodeURIComponent(promptId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function updatePromptsBulk(
  items: { id: string; content: string }[],
): Promise<PromptListResponse> {
  return ragFetch<PromptListResponse>("/prompts", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
}

export async function resetPrompt(promptId: string): Promise<PromptDetail> {
  return ragFetch<PromptDetail>(`/prompts/${encodeURIComponent(promptId)}/reset`, {
    method: "POST",
  });
}

export async function resetAllPrompts(): Promise<{ reset: string[]; overrides_dir: string }> {
  return ragFetch<{ reset: string[]; overrides_dir: string }>("/prompts/reset", {
    method: "POST",
  });
}

// --- Prompt templates -------------------------------------------------------
// A prompt template is the system message a pipeline attaches. Distinct from
// the packaged prompt catalog above, which this app no longer edits.

export interface PromptTemplate {
  id: string;
  name: string;
  description: string | null;
  content: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface PromptTemplateInput {
  name: string;
  description?: string | null;
  content: string;
}

export async function listPromptTemplates(): Promise<{ count: number; items: PromptTemplate[] }> {
  return ragFetch<{ count: number; items: PromptTemplate[] }>("/prompt-templates");
}

export async function createPromptTemplate(body: PromptTemplateInput): Promise<PromptTemplate> {
  return ragFetch<PromptTemplate>("/prompt-templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getPromptTemplate(templateId: string): Promise<PromptTemplate> {
  return ragFetch<PromptTemplate>(`/prompt-templates/${templateId}`);
}

export async function updatePromptTemplate(
  templateId: string,
  body: Partial<PromptTemplateInput>,
): Promise<PromptTemplate> {
  return ragFetch<PromptTemplate>(`/prompt-templates/${templateId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deletePromptTemplate(templateId: string): Promise<void> {
  return ragFetch<void>(`/prompt-templates/${templateId}`, { method: "DELETE" });
}

// --- Assistant endpoints ----------------------------------------------------

export interface AssistantConfig {
  slug: string;
  name: string;
  description: string;
  chat_model: string;
  strategy: string;
  strategies_available: { id: string; label: string; description: string }[];
  knowledge_product: {
    id: string | null;
    name: string | null;
    status: string | null;
    chunk_strategy: string | null;
    text_embedding_model: string | null;
  };
  stores: {
    qdrant_collection: string | null;
    opensearch_index: string | null;
    pg_schema: string | null;
    pg_table: string | null;
  };
  prompt_template_id: string | null;
  guardrails_config_id: string | null;
  endpoints: { chat: string; chat_stream: string; openai_base_url: string };
}

export async function getAssistant(slug: string): Promise<AssistantConfig> {
  return ragFetch<AssistantConfig>(`/api/assistants/${slug}`);
}

/** The absolute base URL an OpenAI SDK client points its base_url at. */
export function assistantBaseUrl(slug: string): string {
  return `${RAG_API_URL}/v1/assistants/${slug}`;
}

/** The absolute native chat URL for an assistant. */
export function assistantChatUrl(slug: string): string {
  return `${RAG_API_URL}/api/assistants/${slug}/chat`;
}

/**
 * The absolute URL for one session of an assistant. A GET reads what the session
 * remembers, a DELETE ends it. `{session_id}` is the literal template a caller
 * replaces, so the UI can show the shape before any session exists.
 */
export function assistantSessionUrl(slug: string, sessionId = "{session_id}"): string {
  return `${RAG_API_URL}/api/assistants/${slug}/sessions/${sessionId}`;
}

/**
 * Session memory needs the product's Redis destination, which is the same gate the
 * backend applies. cache_redisvl is not a retrieval destination: it serves no RAG
 * strategy, it only provides the namespace and the TTL for the conversation.
 */
export function sessionMemoryFor(
  destinations: PipelineDestinationSummary[] | undefined,
): { enabled: boolean; ttlSeconds: number | null } {
  const redis = (destinations ?? []).find(
    (d) => d.enabled && d.destination_type === "cache_redisvl",
  );
  const ttl = redis?.config?.ttl_seconds;
  return {
    enabled: Boolean(redis),
    ttlSeconds: typeof ttl === "number" ? ttl : null,
  };
}

export async function getLiteLLMModels(modelKind: string): Promise<{ id: string; label: string }[]> {
  const res = await apiFetch<{ models: ({ id: string; label?: string } | string)[] }>(
    `/api/knowledge-products/config/litellm-models?model_kind=${encodeURIComponent(modelKind)}`,
  );
  return (res.models ?? []).map((m) =>
    typeof m === "string" ? { id: m, label: m } : { id: m.id, label: m.label ?? m.id },
  );
}

// --- Guardrails API ---

export interface GuardItemOption {
  id: string;
  label: string;
}

/** One tunable knob on a validator, as declared by the guardrails service catalog. */
export interface GuardParam {
  name: string;
  /** string | text | integer | number | boolean | string_list | select */
  type: string;
  label: string;
  help: string;
  required: boolean;
  default: unknown;
  /** Present only when type is "select". */
  options?: GuardItemOption[] | null;
  min?: number | null;
  max?: number | null;
}

export interface GuardOption {
  id: string;
  label: string;
  description: string;
  category?: string;
  /** input | output | both */
  phase?: string;
  /** local | model | llm */
  kind?: string;
  available?: boolean;
  unavailable_reason?: string | null;
  params?: GuardParam[];
  /** Legacy fields kept for backward compatibility. Prefer `params`. */
  items_key?: string | null;
  items_label?: string | null;
  allow_custom?: boolean;
  options?: GuardItemOption[];
}

export interface OnFailOption {
  id: string;
  label: string;
  help: string;
  fixes_text: boolean;
}

/**
 * Per-validator settings. One key per selected validator id. `on_fail` sits next to the
 * parameters. The backend always returns this nested shape, even for old flat rows.
 */
export type GuardrailsSettings = Record<string, Record<string, unknown>>;

export interface GuardrailsConfig {
  id: string;
  name: string;
  description: string | null;
  guards: string[];
  settings?: GuardrailsSettings;
  mode: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface GuardResult {
  validation_passed: boolean;
  error: string | null;
  detail: string | null;
}

export interface GuardrailsTrace {
  id: string;
  /** Null when the trace was recorded without a guardrails config. */
  config_id: string | null;
  config_name: string | null;
  chat_message_id: string | null;
  query: string;
  response: string | null;
  blocked: boolean;
  blocked_by_guard: string | null;
  blocked_on: string | null;
  guard_results: Record<string, GuardResult>;
  created_at: string | null;
}

export interface GuardrailsStats {
  total_requests: number;
  blocked_requests: number;
  passed_requests: number;
  block_rate: number;
  per_guard: Record<string, number>;
}

export async function listAvailableGuards(): Promise<GuardOption[]> {
  return ragFetch<GuardOption[]>("/guardrails/guards");
}

/** Failure actions, fetched from the service so the labels stay with the implementation. */
export async function listGuardOnFailOptions(): Promise<OnFailOption[]> {
  return ragFetch<OnFailOption[]>("/guardrails/on-fail-options");
}

export async function createGuardrailsConfig(body: {
  name: string;
  description?: string;
  guards: string[];
  mode: string;
  settings?: GuardrailsSettings;
}): Promise<GuardrailsConfig> {
  return ragFetch<GuardrailsConfig>("/guardrails/configs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function listGuardrailsConfigs(activeOnly = false): Promise<{ count: number; items: GuardrailsConfig[] }> {
  const qs = activeOnly ? "?active_only=true" : "";
  return ragFetch<{ count: number; items: GuardrailsConfig[] }>(`/guardrails/configs${qs}`);
}

export async function updateGuardrailsConfig(
  configId: string,
  body: Partial<{
    name: string;
    description: string;
    guards: string[];
    mode: string;
    is_active: boolean;
    settings: GuardrailsSettings;
  }>,
): Promise<GuardrailsConfig> {
  return ragFetch<GuardrailsConfig>(`/guardrails/configs/${configId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteGuardrailsConfig(configId: string): Promise<void> {
  await ragFetch(`/guardrails/configs/${configId}`, { method: "DELETE" });
}

export async function listGuardrailsTraces(opts?: {
  guard?: string;
  blocked?: boolean;
  limit?: number;
  offset?: number;
}): Promise<{ total: number; limit: number; offset: number; items: GuardrailsTrace[] }> {
  const params = new URLSearchParams();
  if (opts?.guard) params.set("guard", opts.guard);
  if (opts?.blocked !== undefined) params.set("blocked", String(opts.blocked));
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return ragFetch(`/guardrails/traces${qs ? `?${qs}` : ""}`);
}

export async function getGuardrailsStats(): Promise<GuardrailsStats> {
  return ragFetch<GuardrailsStats>("/guardrails/stats");
}
// --- Data Sources & Storage Connectors API ---

export interface ConnectorOption {
  id: string;
  label: string;
  description: string;
}

export interface SourceConnectorRecord {
  id: string;
  source_id: string;
  connector_type: string;
  config: Record<string, unknown>;
  monitor_mode: "live" | "scheduled";
  sync_interval_minutes: number | null;
  enabled: boolean;
  last_sync_at: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceRecord {
  id: string;
  name: string;
  connector_type: string | null;
  config: Record<string, unknown> | null;
  connector_monitor_mode: "live" | "scheduled";
  connector_sync_interval_minutes: number | null;
  pipeline_monitor_mode: "live" | "scheduled";
  pipeline_sync_interval_minutes: number | null;
  minio_bucket: string;
  enabled: boolean;
  last_sync_at: string | null;
  status: string;
  error_message: string | null;
  pipelines: PipelineLinkInfo[];
  connectors: SourceConnectorRecord[];
  created_at: string;
  updated_at: string;
}

export interface PipelineLinkInfo {
  pipeline_id: string;
  pipeline_name?: string;
  monitor_mode?: "live" | "scheduled" | null;
  sync_interval_minutes?: number | null;
  created_at?: string;
}

export interface SourceCreateRequest {
  name: string;
  connector_type?: string;
  config?: Record<string, unknown>;
  monitor_mode?: "live" | "scheduled";
  sync_interval_minutes?: number | null;
}

export interface SourceUpdateRequest {
  name?: string;
  config?: Record<string, unknown>;
  connector_monitor_mode?: "live" | "scheduled";
  connector_sync_interval_minutes?: number | null;
  pipeline_monitor_mode?: "live" | "scheduled";
  pipeline_sync_interval_minutes?: number | null;
  enabled?: boolean;
}

export interface ConnectorCreateRequest {
  connector_type: string;
  config?: Record<string, unknown>;
  monitor_mode?: "live" | "scheduled";
  sync_interval_minutes?: number | null;
  enabled?: boolean;
}

export interface SourceFileEntry {
  key: string;
  size: number;
  last_modified: string;
}

export interface SourceFilesResponse {
  source_id: string;
  bucket: string;
  files: SourceFileEntry[];
}

export async function listConnectors(): Promise<ConnectorOption[]> {
  const res = await apiFetch<{ connectors: ConnectorOption[] }>("/api/sources/connectors");
  return res.connectors;
}

export async function listSources(): Promise<SourceRecord[]> {
  return apiFetch<SourceRecord[]>("/api/sources");
}

export async function createSource(body: SourceCreateRequest): Promise<SourceRecord> {
  return apiFetch<SourceRecord>("/api/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getSource(sourceId: string): Promise<SourceRecord> {
  return apiFetch<SourceRecord>(`/api/sources/${sourceId}`);
}

export async function updateSource(sourceId: string, body: SourceUpdateRequest): Promise<SourceRecord> {
  return apiFetch<SourceRecord>(`/api/sources/${sourceId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteSource(sourceId: string): Promise<void> {
  await apiFetch(`/api/sources/${sourceId}`, { method: "DELETE" });
}

export async function addSourceConnector(
  sourceId: string,
  body: ConnectorCreateRequest,
): Promise<SourceConnectorRecord> {
  return apiFetch<SourceConnectorRecord>(`/api/sources/${sourceId}/connectors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateSourceConnector(
  sourceId: string,
  connectorId: string,
  body: Partial<ConnectorCreateRequest>,
): Promise<SourceConnectorRecord> {
  return apiFetch<SourceConnectorRecord>(`/api/sources/${sourceId}/connectors/${connectorId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteSourceConnector(sourceId: string, connectorId: string): Promise<void> {
  await apiFetch(`/api/sources/${sourceId}/connectors/${connectorId}`, { method: "DELETE" });
}

export async function linkSourceToPipeline(
  sourceId: string,
  pipelineId: string,
  body?: { monitor_mode?: "live" | "scheduled"; sync_interval_minutes?: number | null },
): Promise<void> {
  await apiFetch(`/api/sources/${sourceId}/pipeline/${pipelineId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function unlinkSourceFromPipeline(sourceId: string, pipelineId: string): Promise<void> {
  await apiFetch(`/api/sources/${sourceId}/pipeline/${pipelineId}`, { method: "DELETE" });
}

export async function listSourceFiles(sourceId: string, prefix = ""): Promise<SourceFilesResponse> {
  const params = new URLSearchParams();
  if (prefix) params.set("prefix", prefix);
  const qs = params.toString();
  return apiFetch<SourceFilesResponse>(`/api/sources/${sourceId}/files${qs ? `?${qs}` : ""}`);
}
export async function uploadSourceFile(sourceId: string, file: File): Promise<{ status: string; source_id: string; bucket: string; key: string; size: number }> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<{ status: string; source_id: string; bucket: string; key: string; size: number }>(`/api/sources/${sourceId}/files`, {
    method: "POST",
    body: formData,
  });
}

export async function deleteSourceFile(sourceId: string, key: string): Promise<{ status: string; source_id: string; bucket: string; key: string }> {
  const params = new URLSearchParams({ key });
  return apiFetch<{ status: string; source_id: string; bucket: string; key: string }>(`/api/sources/${sourceId}/files?${params.toString()}`, {
    method: "DELETE",
  });
}
export function getSourceFileContentUrl(sourceId: string, key: string): string {
  const params = new URLSearchParams({ key });
  return `${API_URL}/api/sources/${sourceId}/files/content?${params.toString()}`;
}

export async function getSourceFileContent(sourceId: string, key: string): Promise<string> {
  const url = getSourceFileContentUrl(sourceId, key);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch file content: ${res.statusText}`);
  }
  return res.text();
}
export async function triggerConnectorSync(sourceId: string, _connectorId?: string): Promise<TriggerSyncResponse> {
  return apiFetch<TriggerSyncResponse>(`/api/sources/${sourceId}/sync`, { method: "POST" });
}

export interface TriggerSyncResponse {
  status: string;
  source_id?: string;
  connector_type?: string;
  minio_bucket?: string;
  message?: string;
}

export async function triggerSourceSync(sourceId: string): Promise<TriggerSyncResponse> {
  return apiFetch<TriggerSyncResponse>(`/api/sources/${sourceId}/sync`, { method: "POST" });
}

