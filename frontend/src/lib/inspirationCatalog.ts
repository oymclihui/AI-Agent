import type { InspirationDocument } from "@/lib/inspirationDocument";
import { renderDocumentToHtml } from "@/lib/inspirationDocument";
import {
  DOC_AI_RESEARCH_ZH,
  DOC_API_PORTAL_ZH,
  DOC_DASHBOARD_ZH,
  DOC_INITIATION_ZH,
  DOC_MANUFACTURING_FINANCE_ZH,
  DOC_FINANCE_MONTHLY_ZH,
  DOC_FINANCE_QUARTERLY_PL_ZH,
  DOC_FINANCE_BUDGET_ZH,
  DOC_FINANCE_CFO_BRIEF_ZH,
} from "@/lib/inspirationDocuments";

export type InspirationCategory = "all" | "finance" | "office" | "research" | "automation" | "creative";
export type InspirationFormat = "html" | "markdown";

export interface InspirationItem {
  id: string;
  category: InspirationCategory;
  title: { zh: string; en: string };
  subtitle: { zh: string; en: string };
  /** Page JSON (block tree) — source of truth when present */
  document?: { zh?: InspirationDocument; en?: InspirationDocument };
  /** Legacy / cached preview HTML (derived from document or hand-authored) */
  previewHtml: { zh: string; en: string };
  prompt: { zh: string; en: string };
  format: InspirationFormat;
  official?: boolean;
  /** User-created item (stored in browser localStorage) */
  custom?: boolean;
  agentHint?: string;
  scene?: "office" | "finance" | "code" | "creative";
  tone: "orange" | "blue" | "green" | "purple" | "slate";
  featured?: boolean;
}

export const INSPIRATION_CATEGORIES: { id: InspirationCategory; label: { zh: string; en: string } }[] = [
  { id: "all", label: { zh: "全部", en: "All" } },
  { id: "finance", label: { zh: "财务", en: "Finance" } },
  { id: "office", label: { zh: "办公", en: "Office" } },
  { id: "research", label: { zh: "研究", en: "Research" } },
  { id: "automation", label: { zh: "自动化", en: "Automation" } },
  { id: "creative", label: { zh: "创意", en: "Creative" } },
];

