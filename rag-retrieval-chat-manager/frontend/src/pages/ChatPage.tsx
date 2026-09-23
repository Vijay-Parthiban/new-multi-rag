import React, { useEffect, useState, useRef } from "react";
import {
    listPipelines,
    listChatSessions,
    getChatSessionMessages,
    streamChat,
    getMessageMetrics,
    getChatStats,
    listGoldenDatasets,
    createEvaluationRun,
    getEvaluationRun,
    listGuardrailsConfigs,
    listPromptTemplates,
    closeChatSession,
    deleteChatSession,
    deleteChatMessage,
    sessionMemoryFor,
    PipelineRecord,
    PromptTemplate,
    ChatSession,
    ChatMessage,
    RAGMetricsResponse,
    GuardrailsConfig,
    ModelSettings,
    DEFAULT_MODEL_SETTINGS,
    MODEL_SETTING_FIELDS,
} from "../api";
import { IconChat, IconMoreHorizontal } from "../components/Icons";
import MarkdownMessage from "../components/MarkdownMessage";

const GUARD_CARD: Record<string, { icon: string; title: string; hint: string; tone: string }> = {
    ban_list: {
        icon: "🚫",
        title: "Banned keyword",
        hint: "This message contains a word or phrase that is not allowed.",
        tone: "ban",
    },
    pii_check: {
        icon: "🔒",
        title: "Personal information",
        hint: "This message appears to contain personally identifiable information.",
        tone: "pii",
    },
    toxic_language: {
        icon: "⚠️",
        title: "Toxic language",
        hint: "This message was flagged for toxic or harmful language.",
        tone: "toxic",
    },
};

function BlockedCard({
    guard,
    phase,
    content,
}: {
    guard?: string | null;
    phase?: string | null;
    content?: string;
}) {
    const card = GUARD_CARD[guard || ""] || {
        icon: "🛡️",
        title: guard || "Guardrail",
        hint: content || "This message was blocked by a safety policy.",
        tone: "ban",
    };
    const phaseLabel = phase === "output" ? "Response blocked" : "Input blocked";
    return (
        <div className={`chat-blocked-card chat-blocked-card--${card.tone}`}>
            <div className="chat-blocked-card-header">
                <span className="chat-blocked-card-icon">{card.icon}</span>
                <div>
                    <div className="chat-blocked-card-title">{card.title}</div>
                    <div className="chat-blocked-card-phase">{phaseLabel}</div>
                </div>
            </div>
            <p className="chat-blocked-card-body">{content || card.hint}</p>
        </div>
    );
}

/**
 * The pipeline's saved settings, with any unset key filled from the defaults.
 *
 * A saved record can leave a key out, or set it to null, when it predates that
 * key. Both mean "not configured", so the default fills the gap rather than the
 * input rendering empty.
 */
function seedModelSettings(saved?: ModelSettings | null): Required<ModelSettings> {
    const out = { ...DEFAULT_MODEL_SETTINGS };
    if (saved) {
        for (const field of MODEL_SETTING_FIELDS) {
            const value = saved[field.key];
            if (value !== null && value !== undefined) {
                out[field.key] = value;
            }
        }
    }
    return out;
}

