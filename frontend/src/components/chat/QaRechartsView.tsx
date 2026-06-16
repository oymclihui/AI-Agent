"use client";

import type { ReactNode } from "react";
import { useMemo } from "react";
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
import type { QaChartPayload, QaChartYKey } from "@/lib/qaIntentProtocol";
import {
  formatChartNum,
  QA_CHART_PALETTE,
  useQaChartTheme,
  type QaChartThemeColors,
} from "@/lib/qaChartTheme";

function toNumber(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function resolveYKeys(chart: QaChartPayload): QaChartYKey[] {
  if (chart.yKeys?.length) return chart.yKeys;
  const sample = chart.data[0] ?? {};
  const xKey = chart.xKey ?? "date";
  return Object.keys(sample)
    .filter((k) => k !== xKey && typeof sample[k] === "number")
    .map((key) => ({ key, name: key }));
}

function seriesColor(yk: QaChartYKey, index: number): string {
  return yk.color ?? QA_CHART_PALETTE[index % QA_CHART_PALETTE.length];
}

function buildRows(chart: QaChartPayload, xKey: string) {
  return chart.data.map((row, i) => ({
    ...row,
    __x: String(row[xKey] ?? row.name ?? `#${i + 1}`),
  }));
}

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
      className="qa-chart-tooltip"
      style={{
        background: theme.tooltipBg,
        border: `1px solid ${theme.border}`,
        color: theme.foreground,
      }}
    >
      <p className="qa-chart-tooltip-label" style={{ color: theme.heading }}>
        {label}
      </p>
      {payload.map((entry) => (
        <p key={String(entry.name)} className="qa-chart-tooltip-row">
          <span className="qa-chart-tooltip-dot" style={{ background: entry.color }} />
          <span>{entry.name}</span>
          <span className="qa-chart-tooltip-val">{formatChartNum(toNumber(entry.value))}</span>
        </p>
      ))}
    </div>
  );
}

function ChartShell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="qa-chart">
      {title && <p className="qa-chart-title">{title}</p>}
      <div className="qa-chart-body">{children}</div>
    </div>
  );
}

export function QaRechartsView({ chart }: { chart: QaChartPayload }) {
  const theme = useQaChartTheme();
  const xKey = chart.xKey ?? "date";
  const yKeys = useMemo(() => resolveYKeys(chart), [chart]);
  const rows = useMemo(() => buildRows(chart, xKey), [chart, xKey]);
  const primaryKey = yKeys[0]?.key ?? "value";

  const axisTick = { fill: theme.muted, fontSize: 11 };
  const gridStroke = theme.grid;

  if (chart.type === "pie") {
    const slices = chart.data.map((row, i) => ({
      name: String(row[xKey] ?? row.name ?? `#${i + 1}`),
      value: toNumber(row[primaryKey] ?? row.value),
      fill: seriesColor({ key: String(i), color: undefined }, i),
    }));

    return (
      <ChartShell title={chart.title}>
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              cx="42%"
              cy="50%"
              innerRadius={52}
              outerRadius={78}
              paddingAngle={2}
              stroke={theme.surface}
              strokeWidth={2}
            >
              {slices.map((entry) => (
                <Cell key={entry.name} fill={entry.fill} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip theme={theme} />} />
            <Legend
              layout="vertical"
              align="right"
              verticalAlign="middle"
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, color: theme.foreground, paddingLeft: 8 }}
              formatter={(value: string) => (
                <span style={{ color: theme.foreground }}>{value}</span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </ChartShell>
    );
  }

  const isStacked = chart.type === "stacked_bar";
  const isArea = chart.type === "area";
  const isLine = chart.type === "line" || isArea;
  const ChartComponent = isLine ? (isArea ? AreaChart : LineChart) : BarChart;
  const showLabels =
    chart.showLabels ?? (rows.length <= 12 && yKeys.length === 1 && !isStacked);

  return (
    <ChartShell title={chart.title}>
      <ResponsiveContainer width="100%" height={showLabels ? 260 : 240}>
        <ChartComponent
          data={rows}
          margin={{ top: showLabels ? 22 : 8, right: 12, left: 4, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
          <XAxis
            dataKey="__x"
            tick={axisTick}
            axisLine={{ stroke: gridStroke }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={axisTick}
            axisLine={false}
            tickLine={false}
            width={44}
            tickFormatter={(v) => formatChartNum(Number(v))}
          />
          <Tooltip content={<ChartTooltip theme={theme} />} />
          {yKeys.length > 1 && (
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              formatter={(value: string) => (
                <span style={{ color: theme.foreground }}>{value}</span>
              )}
            />
          )}
          {yKeys.map((yk, i) => {
            const color = seriesColor(yk, i);
            const name = yk.name ?? yk.key;
            const valueLabel = showLabels ? (
              <LabelList
                dataKey={yk.key}
                position={isLine ? "top" : "top"}
                offset={6}
                formatter={(v: number) => formatChartNum(toNumber(v))}
                style={{ fill: theme.muted, fontSize: 10, fontWeight: 500 }}
              />
            ) : null;

            if (isArea) {
              return (
                <Area
                  key={yk.key}
                  type="monotone"
                  dataKey={yk.key}
                  name={name}
                  stroke={color}
                  fill={color}
                  fillOpacity={0.18}
                  strokeWidth={2}
                  dot={{ r: 3, strokeWidth: 0, fill: color }}
                  activeDot={{ r: 5 }}
                >
                  {valueLabel}
                </Area>
              );
            }
            if (isLine) {
              return (
                <Line
                  key={yk.key}
                  type="monotone"
                  dataKey={yk.key}
                  name={name}
                  stroke={color}
                  strokeWidth={2}
                  dot={{ r: 3, strokeWidth: 0, fill: color }}
                  activeDot={{ r: 5 }}
                >
                  {valueLabel}
                </Line>
              );
            }
            return (
              <Bar
                key={yk.key}
                dataKey={yk.key}
                name={name}
                fill={color}
                radius={[4, 4, 0, 0]}
                stackId={isStacked ? "stack" : undefined}
                maxBarSize={isStacked ? 48 : 36}
              >
                {valueLabel}
              </Bar>
            );
          })}
        </ChartComponent>
      </ResponsiveContainer>
    </ChartShell>
  );
}
