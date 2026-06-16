"use client";

import { useEffect, useState } from "react";
import { clsx } from "clsx";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";
import type { GroupChatConfig, GroupChatTemplate, GroupOrchestration } from "@/lib/groupChat";
import { buildGroupConfig, resolveTemplateAgents } from "@/lib/groupChat";

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

  const toggleAgent = (id: string) => {
    if (groupAgentIds.includes(id)) {
      onGroupAgentIdsChange(groupAgentIds.filter((x) => x !== id));
    } else if (groupAgentIds.length < 6) {
      onGroupAgentIdsChange([...groupAgentIds, id]);
    }
  };

  return (
    <div className="border-b border-[#2d2d4e] bg-[#12121f] px-3 py-2 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-[#2d2d4e] p-0.5">
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

        {chatMode === "group" && (
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
          </>
        )}
      </div>

      {chatMode === "group" && (
        <>
          <div className="flex flex-wrap gap-1.5">
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
            <div className="flex flex-wrap gap-1.5">
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
        </>
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
