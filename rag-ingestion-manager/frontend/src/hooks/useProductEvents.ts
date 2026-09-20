import { useEffect, useState } from "react";
import { API_URL, authHeaders, productEventsPath } from "../api";

export interface ProductEvent {
  seq: number;
  ts: string;
  kind: string;
  [key: string]: unknown;
}

const MAX_EVENTS = 300;
const RETRY_DELAY_MS = 3000;

/**
 * Stream a Knowledge Product's fanout progress.
 *
 * Uses fetch + ReadableStream rather than EventSource, because EventSource
 * cannot send the X-API-Key header.
 */
export function useProductEvents(productId: string | null): {
  events: ProductEvent[];
  connected: boolean;
} {
  const [events, setEvents] = useState<ProductEvent[]>([]);
  const [connected, setConnected] = useState<boolean>(false);

  useEffect(() => {
    if (!productId) {
      setEvents([]);
      setConnected(false);
      return;
    }

    let cancelled = false;
    let retryTimer: number | undefined;
    const controller = new AbortController();

    setEvents([]);

    const run = async () => {
      try {
        const response = await fetch(`${API_URL}${productEventsPath(productId)}`, {
          headers: authHeaders(),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`Event stream failed: ${response.status}`);
        }
        if (cancelled) return;
        setConnected(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let separator = buffer.indexOf("\n\n");
          while (separator !== -1) {
            const block = buffer.slice(0, separator);
            buffer = buffer.slice(separator + 2);
            separator = buffer.indexOf("\n\n");

            // A ": keepalive" comment carries no data.
            if (block.startsWith(":")) continue;
            const dataLine = block
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (!dataLine) continue;
            try {
              const event = JSON.parse(dataLine.slice(6)) as ProductEvent;
              setEvents((prev) => [...prev, event].slice(-MAX_EVENTS));
            } catch {
              /* ignore a partial frame */
            }
          }
        }
      } catch {
        /* aborted or unreachable; retried below */
      }

      if (cancelled) return;
      setConnected(false);
      retryTimer = window.setTimeout(run, RETRY_DELAY_MS);
    };

    void run();

    return () => {
      cancelled = true;
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      setConnected(false);
    };
  }, [productId]);

  return { events, connected };
}
