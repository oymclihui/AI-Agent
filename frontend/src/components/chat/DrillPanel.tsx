"use client";

/* 图表下钻面板（蓝图二期 p2-1/p2-2）：
 * 点击图表数据点 → 下钻明细 + 占比贡献度排名 + 「为什么变化」对比归因。
 * 支持结果图继续点击下钻（面包屑记录路径）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { X, Search } from "lucide-react";
import { ChartRenderer, type ChatChartData } from "@/components/ChartRenderer";
import { getAuthToken } from "@/lib/authStore";

export interface DrillSeed {
  label: string;
  labels: string[];
  seriesLabel: string;
}

interface DrillResult {
  ok: boolean;
  action: "drill" | "why";
  answer: string;
  metric: string;
  dimension?: string;
  time_desc?: string;
  time?: { start?: string | null; end?: string | null; prev_start?: string; prev_end?: string };
  columns: string[];
  rows: unknown[][];
  chart?: ChatChartData | null;
  contribution?: {
    available: boolean;
    metric?: string;
    total?: number;
    top?: { group: string; value: number; pct: number }[];
    others?: { group: string; value: number; pct: number };
  };
  attribution?: { group: string; cur: number; prev: number; delta: number; contrib_pct: number | null }[];
}

const fmt = (v: unknown): string => {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v ?? "-");
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
};

async function callDrill(dataSourceId: string, body: Record<string, unknown>): Promise<DrillResult> {
  const res = await fetch("/api/v1/data-ask/drill", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
    },
    body: JSON.stringify({ data_source_id: dataSourceId, ...body }),
  });
  const text = await res.text();
  let detail: unknown = text;
  try {
    detail = JSON.parse(text);
  } catch {
    /* keep raw */
  }
  if (!res.ok) {
    const msg =
      typeof detail === "object" && detail && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `请求失败（${res.status}）`;
    throw new Error(msg);
  }
  return detail as DrillResult;
}

