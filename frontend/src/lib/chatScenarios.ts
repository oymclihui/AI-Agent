export type ChatScene = "code" | "office" | "creative" | "finance";

export interface QuickCapsule {
  id: string;
  scenes: ChatScene[];
  label: { zh: string; en: string };
  prompt: { zh: string; en: string };
  /** Match agent name/role (case-insensitive substring) */
  agentHint?: string;
}

export const CHAT_SCENES: { value: ChatScene; label: { zh: string; en: string } }[] = [
  { value: "code", label: { zh: "代码开发", en: "Development" } },
  { value: "office", label: { zh: "日常办公", en: "Office" } },
  { value: "finance", label: { zh: "财务管报", en: "Finance" } },
  { value: "creative", label: { zh: "设计创意", en: "Creative" } },
];

export const CHAT_CAPSULES: QuickCapsule[] = [
  {
    id: "code-review",
    scenes: ["code"],
    label: { zh: "代码审查", en: "Code Review" },
    prompt: {
      zh: "请审查以下代码的质量、安全与可维护性，列出问题并按优先级给出修改建议。",
      en: "Review the code for quality, security, and maintainability. List issues with prioritized fixes.",
    },
    agentHint: "engineer",
  },
  {
    id: "ppt",
    scenes: ["office", "creative"],
    label: { zh: "幻灯片", en: "Slides" },
    prompt: {
      zh: "帮我生成一份 6 页汇报 PPT 大纲：封面、背景、方案、功能、案例、总结。",
      en: "Draft a 6-slide deck outline: cover, background, solution, features, case study, summary.",
    },
    agentHint: "design",
  },
  {
    id: "doc",
    scenes: ["office"],
    label: { zh: "文档处理", en: "Documents" },
    prompt: {
      zh: "请整理附件或以下内容，输出结构化摘要、关键结论与待办事项。",
      en: "Summarize the content with structured highlights, conclusions, and action items.",
    },
  },
  {
    id: "finance",
    scenes: ["office", "finance"],
    label: { zh: "财务简报", en: "Finance Brief" },
    prompt: {
      zh: "撰写本周财务简报框架：预算执行差异、现金流关注点、3 个异常信号与行动建议。",
      en: "Draft a weekly finance brief: budget variance, cash flow watchpoints, anomalies, and actions.",
    },
    agentHint: "finance",
  },
  {
    id: "weekly-sales-12w",
    scenes: ["finance", "office"],
    label: { zh: "十二周销量分析", en: "12-Week Sales Analysis" },
    prompt: {
      zh: "我有一份 Excel：事业部、国家、第1–12周销量。请做趋势、周环比、事业部/国家对比分析，输出管理层 Markdown 报告（执行摘要、异常、建议）。",
      en: "Analyze Excel with BU, country, and 12 weekly sales columns. Output a management Markdown report with trends, WoW, and comparisons.",
    },
    agentHint: "finance",
  },
  {
    id: "manufacturing-finance-team",
    scenes: ["finance", "office"],
    label: { zh: "制造企业财务体系", en: "Manufacturing Finance Team" },
    prompt: {
      zh: "我是一家制造型企业集团（多基地、多业务板块、含出口），请帮我设计财务体系数字员工方案：\n1）列出 CFO、财务 VP、财务控制、司库、成本会计、FP&A、税务政策等岗位\n2）每个岗位：职责、汇报节奏（日/周/月）、关键 KPI、可定时执行的 task prompt 要点\n3）优先输出可落地为「智能体+数字员工+定时任务」的配置草案\n行业参考：大型制造企业的管报与制造财务实践。",
      en: "Design a digital finance team for a manufacturing enterprise: CFO, VP Finance, controller, treasury, cost, FP&A, tax — with roles, cadence, KPIs, and schedulable task prompts.",
    },
    agentHint: "finance",
  },
  {
    id: "cfo-board-pack",
    scenes: ["finance"],
    label: { zh: "CFO 董事会材料", en: "CFO Board Pack" },
    prompt: {
      zh: "为制造型企业 CFO 起草「月度经营财务综评」大纲：盈利质量、现金流、capex、业务板块拆分、政策与汇率风险、董事会待决事项。",
      en: "Outline a monthly CFO board brief for a manufacturing enterprise: earnings quality, cash, capex, segment split, policy/FX risks.",
    },
    agentHint: "finance",
  },
  {
    id: "manufacturing-cost",
    scenes: ["finance"],
    label: { zh: "制造成本分析", en: "Mfg Cost" },
    prompt: {
      zh: "分析制造环节财务：单车/单台成本 waterfall、关键物料降本跟踪、WIP 与工费差异、本周需制造与财务联合澄清的差异项。",
      en: "Analyze manufacturing finance: unit cost waterfall, material cost-down, WIP and labor variance.",
    },
    agentHint: "cost",
  },
  {
    id: "treasury-fx",
    scenes: ["finance"],
    label: { zh: "司库与汇兑", en: "Treasury & FX" },
    prompt: {
      zh: "撰写制造集团司库周报框架：现金头寸、13 周预测、融资到期、出口应收与汇兑敞口、下周需管理层知晓的资金事项。",
      en: "Draft treasury weekly for a manufacturing group: cash, 13-week forecast, maturities, export FX exposure.",
    },
    agentHint: "treasury",
  },
  {
    id: "deposit-finance-employee",
    scenes: ["finance", "office"],
    label: { zh: "对话沉淀为员工", en: "Chat → Employee" },
    prompt: {
      zh: "基于我们刚才讨论的财务岗位与流程，请整理成一份「数字员工」配置：员工名称、岗位、绑定智能体角色目标、以及 1–2 个可 cron 定时执行的 task prompt（含 cron 建议）。我将从对话沉淀功能一键创建。",
      en: "Turn our finance discussion into a digital employee config: name, title, agent role/goal, and 1–2 cron tasks with prompts.",
    },
    agentHint: "finance",
  },
  {
    id: "data-analysis",
    scenes: ["office", "code"],
    label: { zh: "数据分析", en: "Data Analysis" },
    prompt: {
      zh: "基于数据回答：趋势、同比环比、异常点与可能原因，并给出 2 条可执行建议。",
      en: "Analyze trends, YoY/MoM changes, anomalies with causes, and two actionable recommendations.",
    },
    agentHint: "data",
  },
  {
    id: "deep-research",
    scenes: ["office", "code"],
    label: { zh: "深度研究", en: "Deep Research" },
    prompt: {
      zh: "对以下主题做深度研究：背景、现状、对比、风险与结论，附参考检索要点。",
      en: "Deep research on the topic: background, landscape, comparison, risks, and conclusions.",
    },
    agentHint: "research",
  },
  {
    id: "workflow",
    scenes: ["office", "code"],
    label: { zh: "工作流生成", en: "Workflow" },
    prompt: {
      zh: "用自然语言描述一个自动化工作流：触发条件、步骤、分支与预期输出。",
      en: "Describe an automation workflow: trigger, steps, branches, and expected outputs.",
    },
  },
  {
    id: "html-design",
    scenes: ["creative"],
    label: { zh: "页面设计", en: "UI Design" },
    prompt: {
      zh: "设计一个现代简洁的 HTML 页面结构，说明布局、配色与组件层次。",
      en: "Design a clean modern HTML page structure with layout, colors, and component hierarchy.",
    },
    agentHint: "design",
  },
  {
    id: "marketing",
    scenes: ["creative", "office"],
    label: { zh: "营销文案", en: "Marketing Copy" },
    prompt: {
      zh: "为以下产品写一组营销文案：标题、卖点、3 条社媒短文案与 CTA。",
      en: "Write marketing copy: headline, value props, 3 social posts, and a CTA.",
    },
    agentHint: "marketing",
  },
];

export function capsulesForScene(scene: ChatScene): QuickCapsule[] {
  return CHAT_CAPSULES.filter((c) => c.scenes.includes(scene));
}

export function matchAgentByHint(
  agents: { id: string; name: string; role: string }[],
  hint?: string,
): string {
  if (!hint) return "";
  const h = hint.toLowerCase();
  const found = agents.find(
    (a) => a.name.toLowerCase().includes(h) || a.role.toLowerCase().includes(h),
  );
  return found?.id ?? "";
}
