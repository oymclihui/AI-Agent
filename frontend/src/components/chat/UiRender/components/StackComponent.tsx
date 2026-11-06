"use client";
import type { UiNode } from "../types";
export function StackComponent({ node, children }: { node: UiNode; children?: React.ReactNode }) {
  const props = (node.props || {}) as { direction?: "vertical" | "horizontal"; gap?: number };
  const direction = props.direction === "horizontal" ? "flex-row" : "flex-col";
  const gap = props.gap ?? 16;
  return <div className={`flex ${direction}`} style={{ gap: `${gap}px` }}>{children}</div>;
}
export function GridComponent({ node, children }: { node: UiNode; children?: React.ReactNode }) {
  const props = (node.props || {}) as { columns?: number };
  const cols = Math.max(1, Math.min(props.columns ?? 2, 6));
  return <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>{children}</div>;
}
