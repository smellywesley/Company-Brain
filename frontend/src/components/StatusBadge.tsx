"use client";

import React from "react";

interface StatusBadgeProps {
  variant: "success" | "warning" | "danger" | "info" | "pending";
  children: React.ReactNode;
}

export default function StatusBadge({ variant, children }: StatusBadgeProps) {
  return (
    <span className={`badge badge-${variant}`}>
      <span className={`badge-dot badge-dot-${variant}`} />
      {children}
    </span>
  );
}
