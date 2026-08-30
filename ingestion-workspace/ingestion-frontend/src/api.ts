import { computeFileHash } from "./hash";

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8007";
export const SCRAPER_URL = import.meta.env.VITE_SCRAPER_URL ?? "http://localhost:8000";
export const RAG_API_URL = import.meta.env.VITE_RAG_API_URL ?? "http://localhost:8001";
export const API_KEY = import.meta.env.VITE_API_KEY ?? "";
export const SCRAPER_API_KEY = import.meta.env.VITE_SCRAPER_API_KEY ?? API_KEY;
export const RAG_API_KEY = import.meta.env.VITE_RAG_API_KEY ?? API_KEY;

export const CHUNK_SIZE = 5 * 1024 * 1024;

function authHeaders(apiKey: string = API_KEY): HeadersInit {
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
    const body = (await res.json()) as ApiErrorBody;
    if (body.error) {
      throw new ApiError(res.status, body);
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

export interface PipelineRecord {
  id: string;
  name: string;
  description: string;
  rag_strategy: string;
  embedding_model: string;
  sparse_embedding_model: string | null;
  modality: string | null;
  directory_names: string[];
  chunk_size: number;
  chunk_overlap: number;
  qdrant_collection: string;
  web_scraper_enabled: boolean;
  scraper_seed_url: string | null;
  scraper_max_depth: number;
  scraper_max_pages: number;
  scraper_mode: string;
  created_at: string;
  updated_at: string;
}

export interface PipelineRunRecord {
  id: string;
  pipeline_id: string;
  status: string;
  files_total: number;
  files_processed: number;
  pages_indexed: number;
  points_upserted: number;
  scraper_crawl_job_id: string | null;
  scraper_scrape_job_id: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  pipeline_name?: string;
}

export interface CreatePipelineRequest {
  name: string;
  description: string;
  rag_strategy: string;
  embedding_model: string;
  sparse_embedding_model?: string | null;
  modality?: string | null;
  directory_names: string[];
  chunk_size?: number;
  chunk_overlap?: number;
  qdrant_collection: string;
  web_scraper_enabled?: boolean;
  scraper_seed_url?: string | null;
  scraper_max_depth?: number;
  scraper_max_pages?: number;
  scraper_mode?: string;
}

export interface PipelinePatchRequest {
  directory_names?: string[];
  web_scraper_enabled?: boolean;
  scraper_seed_url?: string;
  scraper_max_depth?: number;
  scraper_max_pages?: number;
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

export async function getPipelineStats(pipelineId: string): Promise<PipelineStats> {
  return apiFetch<PipelineStats>(`/api/pipelines/${pipelineId}/stats`);
}

export async function triggerPipelineSync(pipelineId: string): Promise<{ status: string, pipeline_id: string }> {
  return apiFetch<{ status: string, pipeline_id: string }>(`/api/pipelines/${pipelineId}/sync`, { method: "POST" });
}

export async function startPipelineRun(pipelineId: string): Promise<PipelineRunRecord> {
  return apiFetch<PipelineRunRecord>(`/api/pipelines/${pipelineId}/run`, { method: "POST" });
}

export async function listPipelineRuns(pipelineId: string): Promise<PipelineRunRecord[]> {
  return apiFetch<PipelineRunRecord[]>(`/api/pipelines/${pipelineId}/runs`);
}

export async function getPipelineCatalog(): Promise<PipelineCatalogEntry[]> {
  return apiFetch<PipelineCatalogEntry[]>("/api/pipelines/catalog");
}

export async function getPipelineByDescription(description: string): Promise<PipelineRecord> {
  const params = new URLSearchParams({ description });
  return apiFetch<PipelineRecord>(`/api/pipelines/by-description?${params}`);
}

export interface PipelineRunWithPipeline extends PipelineRunRecord {
  pipeline_description?: string;
  qdrant_collection?: string;
}

export async function listAllPipelineRuns(limit = 100): Promise<PipelineRunWithPipeline[]> {
  return apiFetch<PipelineRunWithPipeline[]>(`/api/pipelines/runs?limit=${limit}`);
}

// --- Scraper API ---

async function scraperFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = {
    ...authHeaders(SCRAPER_API_KEY),
    ...(init?.headers ?? {}),
  };
  const res = await fetch(`${SCRAPER_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    throw new Error(`Scraper API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export interface ScraperCrawlResult {
  links_file_path: string;
  total_links: number;
  pages_crawled: number;
  metadata: Record<string, unknown> | null;
}

export interface ScraperCrawlJob {
  id: string;
  seed_url: string;
  max_depth: number;
  max_pages: number;
  mode: string;
  status: string;
  error_message: string | null;
  markdown_ingested: boolean;
  image_ingested: boolean;
  markdown_indexed_at: string | null;
  image_indexed_at: string | null;
  result: ScraperCrawlResult | null;
}

export interface ScraperScrapeJob {
  id: string;
  crawl_job_id: string;
  status: string;
  output_dir: string | null;
  embedding_source: string;
  pages_scraped: number;
  error_message: string | null;
}

export async function listScraperCrawls(limit = 20): Promise<ScraperCrawlJob[]> {
  return scraperFetch<ScraperCrawlJob[]>(`/crawls?limit=${limit}`);
}

export async function listScraperScrapes(limit = 20): Promise<ScraperScrapeJob[]> {
  return scraperFetch<ScraperScrapeJob[]>(`/scrapes?limit=${limit}`);
}

export async function getScraperCrawl(jobId: string): Promise<ScraperCrawlJob> {
  return scraperFetch<ScraperCrawlJob>(`/crawls/${jobId}`);
}

export async function getScraperScrape(jobId: string): Promise<ScraperScrapeJob> {
  return scraperFetch<ScraperScrapeJob>(`/scrapes/${jobId}`);
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
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`RAG API error ${res.status}: ${text || res.statusText}`);
  }
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

export async function* streamChat(payload: any): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${RAG_API_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(RAG_API_KEY) },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`RAG API error ${res.status}: ${text || res.statusText}`);
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
    k_values?: number[];
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

// --- Guardrails API ---

export interface GuardItemOption {
  id: string;
  label: string;
}

export interface GuardOption {
  id: string;
  label: string;
  description: string;
  items_key?: string | null;
  items_label?: string | null;
  allow_custom?: boolean;
  options?: GuardItemOption[];
}

export interface GuardrailsSettings {
  banned_words: string[];
  pii_entities: string[];
}

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

export interface GuardrailsTrace {
  id: string;
  config_id: string;
  config_name: string | null;
  chat_message_id: string | null;
  query: string;
  response: string | null;
  blocked: boolean;
  blocked_by_guard: string | null;
  blocked_on: string | null;
  guard_results: Record<string, { passed: boolean; error: string | null }>;
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

