"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus, Sparkles } from "lucide-react";
import { clsx } from "clsx";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";
import type { QaChartPayload, QaKpiPayload } from "@/lib/qaIntentProtocol";

const QaRechartsView = dynamic(
  () => import("@/components/chat/QaRechartsView").then((m) => m.QaRechartsView),
  {
    ssr: false,
    loading: () => <div className="qa-chart qa-chart-loading">图表加载中…</div>,
  },
);


function formatNum(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
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

export function QaChartBlock({ chart }: { chart: QaChartPayload }) {
  return <QaRechartsView chart={chart} />;
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
