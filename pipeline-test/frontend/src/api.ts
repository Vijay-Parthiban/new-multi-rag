/** Everything the page needs to talk to the demo backend. */

export type MemoryState = {
  enabled: boolean;
  ttl_seconds: number | null;
  reason: string | null;
};

/** One chat entry: the id and label come from `.env`, the rest from the pipeline. */
export type ChatbotInfo = {
  id: string;
  label: string;
  name?: string;
  slug?: string;
  chat_model?: string;
  strategy?: string;
  knowledge_product?: {
    name: string;
    status: string;
    chunk_strategy: string;
    text_embedding_model: string;
  };
  session_memory?: MemoryState;
  /** Set when the configured endpoint did not answer. */
  error?: string;
};

/** Which kind of project this is, declared in the backend's `.env`. */
export type MemoryMode = "enabled" | "disabled";

export type ConfigResponse = {
  chatbots: ChatbotInfo[];
  memory_state: MemoryMode;
  error: string | null;
};

/** One server-sent frame from a streaming turn. */
export type Frame = {
  type: "status" | "token" | "done" | "session" | "error" | string;
  content?: string;
  message?: string;
  session_id?: string;
  message_id?: string;
  route?: string;
  metrics_status?: string;
  metadata?: { answer?: string; sources?: unknown[]; [key: string]: unknown };
};

export type SessionReport = {
  session_id: string;
  exists: boolean;
  turns: number;
  ttl_seconds: number | null;
  history: { role: string; content: string }[];
};

/** The outcome of reading a session. A pipeline without Redis answers 422, which is
 *  an answer, not a failure, so it gets its own case instead of an exception. */
export type InspectResult =
  | { kind: "memory"; report: SessionReport }
  | { kind: "none"; code: string; message: string }
  | { kind: "error"; message: string };

export type CloseSessionResponse = {
  session_id: string;
  turns: number;
  memory: { enabled: boolean; cleared: boolean };
  trace: { emitted: boolean; trace_id: string | null; tags: string[] };
};

export async function loadChatbots(): Promise<ConfigResponse> {
  const response = await fetch("/api/assistants");
  if (!response.ok) throw new Error(`Could not load the configuration (HTTP ${response.status})`);
  return response.json();
}

export type StreamResult = { sessionId: string | null; answer: string; sourceCount: number };

/** Send one turn and report every frame as it arrives. Resolves on the last frame. */
export async function streamChat(
  chatbot: string,
  message: string,
  sessionId: string | null,
  onFrame: (frame: Frame) => void,
  signal?: AbortSignal,
): Promise<StreamResult> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chatbot, message, session_id: sessionId ?? undefined }),
    signal,
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    throw new Error(`Chat failed (HTTP ${response.status}). ${text.slice(0, 200)}`);
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/event-stream")) {
    const text = await response.text().catch(() => "");
    throw new Error(`Expected a stream, got ${contentType}. ${text.slice(0, 200)}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const result: StreamResult = { sessionId, answer: "", sourceCount: 0 };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Frames are separated by a blank line.
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;

      let frame: Frame;
      try {
        frame = JSON.parse(raw);
      } catch {
        continue; // a keepalive or a partial frame
      }

      if (frame.type === "session" && frame.session_id) {
        result.sessionId = frame.session_id;
      } else if (frame.type === "done") {
        result.answer = frame.metadata?.answer ?? result.answer;
        result.sourceCount = frame.metadata?.sources?.length ?? 0;
      }
      onFrame(frame);
    }
  }

  return result;
}

export async function inspectSession(
  chatbot: string,
  sessionId: string,
): Promise<InspectResult> {
  let response: Response;
  try {
    response = await fetch(`/api/session/${sessionId}?chatbot=${encodeURIComponent(chatbot)}`);
  } catch (error) {
    return { kind: "error", message: (error as Error).message };
  }

  const body = await response.json().catch(() => null);
  if (response.ok) return { kind: "memory", report: body as SessionReport };

  const detail = (body as { detail?: { code?: string; message?: string } | string } | null)?.detail;
  if (response.status === 422 && typeof detail === "object" && detail?.code) {
    return { kind: "none", code: detail.code, message: detail.message ?? "" };
  }
  return {
    kind: "error",
    message: typeof detail === "string" ? detail : `HTTP ${response.status}`,
  };
}

/**
 * End the conversation on the pipeline endpoint, which is the production path.
 *
 * No trace-mode header is sent, so the platform records these turns as production and tags
 * them `prod-session` or `prod-stateless`. When the pipeline keeps a conversation, the
 * platform exports the whole session as one trace and drops the memory; when it does not, it
 * does neither. The response says which happened.
 */
export async function closeChatSession(
  chatbot: string,
  sessionId: string,
): Promise<CloseSessionResponse> {
  const response = await fetch(
    `/api/session/${sessionId}/close?chatbot=${encodeURIComponent(chatbot)}`,
    { method: "POST" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = (body as { detail?: { message?: string } | string } | null)?.detail;
    const message = typeof detail === "string" ? detail : detail?.message ?? response.statusText;
    throw new Error(`HTTP ${response.status}: ${message}`);
  }
  return response.json();
}
