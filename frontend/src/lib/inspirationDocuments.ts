import type { InspirationDocument } from "@/lib/inspirationDocument";

const base = (
  format: "html" | "markdown",
  theme: InspirationDocument["theme"],
  children: InspirationDocument["root"]["children"],
): InspirationDocument => ({
  version: 1,
  format,
  theme,
  root: { id: "root", type: "root", children: children ?? [] },
});

export const DOC_MANUFACTURING_FINANCE_ZH: InspirationDocument = base("html", { mode: "light", accent: "#1e40af" }, [
  {
    id: "wrap",
    type: "section",
    style: {
      fontFamily: "'Segoe UI',system-ui,sans-serif",
      padding: "28px",
      gradient: "linear-gradient(155deg,#eff6ff 0%,#f0f9ff 45%,#ecfdf5 100%)",
      borderRadius: "16px",
      fontSize: "13px",
      lineHeight: "1.55",
      color: "#1e293b",
      minHeight: "320px",
      border: "1px solid #bfdbfe",
      boxShadow: "0 20px 50px rgba(37,99,235,0.12)",
    },
    children: [
      { id: "eyebrow", type: "badge", content: "FINANCE DIGITAL WORKFORCE", style: { display: "inline-block", background: "#dbeafe", color: "#1d4ed8", padding: "4px 10px", borderRadius: "999px", fontSize: "9px", fontWeight: 700, letterSpacing: "0.08em", marginBottom: "10px" } },
      { id: "h", type: "heading", content: "制造企业 · 财务数字员工体系", style: { fontWeight: 800, fontSize: "22px", color: "#1e3a8a", marginBottom: "6px", letterSpacing: "-0.03em" } },
      { id: "sub", type: "text", content: "CFO → VP → 控制 / 司库 / FP&A 全链路岗位编排", style: { color: "#64748b", marginBottom: "16px", fontSize: "12px" } },
      { id: "cfo", type: "cell", content: "CFO · 月度综评 & 战略财务", style: { textAlign: "center", padding: "12px", background: "linear-gradient(135deg,#2563eb,#1d4ed8)", borderRadius: "10px", margin: "6px 0", color: "#fff", fontWeight: 700, fontSize: "13px", boxShadow: "0 8px 20px rgba(37,99,235,0.25)" } },
      { id: "vp", type: "cell", content: "财务 VP · 周例会 & 跨部门协同", style: { textAlign: "center", padding: "10px", background: "#fff", borderRadius: "10px", margin: "6px 0", border: "1px solid #e2e8f0", fontWeight: 600 } },
      {
        id: "grid",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px", marginTop: "8px" },
        children: [
          { id: "a", type: "cell", content: "财务控制", style: { background: "#fff", padding: "10px", borderRadius: "8px", textAlign: "center", border: "1px solid #e2e8f0", fontSize: "12px", fontWeight: 600 } },
          { id: "b", type: "cell", content: "司库资金", style: { background: "#fff", padding: "10px", borderRadius: "8px", textAlign: "center", border: "1px solid #e2e8f0", fontSize: "12px", fontWeight: 600 } },
          { id: "c", type: "cell", content: "FP&A", style: { background: "#fff", padding: "10px", borderRadius: "8px", textAlign: "center", border: "1px solid #e2e8f0", fontSize: "12px", fontWeight: 600 } },
        ],
      },
    ],
  },
]);

export const DOC_INITIATION_ZH: InspirationDocument = base("markdown", { mode: "light", accent: "#ea580c" }, [
  {
    id: "wrap",
    type: "section",
    style: { fontFamily: "system-ui,sans-serif", padding: "14px", background: "#fff7ed", borderRadius: "10px", fontSize: "11px", color: "#431407", minHeight: "120px" },
    children: [
      { id: "h", type: "heading", content: "📊 首次覆盖 · 投资要点", style: { fontWeight: 700, marginBottom: "8px", fontSize: "12px" } },
      {
        id: "list",
        type: "list",
        items: ["行业与公司定位", "核心投资逻辑 3 条", "盈利预测与估值", "风险提示"],
        style: { margin: "0", paddingLeft: "16px", lineHeight: "1.7" },
      },
    ],
  },
]);

