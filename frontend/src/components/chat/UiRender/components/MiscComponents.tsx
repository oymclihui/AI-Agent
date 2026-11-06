"use client";

import type { UiNode, StatProps } from "../types";

export function StatComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as unknown as StatProps;
  const trendColor = props.trend === "up" ? "text-emerald-600" : props.trend === "down" ? "text-rose-600" : "text-slate-500";
  const trendIcon = props.trend === "up" ? "▲" : props.trend === "down" ? "▼" : "—";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium text-slate-500">{props.label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-2xl font-bold text-slate-900 tabular-nums">
          {typeof props.value === "number" ? props.value.toLocaleString() : props.value}
        </span>
        {props.unit && <span className="text-xs text-slate-500">{props.unit}</span>}
      </div>
      {(props.delta || props.trend) && (
        <div className={`mt-1 text-xs ${trendColor}`}>
          {props.trend && <span className="mr-0.5">{trendIcon}</span>}
          {props.delta}
        </div>
      )}
    </div>
  );
}

export function TextComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as { text?: string; tone?: string };
  const toneMap: Record<string, string> = {
    default: "text-slate-800",
    muted: "text-slate-500",
    info: "text-sky-600",
    success: "text-emerald-600",
    warning: "text-amber-600",
    error: "text-rose-600",
  };
  const cls = toneMap[props.tone || "default"] || toneMap.default;
  return <p className={cls}>{props.text}</p>;
}

export function AlertComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as { title?: string; text?: string; tone?: string };
  const toneMap: Record<string, string> = {
    default: "border-slate-200 bg-slate-50 text-slate-800",
    muted: "border-slate-200 bg-white text-slate-500",
    info: "border-sky-200 bg-sky-50 text-sky-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warning: "border-amber-200 bg-amber-50 text-amber-700",
    error: "border-rose-200 bg-rose-50 text-rose-700",
  };
  const cls = toneMap[props.tone || "info"] || toneMap.info;
  return (
    <div className={`rounded-lg border p-3 text-sm ${cls}`}>
      {props.title && <div className="mb-1 font-semibold">{props.title}</div>}
      {props.text && <div>{props.text}</div>}
    </div>
  );
}

export function BadgeComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as { text?: string; tone?: string };
  const toneMap: Record<string, string> = {
    default: "bg-slate-100 text-slate-700",
    muted: "bg-slate-100 text-slate-500",
    info: "bg-sky-100 text-sky-700",
    success: "bg-emerald-100 text-emerald-700",
    warning: "bg-amber-100 text-amber-700",
    error: "bg-rose-100 text-rose-700",
  };
  const cls = toneMap[props.tone || "default"] || toneMap.default;
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{props.text}</span>;
}

export function DividerComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as { text?: string };
  if (props.text) {
    return (
      <div className="my-3 flex items-center gap-3 text-xs text-slate-400">
        <div className="h-px flex-1 bg-slate-200" />
        <span>{props.text}</span>
        <div className="h-px flex-1 bg-slate-200" />
      </div>
    );
  }
  return <div className="my-3 h-px bg-slate-200" />;
}

export function ListComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as { items?: string[]; ordered?: boolean };
  if (props.ordered) {
    return (
      <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-700">
        {props.items?.map((item, i) => <li key={i}>{item}</li>)}
      </ol>
    );
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
      {props.items?.map((item, i) => <li key={i}>{item}</li>)}
    </ul>
  );
}