export default function ChatPage() {
    const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
    const [selectedPipeline, setSelectedPipeline] = useState<PipelineRecord | null>(null);

    // Chat sessions
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [inputText, setInputText] = useState("");
    const [chatLoading, setChatLoading] = useState(false);
    // False until a conversation is started or opened. The chat area is blank until then,
    // so the first turn cannot be sent into a session the user never began.
    const [composerReady, setComposerReady] = useState(false);

    // Streaming state
    const [agentStatus, setAgentStatus] = useState<string | null>(null);
    const [streamingAnswer, setStreamingAnswer] = useState<string>("");

    // Metrics database
    const [messageMetrics, setMessageMetrics] = useState<Record<string, RAGMetricsResponse>>({});
    const [pollingMetrics, setPollingMetrics] = useState<Record<string, boolean>>({});

    // Config overrides
    const [retrievalMode, setRetrievalMode] = useState<string>("hybrid");
    const [retrieveLimit, setRetrieveLimit] = useState<number>(20);
    const [rerankEnabled, setRerankEnabled] = useState<boolean>(true);
    const [topK, setTopK] = useState<number>(5);

    const [guardrailsConfigs, setGuardrailsConfigs] = useState<GuardrailsConfig[]>([]);
    const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);

    // Working copies of the pipeline's own settings. A turn reads these, so they
    // can be changed and tried without writing back to the pipeline. Picking
    // another pipeline, or pressing Reset, puts them back to the saved values.
    const [overridePromptId, setOverridePromptId] = useState<string>("");
    const [overrideGuardrailsId, setOverrideGuardrailsId] = useState<string>("");
    const [overrideSettings, setOverrideSettings] = useState<ModelSettings>({
        ...DEFAULT_MODEL_SETTINGS,
    });
    // Bumped by Reset so the seeding effect runs again for the same pipeline.
    const [resetNonce, setResetNonce] = useState(0);

    // Both panels start open. The choice is remembered, so a reload does not
    // undo it and does not fight the pipeline seeding below.
    const [showConfig, setShowConfig] = useState<boolean>(
        () => localStorage.getItem("chat.configCollapsed") !== "1",
    );
    const [showAside, setShowAside] = useState<boolean>(
        () => localStorage.getItem("chat.asideCollapsed") !== "1",
    );

    useEffect(() => {
        localStorage.setItem("chat.configCollapsed", showConfig ? "0" : "1");
    }, [showConfig]);

    useEffect(() => {
        localStorage.setItem("chat.asideCollapsed", showAside ? "0" : "1");
    }, [showAside]);

    // Derived, not stored: the id is the single source of truth, so seeding it
    // from a pipeline needs no second lookup when the option list arrives late.
    const selectedGuardrailsConfig =
        guardrailsConfigs.find((c) => c.id === overrideGuardrailsId) ?? null;

    // Whether this pipeline keeps the conversation. This is the same rule the backend
    // applies and the Pipelines page shows, read from the Knowledge Product's destinations:
    // an enabled Redis destination is the whole gate.
    const memoryState = sessionMemoryFor(selectedPipeline?.knowledge_product?.destinations);
    // An open conversation, or one just started, is what makes the composer live.
    const chatReady = composerReady || Boolean(activeSessionId);

    // Stats
    const [stats, setStats] = useState<any>(null);

    // Evaluations
    const [datasets, setDatasets] = useState<any[]>([]);
    const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
    const [activeEvalRun, setActiveEvalRun] = useState<any>(null);

    // Collapsible eval panel
    const [showEvalPanel, setShowEvalPanel] = useState(false);

    const [sessionMenuId, setSessionMenuId] = useState<string | null>(null);
    const [messageMenuId, setMessageMenuId] = useState<string | null>(null);

    const messageEndRef = useRef<HTMLDivElement>(null);

    // Load initial data
    useEffect(() => {
        loadPipelines();
        loadSessions();
        loadStats();
        loadDatasets();
        loadGuardrailsConfigs();
        loadPromptTemplates();
    }, []);

    // Seed the working copies from the chosen pipeline, and again on Reset.
    useEffect(() => {
        if (!selectedPipeline) return;
        setOverridePromptId(selectedPipeline.prompt_template_id ?? "");
        setOverrideGuardrailsId(selectedPipeline.guardrails_config_id ?? "");
        setOverrideSettings(seedModelSettings(selectedPipeline.model_settings));
    }, [selectedPipeline, resetNonce]);

    // Scroll to bottom on new message
    useEffect(() => {
        messageEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    // Load message history on active session change
    useEffect(() => {
        if (activeSessionId) {
            loadMessages(activeSessionId);
        } else {
            setMessages([]);
        }
    }, [activeSessionId]);

    // Poll metrics only for assistant messages that have a pending/unknown metrics job
    useEffect(() => {
        const pendingMsgIds = messages
            .filter((m) => {
                if (m.role !== "assistant" || m.id.startsWith("temp-")) return false;
                if (messageMetrics[m.id] || pollingMetrics[m.id]) return false;
                // Skip greetings / blocked turns / messages with no metrics row expected
                if (m.blocked || m.trace?.route === "greeting" || m.trace?.route === "blocked") return false;
                if (m.metrics_status === "skipped" || m.metrics_status === "failed") return false;
                // Poll when pending, completed-but-not-loaded, or unknown (just streamed)
                return m.metrics_status === "pending" || m.metrics_status === "completed" || m.metrics_status == null;
            })
            .map((m) => m.id);

        pendingMsgIds.forEach((msgId) => {
            startPollingMetrics(msgId);
        });
    }, [messages, messageMetrics]);

    // Poll active evaluation run
    useEffect(() => {
        if (!activeEvalRun || activeEvalRun.status === "completed" || activeEvalRun.status === "failed") {
            return;
        }
        const timer = setInterval(async () => {
            try {
                const run = await getEvaluationRun(activeEvalRun.run_id);
                setActiveEvalRun(run);
                if (run.status === "completed" || run.status === "failed") {
                    clearInterval(timer);
                }
            } catch (err) {
                console.error("Error polling evaluation run", err);
            }
        }, 2000);

        return () => clearInterval(timer);
    }, [activeEvalRun]);

    // Close open menus on outside click / Escape
    useEffect(() => {
        if (!sessionMenuId && !messageMenuId) return;
        const onPointerDown = (e: MouseEvent) => {
            const target = e.target as HTMLElement | null;
            if (target?.closest(".chat-menu")) return;
            setSessionMenuId(null);
            setMessageMenuId(null);
        };
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                setSessionMenuId(null);
                setMessageMenuId(null);
            }
        };
        document.addEventListener("mousedown", onPointerDown);
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("mousedown", onPointerDown);
            document.removeEventListener("keydown", onKeyDown);
        };
    }, [sessionMenuId, messageMenuId]);

    const loadPipelines = async () => {
        try {
            const list = await listPipelines();
            setPipelines(list);
            if (list.length > 0) {
                setSelectedPipeline(list[0]);
            }
        } catch (err) {
            console.error("Failed to load pipelines", err);
        }
    };

    const loadSessions = async () => {
        try {
            const list = await listChatSessions();
            // The list is refreshed, but no conversation is opened. The chat area starts
            // blank, and a conversation begins only when + New is pressed or a history row
            // is chosen, so the page never lands in the middle of an old session.
            setSessions(list);
        } catch (err) {
            console.error("Failed to load sessions", err);
        }
    };

    const loadMessages = async (sid: string) => {
        try {
            const msgs = await getChatSessionMessages(sid);
            setMessages(msgs);
        } catch (err) {
            console.error("Failed to load messages", err);
        }
    };

    const loadStats = async () => {
        try {
            const s = await getChatStats(10);
            setStats(s);
        } catch (err) {
            console.error("Failed to load stats", err);
        }
    };

    const loadDatasets = async () => {
        try {
            const ds = await listGoldenDatasets();
            setDatasets(ds);
            if (ds.length > 0) {
                setSelectedDatasetId(ds[0].dataset_id);
            }
        } catch (err) {
            console.error("Failed to load datasets", err);
        }
    };

    const loadGuardrailsConfigs = async () => {
        try {
            const res = await listGuardrailsConfigs(false);
            // The chosen id is the selection, so only the options change here.
            setGuardrailsConfigs(res.items || []);
        } catch (err) {
            console.error("Failed to load guardrails configs", err);
        }
    };

    const loadPromptTemplates = async () => {
        try {
            const res = await listPromptTemplates();
            setPromptTemplates(res.items || []);
        } catch (err) {
            console.error("Failed to load prompt templates", err);
        }
    };

    const startPollingMetrics = async (msgId: string) => {
        setPollingMetrics((prev) => ({ ...prev, [msgId]: true }));
        let attempts = 0;
        const interval = setInterval(async () => {
            attempts++;
            try {
                const metrics = await getMessageMetrics(msgId);
                if (metrics.status === "completed" || metrics.status === "failed" || attempts > 40) {
                    setMessageMetrics((prev) => ({ ...prev, [msgId]: metrics }));
                    setPollingMetrics((prev) => ({ ...prev, [msgId]: false }));
                    clearInterval(interval);
                    if (metrics.status === "completed") loadStats();
                }
            } catch (err) {
                const msg = err instanceof Error ? err.message : String(err);
                // 404 = metrics row not created yet — keep polling briefly
                if (msg.includes("404") && attempts <= 8) return;
                console.error("Error polling metrics for message", msgId, err);
                clearInterval(interval);
                setPollingMetrics((prev) => ({ ...prev, [msgId]: false }));
            }
        }, 2500);
    };

    const handleStartNewSession = () => {
        setActiveSessionId(null);
        setMessages([]);
        setMessageMetrics({});
        setSessionMenuId(null);
        setMessageMenuId(null);
        // The next turn goes into a conversation that now exists. Until + New is pressed the
        // area stays blank, so a turn is never sent into a session nobody opened.
        setComposerReady(true);
    };

    /**
     * Close the conversation.
     *
     * A pipeline with session memory exports the whole conversation as one trace and drops
     * what it remembered. A stateless pipeline kept nothing, so this only closes the page.
     */
    const handleEndSession = async () => {
        const keepsMemory = memoryState.enabled;
        const question = keepsMemory
            ? "End this session?\n\nThe conversation closes, its session memory is removed, and it stays in chat history."
            : "Close this chat?\n\nThe conversation closes and stays in chat history.";
        if (!window.confirm(question)) return;

        if (activeSessionId) {
            try {
                await closeChatSession(activeSessionId, selectedPipeline?.id ?? null);
            } catch (err) {
                console.error("Failed to close the session", err);
                alert("Failed to close the session");
                return;
            }
        }

        setActiveSessionId(null);
        setMessages([]);
        setMessageMetrics({});
        setComposerReady(false);
        await loadSessions();
    };

    const handleDeleteSession = async (sessionId: string) => {
        if (!window.confirm("Delete this conversation? It will be removed from chat history.")) return;
        setSessionMenuId(null);
        try {
            await deleteChatSession(sessionId);
            setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
            if (activeSessionId === sessionId) {
                setActiveSessionId(null);
                setMessages([]);
            }
        } catch (err) {
            console.error("Failed to delete conversation", err);
            alert("Failed to delete conversation");
        }
    };

    const handleDeleteMessageTurn = async (assistantMessageId: string) => {
        if (assistantMessageId.startsWith("temp-")) return;
        if (!window.confirm("Delete this reply and its question from the conversation?")) return;
        setMessageMenuId(null);
        try {
            const result = await deleteChatMessage(assistantMessageId);
            const deleted = new Set(result.deleted_message_ids);
            setMessages((prev) => {
                const next = prev.filter((m) => !deleted.has(m.id));
                if (next.length === 0 && activeSessionId === result.session_id) {
                    setActiveSessionId(null);
                }
                return next;
            });
            setMessageMetrics((prev) => {
                const next = { ...prev };
                deleted.forEach((id) => {
                    delete next[id];
                });
                return next;
            });
            await loadSessions();
        } catch (err) {
            console.error("Failed to delete message", err);
            alert("Failed to delete message");
        }
    };

    const handleSendMessage = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!inputText.trim() || chatLoading) return;

        const userMessage: ChatMessage = {
            id: `temp-${Date.now()}`,
            role: "user",
            content: inputText,
            created_at: new Date().toISOString(),
            sources: []
        };

        setMessages((prev) => [...prev, userMessage]);
        setInputText("");
        setChatLoading(true);
        setAgentStatus(null);
        setStreamingAnswer("");

        try {
            const payload: any = {
                query: userMessage.content,
                session_id: activeSessionId,
                // Names the pipeline for the trace. The backend reads the pipeline and its
                // Knowledge Product from the ingestion service itself, so the recorded
                // configuration describes what actually ran.
                pipeline_id: selectedPipeline?.id ?? undefined,
                retrieval_mode: retrievalMode,
                retrieve_limit: retrieveLimit,
                rerank_enabled: rerankEnabled,
                top_k: topK,
                // The working copies, not the pipeline's saved values. The
                // assistant route treats each of these as an override for this
                // turn only, so nothing here is written back to the pipeline.
                guardrails_config_id: overrideGuardrailsId || undefined,
                prompt_template_id: overridePromptId || undefined,
                model_settings: overrideSettings,
            };

            // An assistant resolves its own collection, embedding model and
            // strategy from the Knowledge Product it reads, so the request
            // carries none of them. A legacy pipeline still runs the old path.
            const assistantSlug = selectedPipeline?.slug ?? null;
            if (selectedPipeline && !assistantSlug) {
                payload.collection = selectedPipeline.qdrant_collection;
                payload.embedding_model = selectedPipeline.embedding_model;
                if (selectedPipeline.sparse_embedding_model) {
                    payload.sparse_embedding_model = selectedPipeline.sparse_embedding_model;
                }
                // Image-only multimodal indexes have no sparse vectors — dense retrieval is required
                if (
                    selectedPipeline.modality === "image" ||
                    (selectedPipeline.rag_strategy === "multimodal" && !selectedPipeline.sparse_embedding_model)
                ) {
                    payload.retrieval_mode = "dense";
                }
            }

            let finalMetadata: any = null;
            let fullText = "";
            // sessionAck holds real IDs sent after DB save
            let sessionAck: { session_id: string; message_id: string; route: string; metrics_status?: string } | null = null;
            let blockedInfo: {
                content: string;
                blocked_by_guard?: string;
                blocked_on?: string;
            } | null = null;

            for await (const event of streamChat(
                payload,
                {
                    ...(assistantSlug ? { path: `/api/assistants/${assistantSlug}/chat/stream` } : {}),
                    // Every turn from this page is a test turn. An external caller uses the
                    // same route and sends no header, so its turns are production.
                    traceMode: "test",
                },
            )) {
                if (event.type === "status") {
                    setAgentStatus(event.message || null);
                } else if (event.type === "token") {
                    setAgentStatus(null); // Hide pill once tokens start
                    fullText += event.content || "";
                    setStreamingAnswer(fullText);
                } else if (event.type === "done") {
                    finalMetadata = event.metadata;
                } else if (event.type === "blocked") {
                    blockedInfo = {
                        content: event.content || "This message was blocked by a safety policy.",
                        blocked_by_guard: event.blocked_by_guard,
                        blocked_on: event.blocked_on,
                    };
                    setAgentStatus(null);
                    setStreamingAnswer("");
                } else if (event.type === "session") {
                    // Sent after DB save — contains real session_id, message_id, and route
                    sessionAck = {
                        session_id: event.session_id!,
                        message_id: event.message_id!,
                        route: event.route || "normal",
                        metrics_status: event.metrics_status,
                    };
                } else if (event.type === "error") {
                    throw new Error(event.content || "Unknown stream error");
                }
            }

            // Prefer real IDs from the session ack event
            const resSessionId = sessionAck?.session_id || finalMetadata?.session_id || activeSessionId;
            const resMsgId = sessionAck?.message_id || finalMetadata?.message_id;
            const resRoute = blockedInfo ? "blocked" : (sessionAck?.route || finalMetadata?.route || null);
            const resMetricsStatus =
                sessionAck?.metrics_status ??
                (resRoute === "greeting" || resRoute === "blocked" ? "skipped" : "pending");

            // Build the final assistant message with real ID + route
            const asstMsg: ChatMessage = {
                id: resMsgId || `temp-asst-${Date.now()}`,
                role: "assistant",
                content: blockedInfo?.content || fullText,
                created_at: new Date().toISOString(),
                sources: blockedInfo ? [] : (finalMetadata?.sources || []),
                trace: resRoute
                    ? { retrieval_mode: null, rerank_enabled: null, generation_model: null, route: resRoute }
                    : undefined,
                metrics_status: resMetricsStatus,
                blocked: Boolean(blockedInfo),
                blocked_by_guard: blockedInfo?.blocked_by_guard || null,
                blocked_on: blockedInfo?.blocked_on || null,
            };

            setMessages(prev => [...prev, asstMsg]);

            if (!activeSessionId && resSessionId) {
                setActiveSessionId(resSessionId);
                loadSessions();
            } else if (resSessionId) {
                // Background refresh to pick up any DB-side changes
                loadMessages(resSessionId);
            }
        } catch (err) {
            console.error("Failed to stream chat message", err);
            setMessages((prev) => [
                ...prev,
                {
                    id: `temp-err-${Date.now()}`,
                    role: "assistant",
                    content: `Error occurred: ${(err as Error).message}`,
                    created_at: new Date().toISOString(),
                    sources: []
                }
            ]);
        } finally {
            setChatLoading(false);
            setAgentStatus(null);
            setStreamingAnswer("");
        }
    };

    const handleStartEval = async () => {
        if (!selectedDatasetId) return;
        try {
            const config: any = {
                retrieval_mode: retrievalMode,
                retrieve_limit: retrieveLimit,
                rerank_enabled: rerankEnabled,
                top_k: topK,
            };

            // A legacy pipeline passes its own store; an assistant resolves it
            // from the Knowledge Product, so the config carries none of it.
            if (selectedPipeline && !selectedPipeline.slug) {
                config.collection = selectedPipeline.qdrant_collection;
                config.embedding_model = selectedPipeline.embedding_model;
                if (selectedPipeline.sparse_embedding_model) {
                    config.sparse_embedding_model = selectedPipeline.sparse_embedding_model;
                }
            }

            const run = await createEvaluationRun(selectedDatasetId, config);
            const initialRun = await getEvaluationRun(run.run_id);
            setActiveEvalRun(initialRun);
        } catch (err) {
            alert(`Failed to start evaluation run: ${(err as Error).message}`);
        }
    };


    const formatTime = (dateStr: string | null) => {
        if (!dateStr) return "";
        try {
            const d = new Date(dateStr);
            return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        } catch {
            return "";
        }
    };

    // What the pipeline saved, for comparing against the working copies.
    const savedSettings = seedModelSettings(selectedPipeline?.model_settings);
    const promptOverridden = overridePromptId !== (selectedPipeline?.prompt_template_id ?? "");
    const guardrailsOverridden =
        overrideGuardrailsId !== (selectedPipeline?.guardrails_config_id ?? "");
    const settingsOverridden = MODEL_SETTING_FIELDS.some(
        (f) => overrideSettings[f.key] !== savedSettings[f.key],
    );
    const isOverridden = promptOverridden || guardrailsOverridden || settingsOverridden;

    // Reset re-seeds from the pipeline; it writes nothing back.
    const resetOverrides = () => setResetNonce((n) => n + 1);

    // Stable sort: chronologically by created_at, with role-based tie-breaker
    const sortedMessages = [...messages].sort((a, b) => {
        const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;

        if (timeA !== timeB) return timeA - timeB;

        // Tie-breaker for identical timestamps (which happens because backend adds them in the same second)
        if (a.role === "user" && b.role === "assistant") return -1;
        if (a.role === "assistant" && b.role === "user") return 1;

        return 0;
    });

    return (
        <div className="page" style={{ maxWidth: "100%", padding: "1rem 1rem 0" }}>
            <div className={`chat-layout${showAside ? "" : " chat-layout--aside-collapsed"}`}>

                {/* ═══ LEFT: Conversation Sidebar ═══ */}
                <div className="chat-sidebar">

                    {/* Sidebar Header */}
                    <div className="chat-sidebar-header">
                        <h2>
                            <IconChat className="panel-title-icon" size={16} />
                            Conversations
                        </h2>
                        <button className="btn btn-sm btn-primary" onClick={handleStartNewSession}>
                            + New
                        </button>
                    </div>

                    {/* Pipeline Selector */}
                    <div className="chat-pipeline-config">
                        <div className="chat-sidebar-section-title">Pipeline</div>
                        <select
                            className="input"
                            value={selectedPipeline?.id || ""}
                            onChange={(e) => {
                                const found = pipelines.find((p) => p.id === e.target.value);
                                if (found) setSelectedPipeline(found);
                            }}
                        >
                            {pipelines.map((p) => (
                                <option key={p.id} value={p.id}>
                                    {p.name} ({p.rag_strategy})
                                </option>
                            ))}
                        </select>

                        {selectedPipeline && (
                            <div className="chat-pipeline-info">
                                <div><span className="muted">Strategy:</span> <span className="mono">{selectedPipeline.rag_strategy}</span></div>
                                {selectedPipeline.knowledge_product && (
                                    <div>
                                        <span className="muted">Knowledge Product:</span>{" "}
                                        <span className="mono">{selectedPipeline.knowledge_product.name}</span>
                                        <span className="muted"> · {selectedPipeline.knowledge_product.chunk_strategy}</span>
                                    </div>
                                )}
                                {selectedPipeline.chat_model && (
                                    <div><span className="muted">Model:</span> <span className="mono" style={{ wordBreak: "break-all" }}>{selectedPipeline.chat_model}</span></div>
                                )}
                                {selectedPipeline.slug && (
                                    <div><span className="muted">Endpoint:</span> <span className="mono" style={{ wordBreak: "break-all" }}>{selectedPipeline.slug}</span></div>
                                )}
                                <div>
                                    <span className="muted">Memory:</span>{" "}
                                    <span className={`memory-chip ${memoryState.enabled ? "memory-chip--on" : "memory-chip--off"}`}>
                                        {memoryState.enabled
                                            ? `available · ${memoryState.ttlSeconds ? Math.round(memoryState.ttlSeconds / 3600) + "h" : "no"} TTL`
                                            : "not available"}
                                    </span>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Session List */}
                    <div className="chat-sidebar-section">
                        <div className="chat-sidebar-section-title">Chat History</div>
                    </div>
                    <div className="chat-sessions-list">
                        {sessions.length === 0 ? (
                            <div style={{ padding: "1.5rem 0.5rem", textAlign: "center" }}>
                                <span className="muted" style={{ fontSize: "0.8rem" }}>No conversations yet</span>
                            </div>
                        ) : (
                            sessions.map((s) => {
                                const isActive = s.session_id === activeSessionId;
                                const menuOpen = sessionMenuId === s.session_id;
                                return (
                                    <div
                                        key={s.session_id}
                                        className={`chat-session-item ${isActive ? "active" : ""}`}
                                        onClick={() => {
                                            setActiveSessionId(s.session_id);
                                            setComposerReady(true);
                                        }}
                                    >
                                        <div className="chat-session-item-main">
                                            <span className="session-preview">
                                                {s.preview || `Session ${s.session_id.substring(0, 8)}`}
                                            </span>
                                            <span className="session-meta">
                                                {s.message_count} messages
                                                {s.last_message_at && ` · ${formatTime(s.last_message_at)}`}
                                            </span>
                                        </div>
                                        <div className="chat-menu chat-session-menu">
                                            <button
                                                type="button"
                                                className="chat-menu-trigger"
                                                aria-label="Conversation actions"
                                                aria-expanded={menuOpen}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setMessageMenuId(null);
                                                    setSessionMenuId(menuOpen ? null : s.session_id);
                                                }}
                                            >
                                                <IconMoreHorizontal size={14} />
                                            </button>
                                            {menuOpen && (
                                                <div className="chat-menu-dropdown" role="menu">
                                                    <button
                                                        type="button"
                                                        className="chat-menu-item chat-menu-item--danger"
                                                        role="menuitem"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleDeleteSession(s.session_id);
                                                        }}
                                                    >
                                                        Delete conversation
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>

                {/* ═══ RIGHT: Main Chat Area ═══ */}
                <div className="chat-main">

                    {/* Pipeline configuration. Strategy and Model are fixed by
                        the pipeline and cannot be changed here. Everything to
                        the right of them is a working copy: it applies to the
                        turns from this page, and Reset restores the values the
                        pipeline saved. Nothing here is written back. */}
                    <div className="chat-config-bar">
                        <div className="chat-config-bar-row">
                            <button
                                type="button"
                                className="btn btn-sm chat-panel-toggle"
                                onClick={() => setShowAside((v) => !v)}
                                aria-expanded={showAside}
                                title={showAside ? "Hide the conversation list" : "Show the conversation list"}
                            >
                                {showAside ? "◀ History" : "▶ History"}
                            </button>

                            <div className="chat-config-bar-item">
                                <span className="chat-config-bar-label">Strategy</span>
                                <span className="mono">{selectedPipeline?.rag_strategy ?? "—"}</span>
                                <span className="chat-config-lock" title="Fixed by the pipeline">
                                    locked
                                </span>
                            </div>
                            <div className="chat-config-bar-item">
                                <span className="chat-config-bar-label">Model</span>
                                <span className="mono" style={{ wordBreak: "break-all" }}>
                                    {selectedPipeline?.chat_model ?? "—"}
                                </span>
                                <span className="chat-config-lock" title="Fixed by the pipeline">
                                    locked
                                </span>
                            </div>

                            <div className="chat-config-bar-spacer" />

                            {/* The session the next turn continues. */}
                            <div className="chat-session-indicator">
                                <div className={`session-dot ${activeSessionId ? "connected" : "new"}`} />
                                <span className="mono" style={{ color: "var(--text-secondary)" }}>
                                    {activeSessionId ? activeSessionId.substring(0, 12) + "…" : "New Session"}
                                </span>
                            </div>

                            {/* Ending the conversation. A pipeline with session memory is
                                asked to end a session, because there is memory to drop and a
                                whole conversation to export. One without keeps nothing, so it
                                only closes the chat. */}
                            {chatReady && (
                                <button
                                    type="button"
                                    className="btn btn-sm"
                                    onClick={handleEndSession}
                                    disabled={chatLoading}
                                    title={
                                        memoryState.enabled
                                            ? "Close this conversation, export it as one trace, and remove its session memory"
                                            : "Close this conversation"
                                    }
                                >
                                    {memoryState.enabled ? "End Session" : "End Chat"}
                                </button>
                            )}

                            {isOverridden && (
                                <span className="chat-override-badge" role="status">
                                    testing overrides
                                </span>
                            )}

                            <button
                                type="button"
                                className="btn btn-sm chat-panel-toggle"
                                onClick={() => setShowConfig((v) => !v)}
                                aria-expanded={showConfig}
                                aria-controls="chat-config-controls"
                                title={
                                    showConfig
                                        ? "Hide the settings below"
                                        : "Show the settings to change and test"
                                }
                            >
                                {showConfig ? "Hide settings" : "Show settings"}
                            </button>

                            <button
                                type="button"
                                className="btn btn-sm"
                                onClick={resetOverrides}
                                disabled={!isOverridden}
                                title={
                                    isOverridden
                                        ? "Restore the values saved on this pipeline"
                                        : "Already showing the values saved on this pipeline"
                                }
                            >
                                Reset
                            </button>
                        </div>

                        {showConfig && (
                            <>
                            <div className="chat-config-bar-row chat-config-controls" id="chat-config-controls">
                                {/* How the sources are found, before the model
                                    sees them. These four are the old toolbar. */}
                                <div className="chat-setting">
                                    <label className="chat-setting-label" htmlFor="chat-override-mode">
                                        Retrieval mode
                                    </label>
                                    <select
                                        id="chat-override-mode"
                                        className="input"
                                        value={retrievalMode}
                                        onChange={(e) => setRetrievalMode(e.target.value)}
                                    >
                                        <option value="hybrid">Hybrid</option>
                                        <option value="dense">Dense</option>
                                        <option value="sparse">Sparse</option>
                                    </select>
                                    <span className="chat-setting-hint">
                                        Which store to search: vectors, keywords, or both fused.
                                    </span>
                                </div>

                                <div className="chat-setting">
                                    <label className="chat-setting-label" htmlFor="chat-override-limit">
                                        Retrieve limit
                                    </label>
                                    <input
                                        id="chat-override-limit"
                                        className="input"
                                        type="number"
                                        min={1}
                                        max={50}
                                        value={retrieveLimit}
                                        title="How many chunks to fetch before reranking."
                                        onChange={(e) => setRetrieveLimit(parseInt(e.target.value) || 1)}
                                    />
                                    <span className="chat-setting-hint">
                                        Chunks fetched before reranking.
                                    </span>
                                </div>

                                <div className="chat-setting">
                                    <label className="chat-setting-label" htmlFor="chat-override-rerank">
                                        Rerank
                                    </label>
                                    <input
                                        id="chat-override-rerank"
                                        type="checkbox"
                                        checked={rerankEnabled}
                                        onChange={(e) => setRerankEnabled(e.target.checked)}
                                    />
                                    <span className="chat-setting-hint">
                                        Reorder the fetched chunks by relevance.
                                    </span>
                                </div>

                                {rerankEnabled && (
                                    <div className="chat-setting">
                                        <label className="chat-setting-label" htmlFor="chat-override-chunks">
                                            Top K (chunks)
                                        </label>
                                        <input
                                            id="chat-override-chunks"
                                            className="input"
                                            type="number"
                                            min={1}
                                            max={20}
                                            value={topK}
                                            onChange={(e) => setTopK(parseInt(e.target.value) || 1)}
                                        />
                                        <span className="chat-setting-hint">
                                            How many reranked chunks reach the prompt.
                                        </span>
                                    </div>
                                )}

                                <div className="chat-setting">
                                    <label className="chat-setting-label" htmlFor="chat-override-prompt">
                                        Prompt template
                                        {promptOverridden && (
                                            <span className="chat-override-badge">modified</span>
                                        )}
                                    </label>
                                    <select
                                        id="chat-override-prompt"
                                        className="input"
                                        value={overridePromptId}
                                        onFocus={() => loadPromptTemplates()}
                                        onChange={(e) => setOverridePromptId(e.target.value)}
                                    >
                                        <option value="">Pipeline default</option>
                                        {promptTemplates.map((t) => (
                                            <option key={t.id} value={t.id}>
                                                {t.name}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                <div className="chat-setting">
                                    <label
                                        className="chat-setting-label"
                                        htmlFor="chat-override-guardrails"
                                    >
                                        Guardrails
                                        {guardrailsOverridden && (
                                            <span className="chat-override-badge">modified</span>
                                        )}
                                    </label>
                                    <select
                                        id="chat-override-guardrails"
                                        className="input"
                                        value={overrideGuardrailsId}
                                        onFocus={() => loadGuardrailsConfigs()}
                                        onChange={(e) => setOverrideGuardrailsId(e.target.value)}
                                    >
                                        <option value="">None</option>
                                        {guardrailsConfigs.map((c) => (
                                            <option key={c.id} value={c.id}>
                                                {c.name}
                                                {c.is_active ? "" : " (inactive)"}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                {MODEL_SETTING_FIELDS.map((field) => (
                                    <div className="chat-setting" key={field.key}>
                                        <label
                                            className="chat-setting-label"
                                            htmlFor={`chat-setting-${field.key}`}
                                        >
                                            {field.label}
                                            {settingsOverridden &&
                                                overrideSettings[field.key] !== savedSettings[field.key] && (
                                                    <span className="chat-override-badge">
                                                        modified
                                                    </span>
                                                )}
                                        </label>
                                        <input
                                            id={`chat-setting-${field.key}`}
                                            className="input"
                                            type="number"
                                            min={field.min}
                                            max={field.max}
                                            step={field.step}
                                            value={overrideSettings[field.key] ?? ""}
                                            title={field.hint}
                                            onChange={(e) => {
                                                const raw = e.target.value;
                                                setOverrideSettings((prev) => ({
                                                    ...prev,
                                                    [field.key]: raw === "" ? null : Number(raw),
                                                }));
                                            }}
                                        />
                                        <span className="chat-setting-hint">{field.hint}</span>
                                    </div>
                                ))}
                            </div>

                            <div className="chat-config-bar-note">
                                Values saved on this pipeline. Changes above apply to this page only
                                and are restored by Reset or a page refresh.
                                {selectedGuardrailsConfig && (
                                    <>
                                        {" "}Guardrails mode: {selectedGuardrailsConfig.mode}.
                                    </>
                                )}
                            </div>
                            </>
                        )}
                    </div>

                    {/* Messages */}
                    <div className="chat-messages">
                        {sortedMessages.length === 0 ? (
                            <div className="chat-empty">
                                <IconChat className="empty-icon" size={36} />
                                <h3>{chatReady ? "New conversation" : "Click New to start chatting"}</h3>
                                <p>
                                    {chatReady
                                        ? memoryState.enabled
                                            ? "This pipeline keeps the conversation, so a follow-up question is understood in context. End the session when you are done to export it and clear the memory."
                                            : "This pipeline keeps no conversation, so each question is answered on its own. Every turn is traced separately."
                                        : memoryState.enabled
                                            ? `Select a pipeline in the sidebar, then press + New. "${selectedPipeline?.knowledge_product?.name ?? "This pipeline"}" has Redis enabled, so the conversation will be remembered.`
                                            : `Select a pipeline in the sidebar, then press + New. "${selectedPipeline?.knowledge_product?.name ?? "This pipeline"}" has no Redis destination, so each question will be answered on its own.`}
                                </p>
                            </div>
                        ) : (
                            sortedMessages.map((m) => {
                                const isUser = m.role === "user";
                                const mMetrics = messageMetrics[m.id];
                                const isPolling = pollingMetrics[m.id];

                                return (
                                    <div
                                        key={m.id}
                                        className={`chat-message ${isUser ? "chat-message--user" : "chat-message--assistant"}`}
                                    >
                                        {/* Role label + timestamp */}
                                        <div className="chat-message-header">
                                            <span className="chat-role-label">{isUser ? "You" : "Assistant"}</span>
                                            {m.created_at && (
                                                <span className="chat-message-time">{formatTime(m.created_at)}</span>
                                            )}
                                            {/* Route badge */}
                                            {!isUser && m.trace?.route && (() => {
                                                const routeLabels: Record<string, { icon: string; label: string; color: string }> = {
                                                    // Only "normal" and "blocked" are reachable: the query
                                                    // router and self-corrective RAG were never implemented.
                                                    normal: { icon: "🔍", label: "Normal RAG", color: "var(--success-subtle, rgba(34,197,94,.15))" },
                                                    blocked: { icon: "🛡️", label: "Blocked", color: "var(--danger-subtle)" },
                                                };
                                                const r = routeLabels[m.trace.route] || { icon: "🔍", label: m.trace.route, color: "var(--surface-2)" };
                                                return (
                                                    <span title={`Routing: ${m.trace.route}`} style={{
                                                        marginLeft: "6px",
                                                        fontSize: "0.68rem",
                                                        background: r.color,
                                                        borderRadius: "10px",
                                                        padding: "1px 7px",
                                                        fontWeight: 600,
                                                        border: "1px solid rgba(255,255,255,0.08)",
                                                        whiteSpace: "nowrap",
                                                    }}>
                                                        {r.icon} {r.label}
                                                    </span>
                                                );
                                            })()}
                                            {/* SC loop count badge */}
                                            {!isUser && (m as any).latency_ms?.sc_loops > 1 && (
                                                <span style={{
                                                    marginLeft: "6px",
                                                    fontSize: "0.7rem",
                                                    background: "var(--accent-subtle)",
                                                    color: "var(--accent-emphasis)",
                                                    borderRadius: "10px",
                                                    padding: "1px 7px",
                                                    fontWeight: 600,
                                                }}>
                                                    🔁 {(m as any).latency_ms.sc_loops} loops
                                                </span>
                                            )}
                                            {!isUser && !m.id.startsWith("temp-") && (
                                                <div className="chat-menu chat-message-menu">
                                                    <button
                                                        type="button"
                                                        className="chat-menu-trigger"
                                                        aria-label="Message actions"
                                                        aria-expanded={messageMenuId === m.id}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setSessionMenuId(null);
                                                            setMessageMenuId(messageMenuId === m.id ? null : m.id);
                                                        }}
                                                    >
                                                        <IconMoreHorizontal size={14} />
                                                    </button>
                                                    {messageMenuId === m.id && (
                                                        <div className="chat-menu-dropdown" role="menu">
                                                            <button
                                                                type="button"
                                                                className="chat-menu-item chat-menu-item--danger"
                                                                role="menuitem"
                                                                onClick={() => handleDeleteMessageTurn(m.id)}
                                                            >
                                                                Delete message
                                                            </button>
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>

                                        {/* Message bubble */}
                                        {!isUser && (m.blocked || m.trace?.route === "blocked") ? (
                                            <BlockedCard
                                                guard={m.blocked_by_guard}
                                                phase={m.blocked_on}
                                                content={m.content}
                                            />
                                        ) : (
                                            <div className={`chat-bubble ${isUser ? "chat-bubble--user" : "chat-bubble--assistant"}`}>
                                                {isUser ? m.content : <MarkdownMessage content={m.content} />}
                                            </div>
                                        )}

                                        {/* Metrics & Sources for assistant messages */}
                                        {!isUser && !m.blocked && m.trace?.route !== "blocked" && (
                                            <div className="chat-message-meta">
                                                <div className="chat-metrics-row">
                                                    {isPolling && (
                                                        <span className="chat-metric-badge" style={{ background: "var(--warn-subtle)", color: "var(--warn-text)" }}>
                                                            RAGAS: Evaluating…
                                                        </span>
                                                    )}
                                                    {!isPolling && mMetrics && mMetrics.status === "completed" && (
                                                        <>
                                                            {mMetrics.faithfulness != null && (
                                                                <span
                                                                    className="chat-metric-badge"
                                                                    style={{
                                                                        background: mMetrics.faithfulness >= 0.7 ? "var(--success-subtle)" : "var(--danger-subtle)",
                                                                        color: mMetrics.faithfulness >= 0.7 ? "var(--success-text)" : "var(--danger)"
                                                                    }}
                                                                >
                                                                    Faithful: {(mMetrics.faithfulness * 100).toFixed(0)}%
                                                                </span>
                                                            )}
                                                            {mMetrics.answer_relevancy != null && (
                                                                <span className="chat-metric-badge" style={{ background: "var(--accent-subtle)", color: "var(--accent-emphasis)" }}>
                                                                    Relevance: {(mMetrics.answer_relevancy * 100).toFixed(0)}%
                                                                </span>
                                                            )}
                                                            {mMetrics.context_precision != null && (
                                                                <span className="chat-metric-badge" style={{ background: "var(--bg-inset)", color: "var(--text-secondary)" }}>
                                                                    Ctx Prec: {(mMetrics.context_precision * 100).toFixed(0)}%
                                                                </span>
                                                            )}
                                                        </>
                                                    )}
                                                    {m.sources && m.sources.length > 0 && (
                                                        <span className="chat-metric-badge" style={{ background: "var(--bg-inset)", color: "var(--text-secondary)" }}>
                                                            {m.sources.length} sources
                                                        </span>
                                                    )}
                                                </div>

                                                {m.sources && m.sources.length > 0 && (
                                                    <div className="chat-sources-list">
                                                        {m.sources.slice(0, 3).map((src: any, idx: number) => (
                                                            <div key={idx} className="chat-source-item">
                                                                📄 {src.source_locator} (Score: {src.rerank_score.toFixed(2)})
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        )}

                        {/* Loading / Streaming state */}
                        {chatLoading && (
                            <div className="chat-message chat-message--assistant">
                                <div className="chat-message-header">
                                    <span className="chat-role-label">Assistant</span>
                                </div>
                                <div className="chat-bubble chat-bubble--assistant" style={{ padding: agentStatus ? "8px 12px" : undefined }}>
                                    {agentStatus ? (
                                        <div className="chat-agent-status">
                                            <div className="chat-loading-pulse"></div>
                                            <span>{agentStatus}</span>
                                        </div>
                                    ) : (
                                        <div className="chat-streaming-content">
                                            <MarkdownMessage content={streamingAnswer} />
                                            <span className="chat-cursor-blink" />
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        <div ref={messageEndRef} />
                    </div>

                    {/* Input Area */}
                    <div className="chat-input-area">
                        <form onSubmit={handleSendMessage} className="chat-input-form">
                            <input
                                type="text"
                                value={inputText}
                                onChange={(e) => setInputText(e.target.value)}
                                placeholder={chatReady ? "Ask anything about your documents…" : "Click + New to start chatting"}
                                disabled={chatLoading || !chatReady}
                            />
                            <button
                                type="submit"
                                className="btn btn-primary chat-send-btn"
                                disabled={chatLoading || !chatReady || !inputText.trim()}
                            >
                                Send
                            </button>
                        </form>
                    </div>

                    {/* Collapsible Eval & Stats Panel */}
                    <button className="chat-eval-toggle" onClick={() => setShowEvalPanel(!showEvalPanel)}>
                        <span className={`toggle-arrow ${showEvalPanel ? "open" : ""}`}>▼</span>
                        Evaluation & Metrics
                    </button>

                    {showEvalPanel && (
                        <div className="chat-eval-panel">

                            {/* Golden Dataset Evaluator */}
                            <div className="chat-eval-card">
                                <h3>🎯 Golden Dataset Eval</h3>
                                {datasets.length === 0 ? (
                                    <div className="muted" style={{ fontSize: "0.75rem" }}>No datasets configured</div>
                                ) : (
                                    <div style={{ display: "flex", flexDirection: "column", gap: "0.375rem" }}>
                                        <select
                                            className="input"
                                            value={selectedDatasetId}
                                            onChange={(e) => setSelectedDatasetId(e.target.value)}
                                            style={{ padding: "0.3rem", fontSize: "0.75rem" }}
                                        >
                                            {datasets.map((d) => (
                                                <option key={d.dataset_id} value={d.dataset_id}>
                                                    {d.name} ({d.item_count} items)
                                                </option>
                                            ))}
                                        </select>
                                        <button
                                            className="btn btn-primary btn-sm"
                                            onClick={handleStartEval}
                                            disabled={!!(activeEvalRun && activeEvalRun.status === "running")}
                                            style={{ width: "100%", fontSize: "0.75rem" }}
                                        >
                                            Run Pipeline Eval
                                        </button>
                                    </div>
                                )}
                            </div>

                            {/* Eval Run Progress */}
                            <div className="chat-eval-card">
                                <h3>📊 Eval Progress</h3>
                                {activeEvalRun ? (
                                    <div style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: "4px" }}>
                                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                                            <span className="muted">Run {activeEvalRun.run_id.substring(0, 8)}</span>
                                            <span style={{ color: activeEvalRun.status === "completed" ? "var(--success-text)" : activeEvalRun.status === "failed" ? "var(--danger)" : "var(--warn-text)", fontWeight: 600, textTransform: "capitalize" }}>
                                                {activeEvalRun.status}
                                            </span>
                                        </div>
                                        <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.1)", borderRadius: "2px", overflow: "hidden" }}>
                                            <div style={{ width: `${(activeEvalRun.progress.items_completed / activeEvalRun.progress.items_total) * 100}%`, height: "100%", background: "var(--accent)", transition: "width 0.3s ease" }} />
                                        </div>
                                        <div className="muted">{activeEvalRun.progress.items_completed} / {activeEvalRun.progress.items_total} items</div>

                                        {activeEvalRun.aggregate_metrics && (
                                            <div style={{ marginTop: "4px", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "4px" }}>
                                                {(["retrieval", "reranker", "generation"] as const).flatMap((stage) => {
                                                    const block = activeEvalRun.aggregate_metrics?.[stage];
                                                    if (!block || typeof block !== "object") return [];
                                                    return Object.entries(block)
                                                        .filter(([, v]) => typeof v === "number")
                                                        .map(([key, val]) => (
                                                            <div key={`${stage}.${key}`} style={{ display: "flex", justifyContent: "space-between" }}>
                                                                <span className="muted">{String(key).replace(/^mean_/, "")}</span>
                                                                <span className="mono">{(val as number).toFixed(3)}</span>
                                                            </div>
                                                        ));
                                                })}
                                            </div>
                                        )}
                                    </div>
                                ) : (
                                    <div className="muted" style={{ fontSize: "0.75rem" }}>No evaluation runs yet</div>
                                )}
                            </div>

                            {/* Historical Stats */}
                            <div className="chat-eval-card">
                                <h3>📈 Historical Metrics</h3>
                                {stats && stats.items && stats.items.length > 0 ? (
                                    (() => {
                                        const items = stats.items.filter((i: any) => i.faithfulness !== null || i.answer_relevancy !== null);
                                        if (items.length === 0) return <div className="muted" style={{ fontSize: "0.75rem" }}>No metrics loaded yet</div>;

                                        const avgFaithfulness = items.reduce((acc: number, i: any) => acc + (i.faithfulness || 0), 0) / items.length;
                                        const avgRelevancy = items.reduce((acc: number, i: any) => acc + (i.answer_relevancy || 0), 0) / items.length;

                                        return (
                                            <div style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: "4px" }}>
                                                <div style={{ display: "flex", justifyContent: "space-between" }}>
                                                    <span className="muted">Avg Faithfulness</span>
                                                    <span className="mono" style={{ color: "var(--success-text)" }}>{(avgFaithfulness * 100).toFixed(0)}%</span>
                                                </div>
                                                <div style={{ display: "flex", justifyContent: "space-between" }}>
                                                    <span className="muted">Avg Relevance</span>
                                                    <span className="mono" style={{ color: "var(--text-link)" }}>{(avgRelevancy * 100).toFixed(0)}%</span>
                                                </div>
                                                <div style={{ display: "flex", justifyContent: "space-between" }}>
                                                    <span className="muted">Evaluated</span>
                                                    <span className="mono">{items.length}</span>
                                                </div>
                                            </div>
                                        );
                                    })()
                                ) : (
                                    <div className="muted" style={{ fontSize: "0.75rem" }}>No stats available</div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
