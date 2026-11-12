import { useEffect } from "react";

import { IconClose } from "./Icons";
import MarkdownMessage from "./MarkdownMessage";
import type { SyntheticDatasetKind, SyntheticVersionItem } from "../api";

export const KIND_WORD: Record<SyntheticDatasetKind, string> = {
  single_turn: "Single-turn",
  multi_turn: "Multi-turn",
};

/** Pairs a row's user turns with the assistant answers kept in `metadata.expected_turns`. */
function rowConversation(item: SyntheticVersionItem) {
  const raw = item.metadata?.expected_turns;
  const answers = Array.isArray(raw)
    ? raw.map((turn) =>
        typeof turn === "string"
          ? turn
          : String((turn as { content?: unknown } | null)?.content ?? ""),
      )
    : [];
  return (item.turns ?? []).map((turn, index) => ({
    user: turn.content,
    answer: answers[index] ?? "",
  }));
}

function metaText(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((entry) =>
        entry && typeof entry === "object" ? JSON.stringify(entry) : String(entry),
      )
      .join(", ");
  }
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

/** A source may be a plain string or an object the uploader kept: `{ name: "Resume-1.pdf" }`. */
export function sourceLabel(source: unknown): string {
  if (source && typeof source === "object") {
    const named = source as { name?: unknown; title?: unknown; file?: unknown };
    return String(named.name ?? named.title ?? named.file ?? "");
  }
  return String(source ?? "");
}

/** The whole record, because a table cell can hold one line of it at most. */
export default function RowDrawer({
  item,
  position,
  kind,
  onClose,
}: {
  item: SyntheticVersionItem;
  position: number;
  kind: SyntheticDatasetKind;
  onClose: () => void;
}) {
  const conversation = rowConversation(item);
  const sources = Array.isArray(item.expected_sources)
    ? item.expected_sources.map(sourceLabel)
    : [];
  const evolutions = asList(item.metadata?.evolutions);
  const contexts = asList(item.metadata?.source_contexts);
  const scenario = typeof item.metadata?.scenario === "string" ? item.metadata.scenario : null;
  const model = typeof item.metadata?.model === "string" ? item.metadata.model : null;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onMouseDown={onClose} role="presentation">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sd-row-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <div>
            <h3 id="sd-row-title" className="panel-title">
              Row {position}
            </h3>
            <p className="fabric-meta sd-row-meta">
              {KIND_WORD[kind]} ·{" "}
              {conversation.length > 1 ? `${conversation.length} turns` : "1 turn"}
              {model ? ` · ${model}` : ""}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            aria-label="Close row"
            autoFocus
          >
            <IconClose size={14} />
          </button>
        </div>

        <div className="drawer-body">
          {conversation.length > 1 && (
            <ol className="sd-conv">
              {conversation.map((turn, index) => (
                <li className="sd-conv-turn" key={index}>
                  <p className="sd-row-label">Turn {index + 1} · user</p>
                  <p className="sd-row-text">{turn.user}</p>
                  {turn.answer && (
                    <>
                      <p className="sd-row-label">Turn {index + 1} · assistant</p>
                      <MarkdownMessage className="sd-row-md" content={turn.answer} />
                    </>
                  )}
                </li>
              ))}
            </ol>
          )}

          {conversation.length <= 1 && (
            <section className="sd-row-section">
              <p className="sd-row-label">Question</p>
              <p className="sd-row-text">{item.question}</p>
            </section>
          )}

          <section className="sd-row-section">
            <p className="sd-row-label">Ground truth</p>
            {item.ground_truth_answer ? (
              <MarkdownMessage className="sd-row-md" content={item.ground_truth_answer} />
            ) : (
              <p className="sd-row-text">—</p>
            )}
          </section>

          <section className="sd-row-section">
            <p className="sd-row-label">Expected sources</p>
            {sources.length > 0 ? (
              <div className="sd-chips">
                {sources.map((source, index) => (
                  <span className="sd-kind" key={`${source}-${index}`}>
                    {source}
                  </span>
                ))}
              </div>
            ) : (
              <p className="sd-row-text">None</p>
            )}
          </section>

          {scenario && (
            <section className="sd-row-section">
              <p className="sd-row-label">Scenario</p>
              <p className="sd-row-text">{scenario}</p>
            </section>
          )}

          {evolutions.length > 0 && (
            <section className="sd-row-section">
              <p className="sd-row-label">Evolutions</p>
              <div className="sd-chips">
                {evolutions.map((name, index) => (
                  <span className="sd-kind" key={`${name}-${index}`}>
                    {name}
                  </span>
                ))}
              </div>
            </section>
          )}

          {contexts.length > 0 && (
            <section className="sd-row-section">
              <p className="sd-row-label">Reference contexts</p>
              {contexts.map((context, index) => (
                <details className="sd-context" key={index}>
                  <summary>
                    Context {index + 1} · {context.length.toLocaleString()} characters
                  </summary>
                  <pre className="sd-context-body">{context}</pre>
                </details>
              ))}
            </section>
          )}

          {Object.entries(item.metadata ?? {})
            .filter(
              ([key, value]) =>
                key !== "expected_turns" && value !== null && value !== "" && value !== undefined,
            )
            .map(([key, value]) => (
              <section className="sd-row-section" key={key}>
                <p className="sd-row-label">{key}</p>
                <p className="sd-row-text">{metaText(value)}</p>
              </section>
            ))}
        </div>
      </aside>
    </div>
  );
}
