"use client";

import { fmtNumber } from "./chartTheme";

export interface DashTooltipItem {
  name?: string;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

export interface DashTooltipProps {
  active?: boolean;
  payload?: DashTooltipItem[];
  label?: string | number;
  /** 饼图/占比图传入合计值，行内追加百分比 */
  total?: number;
  unit?: string;
}

/** 看板统一 tooltip：复用全局 .qa-chart-tooltip 结构，颜色走主题变量 */
export function DashTooltip({ active, payload, label, total, unit }: DashTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div
      className="qa-chart-tooltip"
      style={{
        background: "var(--surface-elevated)",
        border: "1px solid var(--border)",
        color: "var(--foreground)",
        boxShadow: "0 8px 24px -12px rgba(15, 23, 42, 0.45)",
        borderRadius: 10,
        padding: "8px 10px",
      }}
    >
      {label !== undefined && label !== "" && (
        <p className="qa-chart-tooltip-label" style={{ color: "var(--foreground)" }}>
          {String(label)}
        </p>
      )}
      {payload.map((item, index) => {
        const numeric = Number(item.value);
        const percent = total && Number.isFinite(numeric) && total > 0
          ? (numeric / total) * 100
          : null;
        return (
          <p key={`${item.dataKey ?? index}`} className="qa-chart-tooltip-row">
            <span
              className="qa-chart-tooltip-dot"
              style={{ background: item.color || "var(--primary)" }}
            />
            <span style={{ color: "var(--muted)" }}>{item.name ?? item.dataKey}</span>
            <span className="qa-chart-tooltip-val" style={{ color: "var(--foreground)" }}>
              {fmtNumber(item.value)}
              {unit || ""}
              {percent !== null ? ` · ${percent.toFixed(1)}%` : ""}
            </span>
          </p>
        );
      })}
    </div>
  );
}
