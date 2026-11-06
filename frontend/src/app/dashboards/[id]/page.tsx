"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  Filter,
  LayoutDashboard,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { analysisApi, dsDashboardApi, formatApiError } from "@/lib/api";
import { getAuthToken } from "@/lib/authStore";
import { WidgetRenderer, type Widget } from "@/components/WidgetRenderer";

interface DimensionDef {
  field: string;
  label: string;
  type: string;
  level: number;
}

interface ManifestResp {
  dashboard_id: string;
  artifact_id: string;
  data_source_id: string;
  template: string;
  widgets: Widget[];
  filters: DimensionDef[];
  metric_expressions: Record<string, string>;
  issues: string[];
}

interface ActiveFilters {
  cat: string;
  cat2: string;
  start: string;
  end: string;
}

const EMPTY: ActiveFilters = { cat: "", cat2: "", start: "", end: "" };

const FIELD_LABELS: Record<string, string> = {
  FL1MC: "一级品类",
  FL2MC: "二级品类",
  FL3MC: "三级品类",
  FL4MC: "四级品类",
  SPMC: "商品",
  GHDWMC: "供货单位",
  FDMC: "分店",
  RQ: "日期",
  m0: "指标值",
};

function displayColumns(columns: string[], metricName?: string): string[] {
  return columns.map((c) => (c === "m0" && metricName ? metricName : FIELD_LABELS[c] || c));
}

