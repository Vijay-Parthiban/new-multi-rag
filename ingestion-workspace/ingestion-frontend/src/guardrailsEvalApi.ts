/**
 * API client for offline guardrails golden evaluation.
 * Kept separate from api.ts / RAG evaluate helpers for review.
 */

import { RAG_API_KEY, RAG_API_URL } from "./api";

async function grEvalFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const baseHeaders: HeadersInit = RAG_API_KEY ? { "X-API-Key": RAG_API_KEY } : {};
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: HeadersInit = { ...baseHeaders, ...(init?.headers ?? {}) };

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

export interface GuardrailsGoldenDatasetSummary {
  dataset_id: string;
  name: string;
  description: string | null;
  item_count: number;
  created_at: string | null;
}

export interface GuardrailsEvalRunResponse {
  run_id: string;
  dataset_id: string;
  config_id: string;
  status: string;
  config_snapshot: {
    name?: string;
    mode?: string;
    guards?: string[];
    settings?: Record<string, unknown>;
    config_id?: string;
  };
  aggregate_metrics: {
    items_total?: number;
    items_evaluated?: number;
    items_skipped?: number;
    accuracy?: number | null;
    precision?: number | null;
    recall?: number | null;
    f1?: number | null;
    guard_match_rate?: number | null;
    true_positives?: number;
    true_negatives?: number;
    false_positives?: number;
    false_negatives?: number;
    categories?: Record<string, { item_count: number; correct: number; accuracy: number }>;
  } | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface GuardrailsEvalRunItemRow {
  run_item_id: string;
  dataset_item_id: string;
  text: string;
  phase: string;
  category: string | null;
  status: string;
  skipped: boolean;
  skip_reason: string | null;
  expected_blocked: boolean;
  expected_guard: string | null;
  actual_blocked: boolean;
  actual_guard: string | null;
  correct_block: boolean | null;
  correct_guard: boolean | null;
  guard_results: Record<string, { passed?: boolean; error?: string | null }>;
  error_message: string | null;
}

export async function uploadGuardrailsGoldenDataset(
  file: File,
  replace = false,
): Promise<{ dataset_id: string; name: string; item_count: number; replaced: boolean }> {
  const form = new FormData();
  form.append("file", file);
  return grEvalFetch(`/guardrails-evaluate/datasets/upload?replace=${replace}`, {
    method: "POST",
    body: form,
  });
}

export async function listGuardrailsGoldenDatasets(): Promise<{
  count: number;
  items: GuardrailsGoldenDatasetSummary[];
}> {
  return grEvalFetch("/guardrails-evaluate/datasets");
}

export async function deleteGuardrailsGoldenDataset(datasetId: string): Promise<void> {
  await grEvalFetch(`/guardrails-evaluate/datasets/${datasetId}`, { method: "DELETE" });
}

export async function createGuardrailsEvalRun(
  datasetId: string,
  guardrailsConfigId: string,
): Promise<{ run_id: string; status: string }> {
  return grEvalFetch("/guardrails-evaluate/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dataset_id: datasetId,
      guardrails_config_id: guardrailsConfigId,
    }),
  });
}

export async function getGuardrailsEvalRun(runId: string): Promise<GuardrailsEvalRunResponse> {
  return grEvalFetch(`/guardrails-evaluate/runs/${runId}`);
}

export async function listGuardrailsDatasetRuns(
  datasetId: string,
  opts?: { skip?: number; limit?: number },
): Promise<{ count: number; items: GuardrailsEvalRunResponse[] }> {
  const params = new URLSearchParams();
  if (opts?.skip != null) params.set("skip", String(opts.skip));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return grEvalFetch(`/guardrails-evaluate/datasets/${datasetId}/runs${qs ? `?${qs}` : ""}`);
}

export async function listGuardrailsEvalRunItems(
  runId: string,
): Promise<{ count: number; items: GuardrailsEvalRunItemRow[] }> {
  return grEvalFetch(`/guardrails-evaluate/runs/${runId}/items`);
}
