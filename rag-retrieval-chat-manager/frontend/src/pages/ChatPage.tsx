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
    deleteChatSession,
    deleteChatMessage,
    PipelineRecord,
    ChatSession,
    ChatMessage,
    RAGMetricsResponse,
    GuardrailsConfig,
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

export default function ChatPage() {
    const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
    const [selectedPipeline, setSelectedPipeline] = useState<PipelineRecord | null>(null);

    // Chat sessions
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [inputText, setInputText] = useState("");
    const [chatLoading, setChatLoading] = useState(false);

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

    const [routerEnabled, setRouterEnabled] = useState<boolean>(true);
    const [routerMode, setRouterMode] = useState<string>("llm");
    const [ragMode, setRagMode] = useState<string>("normal");
    const [scMaxLoops, setScMaxLoops] = useState<number>(3);

    const [guardrailsConfigs, setGuardrailsConfigs] = useState<GuardrailsConfig[]>([]);
    const [selectedGuardrailsConfig, setSelectedGuardrailsConfig] = useState<GuardrailsConfig | null>(null);

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
    }, []);

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
            setSessions(list);
            if (list.length > 0 && !activeSessionId) {
                setActiveSessionId(list[0].session_id);
            }
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
            const items = res.items || [];
            setGuardrailsConfigs(items);
            setSelectedGuardrailsConfig((prev) => {
                if (!prev) return prev;
                return items.find((c) => c.id === prev.id) || null;
            });
        } catch (err) {
            console.error("Failed to load guardrails configs", err);
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
        setSessionMenuId(null);
        setMessageMenuId(null);
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
                retrieval_mode: retrievalMode,
                retrieve_limit: retrieveLimit,
                rerank_enabled: rerankEnabled,
                top_k: topK,
                router_enabled: routerEnabled,
                router_mode: routerEnabled ? routerMode : undefined,
                rag_mode: routerEnabled ? "normal" : ragMode, // Overridden by backend if routed to crag
                self_corrective_max_loops: scMaxLoops,
                guardrails_config_id: selectedGuardrailsConfig?.id || undefined,
            };

            if (selectedPipeline) {
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

            for await (const event of streamChat(payload)) {
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
                router_enabled: routerEnabled,
                router_mode: routerEnabled ? routerMode : undefined,
                rag_mode: routerEnabled ? "normal" : ragMode,
                self_corrective_max_loops: scMaxLoops,
            };

            if (selectedPipeline) {
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
            <div className="chat-layout">

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
                                <div><span className="muted">Embedding:</span> <span className="mono" style={{ wordBreak: "break-all" }}>{selectedPipeline.embedding_model}</span></div>
                                {selectedPipeline.sparse_embedding_model && (
                                    <div><span className="muted">Sparse:</span> <span className="mono">{selectedPipeline.sparse_embedding_model}</span></div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Guardrails Config Selector */}
                    <div className="chat-pipeline-config">
                        <div className="chat-sidebar-section-title">Guardrails</div>
                        <select
                            className="input"
                            value={selectedGuardrailsConfig?.id || ""}
                            onFocus={() => loadGuardrailsConfigs()}
                            onChange={(e) => {
                                const found = guardrailsConfigs.find((c) => c.id === e.target.value);
                                setSelectedGuardrailsConfig(found || null);
                            }}
                        >
                            <option value="">None</option>
                            {guardrailsConfigs.map((c) => (
                                <option key={c.id} value={c.id}>
                                    {c.name}{c.is_active ? "" : " (inactive)"}
                                </option>
                            ))}
                        </select>

                        {selectedGuardrailsConfig && (
                            <div className="chat-pipeline-info">
                                <div><span className="muted">Mode:</span> <span className="mono">{selectedGuardrailsConfig.mode}</span></div>
                                <div><span className="muted">Guards:</span> <span className="mono">{selectedGuardrailsConfig.guards.join(", ") || "—"}</span></div>
                                {selectedGuardrailsConfig.description && (
                                    <div><span className="muted">About:</span> {selectedGuardrailsConfig.description}</div>
                                )}
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
                                        onClick={() => setActiveSessionId(s.session_id)}
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

                    {/* Config Toolbar */}
                    <div className="chat-toolbar">
                        <div className="chat-toolbar-group">
                            <label>Mode</label>
                            <select value={retrievalMode} onChange={(e) => setRetrievalMode(e.target.value)}>
                                <option value="hybrid">Hybrid</option>
                                <option value="dense">Dense</option>
                                <option value="sparse">Sparse</option>
                            </select>
                        </div>

                        <div className="chat-toolbar-divider" />

                        <div className="chat-toolbar-group">
                            <label>Limit</label>
                            <input
                                type="number"
                                min={1}
                                max={50}
                                value={retrieveLimit}
                                onChange={(e) => setRetrieveLimit(parseInt(e.target.value) || 1)}
                                style={{ width: "52px" }}
                            />
                        </div>

                        <div className="chat-toolbar-divider" />

                        <div className="chat-toolbar-group">
                            <label>Rerank</label>
                            <input
                                type="checkbox"
                                checked={rerankEnabled}
                                onChange={(e) => setRerankEnabled(e.target.checked)}
                            />
                        </div>

                        {rerankEnabled && (
                            <>
                                <div className="chat-toolbar-divider" />
                                <div className="chat-toolbar-group">
                                    <label>Top K</label>
                                    <input
                                        type="number"
                                        min={1}
                                        max={20}
                                        value={topK}
                                        onChange={(e) => setTopK(parseInt(e.target.value) || 1)}
                                        style={{ width: "48px" }}
                                    />
                                </div>
                            </>
                        )}

                        <div className="chat-toolbar-divider" />
                        <div className="chat-toolbar-group">
                            <label>Strategy</label>
                            <select
                                value={routerEnabled ? "auto" : "manual"}
                                onChange={(e) => setRouterEnabled(e.target.value === "auto")}
                            >
                                <option value="auto">Intelligent (Auto)</option>
                                <option value="manual">Manual Selection</option>
                            </select>
                        </div>

                        {routerEnabled && (
                            <>
                                <div className="chat-toolbar-divider" />
                                <div className="chat-toolbar-group">
                                    <label title="How Auto decides greeting vs simple RAG vs CRAG">Classifier</label>
                                    <select
                                        value={routerMode}
                                        onChange={(e) => setRouterMode(e.target.value)}
                                    >
                                        <option value="llm">LLM (small model)</option>
                                        <option value="heuristic">Heuristic rules</option>
                                    </select>
                                </div>
                            </>
                        )}

                        {!routerEnabled && (
                            <>
                                <div className="chat-toolbar-divider" />
                                <div className="chat-toolbar-group">
                                    <label>RAG Mode</label>
                                    <select value={ragMode} onChange={(e) => setRagMode(e.target.value)}>
                                        <option value="normal">Normal</option>
                                        <option value="self_corrective">Self-Corrective</option>
                                    </select>
                                </div>
                            </>
                        )}

                        {((routerEnabled) || (!routerEnabled && ragMode === "self_corrective")) && (
                            <>
                                <div className="chat-toolbar-divider" />
                                <div className="chat-toolbar-group">
                                    <label>Max Loops</label>
                                    <input
                                        type="number"
                                        min={1}
                                        max={5}
                                        value={scMaxLoops}
                                        onChange={(e) => setScMaxLoops(Math.min(5, Math.max(1, parseInt(e.target.value) || 1)))}
                                        style={{ width: "44px" }}
                                        title={routerEnabled ? "Used when Auto routes to CRAG" : "Self-Corrective max loops"}
                                    />
                                </div>
                            </>
                        )}

                        {/* Session indicator */}
                        <div className="chat-toolbar-session">
                            <div className={`session-dot ${activeSessionId ? "connected" : "new"}`} />
                            <span className="mono" style={{ color: "var(--text-secondary)" }}>
                                {activeSessionId ? activeSessionId.substring(0, 12) + "…" : "New Session"}
                            </span>
                        </div>
                    </div>

                    {/* Messages */}
                    <div className="chat-messages">
                        {sortedMessages.length === 0 ? (
                            <div className="chat-empty">
                                <IconChat className="empty-icon" size={36} />
                                <h3>RAG Playground</h3>
                                <p>
                                    Ask questions about your ingested documents. With Intelligent (Auto), a classifier
                                    picks greeting, simple RAG, or CRAG per query.
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
                                                    greeting: { icon: "💬", label: "Greeting", color: "var(--info-subtle, rgba(59,130,246,.15))" },
                                                    normal: { icon: "🔍", label: "Normal RAG", color: "var(--success-subtle, rgba(34,197,94,.15))" },
                                                    simple_rag_auto: { icon: "🔍", label: "Simple RAG (Auto)", color: "var(--success-subtle, rgba(34,197,94,.15))" },
                                                    self_corrective: { icon: "🔄", label: "Self-Corrective", color: "var(--accent-subtle, rgba(139,92,246,.15))" },
                                                    self_corrective_auto: { icon: "⚡", label: "CRAG (Auto)", color: "var(--warn-subtle, rgba(245,158,11,.15))" },
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
                                                            {Array.isArray(mMetrics.metrics?.generation?.sc_iterations) &&
                                                                mMetrics.metrics!.generation!.sc_iterations.length > 0 && (
                                                                <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginLeft: "4px" }}>
                                                                    {mMetrics.metrics!.generation!.sc_iterations.map((iter: any, i: number) => {
                                                                        const faith = iter?.generation?.faithfulness ?? iter?.faithfulness;
                                                                        const n = mMetrics.metrics!.generation!.sc_iterations.length;
                                                                        return (
                                                                            <span key={i} style={{ marginRight: "6px" }}>
                                                                                {i + 1}: {typeof faith === "number" ? `${(faith * 100).toFixed(0)}%` : "N/A"}
                                                                                {i < n - 1 ? " →" : ""}
                                                                            </span>
                                                                        );
                                                                    })}
                                                                </div>
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
                                placeholder="Ask anything about your documents…"
                                disabled={chatLoading}
                            />
                            <button
                                type="submit"
                                className="btn btn-primary chat-send-btn"
                                disabled={chatLoading || !inputText.trim()}
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
