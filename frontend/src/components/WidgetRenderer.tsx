"use client";

import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Download } from "lucide-react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart as RScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AXIS_TICK,
  CHART_PALETTE,
  GRID_COLOR,
  accentOf,
  axisLabel,
  compactNumber,
  fmtNumber as fmt,
  isNumLike as isNum,
  numOf as num,
} from "./charts/chartTheme";
import { DashTooltip } from "./charts/ChartTooltip";

export interface WidgetData {
  columns?: string[];
  rows?: unknown[][];
}

export interface WidgetDrill {
  enabled: boolean;
  field: string;
  label: string;
  metric_name: string;
  metric_expr: string;
  metric_alias: string;
  detail_dimensions: string[];
}

export interface Widget {
  id: string;
  widget_type: string;
  title: string;
  layout?: { x?: number; y?: number; w?: number; h?: number };
  columns?: string[];
  options?: Record<string, unknown>;
  data?: WidgetData;
  drill?: WidgetDrill;
}

const SURFACE_TEXT = "var(--foreground)";
const MUTED_TEXT = "var(--muted)";

function downloadCsv(name: string, columns: string[], rows: unknown[][]) {
  const escape = (cell: unknown) => {
    const text = cell === null || cell === undefined ? "" : String(cell);
    return `"${text.replace(/"/g, '""')}"`;
  };
  const lines = [columns.map(escape).join(","), ...rows.map((r) => r.map(escape).join(","))];
  const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function Empty() {
  return <div className="py-8 text-center text-xs" style={{ color: "var(--muted)" }}>筛选后无数据</div>;
}

function Skeleton({ type }: { type: string }) {
  if (type === "kpi_card") {
    return (
      <div className="space-y-2 py-1">
        <div className="dash-skel h-3 w-20" />
        <div className="dash-skel h-8 w-28" />
      </div>
    );
  }
  if (type === "share_pie") {
    return (
      <div className="flex items-center gap-3">
        <div className="dash-skel h-32 w-32 shrink-0 rounded-full" />
        <div className="flex-1 space-y-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="dash-skel h-3 w-full" />)}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2 py-1">
      <div className="dash-skel h-3 w-1/3" />
      <div className="dash-skel h-24 w-full" />
      <div className="dash-skel h-3 w-2/3" />
    </div>
  );
}

function DataTable({ columns, rows, limit = 50 }: { columns: string[]; rows: unknown[][]; limit?: number }) {
  const head = columns.length ? columns : (rows[0] || []).map((_, i) => `列${i + 1}`);
  return (
    <div className="dash-scroll max-h-72 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0" style={{ background: "var(--surface-elevated)" }}>
          <tr>
            {head.map((c, i) => (
              <th
                key={`${c}-${i}`}
                className="whitespace-nowrap border-b px-2 py-1.5 text-left font-medium"
                style={{ borderColor: "var(--border)", color: MUTED_TEXT }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, limit).map((row, i) => (
            <tr key={i} className="transition-colors hover:bg-[var(--hover)]">
              {row.map((cell, j) => (
                <td
                  key={j}
                  className="whitespace-nowrap border-b px-2 py-1.5 tabular-nums"
                  style={{ borderColor: "var(--border)", color: SURFACE_TEXT }}
                >
                  {fmt(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 趋势线：面积渐变 + 预测虚线 + 图例 + 十字准线 */
function TrendLine({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  const series = ((widget.options?.series as string[]) || []).filter((s) => columns.includes(s));
  const forecastCol = (widget.options?.type_col as string) || "";
  const typeIndex = forecastCol ? columns.indexOf(forecastCol) : -1;
  if (!rows.length || !series.length) return <Empty />;

  const forecastStart = typeIndex >= 0 ? rows.findIndex((r) => String(r[typeIndex]) === "预测") : -1;
  // 双序列量级差超过 6 倍时启用右轴，避免小量级序列贴地不可读
  const scales = series.map((s) =>
    Math.max(...rows.map((row) => Math.abs(num(row[columns.indexOf(s)]))), 0),
  );
  const largest = Math.max(...scales);
  const smallest = Math.max(Math.min(...scales), 1);
  const dual = series.length > 1 && largest > 6 * smallest;
  const primary = scales.indexOf(largest);
  const axisOf = (i: number) => (dual && i !== primary ? "right" : "left");
  const data = rows.map((row, i) => {
    const item: Record<string, unknown> = { __x: axisLabel(row[0]) };
    series.forEach((s) => {
      const value = num(row[columns.indexOf(s)]);
      const isForecast = forecastStart >= 0 && i >= forecastStart;
      item[s] = isForecast ? null : value;
      if (typeIndex >= 0) item[`${s}__fc`] = isForecast ? value : null;
    });
    return item;
  });

  return (
    <div style={{ height: 196 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -6 }}>
          <defs>
            {series.map((s, i) => (
              <linearGradient key={s} id={`grad-${widget.id}-${i}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={CHART_PALETTE[i % CHART_PALETTE.length]} stopOpacity={0.26} />
                <stop offset="100%" stopColor={CHART_PALETTE[i % CHART_PALETTE.length]} stopOpacity={0.01} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid stroke={GRID_COLOR} vertical={false} strokeDasharray="3 4" />
          <XAxis dataKey="__x" tick={AXIS_TICK} tickLine={false} axisLine={false} interval="preserveStartEnd" />
          <YAxis yAxisId="left" tick={AXIS_TICK} tickLine={false} axisLine={false} width={46} tickFormatter={(v: number) => compactNumber(v)} />
          {dual && (
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={AXIS_TICK}
              tickLine={false}
              axisLine={false}
              width={40}
              tickFormatter={(v: number) => compactNumber(v)}
            />
          )}
          <Tooltip content={<DashTooltip />} cursor={{ stroke: "var(--border)" }} />
          <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11, paddingTop: 2 }} />
          {series.map((s, i) => (
            <Area
              key={s}
              yAxisId={axisOf(i)}
              type="monotone"
              dataKey={s}
              name={s}
              stroke={CHART_PALETTE[i % CHART_PALETTE.length]}
              fill={`url(#grad-${widget.id}-${i})`}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3.5, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
          {typeIndex >= 0 && series.map((s, i) => (
            <Line
              key={`${s}-fc`}
              yAxisId={axisOf(i)}
              type="monotone"
              dataKey={`${s}__fc`}
              name={`${s}·预测`}
              stroke={CHART_PALETTE[i % CHART_PALETTE.length]}
              strokeDasharray="5 4"
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** 预测图：置信带 + 实线实际 + 虚线预测 */
function ForecastChart({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  const vi = columns.indexOf("值");
  const ti = columns.indexOf("类型");
  const lo = columns.indexOf("下限");
  const hi = columns.indexOf("上限");
  if (!rows.length || vi < 0) return <Empty />;

  const firstForecast = rows.findIndex((r) => ti >= 0 && String(r[ti]) === "预测");
  const data = rows.map((row, i) => {
    const lower = lo >= 0 && isNum(row[lo]) ? num(row[lo]) : null;
    const upper = hi >= 0 && isNum(row[hi]) ? num(row[hi]) : null;
    const inForecast = firstForecast >= 0 && i >= firstForecast;
    return {
      __x: axisLabel(row[0]),
      __lo: lower,
      __band: lower !== null && upper !== null ? Math.max(upper - lower, 0) : null,
      实际: inForecast ? null : num(row[vi]),
      预测: inForecast ? num(row[vi]) : null,
    };
  });

  return (
    <div style={{ height: 200 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 10, bottom: 0, left: -6 }}>
          <CartesianGrid stroke={GRID_COLOR} vertical={false} strokeDasharray="3 4" />
          <XAxis dataKey="__x" tick={AXIS_TICK} tickLine={false} axisLine={false} interval="preserveStartEnd" />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={46} tickFormatter={(v: number) => compactNumber(v)} />
          <Tooltip content={<DashTooltip />} cursor={{ stroke: "var(--border)" }} />
          <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11, paddingTop: 2 }} />
          <Area dataKey="__lo" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
          <Area dataKey="__band" stackId="band" name="置信区间" stroke="none" fill={CHART_PALETTE[1]} fillOpacity={0.14} isAnimationActive={false} />
          <Line type="monotone" dataKey="实际" name="实际" stroke={CHART_PALETTE[0]} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="预测" name="预测" stroke={CHART_PALETTE[1]} strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** 环形占比：中心合计 + 右侧图例 */
function SharePie({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  const dim = String(widget.options?.dimension || columns[0] || "");
  const metric = String(widget.options?.metric || columns[1] || "");
  let di = columns.indexOf(dim);
  let mi = columns.indexOf(metric);
  if (di < 0 && columns.length) di = 0;
  if (mi < 0) mi = columns.length > 1 ? 1 : -1;
  if (di < 0 || mi < 0 || !rows.length) return <Empty />;

  const items = rows
    .map((r) => ({ name: String(r[di] ?? ""), value: Math.abs(num(r[mi])) }))
    .filter((x) => x.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
  const total = items.reduce((sum, x) => sum + x.value, 0) || 1;

  return (
    <div className="flex items-center gap-2">
      <div className="relative shrink-0" style={{ width: 148, height: 148 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip content={<DashTooltip total={total} />} />
            <Pie
              data={items}
              dataKey="value"
              nameKey="name"
              innerRadius={46}
              outerRadius={68}
              paddingAngle={2}
              cornerRadius={4}
              stroke="none"
              isAnimationActive={false}
            >
              {items.map((item, i) => (
                <Cell key={item.name} fill={CHART_PALETTE[i % CHART_PALETTE.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[10px]" style={{ color: MUTED_TEXT }}>合计</span>
          <span className="text-sm font-semibold tabular-nums" style={{ color: SURFACE_TEXT }}>
            {compactNumber(total)}
          </span>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        {items.map((item, i) => (
          <div key={item.name} className="flex items-center gap-1.5 text-xs">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: CHART_PALETTE[i % CHART_PALETTE.length] }}
            />
            <span className="min-w-0 flex-1 truncate" style={{ color: MUTED_TEXT }}>{item.name}</span>
            <span className="tabular-nums" style={{ color: SURFACE_TEXT }}>
              {((item.value / total) * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 横向排名：可下钻 */
function RankBar({ widget, onDrill }: { widget: Widget; onDrill?: (w: Widget, value: string) => void }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  const dim = String(widget.options?.dimension || columns[0] || "");
  const metric = String(widget.options?.metric || columns[1] || "");
  let di = columns.indexOf(dim);
  let mi = columns.indexOf(metric);
  if (mi < 0) mi = 1;
  if (di < 0) di = 0;
  if (di < 0 || mi < 0 || !rows.length) return <DataTable columns={columns} rows={rows} />;

  const drillable = Boolean(widget.drill?.enabled && onDrill);
  const items = rows.slice(0, 20).map((row) => ({
    __name: String(row[di] ?? ""),
    __value: num(row[mi]),
  }));
  const height = Math.max(140, items.length * 24 + 18);
  // 全负值（负毛利类）：条形自零轴向左生长，数值标签改到左端，避免全部堆在零线上重叠
  const allNegative = items.length > 0 && items.every((it) => it.__value < 0);

  return (
    <div>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={items}
            layout="vertical"
            margin={{ top: 2, right: allNegative ? 10 : 46, bottom: 2, left: allNegative ? 12 : 0 }}
          >
            <CartesianGrid stroke={GRID_COLOR} horizontal={false} strokeDasharray="3 4" />
            <XAxis type="number" tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={(v: number) => compactNumber(v)} />
            <YAxis
              type="category"
              dataKey="__name"
              width={92}
              tick={{ ...AXIS_TICK, fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<DashTooltip />} cursor={{ fill: "var(--hover)" }} />
            <Bar
              dataKey="__value"
              name={metric || "指标值"}
              radius={allNegative ? [6, 0, 0, 6] : [0, 6, 6, 0]}
              barSize={13}
              isAnimationActive={false}
              cursor={drillable ? "pointer" : "default"}
              onClick={(entry: { __name?: string }) => {
                if (!drillable) return;
                const name = entry?.__name;
                if (name !== undefined) onDrill?.(widget, String(name));
              }}
            >
              {items.map((item, i) => (
                <Cell
                  key={item.__name}
                  fill={item.__value < 0 ? CHART_PALETTE[3] : CHART_PALETTE[i % CHART_PALETTE.length]}
                />
              ))}
              <LabelList
                dataKey="__value"
                position={allNegative ? "left" : "right"}
                fontSize={10}
                fill={MUTED_TEXT}
                formatter={(label: unknown) => fmt(label)}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {drillable && <div className="pt-1 text-[10px]" style={{ color: MUTED_TEXT }}>点击条目可下钻</div>}
    </div>
  );
}

/** 帕累托：柱 + 累计占比线（双轴） */
function ParetoChart({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  if (!rows.length) return <Empty />;
  const vi = columns.indexOf("指标值");
  const ci = columns.indexOf("累计占比%");
  if (vi < 0) return <DataTable columns={columns} rows={rows} />;

  const data = rows.slice(0, 15).map((row) => ({
    __name: String(row[0] ?? ""),
    __value: num(row[vi]),
    __pct: ci >= 0 ? num(row[ci]) : null,
  }));

  return (
    <div style={{ height: 210 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -8 }}>
          <CartesianGrid stroke={GRID_COLOR} vertical={false} strokeDasharray="3 4" />
          <XAxis dataKey="__name" tick={{ ...AXIS_TICK, fontSize: 9 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
          <YAxis yAxisId="v" tick={AXIS_TICK} tickLine={false} axisLine={false} width={46} tickFormatter={(v: number) => compactNumber(v)} />
          <YAxis
            yAxisId="pct"
            orientation="right"
            domain={[0, 100]}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={34}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip content={<DashTooltip />} cursor={{ fill: "var(--hover)" }} />
          <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11 }} />
          <Bar yAxisId="v" dataKey="__value" name="指标值" fill={CHART_PALETTE[0]} radius={[4, 4, 0, 0]} barSize={16} isAnimationActive={false} />
          {ci >= 0 && (
            <Line
              yAxisId="pct"
              type="monotone"
              dataKey="__pct"
              name="累计占比%"
              stroke={CHART_PALETTE[2]}
              strokeWidth={2}
              dot={{ r: 2.5, strokeWidth: 0, fill: CHART_PALETTE[2] }}
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** 散点：按 cluster 着色 + 相关系数标注 */
function ScatterChart({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  const xi = columns.indexOf(String(widget.options?.x || columns[1] || ""));
  const yi = columns.indexOf(String(widget.options?.y || columns[2] || ""));
  if (xi < 0 || yi < 0 || !rows.length) return <DataTable columns={columns} rows={rows} />;

  const clusterIndex = columns.indexOf("cluster");
  const points = rows.map((row) => ({
    __name: String(row[0] ?? ""),
    __x: num(row[xi]),
    __y: num(row[yi]),
    __cluster: clusterIndex >= 0 ? num(row[clusterIndex]) : 0,
  }));
  const correlation = widget.options?.correlation;

  return (
    <div className="relative" style={{ height: 206 }}>
      <ResponsiveContainer width="100%" height="100%">
        <RScatterChart margin={{ top: 10, right: 12, bottom: 4, left: -6 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 4" />
          <XAxis
            type="number"
            dataKey="__x"
            name={columns[xi]}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => compactNumber(v)}
          />
          <YAxis
            type="number"
            dataKey="__y"
            name={columns[yi]}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={46}
            tickFormatter={(v: number) => compactNumber(v)}
          />
          <Tooltip content={<DashTooltip />} cursor={{ strokeDasharray: "3 4", stroke: "var(--border)" }} />
          <Scatter data={points} name={`${columns[yi]} / ${columns[xi]}`} isAnimationActive={false}>
            {points.map((point, i) => (
              <Cell
                key={`${point.__name}-${i}`}
                fill={clusterIndex >= 0 ? CHART_PALETTE[point.__cluster % CHART_PALETTE.length] : CHART_PALETTE[0]}
                fillOpacity={0.72}
              />
            ))}
          </Scatter>
        </RScatterChart>
      </ResponsiveContainer>
      {typeof correlation === "number" && (
        <span
          className="absolute right-2 top-0 rounded-md px-1.5 py-0.5 text-[10px]"
          style={{ background: "var(--surface-elevated)", color: CHART_PALETTE[2] }}
        >
          r = {correlation.toFixed(3)}
        </span>
      )}
    </div>
  );
}

/** 热力网格：周×维度，色深表示占比 */
function Heatmap({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  if (!rows.length) return <Empty />;
  const pctCols = columns.map((c, i) => ({ c, i })).filter(({ c }) => c.startsWith("第"));
  return (
    <div className="dash-scroll max-h-80 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0" style={{ background: "var(--surface-elevated)" }}>
          <tr>
            {columns.map((c, i) => (
              <th
                key={i}
                className="whitespace-nowrap border-b px-2 py-1.5 text-left font-medium"
                style={{ borderColor: "var(--border)", color: MUTED_TEXT }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="transition-colors hover:bg-[var(--hover)]">
              {row.map((cell, j) => {
                const isPct = pctCols.some((x) => x.i === j);
                const value = isNum(cell) ? num(cell) : null;
                const alpha = isPct && value !== null ? Math.min(Math.max(value / 100, 0), 1) : 0;
                return (
                  <td
                    key={j}
                    title={isPct && value !== null ? `${value.toFixed(1)}%` : undefined}
                    className="whitespace-nowrap border-b px-2 py-1.5 tabular-nums"
                    style={{
                      borderColor: "var(--border)",
                      color: SURFACE_TEXT,
                      background: isPct ? `rgba(59, 130, 246, ${alpha * 0.34})` : undefined,
                    }}
                  >
                    {isPct ? (value === null ? "-" : `${value.toFixed(1)}%`) : fmt(cell)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 漏斗：阶段条 + 转化率 */
function FunnelBars({ widget }: { widget: Widget }) {
  const rows = widget.data?.rows || [];
  if (!rows.length) return <Empty />;
  const first = num(rows[0][1]) || 1;
  return (
    <div className="space-y-2">
      {rows.map((row, i) => {
        const width = (num(row[1]) / first) * 100;
        return (
          <div key={i} className="text-xs">
            <div className="mb-0.5 flex justify-between" style={{ color: MUTED_TEXT }}>
              <span>{String(row[0])}</span>
              <span className="tabular-nums" style={{ color: SURFACE_TEXT }}>
                {fmt(row[1])} · {fmt(row[2])}%
              </span>
            </div>
            <div className="h-4 overflow-hidden rounded-md" style={{ background: "var(--hover)" }}>
              <div
                className="h-4 rounded-md transition-[width] duration-300"
                style={{
                  width: `${Math.max(width, 1)}%`,
                  background: `linear-gradient(90deg, ${CHART_PALETTE[i % CHART_PALETTE.length]}d9, ${CHART_PALETTE[i % CHART_PALETTE.length]}8c)`,
                }}
                title={`${String(row[0])}：${fmt(row[1])}（${fmt(row[2])}%）`}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 异常检测：条形 + Z 值徽标 */
function AnomalyScatter({ widget }: { widget: Widget }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  const vi = columns.indexOf("指标值");
  const zi = columns.indexOf("Z值");
  if (vi < 0 || !rows.length) return <DataTable columns={columns} rows={rows} />;
  const peak = Math.max(...rows.map((row) => Math.abs(num(row[vi]))), 1);
  return (
    <div className="space-y-1.5">
      {rows.slice(0, 15).map((row, i) => (
        <div key={i} className="flex items-center gap-2 text-xs" title={`${String(row[0] ?? "")}：${fmt(row[vi])}`}>
          <span className="w-24 shrink-0 truncate" style={{ color: MUTED_TEXT }}>{String(row[0] ?? "")}</span>
          <div className="h-2 flex-1 rounded-full" style={{ background: "var(--hover)" }}>
            <div
              className="h-2 rounded-full transition-[width] duration-300"
              style={{
                width: `${Math.max((Math.abs(num(row[vi])) / peak) * 100, 1)}%`,
                background: CHART_PALETTE[3],
              }}
            />
          </div>
          <span className="w-20 shrink-0 text-right tabular-nums" style={{ color: SURFACE_TEXT }}>{fmt(row[vi])}</span>
          <span
            className="w-16 shrink-0 rounded-md px-1 py-0.5 text-right tabular-nums"
            style={{ color: CHART_PALETTE[3], background: "rgba(239,68,68,0.10)" }}
          >
            {zi >= 0 ? `Z ${num(row[zi]).toFixed(2)}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

const KPI_MONEY_HINTS = ["额", "价", "成本", "销售额", "毛利"];

/** KPI 展示：按标题/列名推断金额与百分比，避免丢单位 */
function kpiDisplay(widget: Widget): { text: string; money: boolean } {
  const title = widget.title || "";
  const columns = widget.columns || [];
  const value = widget.options?.value;
  const percent =
    /率$/.test(title) ||
    title.includes("%") ||
    columns.includes(`${title}%`);
  if (percent) return { text: `${fmt(value, 2)}%`, money: false };
  const money = KPI_MONEY_HINTS.some((hint) => title.includes(hint));
  return { text: fmt(value, money ? 2 : 1), money };
}

function KpiCard({ widget }: { widget: Widget }) {
  const display = kpiDisplay(widget);
  const extraUnit = widget.options?.unit ? String(widget.options.unit) : "";
  return (
    <div className="flex h-full flex-col justify-center">
      <div className="truncate text-[11px] font-medium" style={{ color: MUTED_TEXT }}>{widget.title}</div>
      <div className="mt-1 flex items-baseline gap-1">
        {display.money && (
          <span className="text-base font-medium" style={{ color: MUTED_TEXT }}>¥</span>
        )}
        <span className="text-[1.7rem] font-semibold leading-none tracking-tight tabular-nums" style={{ color: SURFACE_TEXT }}>
          {display.text}
        </span>
        {extraUnit && <span className="text-xs font-medium" style={{ color: MUTED_TEXT }}>{extraUnit}</span>}
      </div>
    </div>
  );
}

function WidgetBody({ widget, onDrill }: { widget: Widget; onDrill?: (w: Widget, value: string) => void }) {
  const columns = widget.columns || [];
  const rows = widget.data?.rows || [];
  switch (widget.widget_type) {
    case "kpi_card":
      return <KpiCard widget={widget} />;
    case "trend_line":
      return <TrendLine widget={widget} />;
    case "share_pie":
      return <SharePie widget={widget} />;
    case "rank_bar":
      return <RankBar widget={widget} onDrill={onDrill} />;
    case "pareto_bar":
      return <ParetoChart widget={widget} />;
    case "forecast_line":
      return <ForecastChart widget={widget} />;
    case "scatter":
      return <ScatterChart widget={widget} />;
    case "heatmap":
    case "cohort_grid":
      return <Heatmap widget={widget} />;
    case "funnel_bar":
    case "funnel":
      return <FunnelBars widget={widget} />;
    case "anomaly_scatter":
      return <AnomalyScatter widget={widget} />;
    default:
      return <DataTable columns={columns} rows={rows} />;
  }
}

export function WidgetCard({
  widget,
  onDrill,
  toolbar,
  style,
  loading = false,
}: {
  widget: Widget;
  onDrill?: (widget: Widget, value: string) => void;
  toolbar?: ReactNode;
  style?: CSSProperties;
  loading?: boolean;
}) {
  const isKpi = widget.widget_type === "kpi_card";
  const rows = widget.data?.rows || [];
  const columns = widget.columns || [];
  return (
    <div
      style={{ ...style, "--kpi-accent": accentOf(widget.title || widget.id) } as CSSProperties}
      className={`dash-card group ${isKpi ? "dash-kpi" : ""}`}
    >
      {(!isKpi || toolbar) && (
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="truncate text-[12px] font-semibold" style={{ color: SURFACE_TEXT }}>
            {isKpi ? "" : widget.title}
          </div>
          <div className="flex shrink-0 items-center gap-1 opacity-50 transition-opacity group-hover:opacity-100">
            {!isKpi && (
              <button
                type="button"
                onClick={() => downloadCsv(widget.title || widget.id, columns, rows)}
                className="rounded-md p-1 transition-colors hover:bg-[var(--hover)]"
                style={{ color: MUTED_TEXT }}
                title="导出 CSV"
              >
                <Download className="h-3 w-3" />
              </button>
            )}
            {toolbar}
          </div>
        </div>
      )}
      {loading ? <Skeleton type={widget.widget_type} /> : <WidgetBody widget={widget} onDrill={onDrill} />}
    </div>
  );
}

type ViewportMode = "xl" | "md" | "sm";

function useViewportMode(): ViewportMode {
  const [mode, setMode] = useState<ViewportMode>("xl");
  useEffect(() => {
    const compute = () => {
      const width = window.innerWidth;
      setMode(width >= 1280 ? "xl" : width >= 768 ? "md" : "sm");
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, []);
  return mode;
}

export function WidgetRenderer({
  widgets,
  onDrill,
  loading = false,
}: {
  widgets: Widget[];
  onDrill?: (widget: Widget, value: string) => void;
  loading?: boolean;
}) {
  const mode = useViewportMode();

  const cards = useMemo(
    () =>
      widgets.map((widget) => {
        const layout = widget.layout || {};
        const span12 = Math.min(Math.max(layout.w || 4, 1), 12);
        const span8 = span12 >= 9 ? 8 : 4;
        const style: CSSProperties =
          mode === "xl"
            ? {
                gridColumn: `${(layout.x || 0) + 1} / span ${span12}`,
                gridRow: `${(layout.y || 0) + 1} / span ${Math.max(layout.h || 4, 1)}`,
              }
            : mode === "md"
              ? { gridColumn: `span ${span8}` }
              : { gridColumn: "span 1" };
        return (
          <WidgetCard
            key={widget.id}
            widget={widget}
            onDrill={onDrill}
            style={style}
            loading={loading}
          />
        );
      }),
    [widgets, onDrill, mode, loading],
  );

  const gridClass =
    mode === "sm"
      ? "grid grid-cols-1 gap-3"
      : mode === "md"
        ? "grid grid-cols-8 gap-3"
        : "grid grid-cols-12 gap-3";

  return <div className={gridClass}>{cards}</div>;
}
