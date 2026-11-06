"use client";

import type { UiNode, ChoiceProps } from "../types";

export function ChoiceComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as unknown as unknown as ChoiceProps;
  const { question, options = [], recommended } = props;

  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50 p-4">
      <div className="mb-3 text-sm font-semibold text-violet-700">❓ {question}</div>
      <div className="space-y-2">
        {options.map((opt) => (
          <div
            key={opt.id}
            className={`rounded-md border px-3 py-2 text-sm transition-colors ${
              opt.id === recommended
                ? "border-violet-400 bg-violet-100 text-violet-800"
                : "border-slate-200 bg-white text-slate-700 hover:border-violet-300 hover:bg-violet-50"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{opt.label}</span>
              {opt.id === recommended && (
                <span className="rounded bg-violet-500 px-1.5 py-0.5 text-[10px] text-white">推荐</span>
              )}
            </div>
            {opt.description && <div className="mt-0.5 text-xs text-slate-500">{opt.description}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
