import { useMemo } from "react";
import type { KnowledgeDestinationConfig } from "../../api";
import type { ProductEvent } from "../../hooks/useProductEvents";

interface LiveFanoutTimelineProps {
  events: ProductEvent[];
  connected: boolean;
  destinations: KnowledgeDestinationConfig[];
}

type ChipState = "idle" | "active" | "done" | "error";

function shortName(fileKey: unknown): string {
  if (typeof fileKey !== "string") return "";
  return fileKey.split("/").pop() || fileKey;
}

function clockOf(ts: unknown): string {
  if (typeof ts !== "string") return "--:--:--";
  const date = new Date(ts);
  return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString();
}

/**
 * Live view of one fanout tick.
 *
 * Every value is derived from the event stream, never polled separately, so the
 * panel and the backend cannot disagree.
 */
export default function LiveFanoutTimeline({
  events,
  connected,
  destinations,
}: LiveFanoutTimelineProps) {
  const state = useMemo(() => {
    const chips: Record<string, ChipState> = {};
    let currentFile: string | null = null;
    let counts: Record<string, number> = {};
    let destinationsTouched: string[] = [];

    for (const event of events) {
      switch (event.kind) {
        case "tick_start":
          currentFile = null;
          counts = {};
          destinationsTouched = [];
          for (const key of Object.keys(chips)) delete chips[key];
          break;
        case "file_start":
          currentFile = typeof event.file_key === "string" ? event.file_key : null;
          for (const key of Object.keys(chips)) delete chips[key];
          break;
        case "destination_start":
          if (typeof event.destination_type === "string") chips[event.destination_type] = "active";
          break;
        case "destination_done":
          if (typeof event.destination_type === "string") chips[event.destination_type] = "done";
          break;
        case "destination_failed":
          if (typeof event.destination_type === "string") chips[event.destination_type] = "error";
          break;
        case "file_synced":
          currentFile = null;
          break;
        case "tick_done":
          counts = {
            added: Number(event.files_added ?? 0),
            updated: Number(event.files_updated ?? 0),
            deleted: Number(event.files_deleted ?? 0),
            unchanged: Number(event.files_unchanged ?? 0),
            pages: Number(event.pages ?? 0),
          };
          destinationsTouched = Array.isArray(event.destinations)
            ? (event.destinations as string[])
            : [];
          break;
        default:
          break;
      }
    }

    return { chips, currentFile, counts, destinationsTouched };
  }, [events]);

  const recent = events.slice(-30).reverse();
  const hasTick = Object.keys(state.counts).length > 0;

  return (
    <div className="fanout-panel">
      <div className="fanout-panel-head">
        <h2 className="fanout-panel-title">Live Fanout</h2>
        <span className={`fanout-live${connected ? "" : " fanout-live--down"}`}>
          <span className="fanout-live-dot" aria-hidden />
          {connected ? "Live" : "Reconnecting…"}
        </span>
      </div>

      {/* Stage row: bucket -> parse -> destinations */}
      <div className="fanout-stage">
        <span className="fanout-chip fanout-chip--source">MinIO bucket</span>
        <span className="fanout-arrow" aria-hidden>
          →
        </span>
        <span className={`fanout-chip${state.currentFile ? " fanout-chip--active" : ""}`}>
          Parse &amp; chunk
        </span>
        <span className="fanout-arrow" aria-hidden>
          →
        </span>
        {destinations.length === 0 ? (
          <span className="fanout-chip fanout-chip--idle">No destination enabled</span>
        ) : (
          destinations.map((dest) => (
            <span
              key={dest.id ?? dest.destination_type}
              className={`fanout-chip fanout-chip--${state.chips[dest.destination_type] ?? "idle"}`}
              title={dest.destination_type}
            >
              {dest.destination_type}
            </span>
          ))
        )}
      </div>

      {state.currentFile && (
        <div className="fanout-current">
          Processing <code className="mono">{shortName(state.currentFile)}</code>
        </div>
      )}

      {/* Counters from the last completed tick */}
      <div className="fanout-counters">
        <span className="fanout-counter">
          Added <strong>{hasTick ? state.counts.added : "—"}</strong>
        </span>
        <span className="fanout-counter">
          Updated <strong>{hasTick ? state.counts.updated : "—"}</strong>
        </span>
        <span className="fanout-counter">
          Deleted <strong>{hasTick ? state.counts.deleted : "—"}</strong>
        </span>
        <span className="fanout-counter">
          Unchanged <strong>{hasTick ? state.counts.unchanged : "—"}</strong>
        </span>
        <span className="fanout-counter">
          Pages <strong>{hasTick ? state.counts.pages : "—"}</strong>
        </span>
      </div>

      {state.destinationsTouched.length > 0 && (
        <div className="fanout-current">
          Last tick wrote to {state.destinationsTouched.join(", ")}
        </div>
      )}

      {/* Recent events */}
      <div className="fanout-log" role="log" aria-live="polite">
        {recent.length === 0 ? (
          <div className="fanout-log-empty">Waiting for the first sync tick…</div>
        ) : (
          recent.map((event) => (
            <div key={event.seq} className="fanout-log-row">
              <span className="fanout-log-time">{clockOf(event.ts)}</span>
              <span className="fanout-log-file">
                {shortName(event.file_key) && <code>{shortName(event.file_key)}</code>}
              </span>
              <span className={`fanout-log-kind fanout-log-kind--${event.kind}`}>
                {typeof event.destination_type === "string"
                  ? `${event.destination_type} ${event.kind}`
                  : event.kind}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
