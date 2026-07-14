import React, { useEffect, useState, useRef } from "react";
import {
    listPipelines,
    listChatSessions,
    getChatSessionMessages,
    chatWithPipeline,
    getMessageMetrics,
    getChatStats,
    listGoldenDatasets,
    createEvaluationRun,
    getEvaluationRun,
    PipelineRecord,
    ChatSession,
    ChatMessage,
    RAGMetricsResponse,
} from "../api";
import { IconChat } from "../components/Icons";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

export default function ChatPage() {
    const [pipelines, setPipelines] = useState<PipelineRecord[]>([]);
    const [selectedPipeline, setSelectedPipeline] = useState<PipelineRecord | null>(null);

    // Chat sessions
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [inputText, setInputText] = useState("");
    const [chatLoading, setChatLoading] = useState(false);

    // Metrics database
    const [messageMetrics, setMessageMetrics] = useState<Record<string, RAGMetricsResponse>>({});
    const [pollingMetrics, setPollingMetrics] = useState<Record<string, boolean>>({});

    // Config overrides
    const [retrievalMode, setRetrievalMode] = useState<string>("hybrid");
    const [retrieveLimit, setRetrieveLimit] = useState<number>(20);
    const [rerankEnabled, setRerankEnabled] = useState<boolean>(true);
    const [topK, setTopK] = useState<number>(5);

    // Stats
    const [stats, setStats] = useState<any>(null);

    // Evaluations
    const [datasets, setDatasets] = useState<any[]>([]);
    const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
    const [activeEvalRun, setActiveEvalRun] = useState<any>(null);

    // Collapsible eval panel
    const [showEvalPanel, setShowEvalPanel] = useState(false);

    const messageEndRef = useRef<HTMLDivElement>(null);

    // Load initial data
    useEffect(() => {
        loadPipelines();
        loadSessions();
        loadStats();
        loadDatasets();
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

    // Poll metrics for assistant messages
    useEffect(() => {
        const pendingMsgIds = messages
            .filter((m) => m.role === "assistant" && !m.id.startsWith("temp-") && !messageMetrics[m.id] && !pollingMetrics[m.id])
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

    const startPollingMetrics = async (msgId: string) => {
        setPollingMetrics((prev) => ({ ...prev, [msgId]: true }));
        let attempts = 0;
        const interval = setInterval(async () => {
            attempts++;
            try {
                const metrics = await getMessageMetrics(msgId);
                if (metrics.status === "completed" || metrics.status === "failed" || attempts > 20) {
                    setMessageMetrics((prev) => ({ ...prev, [msgId]: metrics }));
                    setPollingMetrics((prev) => ({ ...prev, [msgId]: false }));
                    clearInterval(interval);
                    loadStats();
                }
            } catch (err) {
                console.error("Error polling metrics for message", msgId, err);
                clearInterval(interval);
                setPollingMetrics((prev) => ({ ...prev, [msgId]: false }));
            }
        }, 2500);
    };

    const handleStartNewSession = () => {
        setActiveSessionId(null);
        setMessages([]);
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

        try {
            const payload: any = {
                query: userMessage.content,
                session_id: activeSessionId,
                retrieval_mode: retrievalMode,
                retrieve_limit: retrieveLimit,
                rerank_enabled: rerankEnabled,
                top_k: topK
            };

            if (selectedPipeline) {
                payload.collection = selectedPipeline.qdrant_collection;
                payload.embedding_model = selectedPipeline.embedding_model;
                if (selectedPipeline.sparse_embedding_model) {
                    payload.sparse_embedding_model = selectedPipeline.sparse_embedding_model;
                }
            }

            const res = await chatWithPipeline(payload);
            if (!activeSessionId) {
                setActiveSessionId(res.session_id);
                loadSessions();
            } else {
                loadMessages(res.session_id);
            }
        } catch (err) {
            console.error("Failed to send chat message", err);
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
        }
    };

    const handleStartEval = async () => {
        if (!selectedDatasetId) return;
        try {
            const config: any = {
                retrieval_mode: retrievalMode,
                retrieve_limit: retrieveLimit,
                rerank_enabled: rerankEnabled,
                top_k: topK
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
                                return (
                                    <button
                                        key={s.session_id}
                                        onClick={() => setActiveSessionId(s.session_id)}
                                        className={`chat-session-item ${isActive ? "active" : ""}`}
                                    >
                                        <span className="session-preview">
                                            {s.preview || `Session ${s.session_id.substring(0, 8)}`}
                                        </span>
                                        <span className="session-meta">
                                            {s.message_count} messages
                                            {s.last_message_at && ` · ${formatTime(s.last_message_at)}`}
                                        </span>
                                    </button>
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
                                    Ask questions about your ingested documents. The selected pipeline's embedding models and vectors will query the store.
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
                                        </div>

                                        {/* Message bubble */}
                                        <div className={`chat-bubble ${isUser ? "chat-bubble--user" : "chat-bubble--assistant"}`}>
                                            {isUser ? m.content : <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{m.content}</ReactMarkdown>}
                                        </div>

                                        {/* Metrics & Sources for assistant messages */}
                                        {!isUser && (
                                            <div className="chat-message-meta">
                                                <div className="chat-metrics-row">
                                                    {isPolling && (
                                                        <span className="chat-metric-badge" style={{ background: "var(--warn-subtle)", color: "var(--warn-text)" }}>
                                                            RAGAS: Evaluating…
                                                        </span>
                                                    )}
                                                    {!isPolling && mMetrics && mMetrics.status === "completed" && (
                                                        <>
                                                            {mMetrics.faithfulness !== null && (
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
                                                            {mMetrics.answer_relevancy !== null && (
                                                                <span className="chat-metric-badge" style={{ background: "var(--accent-subtle)", color: "var(--accent-emphasis)" }}>
                                                                    Relevance: {(mMetrics.answer_relevancy * 100).toFixed(0)}%
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

                        {/* Loading state */}
                        {chatLoading && (
                            <div className="chat-loading">
                                <div className="chat-loading-bubble">
                                    <div className="chat-loading-dots">
                                        <span /><span /><span />
                                    </div>
                                    <span className="muted" style={{ fontSize: "0.8125rem" }}>Thinking…</span>
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
                                                {Object.entries(activeEvalRun.aggregate_metrics).map(([key, val]: any) => (
                                                    <div key={key} style={{ display: "flex", justifyContent: "space-between" }}>
                                                        <span className="muted">{key}</span>
                                                        <span className="mono">{typeof val === "number" ? val.toFixed(3) : val}</span>
                                                    </div>
                                                ))}
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