function isDateLike(value: unknown): boolean {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value);
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function downloadCsv(name: string, columns: string[], rows: unknown[][]) {
  const esc = (cell: unknown) => `"${String(cell ?? "").replace(/"/g, '""')}"`;
  const text = [columns.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
  const blob = new Blob(["\uFEFF" + text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DashboardWidgetPage() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const [data, setData] = useState<ManifestResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<ActiveFilters>(EMPTY);
  const [values, setValues] = useState<{ cat: string[]; cat2: string[] }>({ cat: [], cat2: [] });
  const [requery, setRequery] = useState<Record<string, Widget>>({});
  const [applying, setApplying] = useState(false);
  const [drill, setDrill] = useState<{ widget: Widget; value: string } | null>(null);
  const [drillResult, setDrillResult] = useState<{ columns: string[]; rows: unknown[][]; facts: { text: string }[] } | null>(null);
  const [drillError, setDrillError] = useState<string | null>(null);
  const [drillLoading, setDrillLoading] = useState(false);
  const initialized = useRef(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const { data: resp } = await dsDashboardApi.manifest(id);
      setData(resp as ManifestResp);
    } catch (e) {
      setError(formatApiError(e, "看板加载失败"));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // URL 状态：进入时读取，变更时写回（不触发重新请求）
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const q = new URLSearchParams(window.location.search);
    setFilters({
      cat: q.get("cat") || "",
      cat2: q.get("cat2") || "",
      start: q.get("start") || "",
      end: q.get("end") || "",
    });
  }, []);

  const syncUrl = useCallback((next: ActiveFilters) => {
    const q = new URLSearchParams();
    if (next.cat) q.set("cat", next.cat);
    if (next.cat2) q.set("cat2", next.cat2);
    if (next.start) q.set("start", next.start);
    if (next.end) q.set("end", next.end);
    const qs = q.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, []);

  const update = (patch: Partial<ActiveFilters>) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    syncUrl(next);
  };

  // 筛选器取值（后端只读接口；失败时回退到快照维度值）
  useEffect(() => {
    if (!data) return;
    let alive = true;
    (async () => {
      try {
        const [c1, c2] = await Promise.all([
          analysisApi.dimensionValues(data.data_source_id, "FL1MC"),
          analysisApi.dimensionValues(data.data_source_id, "FL2MC"),
        ]);
        if (!alive) return;
        setValues({
          cat: ((c1.data as { values?: string[] })?.values || []).filter(Boolean),
          cat2: ((c2.data as { values?: string[] })?.values || []).filter(Boolean),
        });
      } catch {
        if (!alive) return;
        const pies = data.widgets.find((w) => w.widget_type === "share_pie");
        setValues({
          cat: ((pies?.data?.rows || []).map((r) => String(r[0])) || []).filter(Boolean),
          cat2: [],
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, [data]);

  const active = Boolean(filters.cat || filters.cat2 || filters.start || filters.end);

  // 筛选后重新执行核心查询（数字全部来自数据库，不在前端推算）
  useEffect(() => {
    if (!data || !active) {
      setRequery({});
      return;
    }
    let alive = true;
    setApplying(true);
    const ds = data.data_source_id;
    const exprs = data.metric_expressions || {};
    const metric = (name: string, alias: string) => ({
      name,
      expr: exprs[name] || "",
      alias,
    });
    const filtersPayload: { field: string; op: string; value: string }[] = [];
    if (filters.cat) filtersPayload.push({ field: "FL1MC", op: "eq", value: filters.cat });
    if (filters.cat2) filtersPayload.push({ field: "FL2MC", op: "eq", value: filters.cat2 });
    const timeRange =
      filters.start || filters.end
        ? { field: "RQ", granularity: "day", start: filters.start || undefined, end: filters.end || undefined }
        : undefined;
    const base = { data_source_id: ds, filters: filtersPayload, time_range: timeRange };
    const dateActive = Boolean(filters.start || filters.end);

    const assign = (target: string, patch: Partial<Widget>) => {
      const w = data.widgets.find((x) => x.id === target);
      if (!w || !alive) return;
      setRequery((prev) => ({ ...prev, [target]: { ...w, ...patch } }));
    };

    (async () => {
      try {
        const calls: Promise<void>[] = [];
        // KPI：聚合口径（品类 + 日期）
        calls.push(
          (async () => {
            const { data: r } = await analysisApi.run({
              ...base,
              type: "aggregate",
              metrics: [
                metric("销售额", "m0"),
                metric("毛利", "m1"),
                metric("销量", "m2"),
              ],
              limit: 1,
            });
            if (!alive || !r?.rows?.length) return;
            const row = r.rows[0];
            const sales = num(row[0]);
            const gross = num(row[1]);
            const qty = num(row[2]);
            const kpis: Record<string, number> = {
              销售额: sales,
              毛利: gross,
              毛利率: sales ? (gross / sales) * 100 : 0,
              销量: qty,
            };
            data.widgets
              .filter((w) => w.widget_type === "kpi_card")
              .forEach((w) => {
                if (kpis[w.title] !== undefined) {
                  assign(w.id, { options: { ...w.options, value: kpis[w.title] } });
                }
              });
          })(),
        );
        // 日趋势（销售额 / 毛利）
        calls.push(
          (async () => {
            const { data: r } = await analysisApi.run({
              ...base,
              type: "timeseries",
              metrics: [metric("销售额", "m0"), metric("毛利", "m1")],
              time_range: {
                field: "RQ",
                granularity: "day",
                start: filters.start || undefined,
                end: filters.end || undefined,
              },
              limit: 400,
            });
            if (!alive || !r?.rows?.length) return;
            const rows = r.rows.map((row: unknown[]) => [row[0], row[1], row[2]]);
            assign("w_4", { columns: ["RQ", "销售额", "毛利"], data: { columns: ["RQ", "销售额", "毛利"], rows } });
          })(),
        );
        // 一级品类分布（日期或二级品类筛选时需要服务端重算）
        if (dateActive || filters.cat2) {
          calls.push(
            (async () => {
              const { data: r } = await analysisApi.run({
                ...base,
                type: "distribution",
                dimensions: ["FL1MC"],
                metrics: [metric("销售额", "m0"), metric("毛利", "m1")],
                limit: 50,
              });
              if (!alive || !r?.rows?.length) return;
              const rows = r.rows.map((row: unknown[]) => [row[0], row[1], row[2]]);
              const columns = ["一级品类", "销售额", "毛利"];
              assign("w_5", { columns, data: { columns, rows } });
              assign("w_6", { columns, data: { columns, rows } });
            })(),
          );
          calls.push(
            (async () => {
              const { data: r } = await analysisApi.run({
                ...base,
                type: "topn",
                dimensions: ["FL1MC", "FL2MC"],
                metrics: [metric("销售额", "m0")],
                limit: 12,
              });
              if (!alive || !r?.rows?.length) return;
              const rows = r.rows.map((row: unknown[]) => [row[0], row[1], row[2]]);
              const columns = ["一级品类", "二级品类", "销售额"];
              assign("w_7", { columns, data: { columns, rows } });
            })(),
          );
          calls.push(
            (async () => {
              const { data: r } = await analysisApi.run({
                ...base,
                type: "topn",
                dimensions: ["SPMC"],
                metrics: [metric("销售额", "m0")],
                limit: 10,
              });
              if (!alive || !r?.rows?.length) return;
              const rows = r.rows.map((row: unknown[]) => [row[0], row[1]]);
              const columns = ["商品", "销售额"];
              assign("w_8", { columns, data: { columns, rows } });
            })(),
          );
        }
        calls.push(
          (async () => {
            const { data: r } = await analysisApi.run({
              ...base,
              type: "topn",
              dimensions: ["GHDWMC"],
              metrics: [metric("销售额", "m0")],
              limit: 8,
            });
            if (!alive || !r?.rows?.length) return;
            const rows = r.rows.map((row: unknown[]) => [row[0], row[1]]);
            const columns = ["供货单位", "销售额"];
            assign("w_14", { columns, data: { columns, rows } });
          })(),
        );
        await Promise.all(calls);
      } finally {
        if (alive) setApplying(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, [data, active, filters.cat, filters.cat2, filters.start, filters.end]);

  // 组合：服务端重算结果优先，其余按品类/日期在快照行内过滤
  const viewWidgets = useMemo(() => {
    if (!data) return [];
    const dateActive = Boolean(filters.start || filters.end);
    const hidden = new Set<string>();
    if (dateActive) {
      ["w_9", "w_11", "w_12", "w_13", "w_15"].forEach((w) => hidden.add(w));
    }
    if (filters.cat || filters.cat2) hidden.add("w_10");
    if (filters.cat2 && !filters.cat) {
      ["w_9", "w_11", "w_12"].forEach((w) => hidden.add(w));
    }
    if (active) hidden.add("w_15");
    return data.widgets
      .filter((w) => !hidden.has(w.id))
      .map((w) => {
        if (requery[w.id]) return requery[w.id];
        const rows = w.data?.rows || [];
        const columns = w.columns || [];
        const di = columns.indexOf("一级品类");
        const di2 = columns.indexOf("二级品类");
        let next = rows;
        if (filters.cat && di >= 0) next = next.filter((r) => String(r[di]) === filters.cat);
        if (filters.cat2 && di2 >= 0) next = next.filter((r) => String(r[di2]) === filters.cat2);
        if (dateActive && rows.length && isDateLike(rows[0][0])) {
          next = next.filter((r) => {
            const d = String(r[0]);
            if (filters.start && d < filters.start) return false;
            if (filters.end && d > filters.end) return false;
            return true;
          });
        }
        if (next === rows) return w;
        return { ...w, data: { columns, rows: next } };
      });
  }, [data, requery, filters]);

  const openRaw = () => {
    if (!data) return;
    const token = getAuthToken();
    const base = `/api/v1/dashboards/${data.artifact_id}/view`;
    window.open(token ? `${base}?token=${encodeURIComponent(token)}` : base, "_blank", "noopener");
  };

  const runDrill = useCallback(
    async (widget: Widget, value: string) => {
      if (!data || !widget.drill) return;
      setDrill({ widget, value });
      setDrillResult(null);
      setDrillError(null);
      setDrillLoading(true);
      try {
        const drillFilters = [{ field: widget.drill.field, op: "eq", value }];
        if (filters.cat && widget.drill.field !== "FL1MC") {
          drillFilters.push({ field: "FL1MC", op: "eq", value: filters.cat });
        }
        if (filters.cat2 && widget.drill.field !== "FL2MC") {
          drillFilters.push({ field: "FL2MC", op: "eq", value: filters.cat2 });
        }
        const { data: resp } = await analysisApi.run({
          type: "topn",
          data_source_id: data.data_source_id,
          dimensions: widget.drill.detail_dimensions,
          metrics: [{ name: widget.drill.metric_name, expr: widget.drill.metric_expr, alias: "m0" }],
          filters: drillFilters,
          time_range:
            filters.start || filters.end
              ? { field: "RQ", granularity: "day", start: filters.start || undefined, end: filters.end || undefined }
              : undefined,
          limit: 30,
        });
        setDrillResult({
          columns: displayColumns(resp.columns || [], widget.drill.metric_name),
          rows: resp.rows || [],
          facts: resp.facts || [],
        });
      } catch (e) {
        setDrillError(formatApiError(e, "下钻查询失败"));
      } finally {
        setDrillLoading(false);
      }
    },
    [data, filters],
  );

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mx-auto max-w-[1400px] space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Link href="/data-sources" className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs">
              <ArrowLeft className="h-3.5 w-3.5" />
              返回
            </Link>
            <h1 className="inline-flex items-center gap-2 text-base font-semibold" style={{ color: "var(--foreground)" }}>
              <span
                className="inline-flex h-6 w-6 items-center justify-center rounded-lg"
                style={{ background: "linear-gradient(135deg, #3b82f6, #14b8a6)" }}
              >
                <LayoutDashboard className="h-3.5 w-3.5 text-white" />
              </span>
              经营分析看板
              <span className="text-xs font-normal" style={{ color: "var(--muted)" }}>组件视图</span>
            </h1>
            {applying && (
              <span className="inline-flex items-center gap-1 text-xs" style={{ color: "#3b82f6" }}>
                <Loader2 className="h-3 w-3 animate-spin" />
                正在按筛选重算…
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void load()} className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs">
              <RefreshCw className="h-3.5 w-3.5" />
              刷新
            </button>
            <button type="button" onClick={openRaw} disabled={!data} className="btn-primary inline-flex items-center gap-1 px-2 py-1 text-xs">
              <ExternalLink className="h-3.5 w-3.5" />
              原始看板
            </button>
          </div>
        </div>

        {!loading && data && (
          <div className="dash-filter">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold" style={{ color: "var(--foreground)" }}>
              <Filter className="h-3.5 w-3.5" style={{ color: "#3b82f6" }} />
              全局筛选
              {active && (
                <button type="button" onClick={() => update(EMPTY)} className="ml-auto inline-flex items-center gap-1 text-[11px]" style={{ color: "var(--muted)" }}>
                  <X className="h-3 w-3" />
                  重置
                </button>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <label className="text-[11px]" style={{ color: "var(--muted)" }}>
                一级品类
                <select
                  value={filters.cat}
                  onChange={(e) => update({ cat: e.target.value })}
                  className="dash-filter-input"
                >
                  <option value="">全部</option>
                  {values.cat.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label className="text-[11px]" style={{ color: "var(--muted)" }}>
                二级品类
                <select
                  value={filters.cat2}
                  onChange={(e) => update({ cat2: e.target.value })}
                  className="dash-filter-input"
                >
                  <option value="">全部</option>
                  {values.cat2.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label className="text-[11px]" style={{ color: "var(--muted)" }}>
                开始日期
                <input
                  type="date"
                  value={filters.start}
                  onChange={(e) => update({ start: e.target.value })}
                  className="dash-filter-input"
                />
              </label>
              <label className="text-[11px]" style={{ color: "var(--muted)" }}>
                结束日期
                <input
                  type="date"
                  value={filters.end}
                  onChange={(e) => update({ end: e.target.value })}
                  className="dash-filter-input"
                />
              </label>
            </div>
            {active && (
              <div className="mt-2 text-[11px]" style={{ color: "var(--muted)" }}>
                筛选已写入 URL，可直接分享当前视图；日期筛选时隐藏无法按日重算的负毛利/折扣/周几组件。
              </div>
            )}
          </div>
        )}

        {loading && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="dash-card" style={{ minHeight: i % 4 === 0 ? 96 : 196 }}>
                <div className="dash-skel mb-3 h-3 w-1/3" />
                <div className="dash-skel" style={{ height: i % 4 === 0 ? 40 : 132 }} />
              </div>
            ))}
          </div>
        )}

        {!loading && error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>
        )}

        {!loading && !error && data && (
          <>
            <div className="text-xs theme-muted">
              artifact <span className="font-mono">{data.artifact_id}</span> · 模板 {data.template} · {viewWidgets.length} 个组件
              {data.issues.length > 0 && <span className="ml-2 text-amber-600">数据校验提示 {data.issues.length} 条</span>}
            </div>
            <WidgetRenderer widgets={viewWidgets} onDrill={runDrill} />
          </>
        )}
      </div>

      {drill && (
        <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/20" onClick={() => setDrill(null)}>
          <div className="h-full w-full max-w-xl overflow-y-auto bg-white p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-800">{drill.widget.title} · 下钻</div>
                <div className="text-xs text-slate-500">
                  {drill.widget.drill?.label} = {drill.value}
                </div>
              </div>
              <button type="button" onClick={() => setDrill(null)} className="rounded p-1 text-slate-400 hover:bg-slate-100">
                <X className="h-4 w-4" />
              </button>
            </div>
            {drillLoading && (
              <div className="py-8 text-center text-xs text-slate-500">
                <Loader2 className="mr-1 inline-block h-4 w-4 animate-spin" />
                查询明细…
              </div>
            )}
            {drillError && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">{drillError}</div>}
            {drillResult && (
              <>
                <div className="mb-2 flex justify-end">
                  <button
                    type="button"
                    onClick={() => downloadCsv(`下钻_${drill.value}`, drillResult.columns, drillResult.rows)}
                    className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs"
                  >
                    <Download className="h-3.5 w-3.5" />
                    导出 CSV
                  </button>
                </div>
                <div className="overflow-auto">
                  <table className="w-full border-collapse text-xs">
                    <thead className="bg-slate-50">
                      <tr>
                        {drillResult.columns.map((c, i) => (
                          <th key={i} className="whitespace-nowrap border-b px-2 py-1 text-left font-medium text-slate-600">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {drillResult.rows.map((r, i) => (
                        <tr key={i} className="odd:bg-white even:bg-slate-50/60">
                          {r.map((cell, j) => (
                            <td key={j} className="whitespace-nowrap border-b border-slate-100 px-2 py-1">
                              {typeof cell === "number"
                                ? cell.toLocaleString("zh-CN", { maximumFractionDigits: 2 })
                                : String(cell ?? "-")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {drillResult.facts.length > 0 && (
                  <div className="mt-3 space-y-1 rounded bg-slate-50 p-2 text-[11px] text-slate-600">
                    {drillResult.facts.map((f, i) => (
                      <div key={i}>· {f.text}</div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
