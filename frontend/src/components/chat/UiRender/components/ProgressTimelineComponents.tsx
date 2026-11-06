"use client";

import type { UiNode, ProgressProps, TimelineProps, UiTone } from "../types";

const TONE_BAR: Record<string, string> = {
  default: "bg-slate-400",
  muted: "bg-slate-500",
  info: "bg-sky-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-rose-500",
};

const TONE_DOT: Record<string, string> = {
  default: "bg-slate-400",
  muted: "bg-slate-500",
  info: "bg-sky-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-rose-500",
};

export function ProgressComponent({ node }: { node: UiNode }) {
  const p = (node.props || {}) as unknown as ProgressProps;
  const max = Number(p.max) > 0 ? Number(p.max) : 100;
  const value = Number(p.value) || 0;
  const pct = Math.max(0, Math.min((value / max) * 100, 100));
  const tone = (p.tone || "info") as UiTone;
  const barCls = TONE_BAR[tone] || TONE_BAR.info;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
        <span>{p.label || ""}</span>
        <span className="tabular-nums text-slate-700">
          {value}
          {max === 100 ? "%" : ` / ${max}`}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full transition-all ${barCls}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function TimelineComponent({ node }: { node: UiNode }) {
  const p = (node.props || {}) as unknown as TimelineProps;
  const items = Array.isArray(p.items) ? p.items : [];

  if (!items.length) {
    return <div className="text-xs text-slate-400">时间轴暂无内容</div>;
  }

  return (
    <div className="relative pl-5">
      <div className="absolute left-1.5 top-1 h-[calc(100%-8px)] w-px bg-slate-200" />
      <ul className="space-y-3">
        {items.map((item, i) => {
          const dotCls = TONE_DOT[(item.tone || "default") as UiTone] || TONE_DOT.default;
          return (
            <li key={i} className="relative">
              <span className={`absolute -left-[18px] top-1.5 h-2.5 w-2.5 rounded-full ${dotCls}`} />
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium text-slate-800">{item.title}</span>
                {item.time && <span className="text-xs text-slate-400">{item.time}</span>}
              </div>
              {item.text && <div className="mt-0.5 text-xs leading-relaxed text-slate-500">{item.text}</div>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
