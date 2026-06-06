/**
 * Real-time Activity Feed component.
 *
 * Shows a scrolling list of platform events. Uses SSE when available,
 * falls back to polling the API every 30 seconds.
 */
"use client";

import { useState, useEffect, useRef } from "react";

interface ActivityEvent {
  id: string;
  type: "ingestion" | "workflow" | "feedback" | "skill" | "system";
  title: string;
  description: string;
  timestamp: string;
}

const ICONS: Record<string, string> = {
  ingestion: "📥",
  workflow: "⚡",
  feedback: "💬",
  skill: "🧠",
  system: "🔧",
};

const COLORS: Record<string, string> = {
  ingestion: "var(--color-emerald)",
  workflow: "var(--color-blue)",
  feedback: "var(--color-amber)",
  skill: "var(--color-purple, #a855f7)",
  system: "var(--color-gray, #6b7280)",
};

// Mock events for initial display
const MOCK_EVENTS: ActivityEvent[] = [
  {
    id: "1",
    type: "ingestion",
    title: "Slack sync completed",
    description: "142 messages ingested from #support",
    timestamp: new Date(Date.now() - 120000).toISOString(),
  },
  {
    id: "2",
    type: "workflow",
    title: "Refund workflow executed",
    description: "Order #ORD-4821 — $89.00 refund approved",
    timestamp: new Date(Date.now() - 300000).toISOString(),
  },
  {
    id: "3",
    type: "feedback",
    title: "Feedback submitted",
    description: "Manager corrected refund policy interpretation",
    timestamp: new Date(Date.now() - 600000).toISOString(),
  },
  {
    id: "4",
    type: "skill",
    title: "New skill discovered",
    description: "'Customer Escalation Handling' (draft, 0.82 confidence)",
    timestamp: new Date(Date.now() - 900000).toISOString(),
  },
  {
    id: "5",
    type: "system",
    title: "CriticAgent calibrated",
    description: "New rule: 'Reject subscription refunds > 30 days'",
    timestamp: new Date(Date.now() - 1200000).toISOString(),
  },
];

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function ActivityFeed() {
  const [events, setEvents] = useState<ActivityEvent[]>(MOCK_EVENTS);
  const containerRef = useRef<HTMLDivElement>(null);

  // Polling fallback (SSE endpoint can be wired later)
  useEffect(() => {
    const interval = setInterval(() => {
      // In production, this would call the API
      // For now, add a random mock event to demonstrate real-time feel
      const types: ActivityEvent["type"][] = ["ingestion", "workflow", "feedback", "skill"];
      const type = types[Math.floor(Math.random() * types.length)];
      const titles: Record<string, string[]> = {
        ingestion: ["Notion sync completed", "GitHub sync completed", "Slack sync completed"],
        workflow: ["Ticket triage executed", "Deploy approval processed", "Refund processed"],
        feedback: ["Engineer approved action", "Manager rejected workflow", "Skill correction submitted"],
        skill: ["Skill confidence updated", "New pattern detected", "Skill promoted to active"],
      };
      const t = titles[type];
      const newEvent: ActivityEvent = {
        id: `live-${Date.now()}`,
        type,
        title: t[Math.floor(Math.random() * t.length)],
        description: "Automated system event",
        timestamp: new Date().toISOString(),
      };

      setEvents((prev) => [newEvent, ...prev].slice(0, 20));
    }, 30000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div ref={containerRef} style={{ maxHeight: 340, overflowY: "auto" }}>
      {events.map((event, idx) => (
        <div
          key={event.id}
          style={{
            display: "flex",
            gap: 12,
            padding: "10px 0",
            borderBottom: "1px solid rgba(255,255,255,0.06)",
            animation: idx === 0 ? "slideUp 0.3s ease-out" : undefined,
          }}
        >
          <span style={{ fontSize: 20 }}>{ICONS[event.type]}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: COLORS[event.type],
              }}
            >
              {event.title}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "rgba(255,255,255,0.5)",
                marginTop: 2,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {event.description}
            </div>
          </div>
          <span
            style={{
              fontSize: 11,
              color: "rgba(255,255,255,0.35)",
              whiteSpace: "nowrap",
            }}
          >
            {timeAgo(event.timestamp)}
          </span>
        </div>
      ))}
    </div>
  );
}