export const INSPIRATION_ITEMS: InspirationItem[] = [
  {
    id: "api-doc-portal",
    category: "creative",
    featured: true,
    official: true,
    format: "html",
    tone: "slate",
    title: { zh: "开发者 API 文档门户", en: "Developer API Doc Portal" },
    subtitle: { zh: "Stripe 风格三栏文档站", en: "Stripe-style three-column docs" },
    scene: "creative",
    document: { zh: DOC_API_PORTAL_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_API_PORTAL_ZH),
      en: renderDocumentToHtml(DOC_API_PORTAL_ZH),
    },
    prompt: {
      zh: "请生成一个 Stripe 风格的开发者 API 文档门户（完整 HTML+内联 CSS）：左侧导航、中间正文、右侧代码示例；深色主题；包含 Authentication 与 GET /v1/users 示例。无外部依赖。",
      en: "Generate a Stripe-style API doc portal as standalone HTML with nav, content, and code panel. Dark theme.",
    },
  },
  {
    id: "ai-agent-research",
    category: "research",
    featured: true,
    official: true,
    format: "html",
    tone: "blue",
    title: { zh: "AI Agent 技术深度调研报告", en: "AI Agent Research Report" },
    subtitle: { zh: "架构 · 工具调用 · 编排", en: "Architecture · tools · orchestration" },
    scene: "office",
    agentHint: "research",
    document: { zh: DOC_AI_RESEARCH_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_AI_RESEARCH_ZH),
      en: renderDocumentToHtml(DOC_AI_RESEARCH_ZH),
    },
    prompt: {
      zh: "撰写一份《AI Agent 技术深度调研报告》（Markdown）：\n1. 定义与架构演进\n2. 工具调用与 MCP\n3. 多智能体编排模式\n4. 企业落地案例\n5. 2025-2026 趋势判断\n含图表占位说明。",
      en: "Write a deep-dive AI Agent research report in Markdown with architecture, tools, multi-agent patterns, and trends.",
    },
  },
  {
    id: "manufacturing-finance-org",
    category: "finance",
    featured: true,
    official: true,
    format: "html",
    tone: "blue",
    title: { zh: "制造企业财务体系", en: "Manufacturing Finance Org" },
    subtitle: { zh: "CFO → VP → 控制/司库/FP&A", en: "CFO → VP → controller/treasury/FP&A" },
    scene: "finance",
    agentHint: "finance",
    document: { zh: DOC_MANUFACTURING_FINANCE_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_MANUFACTURING_FINANCE_ZH),
      en: `<div style="font-family:system-ui,sans-serif;padding:12px;background:linear-gradient(135deg,#eff6ff,#f0fdf4);border-radius:10px;font-size:11px;color:#334155"><b>Manufacturing Finance Team</b><br/>CFO → VP → Ops finance</div>`,
    },
    prompt: {
      zh: "我是一家制造型企业集团（多基地、多业务板块、含出口）。请帮我设计完整财务数字员工体系：\n1）按层级列出 CFO、财务 VP、财务控制、司库、FP&A、成本会计、税务政策等岗位\n2）每个岗位：职责、汇报节奏（日/周/月）、关键 KPI\n3）给出可落地为「智能体+数字员工+定时任务」的配置，含 cron 与 task prompt\n4）输出后可从对话沉淀一键创建员工\n\n请用 Markdown 结构化输出，便于我直接「做同款」执行。",
      en: "Design a full digital finance team for a manufacturing enterprise group with roles, cadence, KPIs, and schedulable task prompts. Structure output in Markdown.",
    },
  },
  {
    id: "finance-monthly-report",
    category: "finance",
    featured: true,
    official: true,
    format: "html",
    tone: "green",
    title: { zh: "月度财务经营汇报", en: "Monthly Finance Report" },
    subtitle: { zh: "营收 · 毛利 · 现金流 · 同比", en: "Revenue · margin · cash · YoY" },
    scene: "finance",
    agentHint: "finance",
    document: { zh: DOC_FINANCE_MONTHLY_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_FINANCE_MONTHLY_ZH),
      en: renderDocumentToHtml(DOC_FINANCE_MONTHLY_ZH),
    },
    prompt: {
      zh: "请生成一份《月度财务经营汇报》完整 HTML 单页（内联 CSS，无外部依赖）：\n- 顶部：报告月份、编制部门、保密标识\n- 4 个 KPI 卡片：营业收入、毛利率、净利润、经营现金流（含同比箭头占位）\n- 中部：收入结构条形图占位 + 费用构成说明\n- 底部：3 条管理层结论与 2 条风险提示\n配色：墨绿 + 金色点缀，商务高级感。",
      en: "Generate a monthly finance report as standalone HTML with KPI cards, charts placeholders, and executive summary. Emerald and gold palette.",
    },
  },
  {
    id: "finance-quarterly-pl",
    category: "finance",
    featured: true,
    official: true,
    format: "html",
    tone: "purple",
    title: { zh: "季度损益分析看板", en: "Quarterly P&L Dashboard" },
    subtitle: { zh: "损益表 · 同比 · 环比", en: "P&L · YoY · QoQ" },
    scene: "finance",
    agentHint: "finance",
    document: { zh: DOC_FINANCE_QUARTERLY_PL_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_FINANCE_QUARTERLY_PL_ZH),
      en: renderDocumentToHtml(DOC_FINANCE_QUARTERLY_PL_ZH),
    },
    prompt: {
      zh: "请生成季度损益分析 HTML 看板（深色主题，内联 CSS）：\n- 标题区：Q1–Q4 切换标签样式\n- 损益瀑布：收入 → 成本 → 毛利 → 三费 → 净利润（用色块阶梯表示）\n- 右侧：同比/环比 KPI 小卡片\n- 表格占位：分业务线收入贡献\n配色：深紫 + 靛蓝渐变，数据大屏风格。",
      en: "Generate a dark-themed quarterly P&L dashboard HTML with waterfall blocks and segment table placeholder.",
    },
  },
  {
    id: "finance-budget-variance",
    category: "finance",
    featured: true,
    official: true,
    format: "html",
    tone: "orange",
    title: { zh: "预算执行偏差分析", en: "Budget Variance Analysis" },
    subtitle: { zh: "预算 vs 实际 · 偏差率", en: "Budget vs actual · variance" },
    scene: "finance",
    agentHint: "finance",
    document: { zh: DOC_FINANCE_BUDGET_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_FINANCE_BUDGET_ZH),
      en: renderDocumentToHtml(DOC_FINANCE_BUDGET_ZH),
    },
    prompt: {
      zh: "请生成《预算执行偏差分析》HTML 报告（浅色暖色主题）：\n- 顶部汇总：年度预算完成率进度条\n- 分部门表格：预算数、实际数、偏差额、偏差率（红绿着色规则）\n- 重点偏差 TOP3 说明区\n- 改进建议清单\n配色：珊瑚橙 + 奶油白背景，清晰易读。",
      en: "Generate budget vs actual variance HTML report with progress bar, department table, and top variances.",
    },
  },
  {
    id: "finance-cfo-executive-brief",
    category: "finance",
    featured: true,
    official: true,
    format: "html",
    tone: "blue",
    title: { zh: "CFO 管理层财务摘要", en: "CFO Executive Brief" },
    subtitle: { zh: "一页纸 · 决策要点", en: "One-pager · decision points" },
    scene: "finance",
    agentHint: "finance",
    document: { zh: DOC_FINANCE_CFO_BRIEF_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_FINANCE_CFO_BRIEF_ZH),
      en: renderDocumentToHtml(DOC_FINANCE_CFO_BRIEF_ZH),
    },
    prompt: {
      zh: "请生成 CFO 向董事会汇报用的「一页纸财务摘要」HTML（内联 CSS）：\n- 左侧：3 个核心指标大数字（ROE、负债率、现金周期）\n- 右侧：本周/本月 3 条要事 + 需决策事项\n- 底部：流动性红绿灯 + 下一里程碑\n配色：藏青 + 香槟金，高管简报风格。",
      en: "Generate a one-page CFO executive brief HTML with key metrics and decision items. Navy and champagne gold.",
    },
  },
  {
    id: "first-coverage-report",
    category: "research",
    featured: true,
    official: true,
    format: "markdown",
    tone: "orange",
    title: { zh: "首次覆盖研报", en: "Initiation Report" },
    subtitle: { zh: "某上市公司首次覆盖模板", en: "Initiation coverage template" },
    scene: "office",
    agentHint: "research",
    document: { zh: DOC_INITIATION_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_INITIATION_ZH),
      en: `<div style="padding:12px;background:#fff7ed;border-radius:10px;font-size:11px"><b>Initiation</b> · thesis · model · risks</div>`,
    },
    prompt: {
      zh: "帮我写一份某公司的首次覆盖研究报告框架（中文 Markdown）：\n- 公司与行业概览\n- 投资亮点与 3 条核心逻辑\n- 业务拆分与竞争格局\n- 3 年盈利预测框架（表格占位）\n- 估值方法（PE/PS/DCF 择一说明）\n- 主要风险\n请标注【待填数据】位置，并给示例表述。",
      en: "Draft an initiation research report framework with thesis, segments, forecast table placeholders, valuation, and risks.",
    },
  },
  {
    id: "weekly-report-auto",
    category: "automation",
    format: "markdown",
    tone: "green",
    title: { zh: "周报自动化", en: "Weekly Report Bot" },
    subtitle: { zh: "每周一自动生成周报", en: "Auto weekly report every Monday" },
    scene: "office",
    previewHtml: {
      zh: `<div style="font-family:system-ui,sans-serif;padding:12px;background:#ecfdf5;border-radius:10px;font-size:11px;color:#064e3b">
  <div style="font-weight:700">📅 周报 · 每周一 09:00</div>
  <p style="margin:6px 0 0">本周完成 · 下周计划 · 风险阻塞</p>
</div>`,
      en: `<div style="padding:12px;background:#ecfdf5;border-radius:10px;font-size:11px"><b>Weekly</b> · Mon 9:00 · done/next/blockers</div>`,
    },
    prompt: {
      zh: "我想做一个「周报自动化」数字员工：每周一 9:00 自动生成个人/团队周报模板，包含：本周关键成果、数据指标占位、下周计划、需协调事项。请给出：智能体角色描述、员工岗位名、以及可直接用于定时任务的 prompt 全文（中文）。",
      en: "Design a weekly report automation employee with agent role, job title, and full schedulable task prompt.",
    },
  },
  {
    id: "interview-prep",
    category: "office",
    format: "markdown",
    tone: "purple",
    title: { zh: "面试准备提醒", en: "Interview Prep" },
    subtitle: { zh: "每日上班前 2 小时提醒", en: "Remind 2h before work" },
    scene: "office",
    previewHtml: {
      zh: `<div style="font-family:system-ui,sans-serif;padding:12px;background:#faf5ff;border-radius:10px;font-size:11px;color:#581c87">
  <div style="font-weight:700">⏰ 面试准备</div>
  <p style="margin:6px 0 0">STAR 案例 · 公司调研 · 反问清单</p>
</div>`,
      en: `<div style="padding:12px;background:#faf5ff;border-radius:10px;font-size:11px"><b>Interview prep</b> · STAR · questions</div>`,
    },
    prompt: {
      zh: "我要准备一场产品经理岗位面试。请生成：1）STAR 法则下的 3 个项目故事提纲；2）针对目标公司的 5 个调研问题；3）可向面试官提出的 5 个高质量反问；4）若做成定时提醒任务，请给出 cron 建议与 task prompt。",
      en: "Generate interview prep: STAR stories, company research questions, questions to ask, and optional cron task prompt.",
    },
  },
  {
    id: "news-digest",
    category: "automation",
    format: "markdown",
    tone: "slate",
    title: { zh: "新闻推送", en: "News Digest" },
    subtitle: { zh: "每日行业要闻摘要", en: "Daily industry digest" },
    scene: "office",
    agentHint: "research",
    previewHtml: {
      zh: `<div style="font-family:system-ui,sans-serif;padding:12px;background:#f8fafc;border-radius:10px;font-size:11px;color:#334155">
  <div style="font-weight:700">📰 今日要闻 Top 5</div>
  <p style="margin:6px 0 0;color:#64748b">行业 · 政策 · 竞品</p>
</div>`,
      en: `<div style="padding:12px;background:#f8fafc;border-radius:10px;font-size:11px"><b>News Top 5</b> · industry · policy</div>`,
    },
    prompt: {
      zh: "设计一个「行业新闻推送」自动化任务：每日早晨汇总制造与科技行业 Top 5 要闻，每条含标题、一句话摘要、对业务的影响。请输出定时任务 prompt 全文，并说明建议 cron。",
      en: "Design a daily news digest automation with Top 5 items and full task prompt.",
    },
  },
  {
    id: "html-dashboard",
    category: "creative",
    featured: true,
    official: true,
    format: "html",
    tone: "blue",
    title: { zh: "AI 创业融资数据信息图", en: "AI Startup Funding Infographic" },
    subtitle: { zh: "深色 KPI 看板", en: "Dark KPI dashboard" },
    scene: "creative",
    agentHint: "design",
    document: { zh: DOC_DASHBOARD_ZH },
    previewHtml: {
      zh: renderDocumentToHtml(DOC_DASHBOARD_ZH),
      en: renderDocumentToHtml(DOC_DASHBOARD_ZH),
    },
    prompt: {
      zh: "请生成一个现代简洁的 HTML 单页数据看板（完整 HTML+内联 CSS，可直接保存为 .html）：\n- 顶部标题与日期\n- 4 个 KPI 卡片（含同比占位）\n- 一段条形/折线占位区（用 div 模拟即可）\n- 底部数据说明\n要求：响应式、浅色主题、无外部依赖。",
      en: "Generate a complete standalone HTML dashboard with KPI cards and chart placeholders, inline CSS, light theme.",
    },
  },
  {
    id: "code-review-sop",
    category: "office",
    format: "markdown",
    tone: "green",
    title: { zh: "代码审查 SOP", en: "Code Review SOP" },
    subtitle: { zh: "PR 审查清单与反馈", en: "PR review checklist" },
    scene: "code",
    agentHint: "engineer",
    previewHtml: {
      zh: `<div style="font-family:ui-monospace,monospace;padding:12px;background:#0f172a;border-radius:10px;font-size:10px;color:#94a3b8">
  <div style="color:#22d3ee">// Code Review</div>
  <div>✓ 安全 · 性能 · 可测</div>
</div>`,
      en: `<div style="padding:12px;background:#0f172a;border-radius:10px;font-size:10px;color:#94a3b8">Review · security · tests</div>`,
    },
    prompt: {
      zh: "请对以下代码变更做审查（我会粘贴 diff）：按优先级列出问题，分类为安全/性能/可维护性/测试，并给出修改建议。若适合沉淀为技能 SOP，请在末尾给出技能摘要标题与要点。",
      en: "Review code changes: security, performance, maintainability, tests — prioritized findings and fixes.",
    },
  },
];

export const INSPIRE_SESSION_KEY = "aiagnet_inspire_pending";

export function getInspirationById(id: string): InspirationItem | undefined {
  return INSPIRATION_ITEMS.find((i) => i.id === id);
}
