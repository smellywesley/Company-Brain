"use client";

import React from "react";

interface GlassCardProps {
  title: string;
  icon: string;
  badge?: string;
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}

export default function GlassCard({
  title,
  icon,
  badge,
  className = "",
  style,
  children,
}: GlassCardProps) {
  return (
    <div className={`glass glass-card animate-slide-up ${className}`} style={style}>
      <div className="glass-card-header">
        <div className="glass-card-title-row">
          <span className="glass-card-icon">{icon}</span>
          <h3 className="glass-card-title">{title}</h3>
        </div>
        {badge && <span className="glass-card-badge">{badge}</span>}
      </div>
      {children}
    </div>
  );
}
