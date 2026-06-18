"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { clsx } from "clsx";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";
import type { GroupChatConfig, GroupChatTemplate, GroupOrchestration } from "@/lib/groupChat";
import { buildGroupConfig, resolveTemplateAgents } from "@/lib/groupChat";
import { useIsMobile } from "@/hooks/useMediaQuery";

interface AgentOption {
  id: string;
  name: string;
  role: string;
}

interface Props {
  lang: Lang;
  agents: AgentOption[];
  templates: GroupChatTemplate[];
  chatMode: "single" | "group";
  groupAgentIds: string[];
  orchestration: GroupOrchestration;
  maxRounds: number;
  consensusOnly: boolean;
  disabled?: boolean;
  onChatModeChange: (mode: "single" | "group") => void;
  onGroupAgentIdsChange: (ids: string[]) => void;
  onOrchestrationChange: (v: GroupOrchestration) => void;
  onMaxRoundsChange: (n: number) => void;
  onConsensusOnlyChange: (v: boolean) => void;
  onApplyTemplate: (tpl: GroupChatTemplate, agentIds: string[]) => void;
  onExport?: () => void;
}

function GroupControls({
  lang,
  orchestration,
  maxRounds,
  consensusOnly,
  disabled,
  onOrchestrationChange,
  onMaxRoundsChange,
  onConsensusOnlyChange,
  onExport,
  compact,
}: {
  lang: Lang;
  orchestration: GroupOrchestration;
  maxRounds: number;
  consensusOnly: boolean;
  disabled?: boolean;
  onOrchestrationChange: (v: GroupOrchestration) => void;
  onMaxRoundsChange: (n: number) => void;
  onConsensusOnlyChange: (v: boolean) => void;
  onExport?: () => void;
  compact?: boolean;
}) {
  const t = translations.chat;
  return (
    <>
      <select
        disabled={disabled}
        value={orchestration}
        onChange={(e) => onOrchestrationChange(e.target.value as GroupOrchestration)}
        className="rounded-md border border-[#2d2d4e] bg-[#1a1a2e] px-2 py-1 text-xs text-slate-200"
      >
        <option value="round_robin">{t.groupModeRoundRobin[lang]}</option>
        <option value="hierarchical">{t.groupModeHierarchical[lang]}</option>
        <option value="parallel">{t.groupModeParallel[lang]}</option>
        <option value="debate">{t.groupModeDebate[lang]}</option>
      </select>
      <label className="flex items-center gap-1 text-xs text-slate-400">
        {t.groupMaxRounds[lang]}
        <select
          disabled={disabled}
          value={maxRounds}
          onChange={(e) => onMaxRoundsChange(Number(e.target.value))}
          className="rounded border border-[#2d2d4e] bg-[#1a1a2e] px-1 py-0.5 text-slate-200"
        >
          {[1, 2, 3].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1 text-xs text-slate-400">
        <input
          type="checkbox"
          checked={consensusOnly}
          onChange={(e) => onConsensusOnlyChange(e.target.checked)}
          disabled={disabled}
        />
        {t.groupConsensusOnly[lang]}
      </label>
      {onExport && !compact && (
        <button
          type="button"
          onClick={onExport}
          disabled={disabled}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {t.groupExport[lang]}
        </button>
      )}
    </>
  );
}

export function GroupChatPanel({
  lang,
  agents,
  templates,
  chatMode,
  groupAgentIds,
  orchestration,
  maxRounds,
  consensusOnly,
  disabled,
  onChatModeChange,
  onGroupAgentIdsChange,
  onOrchestrationChange,
  onMaxRoundsChange,
  onConsensusOnlyChange,
  onApplyTemplate,
  onExport,
}: Props) {
  const t = translations.chat;
  const isMobile = useIsMobile();
  const [expanded, setExpanded] = useState(false);
  const prevAgentCount = useRef(groupAgentIds.length);

  const needsAgentSelection = chatMode === "group" && groupAgentIds.length < 2;
  const canCollapse = chatMode === "group" && groupAgentIds.length >= 2;
  const showDetails = chatMode === "group" && (!isMobile || expanded || needsAgentSelection);

  useEffect(() => {
    if (!isMobile) setExpanded(true);
  }, [isMobile]);

  useEffect(() => {
    if (
      isMobile
      && chatMode === "group"
      && prevAgentCount.current < 2
      && groupAgentIds.length >= 2
    ) {
      setExpanded(false);
    }
    prevAgentCount.current = groupAgentIds.length;
  }, [groupAgentIds.length, isMobile, chatMode]);

  useEffect(() => {
    if (isMobile && chatMode === "group" && needsAgentSelection) {
      setExpanded(true);
    }
  }, [isMobile, chatMode, needsAgentSelection]);

  const toggleAgent = (id: string) => {
    if (groupAgentIds.includes(id)) {
      onGroupAgentIdsChange(groupAgentIds.filter((x) => x !== id));
    } else if (groupAgentIds.length < 6) {
      onGroupAgentIdsChange([...groupAgentIds, id]);
    }
  };

  const selectedNames = groupAgentIds
    .map((id) => agents.find((a) => a.id === id)?.name)
    .filter(Boolean)
    .slice(0, 3)
    .join("、");

  return (
    <div
      className={clsx(
        "group-chat-panel shrink-0 border-b border-[#2d2d4e] bg-[#12121f]",
        isMobile ? "px-2 py-1.5" : "px-3 py-2 space-y-2",
      )}
    >
      <div className={clsx("flex items-center gap-2", isMobile ? "min-h-9" : "flex-wrap")}>
        <div className="inline-flex shrink-0 rounded-lg border border-[#2d2d4e] p-0.5">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChatModeChange("single")}
            className={clsx(
              "rounded-md px-2.5 py-1 text-xs transition-colors",
              chatMode === "single" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-slate-200",
            )}
          >
            {t.groupSingle[lang]}
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChatModeChange("group")}
            className={clsx(
              "rounded-md px-2.5 py-1 text-xs transition-colors",
              chatMode === "group" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-slate-200",
            )}
          >
            {t.groupChat[lang]}
          </button>
        </div>

        {chatMode === "group" && isMobile && (
          <>
            <div className="min-w-0 flex-1 text-[11px] leading-tight text-slate-400">
              {groupAgentIds.length > 0 ? (
                <>
                  <span className="text-slate-300">
                    {lang === "zh"
                      ? `已选 ${groupAgentIds.length} 个`
                      : `${groupAgentIds.length} selected`}
                  </span>
                  {selectedNames && (
                    <span className="ml-1 truncate text-slate-500">{selectedNames}</span>
                  )}
                </>
              ) : (
                <span>{t.groupNeedAgents[lang]}</span>
              )}
            </div>
            {canCollapse && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                disabled={disabled}
                className="group-chat-panel-toggle shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-[#1a1a2e] hover:text-slate-200"
                aria-expanded={expanded}
                aria-label={expanded ? t.groupPanelCollapse[lang] : t.groupPanelExpand[lang]}
                title={expanded ? t.groupPanelCollapse[lang] : t.groupPanelExpand[lang]}
              >
                {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </button>
            )}
          </>
        )}

        {chatMode === "group" && !isMobile && (
          <GroupControls
            lang={lang}
            orchestration={orchestration}
            maxRounds={maxRounds}
            consensusOnly={consensusOnly}
            disabled={disabled}
            onOrchestrationChange={onOrchestrationChange}
            onMaxRoundsChange={onMaxRoundsChange}
            onConsensusOnlyChange={onConsensusOnlyChange}
            onExport={onExport}
          />
        )}
      </div>

      {showDetails && (
        <div className={clsx(isMobile ? "mt-2 space-y-2 pb-0.5" : "space-y-2")}>
          {isMobile && (
            <div className="flex flex-wrap items-center gap-2">
              <GroupControls
                lang={lang}
                orchestration={orchestration}
                maxRounds={maxRounds}
                consensusOnly={consensusOnly}
                disabled={disabled}
                onOrchestrationChange={onOrchestrationChange}
                onMaxRoundsChange={onMaxRoundsChange}
                onConsensusOnlyChange={onConsensusOnlyChange}
                onExport={onExport}
                compact
              />
              {onExport && (
                <button
                  type="button"
                  onClick={onExport}
                  disabled={disabled}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  {t.groupExport[lang]}
                </button>
              )}
            </div>
          )}

          <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto md:max-h-none">
            {agents.slice(0, 20).map((a) => {
              const active = groupAgentIds.includes(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggleAgent(a.id)}
                  className={clsx(
                    "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                    active
                      ? "border-blue-500/60 bg-blue-600/20 text-blue-200"
                      : "border-[#2d2d4e] text-slate-400 hover:border-slate-500",
                  )}
                >
                  {a.name}
                </button>
              );
            })}
            <span className="self-center text-[10px] text-slate-500">
              {groupAgentIds.length}/6 · {t.groupMentionHint[lang]}
            </span>
          </div>

          {templates.length > 0 && (
            <div className="flex max-h-16 flex-wrap gap-1.5 overflow-y-auto md:max-h-none">
              {templates.map((tpl) => (
                <button
                  key={tpl.id}
                  type="button"
                  disabled={disabled}
                  title={tpl.description}
                  onClick={() => onApplyTemplate(tpl, resolveTemplateAgents(tpl, agents))}
                  className="rounded-md border border-[#2d2d4e] px-2 py-0.5 text-[11px] text-slate-300 hover:border-blue-500/40 hover:text-blue-200"
                >
                  {tpl.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function getGroupConfigFromState(
  chatMode: "single" | "group",
  groupAgentIds: string[],
  orchestration: GroupOrchestration,
  maxRounds: number,
  lang: Lang,
): GroupChatConfig | null {
  if (chatMode !== "group" || groupAgentIds.length < 2) return null;
  return buildGroupConfig(groupAgentIds, { orchestration, max_rounds: maxRounds, lang });
}
