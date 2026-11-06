"use client";

import type { UiNode, ChartProps } from "../types";
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

const COLORS = ["#818cf8", "#34d399", "#fbbf24", "#f472b6", "#38bdf8", "#a78bfa", "#fb923c", "#4ade80"];

const AXIS = { stroke: "#64748b", fontSize: 12 };
const GRID = "#e2e8f0";

/** 千分位 + 最多两位小数；非数字统一显示“—” */
function fmtNum(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  const decimals = Math.abs(n) >= 1000 || Number.isInteger(n) ? 0 : 2;
  return n.toLocaleString("zh-CN", { maximumFractionDigits: decimals });
}

export function ChartComponent({ node }: { node: UiNode }) {
  const p = (node.props || {}) as unknown as ChartProps;
  const labels = Array.isArray(p.labels) ? p.labels : [];
  const series = Array.isArray(p.series) ? p.series : [];
  const height = Math.max(120, Math.min(Number(p.height) || 280, 600));
  const pointCount = labels.length;
  const dense = pointCount > 24;

  const data = labels.map((label, i) => {
    const row: Record<string, string | number> = { name: String(label) };
    for (const s of series) {
      const n = Number(s.values?.[i]);
      row[s.name] = Number.isFinite(n) ? n : 0;
    }
    return row;
  });

  const unit = p.unit ? ` ${p.unit}` : "";
  const tooltipProps = {
    contentStyle: { background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12 },
    labelStyle: { color: "#0f172a", marginBottom: 4 },
    itemStyle: { color: "#475569" },
    formatter: (value: unknown, name: unknown) => [`${fmtNum(value)}${unit}`, String(name)],
  };

  if (!labels.length || !series.length) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-500">
        图表缺少 labels 或 series 数据
      </div>
    );
  }

  const wrapper = (chart: React.ReactElement, legend?: React.ReactElement) => (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between">
        {p.title ? <div className="text-xs font-medium text-slate-700">{p.title}</div> : <span />}
        <span className="text-[10px] text-slate-400">
          {series.length} 个系列 · {pointCount} 个数据点
        </span>
      </div>
      <div style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          {chart}
        </ResponsiveContainer>
      </div>
      {legend}
      {p.unit && <div className="mt-1 text-right text-[10px] text-slate-400">单位：{p.unit}</div>}
    </div>
  );

  const legendNode = series.length > 1
    ? <Legend wrapperStyle={{ fontSize: 12, color: "#475569", paddingTop: 4 }} />
    : undefined;

  const xAxis = (
    <XAxis
      dataKey="name"
      tick={{ ...AXIS }}
      interval={dense ? "preserveStartEnd" : 0}
      angle={dense ? -30 : 0}
      textAnchor={dense ? "end" : "middle"}
      height={dense ? 48 : 30}
    />
  );
  const yAxis = <YAxis tick={{ ...AXIS }} tickFormatter={(v) => fmtNum(v)} width={64} />;

  if (p.kind === "pie") {
    const total = labels.reduce<number>((sum, _, i) => {
      const n = Number(series[0]?.values?.[i]);
      return sum + (Number.isFinite(n) ? n : 0);
    }, 0);
    const pieData = labels.map((label, i) => {
      const n = Number(series[0]?.values?.[i]);
      return { name: String(label), value: Number.isFinite(n) ? n : 0 };
    });
    return wrapper(
      <PieChart>
        <Pie
          data={pieData}
          dataKey="value"
          nameKey="name"
          outerRadius={Math.min(height / 2 - 24, 130)}
          paddingAngle={2}
          label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(1)}%`}
          labelLine={false}
        >
          {pieData.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip {...tooltipProps} />
        <Legend wrapperStyle={{ fontSize: 12, color: "#475569" }} />
        {total > 0 && (
          <text x="50%" y="46%" textAnchor="middle" fill="#0f172a" fontSize={16} fontWeight={600}>
            {fmtNum(total)}
          </text>
        )}
      </PieChart>,
    );
  }

  if (p.kind === "line") {
    return wrapper(
      <LineChart data={data} margin={{ top: 6, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.3} />
        {xAxis}
        {yAxis}
        <Tooltip {...tooltipProps} />
        {series.map((s, i) => (
          <Line
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={dense ? false : { r: 2.5 }}
            activeDot={{ r: 4 }}
            animationDuration={600}
          />
        ))}
      </LineChart>,
      legendNode,
    );
  }

  if (p.kind === "area") {
    return wrapper(
      <AreaChart data={data} margin={{ top: 6, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeOpacity={0.3} />
        {xAxis}
        {yAxis}
        <Tooltip {...tooltipProps} />
        {series.map((s, i) => (
          <Area
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stackId={p.stacked ? "1" : undefined}
            stroke={COLORS[i % COLORS.length]}
            fill={COLORS[i % COLORS.length]}
            fillOpacity={0.25}
            animationDuration={600}
          />
        ))}
      </AreaChart>,
      legendNode,
    );
  }

  return wrapper(
    <BarChart data={data} margin={{ top: 6, right: 16, left: 0, bottom: 0 }}>
      <CartesianGrid stroke={GRID} strokeOpacity={0.3} />
      {xAxis}
      {yAxis}
      <Tooltip {...tooltipProps} cursor={{ fill: "#e2e8f0", fillOpacity: 0.5 }} />
      {series.map((s, i) => (
        <Bar
          key={s.name}
          dataKey={s.name}
          stackId={p.stacked ? "1" : undefined}
          fill={COLORS[i % COLORS.length]}
          radius={[3, 3, 0, 0]}
          animationDuration={600}
        />
      ))}
    </BarChart>,
    legendNode,
  );
}
