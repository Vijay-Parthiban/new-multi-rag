import { useEffect, useRef, useState } from "react";
import {
  type ChatbotInfo,
  type CloseSessionResponse,
  type Frame,
  type InspectResult,
  type MemoryMode,
  closeChatSession,
  inspectSession,
  loadChatbots,
  streamChat,
} from "./api";

type Message = { role: "user" | "assistant"; content: string; sources?: number };

const POLICIES = [
  {
    title: "Home Insurance",
    summary: "Cover for the home building and the contents in it against the insured events.",
    points: [
      "The building is covered on a market value basis and the contents for the sum insured shown in the schedule.",
      "The sum insured rises by 10% on each policy anniversary without extra premium, up to 100% of the base sum insured.",
      "Burglary and theft of contents is an add-on, with a cap on items bought after the policy began.",
      "Equipment and appliances are settled after depreciation from the age-wise table in the wording.",
    ],
  },
  {
    title: "Health Insurance",
    summary: "Hospitalization cover, with optional benefits you may add to it.",
    points: [
      "Treatment of an illness in the first 30 days is excluded, except for a claim arising from an accident.",
      "Maternity and child care claims carry a waiting period of 24 months.",
      "AYUSH treatment is covered up to the limit in the schedule, in an AYUSH hospital or day care centre.",
      "A co-payment is the share of the admissible claim the insured bears; it does not reduce the sum insured.",
    ],
  },
  {
    title: "Motor Insurance (Own Damage)",
    summary: "Cover for the insured vehicle against the perils the wording lists.",
    points: [
      "The IDV is fixed at each renewal from the manufacturer's listed selling price, less depreciation.",
      "A repair that costs more than 75% of the IDV makes the vehicle a constructive total loss.",
      "A full year with no claim earns a 20% discount on the own damage premium.",
      "Organised racing, pace making and speed testing are not covered.",
    ],
  },
  {
    title: "Claims",
    summary: "How a claim is reported, assessed and settled.",
    points: [
      "Report an accidental loss to the insurer in writing as soon as it happens.",
      "A motor claim is settled within 7 days of the intimation or of the final survey report.",
      "A health claim needs the claim form, the discharge summary and the hospital bills.",
      "A grievance is acknowledged within 7 days of registration.",
    ],
  },
  {
    title: "Waiting Periods and Exclusions",
    summary: "What is not payable in the first months of a policy, and what is never payable.",
    points: [
      "A pre-existing disease is one diagnosed, or treated, in the 24 months before the policy began.",
      "The 30 day waiting period applies again to any later increase in the sum insured.",
      "A specific waiting period of up to 24 months applies to the listed diseases and treatments.",
      "A subsidence loss excludes the normal settlement of new structures and coastal or river erosion.",
    ],
  },
  {
    title: "Renewal and Servicing",
    summary: "Keeping a policy in force, and moving it between insurers.",
    points: [
      "The grace period is 15 days for a monthly premium mode and 30 days in all other cases.",
      "A no claim bonus is allowed only if the policy is renewed within 90 days of the previous expiry.",
      "Portability transfers the credit gained for pre-existing diseases and specific waiting periods.",
      "The cumulative bonus adds to the base sum insured without an increase in premium.",
    ],
  },
];

function shortId(id: string | null): string {
  return id ? id.slice(0, 8) : "none";
}

function ttlLabel(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "no expiry";
  // Floor the parts: rounding the remainder turns 23h 59m 58s into "23h 60m".
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0 && minutes === 0) return `${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${Math.max(1, minutes)}m`;
}

/** What the platform reported when the conversation was ended. */
function closeSummary(result: CloseSessionResponse): string {
  const parts = [`${result.turns} turn${result.turns === 1 ? "" : "s"}`];
  parts.push(result.memory.cleared ? "session memory removed" : "no memory to remove");
  // The trace id is absent when the exporter is off, which is not a failure: the trace was
  // still written. Report the id only when there is one.
  if (result.trace.emitted) {
    parts.push(
      result.trace.trace_id
        ? `whole session exported as one trace ${shortId(result.trace.trace_id)}`
        : "whole session exported as one trace",
    );
  } else {
    parts.push("no session trace, each turn was traced on its own");
  }
  if (result.trace.tags.length) parts.push(`tagged ${result.trace.tags.join(", ")}`);
  return parts.join(" · ");
}

