"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  Layers, MessageSquareQuote, LayoutTemplate, Scale, Zap, Loader2,
  CheckCircle2, XCircle, ThumbsUp, ThumbsDown, Play, Trash2, TrendingUp,
  GitCompare, Activity, Radio,
} from "lucide-react";
import { dataAskApi, dataSourcesApi, dsDistillApi, formatApiError } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";

interface Stats {
  data_source_id: string;
  examples_positive: number;
  examples_negative: number;
  examples_indexed: number;
  templates_total: number;
  templates_active: number;
  rules_total: number;
  rules_active: number;
  traces_total: number;
  feedback_total: number;
}

interface TrainDayPoint {
  day: string;
  feedback_total: number;
  feedback_correction: number;
  feedback_example: number;
  golden_created: number;
  trace_total: number;
  trace_success: number;
  first_pass_rate: number | null;
  eval_pass_rate: number | null;
}

interface TrainMetrics {
  kpi: {
    feedback_total: number;
    feedback_correction: number;
    feedback_example: number;
    adoption_rate: number | null;
    golden_total: number;
    golden_net_add: number;
    trace_total: number;
    first_pass_rate: number | null;
    memory_hit_rate: number | null;
    eval_runs: number;
    eval_pass_rate: number | null;
    eval_overall: number | null;
    eval_weak: string[];
  };
  series: TrainDayPoint[];
}

interface Attribution {
  data_source_id: string;
  days: number;
  agent: { id: string; name: string | null; production_version: number | null } | null;
  memory: {
    hit_total: number;
    hit_traces: number;
    adopted_true: number;
    adopted_false: number;
    pending: number;
    adopt_rate: number | null;
  };
  adoption_evidence: {
    trace_id: number | null;
    question: string;
    ref: string;
    ref_type: string;
    ref_question: string;
    score: number;
    adopted: boolean;
    feedback_type: string;
  }[];
  eval: {
    has_comparison: boolean;
    after_run_id: number | null;
    after_pass_rate: number | null;
    after_overall: number | null;
    before_run_id: number | null;
    before_pass_rate: number | null;
    before_overall: number | null;
    delta_pp: number | null;
  };
  conclusion: string;
}

interface ShadowDetail {
  question: string;
  with_memory: { success: boolean; sql: string; row_count: number | null; error: string | null };
  without_memory: { success: boolean; sql: string; row_count: number | null; error: string | null };
  same_sql: boolean;
  same_result: boolean;
  conclusion: string;
  duration_ms: number;
}

interface PipelineTask {
  id: number;
  kind: string;
  status: string;
  progress: number;
  detail: Record<string, unknown> | null;
  error: string | null;
  created_at: string | null;
}

interface Pipeline {
  tasks: PipelineTask[];
  eval_runs: {
    id: number;
    trigger: string;
    status: string;
    total: number;
    passed: number;
    overall_score: number | null;
    created_at: string | null;
  }[];
}

interface Example {
  id: string;
  question: string;
  sql_text: string;
  kind: string;
  source: string;
  quality: number;
  indexed: boolean;
}

interface Template {
  id: string;
  name: string;
  intent: string | null;
  framework: string | null;
  sample_questions: string[];
  keywords: string[];
  member_count: number;
  status: string;
  source: string;
}

interface Rule {
  id: string;
  rule_type: string;
  name: string;
  rule_text: string;
  applies_to: string | null;
  status: string;
  confidence: number;
  source: string;
}

interface DataSourceItem {
  id: string;
  name: string;
}

const RULE_TYPE_STYLE: Record<string, string> = {
  caliber: "bg-blue-100 text-blue-700 border-blue-300",
  terminology: "bg-violet-100 text-violet-700 border-violet-300",
  filter: "bg-amber-100 text-amber-700 border-amber-300",
};
const RULE_TYPE_LABEL: Record<string, { zh: string; en: string }> = {
  caliber: { zh: "指标口径", en: "Caliber" },
  terminology: { zh: "术语", en: "Terminology" },
  filter: { zh: "默认过滤", en: "Filter" },
};