export const DOC_DASHBOARD_ZH: InspirationDocument = base("html", { mode: "dark", accent: "#3b82f6" }, [
  {
    id: "wrap",
    type: "section",
    style: { fontFamily: "system-ui,sans-serif", padding: "12px", background: "#1e293b", borderRadius: "10px", color: "#e2e8f0", fontSize: "10px", minHeight: "130px" },
    children: [
      { id: "h", type: "heading", content: "AI 创业融资数据信息图", style: { fontWeight: 700, fontSize: "11px", marginBottom: "8px" } },
      {
        id: "kpis",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginBottom: "8px" },
        children: [
          { id: "k1", type: "kpi", content: "¥2.4B", props: { label: "A 轮估值" }, style: { background: "#334155", padding: "8px", borderRadius: "6px", textAlign: "center" } },
          { id: "k2", type: "kpi", content: "+128%", props: { label: "YoY 营收" }, style: { background: "#334155", padding: "8px", borderRadius: "6px", textAlign: "center" } },
        ],
      },
      { id: "chart", type: "chart-bar", props: { percent: 78, barColor: "linear-gradient(90deg,#3b82f6,#06b6d4)" }, style: { height: "28px", background: "#0f172a", borderRadius: "4px", overflow: "hidden" } },
    ],
  },
]);

export const DOC_API_PORTAL_ZH: InspirationDocument = base("html", { mode: "dark", accent: "#635bff" }, [
  {
    id: "wrap",
    type: "section",
    style: {
      fontFamily: "system-ui,sans-serif",
      padding: "12px",
      background: "linear-gradient(180deg,#0a0a0f,#1a1a2e)",
      borderRadius: "10px",
      color: "#e2e8f0",
      fontSize: "10px",
      minHeight: "140px",
      border: "1px solid #2d2d4e",
    },
    children: [
      { id: "h", type: "heading", content: "Developer API Doc Portal", style: { fontWeight: 700, fontSize: "11px", color: "#a5b4fc" } },
      { id: "sub", type: "text", content: "Stripe 风格三栏 · 导航 / 正文 / 代码", style: { margin: "4px 0 8px", color: "#94a3b8", fontSize: "9px" } },
      {
        id: "cols",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 2fr 1fr", gap: "4px" },
        children: [
          { id: "nav", type: "cell", style: { background: "#16162a", borderRadius: "4px", minHeight: "48px", padding: "4px" }, children: [{ id: "n", type: "code", content: "GET /v1/users", style: { fontSize: "8px", color: "#64748b" } }] },
          { id: "main", type: "cell", style: { background: "#16162a", borderRadius: "4px", minHeight: "48px" } },
          { id: "code", type: "cell", style: { background: "#0f172a", borderRadius: "4px", minHeight: "48px", padding: "4px" }, children: [{ id: "c", type: "code", content: '{ "ok": true }', style: { fontSize: "8px", color: "#22d3ee" } }] },
        ],
      },
    ],
  },
]);

export const DOC_AI_RESEARCH_ZH: InspirationDocument = base("html", { mode: "light", accent: "#2563eb" }, [
  {
    id: "wrap",
    type: "section",
    style: { fontFamily: "system-ui,sans-serif", padding: "14px", background: "#fff", borderRadius: "10px", fontSize: "10px", color: "#1e293b", minHeight: "130px", border: "1px solid #e2e8f0" },
    children: [
      { id: "h", type: "heading", content: "AI Agent 技术深度调研报告", style: { fontWeight: 700, fontSize: "12px", marginBottom: "6px" } },
      { id: "t", type: "text", content: "架构演进 · 工具调用 · 多智能体编排", style: { color: "#64748b", marginBottom: "8px" } },
      {
        id: "chart",
        type: "chart-bar",
        props: { percent: 65, barColor: "linear-gradient(90deg,#6366f1,#8b5cf6)" },
        style: { height: "24px", background: "#f1f5f9", borderRadius: "4px", marginBottom: "6px" },
      },
      { id: "b", type: "badge", content: "Markdown 结构化输出", style: { display: "inline-block", background: "#eff6ff", color: "#2563eb", padding: "2px 6px", borderRadius: "4px", fontSize: "9px" } },
    ],
  },
]);

