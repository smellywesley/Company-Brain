"use client";

import { motion, useReducedMotion } from "motion/react";
import { severityColor } from "@/lib/format";
import type { BlastRadius } from "@/lib/api";

interface BlastRadiusGraphProps {
  data: BlastRadius;
  size?: number;
}

const EFFECT_LABEL: Record<string, string> = {
  write: "writes",
  read: "reads",
  notify: "notifies",
};

/**
 * Pre-execution impact graph: the origin system at the centre, every downstream
 * system it would touch around it, coloured by severity and shaped by effect
 * (write / read / notify). Powered by the graph traversal (or its deterministic
 * fallback). Animates the edges and nodes in so the "blast" reads visually.
 */
export function BlastRadiusGraph({ data, size = 320 }: BlastRadiusGraphProps) {
  const reduce = useReducedMotion();
  const cx = size / 2;
  const cy = size / 2;
  const radius = size * 0.36;
  const n = data.nodes.length;

  const positions = data.nodes.map((_, i) => {
    // Spread around a circle, starting at the top.
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, n);
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="max-w-full">
        <defs>
          <filter id="br-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Edges + a pulse of data flowing along each one */}
        {positions.map((pos, i) => {
          const node = data.nodes[i];
          const color = severityColor(node.severity);
          return (
            <g key={`edge-${node.id}`}>
              <motion.line
                x1={cx}
                y1={cy}
                x2={pos.x}
                y2={pos.y}
                stroke={color}
                strokeWidth={node.effect === "write" ? 2 : 1}
                strokeDasharray={node.effect === "notify" ? "4 4" : undefined}
                strokeOpacity={0.4}
                initial={reduce ? false : { pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 0.4 }}
                transition={{ duration: 0.4, delay: 0.1 + i * 0.06, ease: "easeOut" }}
              />
              {!reduce && (
                <motion.circle
                  r={2.5}
                  fill={color}
                  initial={{ cx, cy, opacity: 0 }}
                  animate={{ cx: [cx, pos.x], cy: [cy, pos.y], opacity: [0, 1, 0] }}
                  transition={{
                    duration: 2.2,
                    delay: 0.5 + i * 0.25,
                    repeat: Infinity,
                    repeatDelay: 1.2,
                    ease: "easeInOut",
                  }}
                />
              )}
            </g>
          );
        })}

        {/* Downstream nodes */}
        {positions.map((pos, i) => {
          const node = data.nodes[i];
          const color = severityColor(node.severity);
          return (
            <motion.g
              key={node.id}
              initial={reduce ? false : { scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{
                duration: 0.35,
                delay: 0.2 + i * 0.06,
                ease: [0.16, 1, 0.3, 1],
              }}
              style={{ transformOrigin: `${pos.x}px ${pos.y}px` }}
            >
              {/* radial glow halo */}
              <circle cx={pos.x} cy={pos.y} r={16} fill={color} opacity={0.14} filter="url(#br-glow)" />
              <circle
                cx={pos.x}
                cy={pos.y}
                r={8}
                fill={node.effect === "read" ? "var(--card)" : color}
                stroke={color}
                strokeWidth={2}
                filter="url(#br-glow)"
              />
              <text
                x={pos.x}
                y={pos.y + (pos.y < cy ? -14 : 20)}
                textAnchor="middle"
                className="fill-foreground"
                style={{ fontSize: 11, fontWeight: 600 }}
              >
                {node.system}
              </text>
              <text
                x={pos.x}
                y={pos.y + (pos.y < cy ? -2 : 32)}
                textAnchor="middle"
                className="fill-muted-foreground"
                style={{ fontSize: 9 }}
              >
                {EFFECT_LABEL[node.effect]}
              </text>
            </motion.g>
          );
        })}

        {/* Pulsing origin */}
        {!reduce && (
          <motion.circle
            cx={cx}
            cy={cy}
            r={16}
            fill="var(--accent-blue-glow)"
            animate={{ r: [16, 26, 16], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        <circle cx={cx} cy={cy} r={15} fill="var(--primary)" />
        <text
          x={cx}
          y={cy + 4}
          textAnchor="middle"
          style={{ fontSize: 10, fontWeight: 700 }}
          className="fill-[var(--primary-foreground)]"
        >
          {data.origin.system.slice(0, 2).toUpperCase()}
        </text>
      </svg>

      <p className="mt-1 text-center text-xs text-muted-foreground">
        Origin: <span className="font-medium text-foreground">{data.origin.label}</span>
        {data.simulated && " · simulated from topology"}
      </p>
    </div>
  );
}
