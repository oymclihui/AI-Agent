"use client";

import MarkdownView, { type MarkdownViewSize } from "@/components/MarkdownView";
import {
  QaChartBlock,
  QaChoicesRow,
  QaKpiCard,
  QaSwitchBadge,
} from "@/components/chat/QaIntentBlocks";
import type { Lang } from "@/lib/i18n";
import {
  hasQaIntentBlocks,
  parseQaIntentContent,
  stripIncompleteQaBlocks,
} from "@/lib/qaIntentProtocol";

/** Convert ```chart fenced blocks to [chart:{...}] inline notation. */
function preprocessChartBlocks(content: string): string {
  return content.replace(
    /```chart\s*\n?(\{[\s\S]*?\})\s*```/g,
    "[chart:$1]"
  );
}

interface ChatRichContentProps {
  children: string;
  size?: MarkdownViewSize;
  highlight?: boolean;
  lang: Lang;
  streaming?: boolean;
  onChoiceSelect?: (text: string) => void;
  choicesDisabled?: boolean;
}

export default function ChatRichContent({
  children,
  size = "sm",
  highlight = true,
  lang,
  streaming = false,
  onChoiceSelect,
  choicesDisabled = false,
}: ChatRichContentProps) {
  const raw = streaming ? stripIncompleteQaBlocks(children) : children;
  const processed = preprocessChartBlocks(raw);
  if (!processed?.trim()) return null;

  if (!hasQaIntentBlocks(processed)) {
    return (
      <MarkdownView size={size} highlight={highlight}>
        {processed}
      </MarkdownView>
    );
  }

  const segments = parseQaIntentContent(processed);

  return (
    <div className="chat-rich-content">
      {segments.map((seg, idx) => {
        if (seg.kind === "text") {
          const text = seg.text.trim();
          if (!text) return null;
          return (
            <MarkdownView key={`t-${idx}`} size={size} highlight={highlight}>
              {seg.text}
            </MarkdownView>
          );
        }
        if (seg.kind === "kpi") {
          return (
            <div key={`k-${idx}`} className="qa-kpi-grid">
              <QaKpiCard data={seg.data} />
            </div>
          );
        }
        if (seg.kind === "chart") {
          return <QaChartBlock key={`c-${idx}`} chart={seg.data} />;
        }
        if (seg.kind === "choices" || seg.kind === "actions") {
          return (
            <QaChoicesRow
              key={`ch-${idx}`}
              options={seg.options}
              variant={seg.kind}
              lang={lang}
              onSelect={(text) => onChoiceSelect?.(text)}
              disabled={choicesDisabled || !onChoiceSelect}
            />
          );
        }
        if (seg.kind === "choices-multiple") {
          return (
            <QaChoicesRow
              key={`cm-${idx}`}
              options={seg.options}
              multiple
              variant="choices"
              lang={lang}
              onSelect={(text) => onChoiceSelect?.(text)}
              disabled={choicesDisabled || !onChoiceSelect}
            />
          );
        }
        if (seg.kind === "switch") {
          return (
            <QaSwitchBadge
              key={`sw-${idx}`}
              persona={seg.persona}
              lang={lang}
              onSelect={(text) => onChoiceSelect?.(text)}
              disabled={choicesDisabled || !onChoiceSelect}
            />
          );
        }
        return null;
      })}
    </div>
  );
}