/** 月度财务经营汇报 — 墨绿 + 金色 (Stripe-style dashboard) */
export const DOC_FINANCE_MONTHLY_ZH: InspirationDocument = base("html", { mode: "light", accent: "#059669" }, [
  {
    id: "wrap",
    type: "section",
    style: {
      fontFamily: "'Segoe UI',system-ui,sans-serif",
      padding: "28px",
      gradient: "linear-gradient(160deg,#ecfdf5 0%,#f0fdf4 35%,#fffbeb 100%)",
      borderRadius: "16px",
      fontSize: "13px",
      color: "#064e3b",
      minHeight: "340px",
      border: "1px solid #6ee7b7",
      boxShadow: "0 24px 60px rgba(5,150,105,0.15)",
    },
    children: [
      {
        id: "head",
        type: "grid",
        style: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px" },
        children: [
          {
            id: "left",
            type: "section",
            children: [
              { id: "eyebrow", type: "badge", content: "MONTHLY REPORT", style: { display: "inline-block", background: "#d1fae5", color: "#047857", padding: "4px 10px", borderRadius: "999px", fontSize: "9px", fontWeight: 700, letterSpacing: "0.08em", marginBottom: "8px" } },
              { id: "ht", type: "heading", content: "月度财务经营汇报", style: { fontWeight: 800, fontSize: "24px", color: "#047857", letterSpacing: "-0.03em" } },
            ],
          },
          { id: "badge", type: "badge", content: "2026 · 05", style: { background: "linear-gradient(135deg,#fef3c7,#fde68a)", color: "#92400e", padding: "8px 14px", borderRadius: "10px", fontSize: "12px", fontWeight: 800, boxShadow: "0 4px 12px rgba(245,158,11,0.25)" } },
        ],
      },
      {
        id: "kpis",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" },
        children: [
          { id: "k1", type: "kpi", content: "¥8.62亿", props: { label: "营业收入 · ↑12.3% YoY" }, style: { background: "rgba(255,255,255,0.92)", padding: "16px", borderRadius: "12px", border: "1px solid #a7f3d0", boxShadow: "0 4px 16px rgba(0,0,0,0.04)" } },
          { id: "k2", type: "kpi", content: "28.6%", props: { label: "毛利率 · ↑1.2pp" }, style: { background: "rgba(255,255,255,0.92)", padding: "16px", borderRadius: "12px", border: "1px solid #a7f3d0" } },
          { id: "k3", type: "kpi", content: "¥1.04亿", props: { label: "净利润 · ↑8.7%" }, style: { background: "rgba(255,255,255,0.92)", padding: "16px", borderRadius: "12px", border: "1px solid #a7f3d0" } },
          { id: "k4", type: "kpi", content: "¥2.18亿", props: { label: "经营现金流" }, style: { background: "rgba(255,255,255,0.92)", padding: "16px", borderRadius: "12px", border: "1px solid #a7f3d0" } },
        ],
      },
      {
        id: "chart",
        type: "chart-bar",
        props: { percent: 82, barColor: "linear-gradient(90deg,#059669,#34d399,#fbbf24)" },
        style: { height: "32px", background: "#d1fae5", borderRadius: "10px", marginBottom: "12px" },
      },
      { id: "note", type: "text", content: "✓ 收入结构稳健   ✓ 费用率控制良好   ⚠ 关注原材料价格波动", style: { fontSize: "11px", color: "#047857", fontWeight: 500 } },
    ],
  },
]);

