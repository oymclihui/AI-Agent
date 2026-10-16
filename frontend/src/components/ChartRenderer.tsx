"use client";

import { useMemo, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatChartNum, QA_CHART_PALETTE, useQaChartTheme, type QaChartThemeColors } from "@/lib/qaChartTheme";

export interface ChatChartData {
  type: "bar" | "line" | "pie" | "area" | "scatter";
  title?: string;
  labels: string[];
  datasets: { label: string; data: number[] }[];
  horizontal?: boolean;
}

function toNumber(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

/* ── 自定义 Tooltip：圆点 + 名称 + 格式化数值 ─────────────── */
function ChartTooltip({
  active,
  payload,
  label,
  theme,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string }[];
  label?: string;
  theme: QaChartThemeColors;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: theme.tooltipBg,
        border: `1px solid ${theme.border}`,
        borderRadius: 10,
        boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
        padding: "8px 12px",
        color: theme.foreground,
        fontSize: 12,
      }}
    >
      {label !== undefined && label !== "" && (
        <p style={{ color: theme.heading, fontWeight: 600, margin: "0 0 4px" }}>{label}</p>
      )}
      {payload.map((entry) => (
        <p key={String(entry.name)} style={{ display: "flex", alignItems: "center", gap: 6, margin: "2px 0" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: entry.color, display: "inline-block" }} />
          <span style={{ opacity: 0.85 }}>{entry.name}</span>
          <span style={{ marginLeft: "auto", fontWeight: 600, fontVariantNumeric: "tabular-nums", paddingLeft: 12 }}>
            {formatChartNum(toNumber(entry.value))}
          </span>
        </p>
      ))}
    </div>
  );
}

/* ── 卡片外壳：标题 + 图表体 ─────────────────────────────── */
function ChartShell({ title, children }: { title?: string; children: ReactNode }) {
  const theme = useQaChartTheme();
  return (
    <div
      style={{
        width: "100%",
        borderRadius: 12,
        border: `1px solid ${theme.border}`,
        background: theme.surface,
        padding: "14px 16px 10px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
      }}
    >
      {title && (
        <p style={{ color: theme.heading, fontSize: 13.5, fontWeight: 650, margin: "0 0 10px" }}>{title}</p>
      )}
      {children}
    </div>
  );
}