export default function KnowledgeDistillPage() {
  const { lang } = useLangStore();
  const [sources, setSources] = useState<DataSourceItem[]>([]);
  const [selectedDs, setSelectedDs] = useState<string>("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [metrics, setMetrics] = useState<TrainMetrics | null>(null);
  const [attrib, setAttrib] = useState<Attribution | null>(null);
  const [examples, setExamples] = useState<Example[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string>("");
  // P2：影子对比 / 训练流水线（SSE）
  const [shadowQ, setShadowQ] = useState("");
  const [shadowBusy, setShadowBusy] = useState(false);
  const [shadowTaskId, setShadowTaskId] = useState<number | null>(() => {
    // 支持 ?shadow=<taskId> 直达历史影子对比结果（回看/分享链接）
    if (typeof window === "undefined") return null;
    const v = new URLSearchParams(window.location.search).get("shadow");
    return v && /^\d+$/.test(v) ? Number(v) : null;
  });
  const [shadow, setShadow] = useState<ShadowDetail | null>(null);
  const [pipeline, setPipeline] = useState<Pipeline | null>(null);
  const [pipeLive, setPipeLive] = useState(false);

  const t = lang === "zh"
    ? {
        title: "知识蒸馏",
        subtitle: "示例库 · 分析模板 · 业务规则 —— 让问数越用越准",
        examples: "示例库（Few-shot RAG）",
        templates: "分析模板",
        rules: "业务规则",
        distillExamples: "蒸馏示例",
        mineTemplates: "挖掘模板",
        mineRules: "蒸馏规则",
        positive: "正例",
        negative: "负例",
        indexed: "已向量化",
        templatesTotal: "模板总数",
        templatesActive: "已启用",
        rulesTotal: "规则总数",
        rulesActive: "已生效",
        noSource: "请选择数据源",
        noExamples: "暂无示例 — 在问数答案卡片点「有用 / 存为示例 / 纠正SQL」后蒸馏",
        noTemplates: "暂无模板 — 高频问题样本达到 3 条后可挖掘",
        noRules: "暂无规则 — 提供纠错（纠正SQL）后可蒸馏",
        activate: "生效",
        reject: "驳回",
        active: "已生效",
        rejected: "已驳回",
        candidate: "候选",
        enable: "启用",
        disable: "停用",
        draft: "草稿",
        delete: "删除",
        memberCount: "样本",
        confidence: "置信度",
        triggering: "任务已启动，稍后刷新查看",
        refresh: "刷新",
        loading: "加载中...",
        dashTitle: "训练度量看板",
        dashSub: "四条主线 · 近 30 天 · 与库内直算口径一致",
        adoption: "反馈采纳率",
        adoptionHint: "(纠正 + 存示例) / 反馈总数",
        goldenAdd: "金标净增",
        goldenAddHint: "30 天新增问数记忆",
        evalPass: "评测通过率",
        evalPassHint: "最近一次回归评测 passed / total",
        firstPass: "首次正确率",
        firstPassHint: "(轨迹 - 被纠正 - 失败) / 轨迹总数",
        memoryHit: "记忆命中率",
        noMetrics: "暂无度量数据",
        weakTitle: "评测弱项（点击一键就弱项提问）",
        trendGolden: "每日金标新增",
        trendFeedback: "每日反馈量",
        attrTitle: "效果归因（P2）",
        attrSub: "命中记忆 → 是否采纳 → 通过率变化，全部可复算",
        attrAgent: "归属智能体",
        attrProd: "生产版本",
        attrHit: "命中记忆",
        attrAdopt: "采纳率",
        attrEvalDelta: "评测通过率变化",
        attrNoEval: "暂无前后两轮评测",
        attrEvidence: "采纳证据（最近）",
        attrRef: "命中记忆",
        attrFb: "反馈",
        attrNone: "暂无已判定的命中记录",
        shadowTitle: "影子对比（P2）",
        shadowSub: "同一问题：未更新记忆 vs 已更新记忆 双路生成",
        shadowPh: "输入要对比的问题，如：最近3天销售额是多少",
        shadowRun: "启动对比",
        shadowRunning: "对比中（两次真实生成，约 30-120 秒）...",
        shadowWith: "已更新记忆",
        shadowWithout: "未更新记忆",
        shadowRows: "行",
        shadowSameSql: "SQL 相同",
        shadowDiffSql: "SQL 不同",
        shadowSameRes: "结果一致",
        shadowDiffRes: "结果不同",
        pipeTitle: "训练流水线（实时）",
        pipeSub: "蒸馏 / 影子对比 / 评测 / 晋升 进度实时推送",
        pipeTask: "任务",
        pipeEval: "评测",
        pipeEmpty: "暂无训练事件",
        kindExample: "蒸馏",
        kindTemplate: "模板",
        kindRule: "规则",
        kindShadow: "影子对比",
        kindPromote: "进化/晋升",
        stQueued: "排队中",
        stRunning: "进行中",
        stDone: "完成",
        stFailed: "失败",
        evolveBtn: "启动进化闭环",
        pipeLive: "实时",
        pipeOff: "已断开",
      }
    : {
        title: "Knowledge Distilling",
        subtitle: "Example library · Analysis templates · Business rules — smarter with every question",
        examples: "Example Library (Few-shot RAG)",
        templates: "Analysis Templates",
        rules: "Business Rules",
        distillExamples: "Distill Examples",
        mineTemplates: "Mine Templates",
        mineRules: "Distill Rules",
        positive: "Positive",
        negative: "Negative",
        indexed: "Indexed",
        templatesTotal: "Templates",
        templatesActive: "Active",
        rulesTotal: "Rules",
        rulesActive: "Activated",
        noSource: "Select a data source",
        noExamples: "No examples — like / save-as-example / correct SQL on an answer to distill",
        noTemplates: "No templates — mining starts once 3+ similar questions exist",
        noRules: "No rules — provide SQL corrections to distill",
        activate: "Activate",
        reject: "Reject",
        active: "Active",
        rejected: "Rejected",
        candidate: "Candidate",
        enable: "Enable",
        disable: "Disable",
        draft: "Draft",
        delete: "Delete",
        memberCount: "Members",
        confidence: "Confidence",
        triggering: "Task started, refresh shortly",
        refresh: "Refresh",
        loading: "Loading...",
        dashTitle: "Training Metrics",
        dashSub: "Four KPIs · last 30 days · verifiable by direct SQL",
        adoption: "Feedback Adoption",
        adoptionHint: "(corrections + saved examples) / total feedback",
        goldenAdd: "Golden Net Add",
        goldenAddHint: "new memory entries in 30d",
        evalPass: "Eval Pass Rate",
        evalPassHint: "latest regression run passed / total",
        firstPass: "First-pass Accuracy",
        firstPassHint: "(traces - corrected - failed) / traces",
        memoryHit: "Memory Hit Rate",
        noMetrics: "No metrics yet",
        weakTitle: "Weak categories (click to ask in chat)",
        trendGolden: "Daily golden adds",
        trendFeedback: "Daily feedback",
        attrTitle: "Effect Attribution (P2)",
        attrSub: "memory hit → adoption → pass-rate change, all verifiable",
        attrAgent: "Agent",
        attrProd: "Production version",
        attrHit: "Memory hits",
        attrAdopt: "Adoption rate",
        attrEvalDelta: "Eval pass-rate change",
        attrNoEval: "No before/after eval runs yet",
        attrEvidence: "Adoption evidence (recent)",
        attrRef: "Matched memory",
        attrFb: "Feedback",
        attrNone: "No judged hits yet",
        shadowTitle: "Shadow Compare (P2)",
        shadowSub: "Same question: without-memory vs with-memory, dual generation",
        shadowPh: "Question to compare, e.g. sales of last 3 days",
        shadowRun: "Run compare",
        shadowRunning: "Comparing (two real generations, ~30-120s)...",
        shadowWith: "With memory",
        shadowWithout: "Without memory",
        shadowRows: "rows",
        shadowSameSql: "Same SQL",
        shadowDiffSql: "SQL differs",
        shadowSameRes: "Same result",
        shadowDiffRes: "Result differs",
        pipeTitle: "Training Pipeline (live)",
        pipeSub: "Distill / shadow / eval / promote streamed in real time",
        pipeTask: "Task",
        pipeEval: "Eval",
        pipeEmpty: "No training events yet",
        kindExample: "Distill",
        kindTemplate: "Template",
        kindRule: "Rule",
        kindShadow: "Shadow",
        kindPromote: "Evolve",
        stQueued: "Queued",
        stRunning: "Running",
        stDone: "Done",
        stFailed: "Failed",
        evolveBtn: "Run evolution",
        pipeLive: "LIVE",
        pipeOff: "Disconnected",
      };

  useEffect(() => {
    dataSourcesApi.list().then((res) => {
      const items: DataSourceItem[] = res.data?.items || res.data || [];
      setSources(items);
      if (items.length > 0) {
        // 支持 ?ds=<id> 直达指定数据源（可分享/收藏视图）
        const qs = new URLSearchParams(window.location.search).get("ds");
        const found = qs ? items.find((s) => s.id === qs) : null;
        setSelectedDs(found ? found.id : items[0].id);
      }
    }).catch(() => setSources([]));
  }, []);

  const fetchAll = useCallback(async (ds: string) => {
    if (!ds) return;
    setLoading(true);
    try {
      const [s, e, tp, r] = await Promise.all([
        dsDistillApi.stats(ds),
        dsDistillApi.examples(ds),
        dsDistillApi.templates(ds),
        dsDistillApi.rules(ds),
      ]);
      setStats(s.data);
      setExamples(e.data.items || e.data || []);
      setTemplates(tp.data.items || tp.data || []);
      setRules(r.data.items || r.data || []);
      dsDistillApi.trainMetrics(ds, 30)
        .then((m) => setMetrics(m.data))
        .catch(() => setMetrics(null));
      dsDistillApi.attribution(ds, 30)
        .then((a) => setAttrib(a.data))
        .catch(() => setAttrib(null));
    } catch (err) {
      setToast(formatApiError(err, "加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(selectedDs); }, [selectedDs, fetchAll]);

  // P2 训练流水线：SSE 实时快照流（fetch 流式读取，带 Authorization 头）
  useEffect(() => {
    if (!selectedDs) return;
    const ctrl = new AbortController();
    setPipeline(null);
    setPipeLive(false);
    (async () => {
      try {
        const { getAuthToken } = await import("@/lib/authStore");
        const token = getAuthToken();
        const res = await fetch(
          `/api/v1/data-ask/train/events?sid=${encodeURIComponent(selectedDs)}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: ctrl.signal,
          },
        );
        if (!res.ok || !res.body) return;
        setPipeLive(true);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const line = frame.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            try {
              const snap = JSON.parse(line.slice(6)) as Pipeline & { event: string };
              setPipeline({ tasks: snap.tasks || [], eval_runs: snap.eval_runs || [] });
            } catch {
              /* 忽略坏帧 */
            }
          }
        }
        setPipeLive(false);
      } catch {
        setPipeLive(false);
      }
    })();
    return () => ctrl.abort();
  }, [selectedDs]);

  // P2 影子对比任务轮询（复用 train/tasks 端点）
  useEffect(() => {
    if (!shadowTaskId) return;
    let stopped = false;
    let ticks = 0;
    const poll = async () => {
      try {
        const { data } = await dataAskApi.trainTask(shadowTaskId);
        if (!stopped && data?.status === "done" && data?.detail?.question) {
          setShadow(data.detail as ShadowDetail);
          setShadowBusy(false);
          return;
        }
        if (!stopped && data?.status === "failed") {
          setShadowBusy(false);
          return;
        }
      } catch {
        /* 轮询失败不打扰 */
      }
      ticks += 1;
      if (ticks < 80 && !stopped) window.setTimeout(poll, 2000);
      else if (!stopped) setShadowBusy(false);
    };
    void poll();
    return () => {
      stopped = true;
    };
  }, [shadowTaskId]);

  const runShadow = async () => {
    const q = shadowQ.trim();
    if (!q || shadowBusy) return;
    setShadowBusy(true);
    setShadow(null);
    try {
      const { data } = await dsDistillApi.shadowCompare(selectedDs, q);
      setShadowTaskId(data?.task_id ?? null);
      setToast(t.shadowRunning);
    } catch (err) {
      setShadowBusy(false);
      setToast(formatApiError(err, "启动失败"));
    }
  };

  const runEvolve = async () => {
    try {
      await dsDistillApi.evolve(selectedDs);
      setToast(t.evolveBtn + " · " + t.stQueued);
    } catch (err) {
      setToast(formatApiError(err, "操作失败"));
    }
  };

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      setToast(t.triggering);
      setTimeout(() => fetchAll(selectedDs), 8000);
    } catch (err) {
      setToast(formatApiError(err, "操作失败"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-7xl p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Layers className="h-7 w-7 text-indigo-500" />
            {t.title}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t.subtitle}</p>
        </div>
        <button
          onClick={() => fetchAll(selectedDs)}
          className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm hover:border-indigo-300 hover:text-indigo-600"
        >
          {t.refresh}
        </button>
      </div>

      {/* Data Source Selector */}
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
          {metrics && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="mb-3 flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-emerald-500" />
                <div>
                  <div className="text-sm font-semibold text-gray-900">{t.dashTitle}</div>
                  <div className="text-[11px] text-gray-400">{t.dashSub}</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.adoption}</div>
                  <div className="mt-0.5 text-xl font-bold text-blue-600">
                    {metrics.kpi.adoption_rate != null ? `${(metrics.kpi.adoption_rate * 100).toFixed(1)}%` : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">{t.adoptionHint}</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.goldenAdd}</div>
                  <div className="mt-0.5 text-xl font-bold text-emerald-600">
                    {metrics.kpi.golden_net_add}
                    <span className="ml-1 text-[11px] font-normal text-gray-400">/ {metrics.kpi.golden_total}</span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">{t.goldenAddHint}</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.evalPass}</div>
                  <div className="mt-0.5 text-xl font-bold text-violet-600">
                    {metrics.kpi.eval_pass_rate != null ? `${(metrics.kpi.eval_pass_rate * 100).toFixed(1)}%` : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">{t.evalPassHint}</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.firstPass}</div>
                  <div className="mt-0.5 text-xl font-bold text-amber-600">
                    {metrics.kpi.first_pass_rate != null ? `${(metrics.kpi.first_pass_rate * 100).toFixed(1)}%` : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">{t.firstPassHint}</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.memoryHit}</div>
                  <div className="mt-0.5 text-xl font-bold text-sky-600">
                    {metrics.kpi.memory_hit_rate != null ? `${(metrics.kpi.memory_hit_rate * 100).toFixed(1)}%` : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">{metrics.kpi.trace_total} traces · 30d</div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                {(
                  [
                    { label: t.trendGolden, key: "golden_created", cls: "bg-emerald-500/70" },
                    { label: t.trendFeedback, key: "feedback_total", cls: "bg-blue-500/70" },
                  ] as const
                ).map((cfg) => {
                  const maxV = Math.max(...metrics.series.map((p) => p[cfg.key]), 1);
                  return (
                    <div key={cfg.key}>
                      <div className="mb-1 text-[11px] text-gray-500">{cfg.label}</div>
                      <div className="flex h-14 items-end gap-[2px]">
                        {metrics.series.map((p) => (
                          <div
                            key={p.day}
                            title={`${p.day} · ${p[cfg.key]}`}
                            className={cfg.cls}
                            style={{ height: `${Math.max((p[cfg.key] / maxV) * 100, 3)}%`, flex: 1 }}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {metrics.kpi.eval_weak.length > 0 && (
                <div className="mt-4">
                  <div className="mb-1 text-[11px] text-gray-500">{t.weakTitle}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {metrics.kpi.eval_weak.map((w) => (
                      <Link
                        key={w}
                        href={`/chat?data_source_id=${selectedDs}&question=${encodeURIComponent(w)}`}
                        className="rounded-full bg-rose-50 px-2.5 py-1 text-[11px] text-rose-600 transition hover:bg-rose-100"
                      >
                        {w} →
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* P2：效果归因 */}
          {attrib && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-amber-500" />
                  <div>
                    <div className="text-sm font-semibold text-gray-900">{t.attrTitle}</div>
                    <div className="text-[11px] text-gray-400">{t.attrSub}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[11px]">
                  {attrib.agent && (
                    <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-indigo-600">
                      {t.attrAgent}: {attrib.agent.name || attrib.agent.id.slice(0, 8)}
                      {attrib.agent.production_version != null && ` · v${attrib.agent.production_version}`}
                    </span>
                  )}
                  <button
                    onClick={() => void runEvolve()}
                    className="rounded-lg border border-violet-200 px-2.5 py-1 text-violet-600 transition hover:bg-violet-50"
                  >
                    {t.evolveBtn}
                  </button>
                </div>
              </div>

              <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[13px] leading-relaxed text-amber-800">
                {attrib.conclusion}
              </div>

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.attrHit}</div>
                  <div className="mt-0.5 text-xl font-bold text-sky-600">{attrib.memory.hit_total}</div>
                  <div className="mt-0.5 text-[10px] text-gray-400">{attrib.memory.hit_traces} traces</div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.attrAdopt}</div>
                  <div className="mt-0.5 text-xl font-bold text-emerald-600">
                    {attrib.memory.adopt_rate != null ? `${(attrib.memory.adopt_rate * 100).toFixed(1)}%` : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">
                    +{attrib.memory.adopted_true} / -{attrib.memory.adopted_false} / ?{attrib.memory.pending}
                  </div>
                </div>
                <div className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{t.attrEvalDelta}</div>
                  <div className={`mt-0.5 text-xl font-bold ${
                    attrib.eval.delta_pp == null ? "text-gray-400"
                      : attrib.eval.delta_pp > 0 ? "text-emerald-600"
                        : attrib.eval.delta_pp < 0 ? "text-rose-500" : "text-gray-600"
                  }`}>
                    {attrib.eval.delta_pp != null
                      ? `${attrib.eval.delta_pp > 0 ? "+" : ""}${attrib.eval.delta_pp} pp`
                      : "—"}
                  </div>
                  <div className="mt-0.5 text-[10px] text-gray-400">
                    {attrib.eval.has_comparison
                      ? `${((attrib.eval.before_pass_rate || 0) * 100).toFixed(1)}% → ${((attrib.eval.after_pass_rate || 0) * 100).toFixed(1)}%`
                      : t.attrNoEval}
                  </div>
                </div>
              </div>

              <div className="mt-3">
                <div className="mb-1 text-[11px] text-gray-500">{t.attrEvidence}</div>
                {attrib.adoption_evidence.length === 0 ? (
                  <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-400">{t.attrNone}</div>
                ) : (
                  <div className="overflow-hidden rounded-lg border border-gray-100">
                    {attrib.adoption_evidence.slice(0, 5).map((ev, i) => (
                      <div key={`${ev.trace_id}-${i}`} className="flex items-start gap-2 border-b border-gray-50 px-3 py-2 last:border-0">
                        <span className={`mt-0.5 inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] ${
                          ev.adopted ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-500"
                        }`}>
                          {ev.adopted ? <ThumbsUp className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
                          {ev.feedback_type || (ev.adopted ? "like" : "dislike")}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-xs text-gray-700">{ev.question}</div>
                          <div className="truncate text-[10px] text-gray-400">
                            {t.attrRef}: {ev.ref_question || ev.ref} · {ev.score.toFixed(2)} · trace#{ev.trace_id}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* P2：影子对比 */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2">
              <GitCompare className="h-4 w-4 text-cyan-500" />
              <div>
                <div className="text-sm font-semibold text-gray-900">{t.shadowTitle}</div>
                <div className="text-[11px] text-gray-400">{t.shadowSub}</div>
              </div>
            </div>
            <div className="flex gap-2">
              <input
                value={shadowQ}
                onChange={(e) => setShadowQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runShadow();
                }}
                placeholder={t.shadowPh}
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-cyan-400"
              />
              <button
                onClick={() => void runShadow()}
                disabled={shadowBusy || !shadowQ.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-sm text-white transition hover:bg-cyan-700 disabled:opacity-50"
              >
                {shadowBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {shadowBusy ? t.stRunning : t.shadowRun}
              </button>
            </div>

            {shadow && (
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className={`rounded-full px-2 py-0.5 ${shadow.same_sql ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>
                    {shadow.same_sql ? t.shadowSameSql : t.shadowDiffSql}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 ${shadow.same_result ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-500"}`}>
                    {shadow.same_result ? t.shadowSameRes : t.shadowDiffRes}
                  </span>
                  <span className="text-gray-400">{shadow.duration_ms}ms</span>
                </div>
                <div className="rounded-lg bg-amber-50 px-3 py-2 text-[13px] text-amber-800">{shadow.conclusion}</div>
                <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                  {(
                    [
                      { label: t.shadowWith, item: shadow.with_memory, cls: "border-cyan-200" },
                      { label: t.shadowWithout, item: shadow.without_memory, cls: "border-gray-200" },
                    ] as const
                  ).map((cfg) => (
                    <div key={cfg.label} className={`rounded-lg border ${cfg.cls} p-2.5`}>
                      <div className="mb-1 flex items-center justify-between text-[11px]">
                        <span className="font-medium text-gray-600">{cfg.label}</span>
                        <span className="text-gray-400">
                          {cfg.item.row_count != null ? `${cfg.item.row_count} ${t.shadowRows}` : ""}
                        </span>
                      </div>
                      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-900 p-2 font-mono text-[10px] leading-relaxed text-slate-100">
                        {cfg.item.sql || cfg.item.error || "-"}
                      </pre>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* P2：训练流水线（SSE 实时） */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-emerald-500" />
                <div>
                  <div className="text-sm font-semibold text-gray-900">{t.pipeTitle}</div>
                  <div className="text-[11px] text-gray-400">{t.pipeSub}</div>
                </div>
              </div>
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] ${
                pipeLive ? "bg-emerald-50 text-emerald-600" : "bg-gray-100 text-gray-400"
              }`}>
                <Radio className={`h-3 w-3 ${pipeLive ? "animate-pulse" : ""}`} />
                {pipeLive ? t.pipeLive : t.pipeOff}
              </span>
            </div>

            {(!pipeline || (pipeline.tasks.length === 0 && pipeline.eval_runs.length === 0)) ? (
              <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-400">{t.pipeEmpty}</div>
            ) : (
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                <div>
                  <div className="mb-1 text-[11px] text-gray-500">{t.pipeTask}</div>
                  <div className="space-y-1">
                    {pipeline.tasks.map((tk) => {
                      const kindLabel =
                        tk.kind === "shadow" ? t.kindShadow
                          : tk.kind === "promote" ? t.kindPromote
                            : tk.kind === "template" ? t.kindTemplate
                              : tk.kind === "rule" ? t.kindRule : t.kindExample;
                      const stLabel =
                        tk.status === "done" ? t.stDone
                          : tk.status === "running" ? t.stRunning
                            : tk.status === "failed" ? t.stFailed : t.stQueued;
                      const reason =
                        tk.detail && typeof tk.detail === "object"
                          ? String((tk.detail as Record<string, unknown>).reason
                            || (tk.detail as Record<string, unknown>).conclusion
                            || (tk.kind === "promote" ? (tk.detail as Record<string, unknown>).reason : "") || "")
                          : "";
                      return (
                        <div key={tk.id} className="flex items-start gap-2 rounded-lg bg-gray-50 px-2.5 py-1.5">
                          <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
                            tk.status === "done" ? "bg-emerald-500"
                              : tk.status === "running" ? "bg-blue-500 animate-pulse"
                                : tk.status === "failed" ? "bg-rose-500" : "bg-gray-300"
                          }`} />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 text-xs">
                              <span className="font-medium text-gray-700">#{tk.id} {kindLabel}</span>
                              <span className={
                                tk.status === "failed" ? "text-rose-500"
                                  : tk.status === "done" ? "text-emerald-600" : "text-gray-400"
                              }>{stLabel}</span>
                              <span className="ml-auto text-[10px] text-gray-300">
                                {(tk.created_at || "").slice(5, 16).replace("T", " ")}
                              </span>
                            </div>
                            {reason && (
                              <div className="truncate text-[10px] text-gray-400" title={reason}>{reason}</div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-[11px] text-gray-500">{t.pipeEval}</div>
                  <div className="space-y-1">
                    {pipeline.eval_runs.length === 0 ? (
                      <div className="rounded-lg bg-gray-50 px-2.5 py-1.5 text-xs text-gray-400">—</div>
                    ) : (
                      pipeline.eval_runs.map((er) => (
                        <div key={er.id} className="flex items-center gap-2 rounded-lg bg-gray-50 px-2.5 py-1.5 text-xs">
                          <span className="font-medium text-gray-700">#{er.id}</span>
                          <span className="text-gray-500">{er.trigger}</span>
                          <span className={er.status === "done" ? "text-emerald-600" : "text-gray-400"}>{er.status}</span>
                          <span className="ml-auto font-mono text-[10px] text-gray-500">
                            {er.passed}/{er.total}
                            {er.overall_score != null && ` · ${(er.overall_score * 100).toFixed(0)}分`}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <StatCard label={t.positive} value={stats?.examples_positive ?? 0} accent="text-emerald-600" />
            <StatCard label={t.negative} value={stats?.examples_negative ?? 0} accent="text-rose-500" />
            <StatCard label={t.indexed} value={stats?.examples_indexed ?? 0} accent="text-indigo-500" />
            <StatCard label={t.templatesTotal} value={stats?.templates_total ?? 0} accent="text-blue-500" />
            <StatCard label={t.rulesTotal} value={stats?.rules_total ?? 0} accent="text-violet-500" />
            <StatCard label={t.rulesActive} value={stats?.rules_active ?? 0} accent="text-amber-500" />
          </div>

          <div className="flex flex-wrap gap-3">
            <ActionButton
              icon={<MessageSquareQuote className="h-4 w-4" />}
              label={t.distillExamples}
              busy={busy === "ex"}
              onClick={() => run("ex", () => dsDistillApi.distillExamples(selectedDs))}
            />
            <ActionButton
              icon={<LayoutTemplate className="h-4 w-4" />}
              label={t.mineTemplates}
              busy={busy === "tp"}
              onClick={() => run("tp", () => dsDistillApi.mineTemplates(selectedDs))}
            />
            <ActionButton
              icon={<Scale className="h-4 w-4" />}
              label={t.mineRules}
              busy={busy === "rl"}
              onClick={() => run("rl", () => dsDistillApi.mineRules(selectedDs))}
            />
          </div>

          {toast && (
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm text-indigo-700">
              {toast}
            </div>
          )}

          {loading && (
            <div className="flex items-center gap-2 text-gray-400 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" /> {t.loading}
            </div>
          )}

          {/* Examples */}
          <Section icon={<MessageSquareQuote className="h-5 w-5 text-indigo-500" />} title={t.examples} count={examples.length}>
            {examples.length === 0 ? (
              <Empty text={t.noExamples} />
            ) : (
              <div className="divide-y divide-gray-50">
                {examples.map((ex) => (
                  <div key={ex.id} className="flex items-start gap-3 px-4 py-3 hover:bg-gray-50">
                    <span className={`mt-0.5 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border whitespace-nowrap ${
                      ex.kind === "positive"
                        ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                        : "bg-rose-50 text-rose-600 border-rose-300"
                    }`}>
                      {ex.kind === "positive" ? <ThumbsUp className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
                      {ex.kind === "positive" ? t.positive : t.negative}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-gray-800">{ex.question}</div>
                      <div className="mt-1 font-mono text-xs text-gray-500 truncate" title={ex.sql_text}>
                        {ex.sql_text}
                      </div>
                      <div className="text-xs text-gray-400 mt-0.5">
                        {ex.source}
                        {ex.indexed ? ` · ${t.indexed}` : ""}
                        {` · ${ex.quality.toFixed(2)}`}
                      </div>
                    </div>
                    <button
                      onClick={() => run("del", async () => {
                        await dsDistillApi.deleteExample(ex.id);
                        await fetchAll(selectedDs);
                      })}
                      className="p-1.5 rounded text-gray-400 hover:text-rose-500 hover:bg-rose-50"
                      title={t.delete}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Templates */}
          <Section icon={<LayoutTemplate className="h-5 w-5 text-blue-500" />} title={t.templates} count={templates.length}>
            {templates.length === 0 ? (
              <Empty text={t.noTemplates} />
            ) : (
              <div className="divide-y divide-gray-50">
                {templates.map((tp) => (
                  <div key={tp.id} className="px-4 py-3 hover:bg-gray-50">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-800">{tp.name}</span>
                      <span className={`px-2 py-0.5 rounded-full text-xs border ${
                        tp.status === "active"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                          : "bg-gray-100 text-gray-600 border-gray-300"
                      }`}>
                        {tp.status === "active" ? t.active : t.draft}
                      </span>
                      <span className="text-xs text-gray-400">{t.memberCount}: {tp.member_count}</span>
                      <button
                        onClick={() => run("tp-up", () => dsDistillApi.updateTemplate(tp.id, {
                          status: tp.status === "active" ? "draft" : "active",
                        }))}
                        className="ml-auto px-2 py-1 rounded text-xs text-gray-600 hover:bg-indigo-50 hover:text-indigo-600"
                      >
                        {tp.status === "active" ? t.disable : t.enable}
                      </button>
                    </div>
                    {tp.intent && <div className="text-xs text-gray-500 mt-1">{tp.intent}</div>}
                    {tp.framework && (
                      <div className="mt-1.5 whitespace-pre-wrap rounded-lg bg-gray-50 p-2.5 text-xs text-gray-600">
                        {tp.framework}
                      </div>
                    )}
                    {tp.sample_questions.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {tp.sample_questions.slice(0, 6).map((q, i) => (
                          <span key={i} className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-600">{q}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* Rules */}
          <Section icon={<Scale className="h-5 w-5 text-violet-500" />} title={t.rules} count={rules.length}>
            {rules.length === 0 ? (
              <Empty text={t.noRules} />
            ) : (
              <div className="divide-y divide-gray-50">
                {rules.map((r) => (
                  <div key={r.id} className="px-4 py-3 hover:bg-gray-50">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full text-xs border ${RULE_TYPE_STYLE[r.rule_type] || ""}`}>
                        {RULE_TYPE_LABEL[r.rule_type]?.[lang] || r.rule_type}
                      </span>
                      <span className="font-medium text-gray-800">{r.name}</span>
                      <span className={`px-2 py-0.5 rounded-full text-xs border ${
                        r.status === "active"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-300"
                          : r.status === "rejected"
                            ? "bg-gray-100 text-gray-500 border-gray-300"
                            : "bg-amber-50 text-amber-700 border-amber-300"
                      }`}>
                        {r.status === "active" ? t.active : r.status === "rejected" ? t.rejected : t.candidate}
                      </span>
                      <span className="text-xs text-gray-400">{t.confidence}: {r.confidence.toFixed(2)}</span>
                      <div className="ml-auto flex items-center gap-2">
                        {r.status !== "active" && (
                          <button
                            onClick={() => run("rl-act", () => dsDistillApi.activateRule(r.id))}
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-emerald-600 hover:bg-emerald-50"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5" /> {t.activate}
                          </button>
                        )}
                        {r.status !== "rejected" && (
                          <button
                            onClick={() => run("rl-rej", () => dsDistillApi.rejectRule(r.id))}
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-500 hover:bg-gray-100"
                          >
                            <XCircle className="h-3.5 w-3.5" /> {t.reject}
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="text-sm text-gray-600 mt-1">{r.rule_text}</div>
                    {r.applies_to && <div className="text-xs text-gray-400 mt-0.5">{r.applies_to}</div>}
                  </div>
                ))}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className={`text-2xl font-bold ${accent}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}

function ActionButton({
  icon, label, busy, onClick,
}: { icon: ReactNode; label: string; busy: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-indigo-500 text-white text-sm hover:bg-indigo-600 disabled:opacity-50"
    >
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {label}
    </button>
  );
}

function Section({
  icon, title, count, children,
}: { icon: ReactNode; title: string; count: number; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <h2 className="flex items-center gap-2 text-lg font-semibold p-5 pb-3">
        {icon}
        {title}
        <span className="text-sm font-normal text-gray-400">({count})</span>
      </h2>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2 px-5 pb-6 text-sm text-gray-400">
      <Play className="h-4 w-4" /> {text}
    </div>
  );
}