/** 季度损益看板 — 深紫靛蓝 */
export const DOC_FINANCE_QUARTERLY_PL_ZH: InspirationDocument = base("html", { mode: "dark", accent: "#8b5cf6" }, [
  {
    id: "wrap",
    type: "section",
    style: {
      fontFamily: "system-ui,sans-serif",
      padding: "12px",
      gradient: "linear-gradient(160deg,#1e1b4b 0%,#312e81 50%,#4c1d95 100%)",
      borderRadius: "10px",
      fontSize: "10px",
      color: "#e9d5ff",
      minHeight: "150px",
      border: "1px solid #6d28d9",
      boxShadow: "0 6px 20px rgba(109,40,217,0.35)",
    },
    children: [
      { id: "h", type: "heading", content: "季度损益分析 · Q2 2026", style: { fontWeight: 800, fontSize: "11px", marginBottom: "8px", color: "#c4b5fd" } },
      {
        id: "waterfall",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: "3px", marginBottom: "8px", alignItems: "end" },
        children: [
          { id: "w1", type: "cell", content: "收入", style: { background: "#6366f1", borderRadius: "4px 4px 0 0", minHeight: "36px", textAlign: "center", fontSize: "8px", padding: "4px 2px", color: "#fff" } },
          { id: "w2", type: "cell", content: "成本", style: { background: "#818cf8", borderRadius: "4px 4px 0 0", minHeight: "28px", textAlign: "center", fontSize: "8px", padding: "4px 2px", color: "#fff" } },
          { id: "w3", type: "cell", content: "毛利", style: { background: "#a78bfa", borderRadius: "4px 4px 0 0", minHeight: "32px", textAlign: "center", fontSize: "8px", padding: "4px 2px", color: "#fff" } },
          { id: "w4", type: "cell", content: "三费", style: { background: "#c084fc", borderRadius: "4px 4px 0 0", minHeight: "22px", textAlign: "center", fontSize: "8px", padding: "4px 2px", color: "#fff" } },
          { id: "w5", type: "cell", content: "净利", style: { background: "#e879f9", borderRadius: "4px 4px 0 0", minHeight: "26px", textAlign: "center", fontSize: "8px", padding: "4px 2px", color: "#fff", fontWeight: 700 } },
        ],
      },
      {
        id: "row",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px" },
        children: [
          { id: "yoy", type: "kpi", content: "+14.2%", props: { label: "同比净利" }, style: { background: "rgba(255,255,255,0.08)", padding: "6px", borderRadius: "6px", textAlign: "center", border: "1px solid rgba(167,139,250,0.3)" } },
          { id: "qoq", type: "kpi", content: "+3.8%", props: { label: "环比净利" }, style: { background: "rgba(255,255,255,0.08)", padding: "6px", borderRadius: "6px", textAlign: "center", border: "1px solid rgba(167,139,250,0.3)" } },
        ],
      },
    ],
  },
]);

/** 预算执行偏差 — 珊瑚橙暖色 */
export const DOC_FINANCE_BUDGET_ZH: InspirationDocument = base("html", { mode: "light", accent: "#ea580c" }, [
  {
    id: "wrap",
    type: "section",
    style: {
      fontFamily: "system-ui,sans-serif",
      padding: "12px",
      gradient: "linear-gradient(135deg,#fff7ed,#ffedd5,#fef3c7)",
      borderRadius: "10px",
      fontSize: "10px",
      color: "#7c2d12",
      minHeight: "150px",
      border: "1px solid #fdba74",
      boxShadow: "0 4px 12px rgba(234,88,12,0.1)",
    },
    children: [
      { id: "h", type: "heading", content: "预算执行偏差分析", style: { fontWeight: 800, fontSize: "11px", marginBottom: "4px", color: "#c2410c" } },
      { id: "sub", type: "text", content: "2026 年度 · 截至 5 月", style: { fontSize: "8px", color: "#9a3412", marginBottom: "8px" } },
      {
        id: "progress-label",
        type: "text",
        content: "年度预算完成率 41.8%",
        style: { fontSize: "8px", fontWeight: 700, marginBottom: "3px", color: "#c2410c" },
      },
      {
        id: "progress",
        type: "chart-bar",
        props: { percent: 42, barColor: "linear-gradient(90deg,#f97316,#fb923c,#fbbf24)" },
        style: { height: "10px", background: "#fed7aa", borderRadius: "999px", marginBottom: "8px", overflow: "hidden" },
      },
      {
        id: "depts",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "4px", marginBottom: "6px" },
        children: [
          { id: "d1", type: "cell", content: "生产 -2.1%", style: { background: "#fff", padding: "5px", borderRadius: "6px", textAlign: "center", fontSize: "8px", color: "#15803d", fontWeight: 600, border: "1px solid #bbf7d0" } },
          { id: "d2", type: "cell", content: "销售 +5.3%", style: { background: "#fff", padding: "5px", borderRadius: "6px", textAlign: "center", fontSize: "8px", color: "#b91c1c", fontWeight: 600, border: "1px solid #fecaca" } },
          { id: "d3", type: "cell", content: "研发 -0.8%", style: { background: "#fff", padding: "5px", borderRadius: "6px", textAlign: "center", fontSize: "8px", color: "#15803d", fontWeight: 600, border: "1px solid #bbf7d0" } },
        ],
      },
      { id: "top", type: "badge", content: "TOP 偏差：市场推广费", style: { display: "inline-block", background: "#ffedd5", color: "#c2410c", padding: "2px 8px", borderRadius: "4px", fontSize: "8px", fontWeight: 600 } },
    ],
  },
]);

