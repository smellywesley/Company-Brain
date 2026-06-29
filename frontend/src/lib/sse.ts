/**
 * SSE (Server-Sent Events) hook for real-time updates.
 *
 * Auto-reconnects with exponential backoff on disconnect.
 */
"use client";

import { useState, useEffect } from "react";

interface SSEState<T = unknown> {
  lastEvent: T | null;
  isConnected: boolean;
  error: string | null;
}

export function useEventStream<T = unknown>(url: string): SSEState<T> {
  const [lastEvent, setLastEvent] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Connection lifecycle lives entirely inside the effect so the reconnect
  // closure can reference `connect` (a hoisted function declaration — no TDZ)
  // and all per-connection state (retries, source, timer) is scoped to the
  // active url and torn down on unmount / url change.
  useEffect(() => {
    if (!url) return;

    let retries = 0;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      try {
        source = new EventSource(url);

        source.onopen = () => {
          setIsConnected(true);
          setError(null);
          retries = 0;
        };

        source.onmessage = (event) => {
          try {
            setLastEvent(JSON.parse(event.data) as T);
          } catch {
            setLastEvent(event.data as unknown as T);
          }
        };

        source.onerror = () => {
          setIsConnected(false);
          source?.close();

          // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
          const delay = Math.min(1000 * Math.pow(2, retries), 30000);
          retries += 1;
          setError(`Disconnected. Reconnecting in ${delay / 1000}s...`);
          timer = setTimeout(connect, delay);
        };
      } catch (err) {
        setError(`Failed to connect: ${err}`);
      }
    }

    connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [url]);

  return { lastEvent, isConnected, error };
}
