"use client";
import type { UiNode } from "../types";
export function CardComponent({ node, children }: { node: UiNode; children?: React.ReactNode }) {
  const props = (node.props || {}) as { title?: string; subtitle?: string; footer?: string };
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {(props.title || props.subtitle) && (
        <div className="mb-3 border-b border-slate-200 pb-2">
          {props.title && <div className="text-sm font-semibold text-slate-900">{props.title}</div>}
          {props.subtitle && <div className="text-xs text-slate-500">{props.subtitle}</div>}
        </div>
      )}
      {children && <div className="space-y-3">{children}</div>}
      {props.footer && <div className="mt-3 border-t border-slate-200 pt-2 text-xs text-slate-500">{props.footer}</div>}
    </div>
  );
}
