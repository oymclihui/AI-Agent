"use client";

import { useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus, Sparkles } from "lucide-react";
import { clsx } from "clsx";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";
import type { QaChartPayload, QaChartYKey, QaKpiPayload } from "@/lib/qaIntentProtocol";

const CHART_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4"];

function formatNum(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function toNumber(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function Sparkline({ values }: { values: number[] }) {
  if (!values.length) return null;
  const max = Math.max(1, ...values.map(Math.abs));
  return (
    <div className="qa-sparkline" aria-hidden>
      {values.map((v, i) => (
        <span
          key={i}
          className="qa-sparkline-bar"
          style={{ height: `${Math.max(8, (Math.abs(v) / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

export function QaKpiCard({ data }: { data: QaKpiPayload }) {
  const trend = data.trend;
  const TrendIcon =
    trend?.direction === "up" ? ArrowUpRight : trend?.direction === "down" ? ArrowDownRight : Minus;
  const trendClass =
    trend?.direction === "up"
      ? "qa-kpi-trend-up"
      : trend?.direction === "down"
        ? "qa-kpi-trend-down"
        : "qa-kpi-trend-flat";

  return (
    <div className="qa-kpi-card">
      <p className="qa-kpi-label">{data.label}</p>
      <p className="qa-kpi-value">
        {data.prefix}
        {typeof data.value === "number" ? formatNum(data.value) : data.value}
        {data.suffix}
      </p>
      {(trend || data.sparkline?.length) && (
        <div className="qa-kpi-footer">
          {trend && (
            <span className={clsx("qa-kpi-trend", trendClass)}>
              <TrendIcon className="h-3.5 w-3.5" />
              {trend.value > 0 ? "+" : ""}
              {trend.value}%
              {trend.label && <span className="qa-kpi-trend-label">{trend.label}</span>}
            </span>
          )}
          {data.sparkline && data.sparkline.length > 0 && <Sparkline values={data.sparkline} />}
        </div>
      )}
    </div>
  );
}

function resolveYKeys(chart: QaChartPayload): QaChartYKey[] {
  if (chart.yKeys?.length) return chart.yKeys;
  const sample = chart.data[0] ?? {};
  const xKey = chart.xKey ?? "date";
  return Object.keys(sample)
    .filter((k) => k !== xKey && typeof sample[k] === "number")
    .map((key) => ({ key, name: key }));
}

export function QaChartBlock({ chart }: { chart: QaChartPayload }) {
  const xKey = chart.xKey ?? "date";
  const yKeys = useMemo(() => resolveYKeys(chart), [chart]);
  const primaryKey = yKeys[0]?.key ?? "value";

  if (chart.type === "pie") {
    const slices = chart.data.map((row, i) => ({
      label: String(row[xKey] ?? row.name ?? `#${i + 1}`),
      value: toNumber(row[primaryKey] ?? row.value),
      color: CHART_COLORS[i % CHART_COLORS.length],
    }));
    const total = slices.reduce((s, x) => s + x.value, 0) || 1;
    let acc = 0;
    const gradient = slices
      .map((s) => {
        const start = (acc / total) * 100;
        acc += s.value;
        return `${s.color} ${start}% ${(acc / total) * 100}%`;
      })
      .join(", ");

    return (
      <div className="qa-chart">
        {chart.title && <p className="qa-chart-title">{chart.title}</p>}
        <div className="qa-chart-pie-row">
          <div className="qa-chart-pie" style={{ background: `conic-gradient(${gradient})` }} />
          <ul className="qa-chart-legend">
            {slices.map((s) => (
              <li key={s.label}>
                <span className="qa-chart-legend-dot" style={{ background: s.color }} />
                <span>{s.label}</span>
                <span className="qa-chart-legend-val">{formatNum(s.value)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  const series = chart.data.map((row) => ({
    label: String(row[xKey] ?? ""),
    values: yKeys.map((yk) => toNumber(row[yk.key])),
  }));
  const max = Math.max(1, ...series.flatMap((s) => s.values));

  return (
    <div className="qa-chart">
      {chart.title && <p className="qa-chart-title">{chart.title}</p>}
      {yKeys.length > 1 && (
        <div className="qa-chart-legend-inline">
          {yKeys.map((yk, i) => (
            <span key={yk.key}>
              <span
                className="qa-chart-legend-dot"
                style={{ background: yk.color ?? CHART_COLORS[i % CHART_COLORS.length] }}
              />
              {yk.name ?? yk.key}
            </span>
          ))}
        </div>
      )}
      <div className={clsx("qa-chart-bars", chart.type === "line" || chart.type === "area" ? "qa-chart-line-mode" : "")}>
        {series.map((s) => (
          <div key={s.label} className="qa-chart-col" title={s.label}>
            <div className="qa-chart-col-inner">
              {chart.type === "line" || chart.type === "area" ? (
                yKeys.map((yk, yi) => {
                  const v = s.values[yi];
                  return (
                    <div
                      key={yk.key}
                      className={clsx("qa-chart-line-dot", chart.type === "area" && "qa-chart-area-dot")}
                      style={{
                        bottom: `${(v / max) * 100}%`,
                        background: yk.color ?? CHART_COLORS[yi % CHART_COLORS.length],
                      }}
                    />
                  );
                })
              ) : (
                yKeys.map((yk, yi) => {
                  const v = s.values[yi];
                  const color = yk.color ?? CHART_COLORS[yi % CHART_COLORS.length];
                  return (
                    <div
                      key={yk.key}
                      className={clsx("qa-chart-bar", chart.type === "stacked_bar" && "qa-chart-bar-stacked")}
                      style={{
                        height: `${(v / max) * 100}%`,
                        background: color,
                        opacity: chart.type === "stacked_bar" ? 1 - yi * 0.08 : 1,
                      }}
                    />
                  );
                })
              )}
            </div>
            <span className="qa-chart-x">{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

interface QaChoicesProps {
  options: string[];
  multiple?: boolean;
  variant: "choices" | "actions";
  lang: Lang;
  onSelect: (text: string) => void;
  disabled?: boolean;
}

export function QaChoicesRow({ options, multiple, variant, lang, onSelect, disabled }: QaChoicesProps) {
  const t = translations.chat;
  const [picked, setPicked] = useState<string[]>([]);

  const toggle = (opt: string) => {
    if (!multiple) {
      onSelect(opt);
      return;
    }
    setPicked((prev) => (prev.includes(opt) ? prev.filter((x) => x !== opt) : [...prev, opt]));
  };

  return (
    <div className="qa-choices">
      <p className="qa-choices-label">
        {variant === "actions" ? t.qaActions[lang] : t.qaFollowUp[lang]}
      </p>
      <div className="qa-choices-row">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            disabled={disabled}
            onClick={() => toggle(opt)}
            className={clsx(
              "qa-choice-btn",
              variant === "actions" && "qa-choice-btn-action",
              multiple && picked.includes(opt) && "qa-choice-btn-active",
            )}
          >
            {opt}
          </button>
        ))}
      </div>
      {multiple && picked.length > 0 && (
        <button
          type="button"
          disabled={disabled}
          className="qa-choice-confirm"
          onClick={() => onSelect(picked.join("、"))}
        >
          {t.qaConfirmSelection[lang]} ({picked.length})
        </button>
      )}
    </div>
  );
}

export function QaSwitchBadge({
  persona,
  lang,
  onSelect,
  disabled,
}: {
  persona: string;
  lang: Lang;
  onSelect: (text: string) => void;
  disabled?: boolean;
}) {
  const t = translations.chat;
  return (
    <button
      type="button"
      disabled={disabled}
      className="qa-switch-badge"
      onClick={() => onSelect(lang === "zh" ? `请切换到「${persona}」角色继续分析` : `Switch to persona「${persona}」`)}
    >
      <Sparkles className="h-3.5 w-3.5" />
      {t.qaSwitchPersona[lang]}：{persona}
    </button>
  );
}
