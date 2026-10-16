"use client";

import { LayoutDashboard, ExternalLink, ShieldCheck, ShieldAlert } from "lucide-react";
import { getAuthToken } from "@/lib/authStore";
import type { Lang } from "@/lib/i18n";

export interface DashboardCardData {
  event?: string;
  artifact_id: string;
  title: string;
  period?: string;
  kpis?: { label: string; value: string }[];
  anchor_status?: "pass" | "warn" | "fail" | null;
  view_url: string;
  stages?: string[];
}

export default function DashboardCard({ card, lang }: { card: DashboardCardData; lang: Lang }) {
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const anchor = card.anchor_status || "pass";

  const openDashboard = () => {
    const token = getAuthToken();
    const sep = card.view_url.includes("?") ? "&" : "?";
    const url = token ? `${card.view_url}${sep}token=${encodeURIComponent(token)}` : card.view_url;
    window.open(url, "_blank", "noopener");
  };

  return (
    <button
      type="button"
      onClick={openDashboard}
      className="mt-2 block w-full rounded-xl border border-[#2d2d4e] bg-[#14142b] p-3.5 text-left transition hover:border-blue-500/60 hover:bg-[#181834]"
    >
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600/20 text-blue-300">
          <LayoutDashboard className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-slate-100">{card.title}</div>
          {card.period && <div className="mt-0.5 text-[11px] text-slate-400">{card.period}</div>}
        </div>
        {anchor === "pass" ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
            <ShieldCheck className="h-3 w-3" />
            {t("锚点通过", "Anchors pass")}
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
            <ShieldAlert className="h-3 w-3" />
            {t("锚点偏差已披露", "Anchor deviation")}
          </span>
        )}
      </div>
      {card.kpis && card.kpis.length > 0 && (
        <div className="mt-2.5 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {card.kpis.map((k) => (
            <div key={k.label} className="rounded-lg bg-[#1a1a2e] px-2 py-1.5">
              <div className="text-[10px] text-slate-500">{k.label}</div>
              <div className="truncate font-mono text-[12px] font-semibold text-slate-200">{k.value}</div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-2.5 inline-flex items-center gap-1 text-[11px] font-medium text-blue-300">
        <ExternalLink className="h-3 w-3" />
        {t("点击在新窗口打开看板", "Open dashboard in new window")}
      </div>
    </button>
  );
}
