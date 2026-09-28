import type { DiagnosisStage, RunDiagnosis, TriadScores } from "../api";

/**
 * The three RAG triad scores and the stage they point at.
 *
 * Each metric reads a different pair of the inputs a turn produces, which is the whole
 * reason three numbers are needed rather than one:
 *
 *   context relevance     question against the retrieved passages
 *   groundedness          answer against those passages
 *   answer relevance      answer against the question
 *
 * Read together they name the stage. Relevant passages with an ungrounded answer means
 * the generator invented; grounded and irrelevant means it answered a different question.
 */

const PASS_MARK = 0.7;

type MetricSpec = {
  key: keyof TriadScores;
  label: string;
  hint: string;
  /** Which stage a low score on this metric points at. */
  blames: string;
};

const METRICS: MetricSpec[] = [
  {
    key: "context_relevance",
    label: "Context relevance",
    hint: "Are the retrieved passages pertinent to the question?",
    blames: "Retrieval",
  },
  {
    key: "response_groundedness",
    label: "Faithfulness (groundedness)",
    hint: "Is each claim in the answer supported by those passages?",
    blames: "Generation — invented",
  },
  {
    key: "answer_relevancy",
    label: "Answer relevance",
    hint: "Does the answer address the question that was asked?",
    blames: "Generation — off the question",
  },
];

export const STAGE_TONE: Record<DiagnosisStage, string> = {
  healthy: "#34d399",
  retrieval: "#fbbf24",
  rerank: "#f472b6",
  generation_grounding: "#f87171",
  generation_relevance: "#fb923c",
  unknown: "#94a3b8",
};

export function scoreTone(value: number | null | undefined): string {
  if (value == null) return "#94a3b8";
  if (value >= PASS_MARK) return "#34d399";
  if (value >= PASS_MARK - 0.2) return "#fbbf24";
  return "#f87171";
}

/** A single score with its bar and its occupant sentence. */
export function TriadMetric({
  spec,
  value,
}: {
  spec: MetricSpec;
  value: number | null | undefined;
}) {
  const scored = value != null;
  return (
    <div style={{ display: "grid", gap: "0.3rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "0.5rem" }}>
        <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "#cbd5e1" }}>{spec.label}</span>
        <span style={{ fontSize: "1.05rem", fontWeight: 700, color: scoreTone(value) }}>
          {scored ? value.toFixed(3) : "not scored"}
        </span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "rgba(148,163,184,0.18)", overflow: "hidden" }}>
        <div
          style={{
            width: `${scored ? Math.max(0, Math.min(1, value)) * 100 : 0}%`,
            height: "100%",
            background: scoreTone(value),
          }}
        />
      </div>
      <span style={{ fontSize: "0.7rem", color: "#64748b" }}>
        {spec.hint} A low score points at {spec.blames}.
      </span>
    </div>
  );
}

export function metricSpecs(): MetricSpec[] {
  return METRICS;
}

/** The triad, drawn as three bars, with the run's own reading underneath. */
export default function TriadPanel({
  triad,
  diagnosis,
  compact = false,
}: {
  triad: TriadScores;
  diagnosis?: RunDiagnosis | null;
  compact?: boolean;
}) {
  const dominant = diagnosis?.dominant_stage ?? null;
  return (
    <div className="panel" style={{ padding: "1rem 1.1rem", display: "grid", gap: "0.9rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "1rem" }}>
        <div>
          <div style={{ fontSize: "0.95rem", fontWeight: 700, color: "#e2e8f0" }}>RAG triad</div>
          <div className="muted" style={{ fontSize: "0.75rem" }}>
            Three scores, each reading a different part of the pipeline
          </div>
        </div>
        {diagnosis?.dominant_label && (
          <span
            className="status-badge"
            style={{ background: `${STAGE_TONE[dominant ?? "unknown"]}22`, color: STAGE_TONE[dominant ?? "unknown"] }}
          >
            Weakest stage: {diagnosis.dominant_label}
          </span>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gap: "0.9rem",
          gridTemplateColumns: compact ? "1fr" : "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        {METRICS.map((spec) => (
          <TriadMetric key={spec.key} spec={spec} value={triad?.[spec.key]} />
        ))}
      </div>

      {diagnosis?.summary && (
        <div
          style={{
            fontSize: "0.82rem",
            lineHeight: 1.5,
            color: "#cbd5e1",
            borderLeft: `3px solid ${STAGE_TONE[dominant ?? "unknown"]}`,
            paddingLeft: "0.7rem",
          }}
        >
          {diagnosis.summary}
        </div>
      )}

      {diagnosis?.stage_counts && (
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {(Object.keys(diagnosis.stage_counts) as DiagnosisStage[])
            .filter((stage) => diagnosis.stage_counts[stage] > 0)
            .map((stage) => (
              <span
                key={stage}
                className="status-badge"
                style={{ background: `${STAGE_TONE[stage]}1f`, color: STAGE_TONE[stage] }}
              >
                {stageLabel(stage)}: {diagnosis.stage_counts[stage]}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}

const LABELS: Record<DiagnosisStage, string> = {
  healthy: "Sound",
  retrieval: "Retrieval",
  rerank: "Reranker",
  generation_grounding: "Generation — invented",
  generation_relevance: "Generation — off the question",
  unknown: "Not scored",
};

export function stageLabel(stage: DiagnosisStage): string {
  return LABELS[stage] ?? stage;
}
