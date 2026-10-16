"use client";

import { HelpCircle } from "lucide-react";
import type { ClarifyPayload } from "@/lib/api";

interface ClarifyCardProps {
  payload: ClarifyPayload;
  lang: string;
  disabled?: boolean;
  onSelect?: (option: string) => void;
}

/** 苏格拉底式反问卡片：聊天 clarify 事件与问数澄清 hint 共用 */
export default function ClarifyCard({ payload, lang, disabled, onSelect }: ClarifyCardProps) {
  const zh = lang === "zh";
  const t = {
    title: zh ? "为了更精准地回答，想先和您确认" : "To answer precisely, let me confirm first",
    why: zh ? "为什么要问" : "Why this matters",
    fallback: zh ? "如果不选择" : "If not selected",
    hint: zh ? "可直接点选选项，也可以输入补充说明" : "Tap an option, or type your answer",
    round: zh
      ? `第 ${payload.round}/${payload.max_rounds} 轮`
      : `Round ${payload.round}/${payload.max_rounds}`,
  };

  return (
    <div className="rounded-xl border border-blue-500/30 bg-blue-500/[0.06] px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <HelpCircle className="h-4 w-4 shrink-0 text-blue-400" />
        <span className="text-sm font-medium text-blue-200">{t.title}</span>
        {payload.max_rounds > 1 && (
          <span className="rounded-full border border-blue-500/40 px-2 py-0.5 text-[10px] text-blue-300">
            {t.round}
          </span>
        )}
      </div>
      <div className="space-y-3">
        {payload.questions.map((q, i) => (
          <div key={i}>
            <div className="text-sm text-slate-200">
              <span className="mr-1.5 font-medium text-blue-400">{i + 1}.</span>
              {q.text}
            </div>
            {q.options && q.options.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-2">
                {q.options.map((opt, j) => (
                  <button
                    key={j}
                    type="button"
                    disabled={disabled}
                    onClick={() => onSelect?.(opt)}
                    className="rounded-full border border-blue-500/50 px-3 py-1 text-xs text-blue-300 transition hover:bg-blue-500/15 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
            {q.why && (
              <div className="mt-1 text-xs italic text-slate-500">
                {t.why}：{q.why}
              </div>
            )}
          </div>
        ))}
      </div>
      {payload.fallback && (
        <div className="mt-2.5 border-t border-blue-500/20 pt-2 text-xs text-slate-500">
          {t.fallback}：{payload.fallback}
        </div>
      )}
      {onSelect && <div className="mt-1.5 text-[11px] text-slate-600">{t.hint}</div>}
    </div>
  );
}
