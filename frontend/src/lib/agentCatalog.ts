export type AgentCategoryId =
  | "all"
  | "content"
  | "tech"
  | "data"
  | "finance"
  | "product"
  | "security"
  | "general";

export interface AgentCategory {
  id: AgentCategoryId;
  label: { zh: string; en: string };
  match: RegExp;
}

export interface FeaturedScene {
  id: AgentCategoryId;
  title: { zh: string; en: string };
  subtitle: { zh: string; en: string };
  tone: string;
}

export const AGENT_CATEGORIES: AgentCategory[] = [
  { id: "all", label: { zh: "全部", en: "All" }, match: /.*/ },
  {
    id: "content",
    label: { zh: "内容创作", en: "Content" },
    match: /content|marketing|copy|writer|social|创作|内容|营销|文案/i,
  },
  {
    id: "tech",
    label: { zh: "技术工程", en: "Engineering" },
    match: /engineer|developer|code|devops|sre|architect|工程|开发|技术/i,
  },
  {
    id: "data",
    label: { zh: "数据分析", en: "Analytics" },
    match: /data|analyst|analytics|metric|viz|数据|分析|报表/i,
  },
  {
    id: "finance",
    label: { zh: "金融投研", en: "Finance" },
    match: /finance|invest|stock|trading|financial|金融|投研|证券/i,
  },
  {
    id: "product",
    label: { zh: "产品设计", en: "Product" },
    match: /product|design|ux|ui|pm|产品|设计/i,
  },
  {
    id: "security",
    label: { zh: "安全合规", en: "Security" },
    match: /security|cyber|compliance|audit|安全|合规/i,
  },
  {
    id: "general",
    label: { zh: "通用助理", en: "General" },
    match: /assistant|research|general|助理|研究/i,
  },
];

export const FEATURED_SCENES: FeaturedScene[] = [
  {
    id: "content",
    title: { zh: "内容创作", en: "Content Creation" },
    subtitle: { zh: "社媒选题 · 文案 · 品牌传播", en: "Social · copy · brand" },
    tone: "agents-scene-content",
  },
  {
    id: "tech",
    title: { zh: "技术工程", en: "Engineering" },
    subtitle: { zh: "代码审查 · 架构 · DevOps", en: "Review · architecture · DevOps" },
    tone: "agents-scene-tech",
  },
  {
    id: "data",
    title: { zh: "数据分析", en: "Data Analytics" },
    subtitle: { zh: "指标 · 归因 · 可视化", en: "Metrics · attribution · viz" },
    tone: "agents-scene-data",
  },
  {
    id: "finance",
    title: { zh: "金融投研", en: "Investment Research" },
    subtitle: { zh: "研报 · 估值 · 市场洞察", en: "Research · valuation · markets" },
    tone: "agents-scene-finance",
  },
];

const AVATAR_TONES = [
  "agents-avatar-1",
  "agents-avatar-2",
  "agents-avatar-3",
  "agents-avatar-4",
  "agents-avatar-5",
  "agents-avatar-6",
];

export function agentCategory(agent: { role: string; goal: string; name: string }): AgentCategoryId {
  const text = `${agent.name} ${agent.role} ${agent.goal}`;
  for (const cat of AGENT_CATEGORIES) {
    if (cat.id === "all") continue;
    if (cat.match.test(text)) return cat.id;
  }
  return "general";
}

export function agentAvatarTone(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash + id.charCodeAt(i)) % AVATAR_TONES.length;
  return AVATAR_TONES[hash];
}

function toolEntryName(t: { tool_name?: string; name?: string } | string | null | undefined): string | null {
  if (typeof t === "string") return t.trim() || null;
  if (!t || typeof t !== "object") return null;
  const raw = t.tool_name ?? t.name;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

export function agentTags(agent: {
  role: string;
  tools_config: Array<{ tool_name?: string; name?: string } | string> | null;
  skills_config?: Array<{ skill_id: string }> | null;
}): string[] {
  const tags: string[] = [];
  const roleBits = agent.role.split(/\s+/).slice(0, 2);
  tags.push(...roleBits.filter(Boolean));
  for (const t of agent.tools_config ?? []) {
    if (tags.length >= 4) break;
    const label = toolEntryName(t);
    if (label) tags.push(label.replace(/_/g, " "));
  }
  if (tags.length < 4 && (agent.skills_config?.length ?? 0) > 0) {
    tags.push(`${agent.skills_config!.length} skills`);
  }
  return tags.slice(0, 4);
}

export function agentPopularity(agent: {
  tools_config: Array<{ tool_name?: string; name?: string } | string> | null;
  skills_config?: Array<{ skill_id: string }> | null;
}): number {
  const toolCount = (agent.tools_config ?? []).filter((t) => toolEntryName(t)).length;
  return toolCount + (agent.skills_config?.length ?? 0) * 2;
}

export function isCustomAgent(agent: {
  skills_config?: Array<{ skill_id: string }> | null;
  tools_config: Array<{ tool_name?: string; name?: string } | string> | null;
}): boolean {
  return (agent.skills_config?.length ?? 0) > 0 || (agent.tools_config ?? []).some((t) => toolEntryName(t));
}
