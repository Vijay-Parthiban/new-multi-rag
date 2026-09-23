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
    title: "Code of Conduct",
    summary: "The standard every employee, contractor and partner is held to.",
    points: [
      "Act with integrity in every client, vendor and colleague interaction.",
      "Declare a conflict of interest to your reporting manager within five working days.",
      "Do not accept gifts or hospitality that could influence a business decision.",
      "Report a suspected breach through the Ethics Helpline without fear of retaliation.",
    ],
  },
  {
    title: "Prevention of Sexual Harassment (POSH)",
    summary: "Zero tolerance, and a redressal path independent of your reporting line.",
    points: [
      "Every location has a constituted Internal Committee (IC) under the POSH Act, 2013.",
      "A complaint may be filed in writing to any IC member within three months of the incident.",
      "The IC completes an inquiry within 90 days and the report is confidential.",
      "Interim relief, including transfer or leave, may be granted while the inquiry runs.",
    ],
  },
  {
    title: "Leave and Attendance",
    summary: "How leave is earned, applied for and approved.",
    points: [
      "Leave is applied for through Ultimatix at least three working days in advance.",
      "Sick leave beyond two days requires a medical certificate from a registered practitioner.",
      "Earned leave lapses at the end of the leave year unless carried forward with approval.",
      "Attendance is recorded daily. A missed entry is regularised by your reporting manager.",
    ],
  },
  {
    title: "Hybrid Working",
    summary: "The default pattern and what a team may change about it.",
    points: [
      "The standard week is three days on campus and two days remote.",
      "An associate must be on campus on any day a client visit is scheduled.",
      "Remote work is from the registered base location only, in a secure network.",
      "A change to the team pattern needs approval from the delivery head, not the manager alone.",
    ],
  },
  {
    title: "Travel and Expense",
    summary: "Booking, entitlements and reimbursement.",
    points: [
      "All travel is booked through the approved travel desk. Self-booking needs prior approval.",
      "Entitlement depends on grade for both air class and hotel category.",
      "Submit claims within 30 days of completing the trip, with original invoices attached.",
      "A claim without a receipt is reimbursed only with a written exception from the unit head.",
    ],
  },
  {
    title: "Data Privacy and Security",
    summary: "How client and employee data must be handled.",
    points: [
      "Client data stays on approved systems. Personal email and consumer storage are prohibited.",
      "Use the corporate VPN for any access from outside an office network.",
      "Report a suspected breach to the Security Operations Centre within one hour.",
      "A security incident is reviewed after resolution to find the root cause.",
    ],
  },
  {
    title: "Resource Management",
    summary: "How associates move between projects.",
    points: [
      "Resource Management Group tags availability and proposes a match to the requesting project.",
      "An associate on the bench is expected to complete the assigned certification track.",
      "A release from a project needs a written handover accepted by the delivery manager.",
      "Interview readiness for an internal position is confirmed by the current reporting manager.",
    ],
  },
  {
    title: "Whistleblower Protection",
    summary: "A protected channel for reporting serious wrongdoing.",
    points: [
      "Reports may be made anonymously through the independent Ethics Helpline.",
      "Retaliation against a reporter is itself a breach of the Code of Conduct.",
      "The Ethics Office acknowledges every report and reports outcomes to the Audit Committee.",
      "Records are retained for the period required by the applicable law.",
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
  parts.push(
    result.trace.emitted
      ? `whole session exported as one trace ${shortId(result.trace.trace_id)}`
      : "no session trace, each turn was traced on its own",
  );
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
            <span className="brand-mark">TCS</span>
            <span className="brand-name">Tata Consultancy Services</span>
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
          <p className="eyebrow">Corporate Governance</p>
          <h1>Corporate Policies</h1>
          <p className="lede">
            The policies below govern how we work with each other, with our clients and with
            their data. Read the policy, then ask the assistant on this page about it.
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
            everything it sends is production traffic. The policy text is illustrative sample
            content and is not an official TCS publication. The assistant answers from the
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