export function DrillPanel({
  dataSourceId,
  seed,
  onClose,
}: {
  dataSourceId: string;
  seed: DrillSeed;
  onClose: () => void;
}) {
  const [result, setResult] = useState<DrillResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [crumbs, setCrumbs] = useState<string[]>([]);
  const [why, setWhy] = useState<DrillResult | null>(null);
  const [whyLoading, setWhyLoading] = useState(false);
  const topRef = useRef<HTMLDivElement | null>(null);

  const run = useCallback(
    async (s: DrillSeed, crumb: string) => {
      setLoading(true);
      setError("");
      setWhy(null);
      try {
        const r = await callDrill(dataSourceId, {
          clicked_label: s.label,
          labels: s.labels,
          series_label: s.seriesLabel,
        });
        setResult(r);
        setCrumbs((c) => [...c, crumb]);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [dataSourceId],
  );

  useEffect(() => {
    void run(seed, seed.label);
    topRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed.label]);

  const runWhy = async () => {
    if (!result) return;
    setWhyLoading(true);
    try {
      const labels = result.chart?.labels || seed.labels;
      const time =
        result.time?.start && result.time?.end
          ? { start: result.time.start, end: result.time.end }
          : undefined;
      const r = await callDrill(dataSourceId, {
        action: "why",
        labels,
        series_label: result.metric || seed.seriesLabel,
        ...(time ? { time } : {}),
      });
      setWhy(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWhyLoading(false);
    }
  };

  const contrib = result?.contribution;
  const contribRows = contrib?.available
    ? [...(contrib.top || []), ...(contrib.others ? [contrib.others] : [])]
    : [];

  return (
    <div
      ref={topRef}
      className="relative z-20 mt-2 w-full overflow-hidden rounded-xl border border-blue-500/30 bg-[#15153080]"
      style={{ backdropFilter: "blur(4px)" }}
    >
      {/* 头部：标题 + 关闭 */}
      <div className="flex items-center gap-2 border-b border-blue-500/20 px-3 py-2">
        <span className="rounded bg-blue-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-blue-300">
          下钻
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-slate-300">
          {crumbs.length > 0 ? crumbs.map((c) => `「${c}」`).join(" → ") : seed.label}
        </span>
        <button
          onClick={onClose}
          className="rounded p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-200"
          aria-label="关闭下钻面板"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="max-h-[420px] space-y-3 overflow-y-auto p-3">
        {loading && <p className="py-6 text-center text-xs text-slate-400">正在下钻取数…</p>}
        {error && (
          <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</p>
        )}

        {result && !loading && (
          <>
            <p className="text-xs leading-relaxed text-slate-200">{result.answer}</p>

            {result.chart && (
              <ChartRenderer
                chart={result.chart}
                onDrill={(label) => {
                  void run(
                    { label, labels: result.chart?.labels || [], seriesLabel: result.metric || seed.seriesLabel },
                    label,
                  );
                }}
              />
            )}

            {/* 占比贡献度排名（p2-2） */}
            {contribRows.length > 0 && (
              <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2.5">
                <p className="mb-2 text-[11px] font-semibold text-slate-300">
                  贡献度排名 · {contrib?.metric}（共 {fmt(contrib?.total)}）
                </p>
                <div className="space-y-1.5">
                  {contribRows.map((it) => {
                    const max = Math.max(...contribRows.map((r) => Math.abs(r.value)), 1);
                    const w = Math.max(2, (Math.abs(it.value) / max) * 100);
                    const isOthers = it.group === "其它";
                    return (
                      <div key={it.group} className="flex items-center gap-2">
                        <span className="w-16 shrink-0 truncate text-[11px] text-slate-400" title={it.group}>
                          {it.group}
                        </span>
                        <div className="h-3.5 flex-1 overflow-hidden rounded bg-white/5">
                          <div
                            className="h-full rounded"
                            style={{
                              width: `${w}%`,
                              background: isOthers
                                ? "rgba(148,163,184,0.5)"
                                : "linear-gradient(90deg,#3b82f6,#60a5fa)",
                            }}
                          />
                        </div>
                        <span className="w-24 shrink-0 text-right text-[11px] tabular-nums text-slate-300">
                          {fmt(it.value)} · {it.pct.toFixed(1)}%
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 明细表 */}
            {result.rows.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-white/10">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="bg-white/5 text-slate-400">
                      {result.columns.map((c) => (
                        <th key={c} className="whitespace-nowrap px-2 py-1.5 text-left font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.slice(0, 15).map((row, i) => (
                      <tr key={i} className="border-t border-white/5 text-slate-300">
                        {row.map((cell, j) => (
                          <td key={j} className="whitespace-nowrap px-2 py-1 tabular-nums">
                            {typeof cell === "number" ? fmt(cell) : String(cell ?? "-")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 归因按钮 + 结果 */}
            {result.action === "drill" && (
              <div>
                <button
                  onClick={() => void runWhy()}
                  disabled={whyLoading}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[11px] font-medium text-amber-300 transition-colors hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <Search className="h-3.5 w-3.5" />
                  {whyLoading ? "归因分析中…" : "为什么变化？（对比上期）"}
                </button>
              </div>
            )}
            {why && why.action === "why" && (
              <div className="space-y-2 rounded-lg border border-amber-500/25 bg-amber-500/[0.06] p-2.5">
                <p className="text-[11px] font-semibold text-amber-300">对比归因 · {why.answer}</p>
                {why.attribution && why.attribution.length > 0 && (
                  <div className="space-y-1">
                    {why.attribution.slice(0, 8).map((it) => {
                      const maxAbs = Math.max(...why.attribution!.map((x) => Math.abs(x.delta)), 1);
                      const w = Math.max(2, (Math.abs(it.delta) / maxAbs) * 50);
                      const pos = it.delta >= 0;
                      return (
                        <div key={it.group} className="flex items-center gap-2 text-[11px]">
                          <span className="w-16 shrink-0 truncate text-slate-400" title={it.group}>
                            {it.group}
                          </span>
                          <div className="relative h-3 flex-1">
                            <div className="absolute left-1/2 top-0 h-full w-px bg-white/15" />
                            <div
                              className="absolute top-0 h-full rounded"
                              style={{
                                width: `${w}%`,
                                left: pos ? "50%" : `${50 - w}%`,
                                background: pos ? "#34d399" : "#f87171",
                              }}
                            />
                          </div>
                          <span
                            className="w-28 shrink-0 text-right tabular-nums"
                            style={{ color: pos ? "#6ee7b7" : "#fca5a5" }}
                          >
                            {pos ? "+" : ""}
                            {fmt(it.delta)}
                            {it.contrib_pct !== null && `（${it.contrib_pct > 0 ? "+" : ""}${it.contrib_pct.toFixed(0)}%）`}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
