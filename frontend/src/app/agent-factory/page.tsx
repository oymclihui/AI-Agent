"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  Sparkles, Gauge, Wand2, FlaskConical, Rocket, History,
  GitCompare, RotateCcw, Loader2, CheckCircle2, XCircle, RefreshCw, Send, Users,
} from "lucide-react";
import { dataSourcesApi, dsFactoryApi, formatApiError } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";

// ── Types ────────────────────────────────────────────

interface DataSourceItem {
  id: string;
  name: string;
}

interface Capability {
  key: string;
  label: string;
  enabled: boolean;
  reason: string;
}

interface ReadinessItem {
  key: string;
  label: string;
  value: string | number;
  target: string | number;
  ok: boolean;
}

interface Coach {
  data_source_id: string;
  data_source_name?: string | null;
  driver?: string | null;
  profile: {
    status?: string;
    version?: number | null;
    table_count?: number | null;
    column_count?: number | null;
    comment_coverage?: number | null;
    total_rows?: number;
    time_columns: string[];
    numeric_columns: string[];
    quality_gaps: string[];
  };
  semantic: { terms: number; metrics: number };
  distill: {
    examples_positive: number;
    examples_negative: number;
    examples_indexed: number;
    templates_active: number;
    rules_active: number;
  };
  signal: { traces: number; feedback: number };
  ml: Record<string, { version: number; metrics?: Record<string, number>; trained_rows?: number | null }>;
  capabilities: Capability[];
  readiness: { score: number; level: string; items: ReadinessItem[] };
  gaps: string[];
}

interface Spec {
  name: string;
  role: string;
  goal: string;
  backstory?: string | null;
  temperature: number;
  tools_config: unknown[];
  skills_config: unknown[];
  memory_config: Record<string, unknown>;
  metadata_: Record<string, unknown>;
  opening_questions: string[];
}

interface Version {
  id: number;
  agent_id: string;
  version: number;
  source: string;
  note?: string | null;
  status: string;
  spec: Record<string, any>;
  created_at?: string | null;
}

interface Release {
  id: string;
  version_id: number;
  version: number;
  scope: string;
  gray_users: string[];
  active: boolean;
  created_at?: string | null;
  note?: string | null;
}

interface DiffOut {
  agent_id: string;
  base_version?: number | null;
  target_version: number;
  items: { field: string; changed: boolean; old_preview: string; new_preview: string }[];
}

interface TrialResult {
  success: boolean;
  sql: string;
  row_count: number;
  analysis_mode: string;
  answer_excerpt: string;
  trace_id?: number | null;
  error?: string | null;
}

const LEVEL_STYLE: Record<string, string> = {
  good: "text-emerald-600 border-emerald-300 bg-emerald-50",
  basic: "text-amber-600 border-amber-300 bg-amber-50",
  insufficient: "text-rose-600 border-rose-300 bg-rose-50",
};
const VERSION_STATUS_STYLE: Record<string, string> = {
  production: "bg-emerald-50 text-emerald-700 border-emerald-300",
  candidate: "bg-amber-50 text-amber-700 border-amber-300",
  retired: "bg-gray-100 text-gray-500 border-gray-300",
};
const SOURCE_LABEL: Record<string, { zh: string; en: string }> = {
  factory: { zh: "工厂生成", en: "Factory" },
  manual: { zh: "手工编辑", en: "Manual" },
  feedback: { zh: "反馈驱动", en: "Feedback" },
  rollback: { zh: "回滚", en: "Rollback" },
};

// ── Page ─────────────────────────────────────────────

