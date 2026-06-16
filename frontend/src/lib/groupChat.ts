export type GroupOrchestration = "round_robin" | "hierarchical" | "parallel" | "debate";

export interface GroupChatConfig {
  agent_ids: string[];
  moderator_agent_id?: string | null;
  orchestration: GroupOrchestration;
  max_rounds: number;
  auto_synthesize: boolean;
  lang?: string;
}

export interface GroupChatTemplate {
  id: string;
  name: string;
  description: string;
  orchestration: GroupOrchestration;
  max_rounds: number;
  auto_synthesize: boolean;
  agent_slots: { label: string; role_hints: string[] }[];
  moderator_slot_index?: number | null;
  sample_prompt: string;
}

export interface GroupMessageMeta {
  kind?: "agent_turn" | "synthesis" | "round_divider" | string;
  agent_id?: string;
  agent_name?: string;
  agent_role?: string;
  round?: number;
  label?: string;
  thinking?: string;
}

export interface GroupStreamEvent {
  event?: string;
  token?: string;
  thinking?: string;
  error?: string;
  agent_id?: string;
  agent_name?: string;
  agent_role?: string;
  round?: number;
  is_synthesis?: boolean;
  message_id?: string;
  content?: string;
  label?: string;
}

export const AGENT_COLORS = [
  "border-blue-500/40 bg-blue-950/30",
  "border-emerald-500/40 bg-emerald-950/30",
  "border-amber-500/40 bg-amber-950/30",
  "border-violet-500/40 bg-violet-950/30",
  "border-rose-500/40 bg-rose-950/30",
  "border-cyan-500/40 bg-cyan-950/30",
];

export function agentColorIndex(agentId: string, agentIds: string[]): number {
  const idx = agentIds.indexOf(agentId);
  return idx >= 0 ? idx % AGENT_COLORS.length : 0;
}

export function resolveTemplateAgents(
  template: GroupChatTemplate,
  agents: { id: string; name: string; role: string }[],
): string[] {
  const picked: string[] = [];
  const used = new Set<string>();
  for (const slot of template.agent_slots) {
    const match = agents.find((a) => {
      if (used.has(a.id)) return false;
      const hay = `${a.name} ${a.role}`.toLowerCase();
      return slot.role_hints.some((h) => hay.includes(h.toLowerCase()));
    });
    if (match) {
      picked.push(match.id);
      used.add(match.id);
    }
  }
  if (picked.length < 2) {
    for (const a of agents) {
      if (used.has(a.id)) continue;
      picked.push(a.id);
      used.add(a.id);
      if (picked.length >= template.agent_slots.length) break;
    }
  }
  return picked.slice(0, 6);
}

export function buildGroupConfig(
  agentIds: string[],
  opts: Partial<GroupChatConfig> = {},
): GroupChatConfig {
  return {
    agent_ids: agentIds,
    moderator_agent_id: opts.moderator_agent_id ?? agentIds[0] ?? null,
    orchestration: opts.orchestration ?? "round_robin",
    max_rounds: opts.max_rounds ?? 2,
    auto_synthesize: opts.auto_synthesize ?? true,
    lang: opts.lang ?? "zh",
  };
}
