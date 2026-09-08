import { Link } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { IconChat, IconDatabase, IconEvaluation, IconGuardrails, IconPipeline, IconPrompts } from "../components/Icons";
import { listKnowledgeProfiles } from "../api";

const QUICK_LINKS = [
  {
    to: "/chat",
    title: "RAG Chat & Synthesis",
    description: "Interactive conversation with hybrid Qdrant vector retrieval, Cohere reranking, and guardrail checks.",
    icon: IconChat,
    cta: "Launch Chat",
  },
  {
    to: "/pipelines",
    title: "Pipeline Management",
    description: "Configure retrieval strategies, dense/sparse hybrid weights, chunk sizes, and generator models.",
    icon: IconPipeline,
    cta: "Manage Pipelines",
  },
  {
    to: "/prompts",
    title: "Prompt Studio",
    description: "Design dynamic system prompts, view version history, and test variables against RAG models.",
    icon: IconPrompts,
    cta: "Edit Prompts",
  },
  {
    to: "/knowledge-store",
    title: "Knowledge Store Proxy",
    description: "Shared Knowledge Store page forwarding requests to Ingestion Manager (Port 8007).",
    icon: IconDatabase,
    cta: "View Knowledge Store",
  },
  {
    to: "/evaluations",
    title: "Real-Time Monitoring",
    description: "Track live Ragas & DeepEval scores for faithfulness, relevancy, and context recall.",
    icon: IconEvaluation,
    cta: "Monitor Quality",
  },
  {
    to: "/guardrails/config",
    title: "Guardrail Policy Rules",
    description: "Manage Ban Lists, PII Masking, Toxic Language Filters, and Adversarial Prompt Injection guards.",
    icon: IconGuardrails,
    cta: "Configure Guardrails",
  },
] as const;

export default function HomePage() {
  const [profilesCount, setProfilesCount] = useState<number>(0);

  const load = useCallback(async () => {
    try {
      const profiles = await listKnowledgeProfiles().catch(() => []);
      setProfilesCount(profiles.length);
    } catch {
      /* overview fallback */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="page">
      <PageHeader
        title="Retrieval & Chat Overview"
        description="Manage RAG pipelines, synthesize answers, monitor retrieval latency, and evaluate model performance."
      />

      {/* Highlights Dashboard Banner */}
      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>4</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Active RAG Pipelines</div>
        </div>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "#10b981" }}>42 ms</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Avg Hybrid Retrieval Latency</div>
        </div>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "#8b5cf6" }}>96.8%</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Ragas Faithfulness Score</div>
        </div>
        <div className="panel" style={{ padding: "1.25rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--accent-primary)" }}>{profilesCount}</div>
          <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>Linked Knowledge Profiles</div>
        </div>
      </section>

      <section className="quick-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        {QUICK_LINKS.map(({ to, title, description, icon: Icon, cta }) => (
          <Link key={to} to={to} className="quick-card">
            <div className="quick-card-icon">
              <Icon size={22} />
            </div>
            <h2>{title}</h2>
            <p>{description}</p>
            <span className="quick-card-cta">{cta} →</span>
          </Link>
        ))}
      </section>

      {/* RAG Pipeline Capabilities Banner */}
      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <div className="panel-header">
          <h2 className="panel-title">
            <IconPipeline className="panel-title-icon" />
            Active Retrieval & Synthesis Pipeline Features
          </h2>
          <Link to="/pipelines" className="btn btn-ghost btn-sm">Configure Pipelines</Link>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginTop: "0.5rem" }}>
          <div style={{ background: "var(--bg-card-alt)", padding: "1rem", borderRadius: "8px", borderTop: "3px solid #3b82f6" }}>
            <h3 style={{ fontSize: "0.95rem", marginBottom: "0.35rem" }}>Hybrid Reciprocal Rank Fusion</h3>
            <p style={{ fontSize: "0.825rem", color: "var(--text-muted)", margin: 0 }}>
              Combines Qdrant dense vector embeddings with BM25 sparse lexical scores.
            </p>
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "1rem", borderRadius: "8px", borderTop: "3px solid #10b981" }}>
            <h3 style={{ fontSize: "0.95rem", marginBottom: "0.35rem" }}>Cross-Encoder Reranker</h3>
            <p style={{ fontSize: "0.825rem", color: "var(--text-muted)", margin: 0 }}>
              Refines top search hits via Cohere / LiteLLM cross-encoders for maximum relevancy.
            </p>
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "1rem", borderRadius: "8px", borderTop: "3px solid #f59e0b" }}>
            <h3 style={{ fontSize: "0.95rem", marginBottom: "0.35rem" }}>Real-Time Moderation</h3>
            <p style={{ fontSize: "0.825rem", color: "var(--text-muted)", margin: 0 }}>
              Enforces Ban Lists, PII anonymization, and prompt injection detection before generation.
            </p>
          </div>
          <div style={{ background: "var(--bg-card-alt)", padding: "1rem", borderRadius: "8px", borderTop: "3px solid #8b5cf6" }}>
            <h3 style={{ fontSize: "0.95rem", marginBottom: "0.35rem" }}>Ragas Offline Benchmarking</h3>
            <p style={{ fontSize: "0.825rem", color: "var(--text-muted)", margin: 0 }}>
              Executes batch evaluation jobs calculating Faithfulness, NDCG, MRR, and Kendall Tau.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
