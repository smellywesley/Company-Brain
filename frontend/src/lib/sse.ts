/**
 * SSE (Server-Sent Events) hook for real-time updates.
 *
 * Auto-reconnects with exponential backoff on disconnect.
 */
"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface SSEState<T = unknown> {
  lastEvent: T | null;
  isConnected: boolean;
  error: string | null;
}

export function useEventStream<T = unknown>(url: string): SSEState<T> {
  const [lastEvent, setLastEvent] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const retriesRef = useRef(0);
  const sourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!url) return;

    try {
      const source = new EventSource(url);
      sourceRef.current = source;

      source.onopen = () => {
        setIsConnected(true);
        setError(null);
        retriesRef.current = 0;
      };

      source.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as T;
          setLastEvent(data);
        } catch {
          setLastEvent(event.data as unknown as T);
        }
      };

      source.onerror = () => {
        setIsConnected(false);
        source.close();

        // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
        const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30000);
        retriesRef.current += 1;
        setError(`Disconnected. Reconnecting in ${delay / 1000}s...`);

        setTimeout(connect, delay);
      };
    } catch (err) {
      setError(`Failed to connect: ${err}`);
    }
  }, [url]);

  useEffect(() => {
    connect();
    return () => {
      sourceRef.current?.close();
    };
  }, [connect]);

  return { lastEvent, isConnected, error };
}