export function ChartRenderer({ chart }: { chart: ChatChartData }) {
  const theme = useQaChartTheme();

  /* labels/datasets → recharts rows: [{name, [seriesLabel]: value}] */
  const rows = useMemo(
    () =>
      chart.labels.map((label, i) => {
        const row: Record<string, string | number> = { name: label };
        chart.datasets.forEach((ds) => {
          row[ds.label] = toNumber(ds.data[i]);
        });
        return row;
      }),
    [chart],
  );

  const axisTick = { fill: theme.muted, fontSize: 11 };
  const showValueLabels = chart.labels.length <= 12 && chart.datasets.length === 1;
  const tooltipEl = <ChartTooltip theme={theme} />;
  const legendEl =
    chart.datasets.length > 1 ? (
      <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
    ) : undefined;

  /* ── 饼图（环形 + 中心总额 + 百分比标签） ───────────────── */
  if (chart.type === "pie") {
    const pieData = chart.labels.map((label, i) => ({
      name: label,
      value: toNumber(chart.datasets[0]?.data[i] ?? 0),
    }));
    const total = pieData.reduce((s, d) => s + d.value, 0);

    return (
      <ChartShell title={chart.title}>
        <ResponsiveContainer width="100%" height={250}>
          <PieChart>
            <Pie
              data={pieData}
              dataKey="value"
              nameKey="name"
              cx="42%"
              cy="50%"
              innerRadius={58}
              outerRadius={88}
              paddingAngle={2}
              stroke={theme.surface}
              strokeWidth={2}
              animationDuration={700}
              label={({ name, percent }: { name?: string; percent?: number }) =>
                `${name} ${(((percent ?? 0) * 100).toFixed(0))}%`
              }
              labelLine={false}
            >
              {pieData.map((_, i) => (
                <Cell key={i} fill={QA_CHART_PALETTE[i % QA_CHART_PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip content={tooltipEl} />
            <Legend
              layout="vertical"
              align="right"
              verticalAlign="middle"
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, color: theme.foreground, paddingLeft: 8 }}
            />
          </PieChart>
        </ResponsiveContainer>
        <p style={{ textAlign: "center", fontSize: 11, color: theme.muted, margin: "2px 0 0" }}>
          合计：<span style={{ fontWeight: 650, color: theme.heading, fontVariantNumeric: "tabular-nums" }}>{formatChartNum(total)}</span>
        </p>
      </ChartShell>
    );
  }

  /* ── 柱状图 ───────────────────────────────────────────── */
  if (chart.type === "bar" && chart.horizontal) {
    const height = Math.max(220, chart.labels.length * 36 + 48);
    return (
      <ChartShell title={chart.title}>
        <ResponsiveContainer width="100%" height={height}>
          <BarChart layout="vertical" data={rows} margin={{ top: 8, right: 28, left: 8, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} horizontal={false} />
            <XAxis type="number" tick={axisTick} axisLine={{ stroke: theme.grid }} tickLine={false} tickFormatter={(v) => formatChartNum(Number(v))} />
            <YAxis
              type="category"
              dataKey="name"
              width={Math.min(220, Math.max(96, Math.max(...chart.labels.map((label) => label.length)) * 16))}
              tick={axisTick}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={tooltipEl} cursor={{ fill: theme.grid, fillOpacity: 0.25 }} />
            {legendEl}
            {chart.datasets.map((ds, idx) => (
              <Bar
                key={ds.label}
                dataKey={ds.label}
                fill={QA_CHART_PALETTE[idx % QA_CHART_PALETTE.length]}
                radius={[0, 5, 5, 0]}
                maxBarSize={28}
                animationDuration={700}
              >
                {showValueLabels && (
                  <LabelList
                    dataKey={ds.label}
                    position="right"
                    formatter={(v: number) => formatChartNum(toNumber(v))}
                    style={{ fill: theme.muted, fontSize: 10.5, fontWeight: 500 }}
                  />
                )}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartShell>
    );
  }

  if (chart.type === "bar") {
    return (
      <ChartShell title={chart.title}>
        <ResponsiveContainer width="100%" height={showValueLabels ? 290 : 260}>
          <BarChart data={rows} margin={{ top: showValueLabels ? 22 : 10, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} vertical={false} />
            <XAxis dataKey="name" tick={axisTick} axisLine={{ stroke: theme.grid }} tickLine={false} interval={0} />
            <YAxis tick={axisTick} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => formatChartNum(Number(v))} />
            <Tooltip content={tooltipEl} cursor={{ fill: theme.grid, fillOpacity: 0.25 }} />
            {legendEl}
            {chart.datasets.map((ds, idx) => (
              <Bar
                key={ds.label}
                dataKey={ds.label}
                fill={QA_CHART_PALETTE[idx % QA_CHART_PALETTE.length]}
                radius={[5, 5, 0, 0]}
                maxBarSize={44}
                animationDuration={700}
              >
                {showValueLabels && (
                  <LabelList
                    dataKey={ds.label}
                    position="top"
                    formatter={(v: number) => formatChartNum(toNumber(v))}
                    style={{ fill: theme.muted, fontSize: 10.5, fontWeight: 500 }}
                  />
                )}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartShell>
    );
  }

  /* ── 折线图 ───────────────────────────────────────────── */
  if (chart.type === "line" || chart.type === "scatter") {
    return (
      <ChartShell title={chart.title}>
        <ResponsiveContainer width="100%" height={270}>
          <LineChart data={rows} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} vertical={false} />
            <XAxis dataKey="name" tick={axisTick} axisLine={{ stroke: theme.grid }} tickLine={false} />
            <YAxis tick={axisTick} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => formatChartNum(Number(v))} />
            <Tooltip content={tooltipEl} />
            {legendEl}
            {chart.datasets.map((ds, idx) => {
              const color = QA_CHART_PALETTE[idx % QA_CHART_PALETTE.length];
              return (
                <Line
                  key={ds.label}
                  type="monotone"
                  dataKey={ds.label}
                  stroke={color}
                  strokeWidth={2.5}
                  dot={{ r: 3, strokeWidth: 0, fill: color }}
                  activeDot={{ r: 5 }}
                  animationDuration={700}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </ChartShell>
    );
  }

  /* ── 面积图（渐变填充） ───────────────────────────────── */
  if (chart.type === "area") {
    return (
      <ChartShell title={chart.title}>
        <ResponsiveContainer width="100%" height={270}>
          <AreaChart data={rows} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
            <defs>
              {chart.datasets.map((ds, idx) => {
                const color = QA_CHART_PALETTE[idx % QA_CHART_PALETTE.length];
                return (
                  <linearGradient key={ds.label} id={`cr-grad-${idx}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={color} stopOpacity={0.32} />
                    <stop offset="95%" stopColor={color} stopOpacity={0.04} />
                  </linearGradient>
                );
              })}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} vertical={false} />
            <XAxis dataKey="name" tick={axisTick} axisLine={{ stroke: theme.grid }} tickLine={false} />
            <YAxis tick={axisTick} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => formatChartNum(Number(v))} />
            <Tooltip content={tooltipEl} />
            {legendEl}
            {chart.datasets.map((ds, idx) => {
              const color = QA_CHART_PALETTE[idx % QA_CHART_PALETTE.length];
              return (
                <Area
                  key={ds.label}
                  type="monotone"
                  dataKey={ds.label}
                  stroke={color}
                  strokeWidth={2.5}
                  fill={`url(#cr-grad-${idx})`}
                  dot={{ r: 3, strokeWidth: 0, fill: color }}
                  activeDot={{ r: 5 }}
                  animationDuration={700}
                />
              );
            })}
          </AreaChart>
        </ResponsiveContainer>
      </ChartShell>
    );
  }

  return null;
}