export default function AgentFactoryPage() {
  const { lang } = useLangStore();
  const [sources, setSources] = useState<DataSourceItem[]>([]);
  const [selectedDs, setSelectedDs] = useState("");
  const [agentId, setAgentId] = useState("");
  const [coach, setCoach] = useState<Coach | null>(null);
  const [spec, setSpec] = useState<Spec | null>(null);
  const [nlPrompt, setNlPrompt] = useState("");
  const [customName, setCustomName] = useState("");
  const [trialQ, setTrialQ] = useState("");
  const [trial, setTrial] = useState<TrialResult | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [releases, setReleases] = useState<Release[]>([]);
  const [diff, setDiff] = useState<DiffOut | null>(null);
  const [grayUsers, setGrayUsers] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState("");

  const t = lang === "zh"
    ? {
        title: "智能体工厂",
        subtitle: "选数据源 → 养成画像 → 生成配置 → 试跑发布 —— 让沉淀的知识长成智能体",
        step1: "① 选择数据源",
        step2: "② 养成画像",
        step3: "③ 生成配置",
        step4: "④ 试跑与发布",
        versionsTitle: "配置版本管理",
        releasesTitle: "发布与灰度记录",
        readiness: "养成就绪度",
        capabilities: "能力自动匹配",
        gaps: "待补齐缺口",
        stats: "知识沉淀资产",
        profileReady: "画像",
        tables: "表",
        columns: "列",
        rows: "总行数",
        cmtCoverage: "注释覆盖",
        terms: "术语",
        metrics: "指标",
        examples: "示例(已向量化)",
        templates: "启用模板",
        rules: "生效规则",
        traces: "问数轨迹",
        enabled: "可用",
        disabled: "不可用",
        timeCols: "时间列",
        numCols: "数值列",
        generate: "生成配置",
        regenerating: "生成中...",
        genHint: "可填写一句话诉求（可选），或留空由系统基于真实素材生成",
        nlPlaceholder: "例如：聚焦门店销售与库存周转分析",
        namePlaceholder: "智能体名称（可选）",
        name: "名称",
        role: "角色",
        goal: "目标",
        backstory: "背景设定",
        temperature: "温度",
        tools: "工具",
        skills: "技能",
        chartPref: "图表偏好",
        opening: "开场问题",
        trialTitle: "试跑（真实问数链路）",
        trialPlaceholder: "输入一个业务问题试跑",
        trialRun: "试跑",
        trialResult: "试跑结果",
        sql: "SQL",
        rowCount: "行数",
        mode: "模式",
        trace: "轨迹ID",
        publish: "发布为标准智能体",
        republish: "更新并发布",
        published: "已发布",
        regenerate: "蒸馏后再生成候选版本",
        noSource: "请选择数据源",
        noVersions: "暂无版本 — 完成向导发布后自动生成 v1",
        noReleases: "暂无发布记录",
        diff: "对比",
        diffTitle: "配置差异",
        diffBase: "基线",
        rollback: "回滚",
        release: "发布",
        releaseGray: "灰度发布",
        grayHint: "灰度白名单（用户ID，逗号分隔，留空为全量）",
        version: "版本",
        status: "状态",
        prod: "现役",
        cand: "候选",
        retired: "历史",
        scope: "范围",
        full: "全量",
        gray: "灰度",
        active: "生效中",
        inactive: "已下线",
        agentBound: "已绑定智能体",
        agentNone: "未绑定智能体",
        refresh: "刷新",
        loading: "加载中...",
        ok: "成功",
        fail: "失败",
        empty: "—",
      }
    : {
        title: "Agent Factory",
        subtitle: "Pick a source → coach profile → generate config → trial & publish — grow distilled knowledge into an agent",
        step1: "① Choose Source",
        step2: "② Coach Profile",
        step3: "③ Generate Config",
        step4: "④ Trial & Publish",
        versionsTitle: "Config Versioning",
        releasesTitle: "Release & Gray Records",
        readiness: "Readiness",
        capabilities: "Auto-matched Capabilities",
        gaps: "Gaps to Close",
        stats: "Distilled Assets",
        profileReady: "Profile",
        tables: "Tables",
        columns: "Columns",
        rows: "Total rows",
        cmtCoverage: "Comment coverage",
        terms: "Terms",
        metrics: "Metrics",
        examples: "Examples (indexed)",
        templates: "Active templates",
        rules: "Active rules",
        traces: "Traces",
        enabled: "Available",
        disabled: "Unavailable",
        timeCols: "Time columns",
        numCols: "Numeric columns",
        generate: "Generate Config",
        regenerating: "Generating...",
        genHint: "Optional one-line intent; leave blank to let the system build from real assets",
        nlPlaceholder: "e.g. focus on store sales and inventory turnover",
        namePlaceholder: "Agent name (optional)",
        name: "Name",
        role: "Role",
        goal: "Goal",
        backstory: "Backstory",
        temperature: "Temperature",
        tools: "Tools",
        skills: "Skills",
        chartPref: "Chart preferences",
        opening: "Opening questions",
        trialTitle: "Trial (real data-ask pipeline)",
        trialPlaceholder: "Type a business question to trial",
        trialRun: "Trial",
        trialResult: "Trial Result",
        sql: "SQL",
        rowCount: "Rows",
        mode: "Mode",
        trace: "Trace ID",
        publish: "Publish as standard agent",
        republish: "Update & publish",
        published: "Published",
        regenerate: "Regenerate candidate after distilling",
        noSource: "Select a data source",
        noVersions: "No versions — v1 is created automatically after the wizard publishes",
        noReleases: "No releases yet",
        diff: "Diff",
        diffTitle: "Config Diff",
        diffBase: "Base",
        rollback: "Rollback",
        release: "Release",
        releaseGray: "Gray release",
        grayHint: "Gray whitelist (user IDs, comma-separated; empty = full)",
        version: "Version",
        status: "Status",
        prod: "Production",
        cand: "Candidate",
        retired: "Retired",
        scope: "Scope",
        full: "Full",
        gray: "Gray",
        active: "Active",
        inactive: "Retired",
        agentBound: "Agent bound",
        agentNone: "No agent bound",
        refresh: "Refresh",
        loading: "Loading...",
        ok: "OK",
        fail: "Failed",
        empty: "—",
      };

  useEffect(() => {
    dataSourcesApi.list().then((res) => {
      const items: DataSourceItem[] = res.data?.items || res.data || [];
      setSources(items);
      if (items.length > 0) setSelectedDs(items[0].id);
    }).catch(() => setSources([]));
  }, []);

  const loadVersions = useCallback(async (aid: string) => {
    if (!aid) {
      setVersions([]);
      setReleases([]);
      return;
    }
    try {
      const [v, r] = await Promise.all([
        dsFactoryApi.versions(aid),
        dsFactoryApi.releases(aid),
      ]);
      setVersions(v.data || []);
      setReleases(r.data || []);
    } catch (e2) {
      setToast(formatApiError(e2, "版本加载失败"));
    }
  }, []);

  const loadSource = useCallback(async (ds: string) => {
    if (!ds) return;
    setLoading(true);
    setDiff(null);
    setTrial(null);
    setSpec(null);
    try {
      const [srcRes, coachRes] = await Promise.all([
        dataSourcesApi.get(ds),
        dsFactoryApi.coach(ds),
      ]);
      const aid: string = srcRes.data?.agent_id || "";
      setAgentId(aid);
      setCoach(coachRes.data);
      setCustomName(coachRes.data?.data_source_name || "");
      await loadVersions(aid);
    } catch (e2) {
      setToast(formatApiError(e2, "加载失败"));
      setCoach(null);
    } finally {
      setLoading(false);
    }
  }, [loadVersions]);

  useEffect(() => { loadSource(selectedDs); }, [selectedDs, loadSource]);

  const runGenerate = async () => {
    if (!selectedDs) return;
    setBusy("gen");
    try {
      const res = await dsFactoryApi.generate(selectedDs, {
        nl_prompt: nlPrompt.trim() || undefined,
        name: customName.trim() || undefined,
      });
      setSpec({ ...res.data.spec, opening_questions: res.data.spec.opening_questions || [] });
      setCoach(res.data.coach);
      setToast("");
    } catch (e2) {
      setToast(formatApiError(e2, "生成失败"));
    } finally {
      setBusy(null);
    }
  };

  const runTrial = async () => {
    if (!selectedDs || !trialQ.trim()) return;
    setBusy("trial");
    try {
      const res = await dsFactoryApi.trial(selectedDs, trialQ.trim());
      setTrial(res.data);
    } catch (e2) {
      setToast(formatApiError(e2, "试跑失败"));
    } finally {
      setBusy(null);
    }
  };

  const runPublish = async () => {
    if (!selectedDs || !spec) return;
    setBusy("pub");
    try {
      const res = await dsFactoryApi.publish(selectedDs, { spec, coach, note: null });
      setToast(`${t.published}: ${res.data.agent_id.slice(0, 8)} · v${res.data.version}`);
      setAgentId(res.data.agent_id);
      await loadVersions(res.data.agent_id);
    } catch (e2) {
      setToast(formatApiError(e2, "发布失败"));
    } finally {
      setBusy(null);
    }
  };

  const runRegenerate = async () => {
    if (!selectedDs) return;
    setBusy("regen");
    try {
      await dsFactoryApi.regenerate(selectedDs);
      setToast(lang === "zh" ? "候选版本生成任务已启动，稍后刷新查看" : "Candidate generation started, refresh shortly");
      setTimeout(() => loadVersions(agentId), 10000);
    } catch (e2) {
      setToast(formatApiError(e2, "操作失败"));
    } finally {
      setBusy(null);
    }
  };

  const showDiff = async (vid: number) => {
    if (!agentId) return;
    setBusy("diff");
    try {
      const res = await dsFactoryApi.diff(agentId, vid);
      setDiff(res.data);
    } catch (e2) {
      setToast(formatApiError(e2, "对比失败"));
    } finally {
      setBusy(null);
    }
  };

  const runRollback = async (vid: number) => {
    if (!agentId) return;
    setBusy("rollback");
    try {
      await dsFactoryApi.rollback(agentId, vid);
      setToast(lang === "zh" ? "已回滚并发布" : "Rolled back & released");
      await loadVersions(agentId);
      await loadSource(selectedDs);
    } catch (e2) {
      setToast(formatApiError(e2, "回滚失败"));
    } finally {
      setBusy(null);
    }
  };

  const runRelease = async (vid: number, scope: string) => {
    if (!agentId) return;
    setBusy(scope === "gray" ? "gray" : "rel");
    try {
      const users = grayUsers.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
      await dsFactoryApi.release(agentId, {
        version_id: vid, scope, gray_users: scope === "gray" ? users : [],
      });
      setToast(lang === "zh" ? "已发布" : "Released");
      await loadVersions(agentId);
    } catch (e2) {
      setToast(formatApiError(e2, "发布失败"));
    } finally {
      setBusy(null);
    }
  };

  const upd = (patch: Partial<Spec>) => setSpec((s) => (s ? { ...s, ...patch } : s));

  const levelStyle = coach ? LEVEL_STYLE[coach.readiness.level] || LEVEL_STYLE.basic : "";

  return (
    <div className="mx-auto max-w-7xl p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Sparkles className="h-7 w-7 text-indigo-500" />
            {t.title}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t.subtitle}</p>
        </div>
        <button
          onClick={() => loadSource(selectedDs)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 text-sm hover:border-indigo-300 hover:text-indigo-600"
        >
          <RefreshCw className="h-3.5 w-3.5" /> {t.refresh}
        </button>
      </div>

      {/* Step 1: data source */}
      <StepHeader index={1} title={t.step1} icon={<Gauge className="h-4 w-4" />} />
      <div className="flex items-center gap-3 flex-wrap">
        {sources.map((s) => (
          <button
            key={s.id}
            onClick={() => setSelectedDs(s.id)}
            className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
              selectedDs === s.id
                ? "bg-indigo-50 border-indigo-300 text-indigo-600"
                : "border-gray-200 hover:border-indigo-200"
            }`}
          >
            {s.name || s.id.slice(0, 8)}
          </button>
        ))}
      </div>

      {!selectedDs ? (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-12 text-center text-gray-400">
          {t.noSource}
        </div>
      ) : (
        <>
          {(toast || loading) && (
            <div className="flex items-center gap-3">
              {toast && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm text-indigo-700 flex-1">
                  {toast}
                </div>
              )}
              {loading && (
                <div className="flex items-center gap-2 text-gray-400 text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" /> {t.loading}
                </div>
              )}
            </div>
          )}

          {/* Step 2: coach */}
          {coach && (
            <>
              <StepHeader index={2} title={t.step2} icon={<Gauge className="h-4 w-4" />} />
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                {/* readiness */}
                <div className="rounded-xl border border-gray-200 bg-white p-5">
                  <div className="text-sm text-gray-500">{t.readiness}</div>
                  <div className="flex items-baseline gap-2 mt-1">
                    <span className="text-4xl font-bold text-gray-800">{coach.readiness.score}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs border ${levelStyle}`}>
                      {coach.readiness.level}
                    </span>
                  </div>
                  <div className="mt-4 space-y-2">
                    {coach.readiness.items.map((it) => (
                      <div key={it.key} className="flex items-center gap-2 text-sm">
                        {it.ok ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
                        )}
                        <span className="text-gray-700 flex-1">{it.label}</span>
                        <span className={`font-mono text-xs ${it.ok ? "text-emerald-600" : "text-rose-500"}`}>
                          {String(it.value)}/{String(it.target)}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className={`mt-4 inline-flex items-center gap-1.5 text-xs rounded-lg border px-2.5 py-1 ${
                    agentId ? "border-indigo-200 bg-indigo-50 text-indigo-600" : "border-gray-200 text-gray-400"
                  }`}>
                    <Sparkles className="h-3.5 w-3.5" />
                    {agentId ? `${t.agentBound} · ${agentId.slice(0, 8)}` : t.agentNone}
                  </div>
                </div>

                {/* capabilities */}
                <div className="rounded-xl border border-gray-200 bg-white p-5">
                  <div className="text-sm text-gray-500 mb-3">{t.capabilities}</div>
                  <div className="space-y-2.5">
                    {coach.capabilities.map((c) => (
                      <div key={c.key} className="flex items-start gap-2">
                        {c.enabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 mt-0.5 shrink-0" />
                        ) : (
                          <XCircle className="h-4 w-4 text-gray-300 mt-0.5 shrink-0" />
                        )}
                        <div className="min-w-0">
                          <div className={`text-sm font-medium ${c.enabled ? "text-gray-800" : "text-gray-400"}`}>
                            {c.label}
                          </div>
                          <div className="text-xs text-gray-400">{c.reason}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* assets + gaps */}
                <div className="rounded-xl border border-gray-200 bg-white p-5">
                  <div className="text-sm text-gray-500 mb-3">{t.stats}</div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <Asset label={t.profileReady} value={coach.profile.status || "none"} />
                    <Asset label={t.rows} value={coach.profile.total_rows ?? 0} />
                    <Asset label={t.tables} value={coach.profile.table_count ?? 0} />
                    <Asset label={t.columns} value={coach.profile.column_count ?? 0} />
                    <Asset label={t.terms} value={coach.semantic.terms} />
                    <Asset label={t.metrics} value={coach.semantic.metrics} />
                    <Asset label={t.examples} value={coach.distill.examples_indexed} />
                    <Asset label={t.templates} value={coach.distill.templates_active} />
                    <Asset label={t.rules} value={coach.distill.rules_active} />
                    <Asset label={t.traces} value={coach.signal.traces} />
                  </div>
                  {coach.gaps.length > 0 && (
                    <div className="mt-4">
                      <div className="text-xs font-medium text-amber-700 mb-1">{t.gaps}</div>
                      <ul className="list-disc list-inside space-y-0.5 text-xs text-gray-500">
                        {coach.gaps.slice(0, 8).map((g, i) => <li key={i}>{g}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          {/* Step 3: generate */}
          <StepHeader index={3} title={t.step3} icon={<Wand2 className="h-4 w-4" />} />
          <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                value={nlPrompt}
                onChange={(e) => setNlPrompt(e.target.value)}
                placeholder={t.nlPlaceholder}
                className="md:col-span-2 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-300 focus:outline-none"
              />
              <input
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                placeholder={t.namePlaceholder}
                className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-300 focus:outline-none"
              />
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={runGenerate}
                disabled={busy === "gen"}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-500 text-white text-sm hover:bg-indigo-600 disabled:opacity-50"
              >
                {busy === "gen" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                {busy === "gen" ? t.regenerating : t.generate}
              </button>
              <span className="text-xs text-gray-400">{t.genHint}</span>
            </div>

            {spec && (
              <div className="border-t border-gray-100 pt-4 space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <Field label={t.name}>
                    <input value={spec.name} onChange={(e) => upd({ name: e.target.value })} className={inputCls} />
                  </Field>
                  <Field label={t.role}>
                    <input value={spec.role} onChange={(e) => upd({ role: e.target.value })} className={inputCls} />
                  </Field>
                </div>
                <Field label={t.goal}>
                  <textarea rows={3} value={spec.goal} onChange={(e) => upd({ goal: e.target.value })} className={inputCls} />
                </Field>
                <Field label={t.backstory}>
                  <textarea rows={3} value={spec.backstory || ""} onChange={(e) => upd({ backstory: e.target.value })} className={inputCls} />
                </Field>
                <div className="flex flex-wrap items-center gap-4 text-sm">
                  <Field label={t.temperature} inline>
                    <input
                      type="number" step="0.05" min="0" max="1"
                      value={spec.temperature}
                      onChange={(e) => upd({ temperature: Number(e.target.value) })}
                      className="w-24 rounded-lg border border-gray-200 px-2 py-1.5 text-sm"
                    />
                  </Field>
                  <Chip label={t.tools} value={`${spec.tools_config.length}`} />
                  <Chip label={t.skills} value={`${spec.skills_config.length}`} />
                  {chartPref(spec) && <Chip label={t.chartPref} value={chartPref(spec)!} />}
                </div>
                {spec.opening_questions.length > 0 && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1.5">{t.opening}</div>
                    <div className="flex flex-wrap gap-1.5">
                      {spec.opening_questions.map((q, i) => (
                        <button
                          key={i}
                          onClick={() => setTrialQ(q)}
                          className="rounded-lg bg-indigo-50 px-2.5 py-1 text-xs text-indigo-600 hover:bg-indigo-100"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Step 4: trial + publish */}
          <StepHeader index={4} title={t.step4} icon={<FlaskConical className="h-4 w-4" />} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-3">
              <div className="text-sm font-medium text-gray-700">{t.trialTitle}</div>
              <div className="flex gap-2">
                <input
                  value={trialQ}
                  onChange={(e) => setTrialQ(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") runTrial(); }}
                  placeholder={t.trialPlaceholder}
                  className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-300 focus:outline-none"
                />
                <button
                  onClick={runTrial}
                  disabled={busy === "trial" || !trialQ.trim()}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-indigo-500 text-white text-sm hover:bg-indigo-600 disabled:opacity-50"
                >
                  {busy === "trial" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  {t.trialRun}
                </button>
              </div>
              {trial && (
                <div className="space-y-2">
                  {!trial.success ? (
                    <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-600">
                      {trial.error || t.fail}
                    </div>
                  ) : (
                    <>
                      <div className="flex flex-wrap gap-3 text-xs text-gray-500">
                        <span>{t.rowCount}: <b className="text-gray-700">{trial.row_count}</b></span>
                        <span>{t.mode}: <b className="text-gray-700">{trial.analysis_mode}</b></span>
                        {trial.trace_id != null && <span>{t.trace}: <b className="text-gray-700">#{trial.trace_id}</b></span>}
                      </div>
                      {trial.sql && (
                        <pre className="rounded-lg bg-gray-900 p-3 text-xs text-gray-100 overflow-x-auto whitespace-pre-wrap">{trial.sql}</pre>
                      )}
                      <div className="rounded-lg bg-gray-50 p-3 text-sm text-gray-700 whitespace-pre-wrap max-h-72 overflow-y-auto">
                        {trial.answer_excerpt}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-5 space-y-3">
              <div className="text-sm font-medium text-gray-700">{t.publish}</div>
              <p className="text-xs text-gray-400">
                {lang === "zh"
                  ? "发布会把当前配置写入标准智能体记录（goal/工具/技能），并生成版本快照与发布记录。"
                  : "Publishing writes the config into a standard agent record and creates a version snapshot + release record."}
              </p>
              <button
                onClick={runPublish}
                disabled={busy === "pub" || !spec}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm hover:bg-emerald-600 disabled:opacity-50"
              >
                {busy === "pub" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                {agentId ? t.republish : t.publish}
              </button>
              {agentId && (
                <button
                  onClick={runRegenerate}
                  disabled={busy === "regen"}
                  className="ml-2 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-gray-200 text-sm hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-50"
                >
                  {busy === "regen" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                  {t.regenerate}
                </button>
              )}
            </div>
          </div>

          {/* Version management */}
          {agentId && (
            <>
              <StepHeader index={0} title={t.versionsTitle} icon={<History className="h-4 w-4" />} />
              <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
                {versions.length === 0 ? (
                  <div className="px-5 py-6 text-sm text-gray-400">{t.noVersions}</div>
                ) : (
                  <div className="divide-y divide-gray-50">
                    {versions.map((v) => (
                      <div key={v.id} className="px-5 py-3 hover:bg-gray-50">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono font-semibold text-gray-800">v{v.version}</span>
                          <span className={`px-2 py-0.5 rounded-full text-xs border ${VERSION_STATUS_STYLE[v.status] || ""}`}>
                            {v.status === "production" ? t.prod : v.status === "candidate" ? t.cand : t.retired}
                          </span>
                          <span className="px-2 py-0.5 rounded-full text-xs border border-gray-200 text-gray-500">
                            {(SOURCE_LABEL[v.source] || { zh: v.source, en: v.source })[lang]}
                          </span>
                          <span className="text-xs text-gray-400">
                            {v.spec?.role} · T{v.spec?.temperature} · {t.tools} {(v.spec?.tools_config || []).length} · {t.skills} {(v.spec?.skills_config || []).length}
                          </span>
                          <div className="ml-auto flex items-center gap-2">
                            <button
                              onClick={() => showDiff(v.id)}
                              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-600 hover:bg-indigo-50 hover:text-indigo-600"
                            >
                              <GitCompare className="h-3.5 w-3.5" /> {t.diff}
                            </button>
                            {v.status !== "production" && (
                              <>
                                <button
                                  onClick={() => runRelease(v.id, "full")}
                                  disabled={busy === "rel"}
                                  className="flex items-center gap-1 px-2 py-1 rounded text-xs text-emerald-600 hover:bg-emerald-50 disabled:opacity-50"
                                >
                                  <Rocket className="h-3.5 w-3.5" /> {t.release}
                                </button>
                                <button
                                  onClick={() => runRollback(v.id)}
                                  disabled={busy === "rollback"}
                                  className="flex items-center gap-1 px-2 py-1 rounded text-xs text-amber-600 hover:bg-amber-50 disabled:opacity-50"
                                >
                                  <RotateCcw className="h-3.5 w-3.5" /> {t.rollback}
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                        {v.note && <div className="text-xs text-gray-500 mt-1">{v.note}</div>}
                        <div className="text-xs text-gray-300 mt-0.5">{fmtTime(v.created_at)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  value={grayUsers}
                  onChange={(e) => setGrayUsers(e.target.value)}
                  placeholder={t.grayHint}
                  className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-300 focus:outline-none"
                />
                <button
                  onClick={() => versions[0] && runRelease(versions[0].id, "gray")}
                  disabled={busy === "gray" || versions.length === 0}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-indigo-200 text-indigo-600 text-sm hover:bg-indigo-50 disabled:opacity-50"
                >
                  {busy === "gray" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Users className="h-4 w-4" />}
                  {t.releaseGray}
                </button>
              </div>

              {/* diff panel */}
              {diff && (
                <div className="rounded-xl border border-indigo-200 bg-white overflow-hidden">
                  <div className="flex items-center gap-2 px-5 py-3 border-b border-gray-100">
                    <GitCompare className="h-4 w-4 text-indigo-500" />
                    <span className="font-medium text-gray-800">{t.diffTitle}</span>
                    <span className="text-xs text-gray-400">
                      {t.diffBase} v{diff.base_version ?? "—"} → v{diff.target_version}
                    </span>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {diff.items.filter((i) => i.changed).length === 0 ? (
                      <div className="px-5 py-4 text-sm text-gray-400">
                        {lang === "zh" ? "与基线配置无差异" : "No difference from base"}
                      </div>
                    ) : (
                      diff.items.filter((i) => i.changed).map((i) => (
                        <div key={i.field} className="px-5 py-2.5">
                          <div className="font-mono text-xs font-medium text-gray-700">{i.field}</div>
                          <div className="mt-1 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                            <div className="rounded bg-rose-50 px-2.5 py-1.5 text-rose-700 whitespace-pre-wrap break-words">
                              {i.old_preview || t.empty}
                            </div>
                            <div className="rounded bg-emerald-50 px-2.5 py-1.5 text-emerald-700 whitespace-pre-wrap break-words">
                              {i.new_preview || t.empty}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* releases */}
              <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
                <h2 className="text-sm font-semibold text-gray-700 px-5 py-3 border-b border-gray-100">{t.releasesTitle}</h2>
                {releases.length === 0 ? (
                  <div className="px-5 py-5 text-sm text-gray-400">{t.noReleases}</div>
                ) : (
                  <div className="divide-y divide-gray-50">
                    {releases.map((r) => (
                      <div key={r.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                        <span className="font-mono text-gray-800">v{r.version}</span>
                        <span className={`px-2 py-0.5 rounded-full text-xs border ${
                          r.scope === "gray" ? "bg-violet-50 text-violet-700 border-violet-300" : "bg-blue-50 text-blue-700 border-blue-300"
                        }`}>
                          {r.scope === "gray" ? t.gray : t.full}
                        </span>
                        <span className={`px-2 py-0.5 rounded-full text-xs border ${
                          r.active ? "bg-emerald-50 text-emerald-700 border-emerald-300" : "bg-gray-100 text-gray-500 border-gray-300"
                        }`}>
                          {r.active ? t.active : t.inactive}
                        </span>
                        {r.gray_users.length > 0 && (
                          <span className="text-xs text-gray-400">
                            {r.gray_users.slice(0, 4).map((u) => u.slice(0, 8)).join(", ")}
                            {r.gray_users.length > 4 ? ` +${r.gray_users.length - 4}` : ""}
                          </span>
                        )}
                        <span className="ml-auto text-xs text-gray-300">{fmtTime(r.created_at)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────

const inputCls =
  "w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-indigo-300 focus:outline-none";

function chartPref(spec: Spec): string | null {
  const cp = (spec.metadata_ as any)?.factory?.chart_preferences;
  if (!cp || typeof cp !== "object") return null;
  return Object.entries(cp).map(([k, v]) => `${k}:${v}`).join(" · ");
}

function fmtTime(s?: string | null): string {
  if (!s) return "";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return String(s);
  }
}

function StepHeader({ index, title, icon }: { index: number; title: string; icon: ReactNode }) {
  return (
    <div className="flex items-center gap-2 pt-2">
      {index > 0 && (
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-500 text-white text-xs font-bold">
          {index}
        </span>
      )}
      <span className="flex items-center gap-1.5 text-lg font-semibold text-gray-800">
        {index === 0 && <span className="text-indigo-500">{icon}</span>}
        {title}
      </span>
    </div>
  );
}

function Asset({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-gray-50 px-2.5 py-1.5">
      <div className="text-xs text-gray-400">{label}</div>
      <div className="font-semibold text-gray-700">{value}</div>
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2 py-1 text-xs text-gray-600">
      <span className="text-gray-400">{label}</span>
      <span className="font-medium text-gray-700">{value}</span>
    </span>
  );
}

function Field({ label, children, inline }: { label: string; children: ReactNode; inline?: boolean }) {
  return (
    <div className={inline ? "flex items-center gap-2" : ""}>
      <div className="text-xs font-medium text-gray-500 mb-1">{label}</div>
      {children}
    </div>
  );
}
