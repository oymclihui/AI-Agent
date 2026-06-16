"use client";

import { clsx } from "clsx";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";
import type { GroupMessageMeta } from "@/lib/groupChat";
import { agentColorIndex } from "@/lib/groupChat";
import ChatRichContent from "@/components/ChatRichContent";
import { MessageCopyButton } from "@/components/MessageCopyButton";
import MarkdownView from "@/components/MarkdownView";

const AGENT_BUBBLE_CLASSES = [
  "border-blue-500/40 bg-blue-950/30",
  "border-emerald-500/40 bg-emerald-950/30",
  "border-amber-500/40 bg-amber-950/30",
  "border-violet-500/40 bg-violet-950/30",
  "border-rose-500/40 bg-rose-950/30",
  "border-cyan-500/40 bg-cyan-950/30",
];

interface Props {
  content: string;
  metadata?: GroupMessageMeta & { thinking?: string };
  lang: Lang;
  groupAgentIds?: string[];
  onChoiceSelect?: (text: string) => void;
  choicesDisabled?: boolean;
}

export function GroupChatMessageRow({
  content,
  metadata,
  lang,
  groupAgentIds = [],
  onChoiceSelect,
  choicesDisabled,
}: Props) {
  const t = translations.chat;
  const kind = metadata?.kind;

  if (kind === "round_divider") {
    return (
      <div className="flex items-center gap-3 py-2">
        <div className="h-px flex-1 bg-slate-700/60" />
        <span className="text-[11px] text-slate-500">{metadata?.label || t.groupRoundEnd[lang]}</span>
        <div className="h-px flex-1 bg-slate-700/60" />
      </div>
    );
  }

  if (!content.trim() && kind === "round_divider") return null;

  const isSynth = kind === "synthesis";
  const agentId = metadata?.agent_id || "";
  const bubbleCls = AGENT_BUBBLE_CLASSES[agentColorIndex(agentId, groupAgentIds)] ?? AGENT_BUBBLE_CLASSES[0];

  return (
    <div className="group flex gap-1.5 justify-start">
      <MessageCopyButton text={content} lang={lang} variant="assistant" className="mt-2 self-start" />
      <div className="max-w-2xl flex-1 min-w-0">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-slate-200">
            {metadata?.agent_name || (isSynth ? t.groupConsensus[lang] : t.groupAgent[lang])}
          </span>
          {metadata?.agent_role && (
            <span className="text-[10px] text-slate-500">{metadata.agent_role}</span>
          )}
          {metadata?.round != null && !isSynth && (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
              R{metadata.round}
            </span>
          )}
          {isSynth && (
            <span className="rounded bg-blue-600/25 px-1.5 py-0.5 text-[10px] text-blue-300">
              {t.groupConsensus[lang]}
            </span>
          )}
        </div>
        {metadata?.thinking && (
          <div className="mb-2 rounded-lg border border-violet-500/25 bg-violet-950/30 px-3 py-2 text-xs text-violet-200/85">
            <MarkdownView size="xs">{metadata.thinking}</MarkdownView>
          </div>
        )}
        <div
          className={clsx(
            "rounded-2xl rounded-bl-sm border px-4 py-3 text-sm text-slate-200",
            isSynth ? "border-blue-500/50 bg-blue-950/40" : bubbleCls,
          )}
        >
          <ChatRichContent
            size="sm"
            lang={lang}
            onChoiceSelect={onChoiceSelect}
            choicesDisabled={choicesDisabled}
          >
            {content}
          </ChatRichContent>
        </div>
      </div>
    </div>
  );
}