export default function App() {
  const [bots, setBots] = useState<ChatbotInfo[]>([]);
  const [configError, setConfigError] = useState<string | null>(null);
  const [memoryMode, setMemoryMode] = useState<MemoryMode>("enabled");
  const [activeId, setActiveId] = useState<string | null>(null);

  // The chatbot window has two states: the invitation to begin, and the conversation.
  const [started, setStarted] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const sessionRef = useRef<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [inspect, setInspect] = useState<InspectResult | null>(null);
  const [lastClose, setLastClose] = useState<CloseSessionResponse | null>(null);
  const [draft, setDraft] = useState("");

  const active = bots.find((bot) => bot.id === activeId) ?? bots[0] ?? null;
  const keepsMemory = active?.session_memory?.enabled === true;

  useEffect(() => {
    loadChatbots()
      .then((config) => {
        setBots(config.chatbots);
        setConfigError(config.error);
        setMemoryMode(config.memory_state);
        setActiveId(config.chatbots[0]?.id ?? null);
      })
      .catch((error: Error) => setConfigError(error.message));
  }, []);

  /** Back to the invitation, with nothing remembered locally. */
  const resetLocal = () => {
    sessionRef.current = null;
    setSessionId(null);
    setMessages([]);
    setInspect(null);
    setStatus("");
    setStarted(false);
  };

  const startChat = () => {
    setLastClose(null);
    resetLocal();
    setStarted(true);
  };

  const setSession = (id: string | null) => {
    sessionRef.current = id;
    setSessionId(id);
  };

  const appendToLast = (text: string) =>
    setMessages((prev) => {
      if (!prev.length) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      next[next.length - 1] = { ...last, content: last.content + text };
      return next;
    });

  const replaceLast = (content: string, sources: number) =>
    setMessages((prev) => {
      if (!prev.length) return prev;
      const next = prev.slice();
      next[next.length - 1] = { ...next[next.length - 1], content, sources };
      return next;
    });

  /** Read back what the pipeline actually holds for this session. */
  const checkMemory = async (chatbotId: string, session: string | null) => {
    if (!session) {
      setInspect({
        kind: "none",
        code: "NO_SESSION",
        message: "No session yet. Send a message first.",
      });
      return;
    }
    setInspect(await inspectSession(chatbotId, session));
  };

  const send = async (text: string) => {
    if (!active || busy) return;
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setBusy(true);
    setStatus("");
    setInspect(null);

    try {
      const result = await streamChat(active.id, text, sessionRef.current, (frame: Frame) => {
        if (frame.type === "status" && frame.message) {
          setStatus(frame.message);
        } else if (frame.type === "token" && frame.content) {
          appendToLast(frame.content);
        } else if (frame.type === "session" && frame.session_id) {
          setSession(frame.session_id);
        } else if (frame.type === "done") {
          replaceLast(frame.metadata?.answer ?? "", frame.metadata?.sources?.length ?? 0);
        } else if (frame.type === "error") {
          appendToLast(`\n[error] ${frame.content ?? "the stream failed"}`);
        }
      });
      if (result.sessionId) setSession(result.sessionId);
    } catch (error) {
      appendToLast(`\n[error] ${(error as Error).message}`);
    } finally {
      setBusy(false);
      setStatus("");
      await checkMemory(active.id, sessionRef.current);
    }
  };

  /**
   * End the conversation.
   *
   * The platform exports the whole conversation as one trace and drops its memory, when the
   * pipeline kept a conversation. When it did not, the turns were already traced one by one.
   * Either way the window returns to its first state.
   */
  const endChat = async () => {
    if (!active) return;

    const question = keepsMemory
      ? "End this session?\n\nThe conversation closes, is exported as one trace, and its session memory is removed."
      : "End this chat?\n\nThe conversation closes. Each question was traced on its own.";
    if (!window.confirm(question)) return;

    const session = sessionRef.current;
    if (session) {
      try {
        setLastClose(await closeChatSession(active.id, session));
      } catch (error) {
        setInspect({ kind: "error", message: `Could not end the session: ${(error as Error).message}` });
        return;
      }
    } else {
      setLastClose(null);
    }
    resetLocal();
  };

  /** A conversation belongs to one pipeline, so end the open one before moving on. */
  const switchTo = async (id: string) => {
    if (!active || id === active.id) return;
    if (sessionRef.current) {
      try {
        await closeChatSession(active.id, sessionRef.current);
      } catch {
        // Best effort: switching pipelines must not be blocked by a failed export.
      }
    }
    setActiveId(id);
    resetLocal();
    setLastClose(null);
  };

  // The declaration and the pipeline can disagree. The page says so rather than promising
  // memory the pipeline cannot keep, or hiding memory it does keep.
  const modeMismatch = active && !active.error && memoryMode === "enabled" && !keepsMemory;
  const modeHidden = active && !active.error && memoryMode === "disabled" && keepsMemory;

  const startLabel = memoryMode === "enabled" ? "Start Session" : "Start Chat";
  const endLabel = keepsMemory ? "End Session" : "End Chat";

  return (
    <div className="page">
      <header className="site-header">
        <div className="shell header-inner">
          <div className="brand">
            <span className="brand-mark">ABC</span>
            <span className="brand-name">ABC Insurance</span>
          </div>
          <nav className="site-nav">
            <a href="#policies">Policies</a>
            <a href="#assistant">Assistant</a>
            <a href="#about">About</a>
          </nav>
        </div>
      </header>

      <section className="hero">
        <div className="shell">
          <p className="eyebrow">Insurance Policy Wordings</p>
          <h1>Policy Wordings</h1>
          <p className="lede">
            The wordings below cover the home, health and motor policies. Read a wording, then
            ask the assistant on this page about the cover, the waiting periods or a claim.
          </p>
        </div>
      </section>

      <main className="shell">
        <section id="policies" className="policies">
          {POLICIES.map((policy) => (
            <article key={policy.title} className="policy-card">
              <h2>{policy.title}</h2>
              <p className="policy-summary">{policy.summary}</p>
              <ul>
                {policy.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>
          ))}
        </section>

        <section id="assistant" className="assistant">
          <div className="assistant-head">
            <div>
              <h2>Ask the assistant</h2>
              <p className="assistant-lede">
                This project runs in <strong>{memoryMode}</strong> mode, set by{" "}
                <code>MEMORY_STATE</code> in the backend&rsquo;s <code>.env</code>.{" "}
                {memoryMode === "enabled"
                  ? "Each conversation is a session: it is started on purpose, remembered while it runs, and ended on purpose."
                  : "Each question is answered on its own, with nothing carried between them."}{" "}
                Every answer is traced to Langfuse and Arize with the pipeline and Knowledge
                Product it ran on.
              </p>
            </div>
            {bots.length > 1 && (
              <label className="picker">
                <span>Assistant</span>
                <select
                  value={active?.id ?? ""}
                  onChange={(event) => void switchTo(event.target.value)}
                >
                  {bots.map((bot) => (
                    <option key={bot.id} value={bot.id}>
                      {bot.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          {configError && (
            <div className="banner error">
              <strong>No assistant is available.</strong> {configError}
            </div>
          )}

          {active?.error && (
            <div className="banner error">
              <strong>{active.label} did not answer.</strong> {active.error}. Check the endpoint
              in <code> backend/.env</code> and confirm the retrieval API runs on port 8001.
            </div>
          )}

          {modeMismatch && (
            <div className="banner warn">
              <strong>This project declares memory it cannot get.</strong> <code>MEMORY_STATE
              </code> is <code>enabled</code>, but the Knowledge Product{" "}
              <code>{active?.knowledge_product?.name ?? "of this pipeline"}</code> has no enabled
              Redis destination, so every question is answered on its own. The turns are tagged{" "}
              <code>prod-stateless</code>.
            </div>
          )}

          {modeHidden && (
            <div className="banner warn">
              <strong>This project declares no memory, but the pipeline keeps one.</strong>{" "}
              <code>MEMORY_STATE</code> is <code>disabled</code>, yet the Knowledge Product{" "}
              <code>{active?.knowledge_product?.name ?? "of this pipeline"}</code> has Redis
              enabled, so the platform still remembers the conversation. The turns are tagged{" "}
              <code>prod-session</code>.
            </div>
          )}

          {active && (
            <article className="panel">
              <header className="panel-head">
                <div className="panel-title">
                  <h3>{active.label}</h3>
                  {active.slug && <code className="slug">{active.slug}</code>}
                </div>
                <span className={keepsMemory ? "badge badge-on" : "badge badge-off"}>
                  {keepsMemory ? `Session memory · ${ttlLabel(active.session_memory?.ttl_seconds)}` : "Stateless"}
                </span>
              </header>

              <dl className="panel-meta">
                <div>
                  <dt>Knowledge Product</dt>
                  <dd>{active.knowledge_product?.name ?? "unknown"}</dd>
                </div>
                <div>
                  <dt>Strategy</dt>
                  <dd>{active.strategy ?? "-"}</dd>
                </div>
                <div>
                  <dt>Chat model</dt>
                  <dd>{active.chat_model ?? "-"}</dd>
                </div>
              </dl>

              {!started ? (
                <div className="chat-start">
                  <p className="chat-start-note">
                    {memoryMode === "enabled"
                      ? "The assistant keeps the conversation for this session, so a follow-up question is understood in context."
                      : "The assistant answers each question on its own and carries nothing between them."}
                  </p>
                  <button className="button primary" onClick={startChat} disabled={!!active.error}>
                    {startLabel}
                  </button>
                  {lastClose && (
                    <div className="inspect memory chat-start-result">
                      <div className="inspect-line">Previous conversation ended</div>
                      <div className="inspect-turn">{closeSummary(lastClose)}</div>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <div className="messages" aria-live="polite">
                    {messages.length === 0 && (
                      <p className="empty">
                        {memoryMode === "enabled"
                          ? "Ask a question to begin. The session is remembered from the first answer."
                          : "Ask a question. Nothing is carried to the next one."}
                      </p>
                    )}
                    {messages.map((message, index) => (
                      <div key={index} className={`bubble ${message.role}`}>
                        <div className="bubble-text">
                          {message.content || <span className="pending">...</span>}
                        </div>
                        {message.role === "assistant" && !!message.sources && (
                          <div className="bubble-meta">{message.sources} source passages</div>
                        )}
                      </div>
                    ))}
                    {busy && status && <p className="status">{status}</p>}
                  </div>

                  <form
                    className="composer"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const text = draft.trim();
                      if (!text || busy) return;
                      setDraft("");
                      void send(text);
                    }}
                  >
                    <input
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      placeholder="Ask about a policy..."
                      aria-label={`Message ${active.label}`}
                      disabled={busy}
                    />
                    <button className="button" type="submit" disabled={busy || !draft.trim()}>
                      Send
                    </button>
                  </form>

                  <p className="composer-hint">
                    {memoryMode === "enabled"
                      ? "The session keeps the newest exchanges. Ask a follow-up without repeating yourself."
                      : "Each question is answered alone. The pipeline keeps no conversation."}
                  </p>

                  <footer className="panel-foot">
                    <div className="session-row">
                      <span className="session-id" title={sessionId ?? ""}>
                        session {shortId(sessionId)}
                      </span>
                      <button
                        className="button ghost"
                        onClick={() => void checkMemory(active.id, sessionRef.current)}
                        disabled={busy}
                      >
                        Check memory
                      </button>
                      <button className="button ghost" onClick={() => void endChat()} disabled={busy}>
                        {endLabel}
                      </button>
                    </div>
                    {inspect && <InspectView result={inspect} />}
                  </footer>
                </>
              )}
            </article>
          )}
        </section>

        <section id="about" className="about">
          <h2>About this page</h2>
          <p>
            This is a demonstration site, and it calls the pipeline&rsquo;s own endpoint, so
            everything it sends is production traffic. The wording on this page is illustrative
            sample content, not a policy document of any insurer. The assistant answers from the
            knowledge base named on its panel, not from the text above.
          </p>
        </section>
      </main>

      <footer className="site-footer">
        <div className="shell">
          <span>Pipeline Test &middot; production mode</span>
          <span>Traces carry the pipeline and Knowledge Product they ran on.</span>
        </div>
      </footer>
    </div>
  );
}

function InspectView({ result }: { result: InspectResult }) {
  if (result.kind === "memory") {
    const { report } = result;
    return (
      <div className="inspect memory">
        <div className="inspect-line">
          <strong>{report.turns}</strong> turns remembered &middot; TTL {ttlLabel(report.ttl_seconds)}
        </div>
        {report.history.slice(-2).map((turn, index) => (
          <div key={index} className="inspect-turn">
            <span className={`role-tag ${turn.role}`}>{turn.role}</span>
            <span>{turn.content.slice(0, 120)}</span>
          </div>
        ))}
      </div>
    );
  }
  if (result.kind === "none") {
    return (
      <div className="inspect none">
        <div className="inspect-line">{result.message}</div>
        {result.code === "SESSION_MEMORY_UNAVAILABLE" && (
          <div className="inspect-turn">
            The Knowledge Product has no enabled Redis destination, so there is nothing to read
            and nothing to clear.
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="inspect bad">
      <div className="inspect-line">{result.message}</div>
    </div>
  );
}