/** CFO 管理层摘要 — 藏青 + 香槟金 */
export const DOC_FINANCE_CFO_BRIEF_ZH: InspirationDocument = base("html", { mode: "dark", accent: "#1e3a5f" }, [
  {
    id: "wrap",
    type: "section",
    style: {
      fontFamily: "Georgia,system-ui,sans-serif",
      padding: "12px",
      gradient: "linear-gradient(145deg,#0f172a 0%,#1e3a5f 55%,#334155 100%)",
      borderRadius: "10px",
      fontSize: "10px",
      color: "#f1f5f9",
      minHeight: "150px",
      border: "1px solid #475569",
      boxShadow: "0 6px 18px rgba(15,23,42,0.4)",
    },
    children: [
      {
        id: "head",
        type: "grid",
        style: { display: "flex", justifyContent: "space-between", marginBottom: "8px", alignItems: "center" },
        children: [
          { id: "ht", type: "heading", content: "CFO 财务摘要", style: { fontWeight: 700, fontSize: "11px", color: "#fcd34d" } },
          { id: "tag", type: "badge", content: "董事会", style: { background: "rgba(252,211,77,0.15)", color: "#fde68a", padding: "2px 6px", borderRadius: "4px", fontSize: "7px", border: "1px solid rgba(252,211,77,0.35)" } },
        ],
      },
      {
        id: "body",
        type: "grid",
        style: { display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "8px" },
        children: [
          {
            id: "metrics",
            type: "section",
            children: [
              { id: "m1", type: "kpi", content: "18.4%", props: { label: "ROE" }, style: { background: "rgba(252,211,77,0.12)", padding: "6px", borderRadius: "6px", marginBottom: "4px", border: "1px solid rgba(252,211,77,0.25)" } },
              { id: "m2", type: "kpi", content: "42.1%", props: { label: "资产负债率" }, style: { background: "rgba(255,255,255,0.06)", padding: "6px", borderRadius: "6px", marginBottom: "4px" } },
              { id: "m3", type: "kpi", content: "68天", props: { label: "现金周期" }, style: { background: "rgba(255,255,255,0.06)", padding: "6px", borderRadius: "6px" } },
            ],
          },
          {
            id: "actions",
            type: "section",
            style: { background: "rgba(255,255,255,0.05)", borderRadius: "6px", padding: "6px", border: "1px solid rgba(148,163,184,0.2)" },
            children: [
              { id: "ah", type: "heading", content: "需决策事项", style: { fontSize: "8px", fontWeight: 700, color: "#fcd34d", marginBottom: "4px" } },
              {
                id: "list",
                type: "list",
                items: ["授信额度调整", "CapEx 二期审批", "外汇 hedging 策略"],
                style: { margin: "0", paddingLeft: "14px", fontSize: "8px", lineHeight: 1.6, color: "#cbd5e1" },
              },
            ],
          },
        ],
      },
      {
        id: "signal",
        type: "badge",
        content: "🟢 流动性充足",
        style: { display: "inline-block", marginTop: "8px", background: "rgba(34,197,94,0.15)", color: "#86efac", padding: "2px 8px", borderRadius: "999px", fontSize: "8px" },
      },
    ],
  },
]);
