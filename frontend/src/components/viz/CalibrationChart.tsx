"use client";

import { motion, useReducedMotion } from "motion/react";
import type { CalibrationBucket } from "@/lib/api";

interface CalibrationChartProps {
  curve: CalibrationBucket[];
  meanAbsError: number | null;
  samples: number;
  size?: number;
}

/**
 * Reliability diagram: predicted risk probability (x) vs observed rate of
 * negative outcomes (y). A perfectly calibrated critic sits on the diagonal.
 * This is the chart that makes a fintech buyer trust the autonomy.
 */
export function CalibrationChart({
  curve,
  meanAbsError,
  samples,
  size = 240,
}: CalibrationChartProps) {
  const reduce = useReducedMotion();
  const pad = 28;
  const inner = size - pad * 2;
  const x = (v: number) => pad + v * inner;
  const y = (v: number) => size - pad - v * inner;

  const populated = curve.filter((b) => b.observed !== null);
  const linePoints = populated
    .map((b) => `${x(b.predicted_mid)},${y(b.observed as number)}`)
    .join(" ");

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="max-w-full">
        {/* grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line x1={x(g)} y1={y(0)} x2={x(g)} y2={y(1)} stroke="var(--border)" strokeWidth={1} />
            <line x1={x(0)} y1={y(g)} x2={x(1)} y2={y(g)} stroke="var(--border)" strokeWidth={1} />
          </g>
        ))}
        {/* perfect-calibration diagonal */}
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--muted-foreground)"
          strokeWidth={1.5}
          strokeDasharray="5 4"
        />
        {/* observed curve */}
        {linePoints && (
          <motion.polyline
            points={linePoints}
            fill="none"
            stroke="var(--accent-blue)"
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduce ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.7, ease: "easeOut" }}
          />
        )}
        {/* points */}
        {populated.map((b, i) => (
          <motion.circle
            key={b.predicted_mid}
            cx={x(b.predicted_mid)}
            cy={y(b.observed as number)}
            r={Math.max(3, Math.min(8, 3 + b.count))}
            fill="var(--accent-blue)"
            stroke="var(--card)"
            strokeWidth={2}
            initial={reduce ? false : { scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2 + i * 0.08, duration: 0.3 }}
          />
        ))}
        {/* axis labels */}
        <text x={size / 2} y={size - 4} textAnchor="middle" className="fill-muted-foreground" style={{ fontSize: 10 }}>
          predicted risk →
        </text>
        <text
          x={10}
          y={size / 2}
          textAnchor="middle"
          transform={`rotate(-90 10 ${size / 2})`}
          className="fill-muted-foreground"
          style={{ fontSize: 10 }}
        >
          observed outcome →
        </text>
      </svg>
      <p className="mt-1 text-xs text-muted-foreground">
        {meanAbsError !== null ? (
          <>
            Mean calibration error{" "}
            <span className="font-semibold text-foreground">{Math.round(meanAbsError * 100)}%</span>
          </>
        ) : (
          "Not enough resolved outcomes yet"
        )}{" "}
        · {samples} samples
      </p>
    </div>
  );
}
