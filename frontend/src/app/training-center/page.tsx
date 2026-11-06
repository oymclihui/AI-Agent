"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Workflow, Play, RefreshCw, Loader2, CheckCircle2, XCircle,
  AlertTriangle, Database, Sparkles, Rocket, History, MessageSquare,
  FlaskConical, ShieldCheck, ChevronRight, BrainCircuit,
} from "lucide-react";
import { dataAskApi, dataSourcesApi, dsDistillApi, dsEvalApi, formatApiError, trainCenterApi } from "@/lib/api";
import { getAuthToken } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";

// ── 类型（与 app/schemas/train_center.py 对齐）────────────────

interface DataSourceItem {
  id: string;
  name: string;
  driver?: string;
  agent_id?: string | null;
  can_manage?: boolean;
}

interface DistillStats {
  examples_positive: number;
  examples_negative: number;
  examples_indexed: number;
  templates_active: number;
  rules_active: number;
  traces_total: number;
  feedback_total: number;
}

interface EvalQuality {
  eval_set_size: number;
  latest_run: {
    id: number;
    overall_score: number | null;
    sql_success_rate: number | null;
    consistency_rate: number | null;
    total: number;
    passed: number;
    created_at?: string | null;
  } | null;
}

interface FeedbackStatus {
  feedback_id: number;
  question?: string | null;
  feedback_type: string;
  task_id?: number | null;
  task_status?: string | null;
  queued: boolean;
  distilled: boolean;
  effective: boolean;
  example_indexed: boolean;
  steps: { key: string; label: string; done: boolean }[];
  message: string;
  created_at?: string | null;
}

interface TrainStage {
  key: string;
  label: string;
  status: string;
  progress: number;
  message?: string | null;
  detail?: Record<string, any> | null;
  started_at?: string | null;
  finished_at?: string | null;
}

interface PromptCandidate {
  id: string;
  agent_id: string;
  field: string;
  before: string;
  after: string;
  reason?: string | null;
  status: string;
  score_delta?: number | null;
  created_at?: string | null;
}

interface TrainJob {
  id: string;
  target_type: string;
  target_id: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  stages: TrainStage[];
  detail?: Record<string, any>;
  error?: string | null;
  note?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

const STAGE_STATUS_CLS: Record<string, string> = {
  done: "text-emerald-600 border-emerald-300 bg-emerald-50",
  running: "text-blue-600 border-blue-300 bg-blue-50",
  failed: "text-rose-600 border-rose-300 bg-rose-50",
  skipped: "text-gray-500 border-gray-300 bg-gray-50",
  pending: "text-gray-400 border-gray-200 bg-white",
};

const JOB_STATUS_CLS: Record<string, string> = {
  done: "bg-emerald-50 text-emerald-700 border-emerald-200",
  running: "bg-blue-50 text-blue-700 border-blue-200",
  queued: "bg-amber-50 text-amber-700 border-amber-200",
  partial: "bg-orange-50 text-orange-700 border-orange-200",
  failed: "bg-rose-50 text-rose-700 border-rose-200",
};

function rate(v: number | null | undefined): string {
  return v == null ? "—" : `${(Number(v) * 100).toFixed(1)}%`;
}

function score(v: number | null | undefined): string {
  return v == null ? "—" : Number(v).toFixed(4);
}

export default function TrainingCenterPage() {
  const { lang } = useLangStore();
  const [sources, setSources] = useState<DataSourceItem[]>([]);
  const [selectedDs, setSelectedDs] = useState("");
  const [stats, setStats] = useState<DistillStats | null>(null);
  const [quality, setQuality] = useState<EvalQuality | null>(null);
  const [feedbacks, setFeedbacks] = useState<FeedbackStatus[]>([]);
  const [jobs, setJobs] = useState<TrainJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string>("");
  const [liveJob, setLiveJob] = useState<TrainJob | null>(null);
  const [kind, setKind] = useState<"full" | "distill" | "eval" | "prompt" | "trajectory">("full");
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [toast, setToast] = useState("");
  const [liveConnected, setLiveConnected] = useState(false);
  // P4: RL 导出
  const [rlExports, setRlExports] = useState<any[]>([]);
  const [rlRange, setRlRange] = useState<"all" | "failed" | "success">("all");
  const [rlRule, setRlRule] = useState("success=+1.0;invalid=-0.5;clarify=+0.2");
  const [rlExporting, setRlExporting] = useState(false);

  const t = lang === "zh"
    ? {
        title: "训练中心",
        subtitle: "选对象 → 喂料 → 训练 → 验证 → 上线：一条流水线把反馈变成能力",
        refresh: "刷新",
        noSource: "请选择数据源",
        step1: "选对象",
        step2: "喂料",
        step3: "训练",
        step4: "验证",
        step5: "上线",
        target: "训练对象",
        agentBound: "已绑定智能体",
        agentNone: "未绑定智能体（候选生成 / 上线将跳过）",
        signal: "训练信号",
        traces: "问数轨迹",
        feedback: "用户反馈",
        examples: "蒸馏示例",
        templates: "分析套路",
        rules: "业务习惯",
        evalSet: "回归考题",
        recentFeedback: "最近反馈的训练状态",
        noFeedback: "暂无反馈 — 在问数页面点「有用 / 纠正SQL / 存为示例」即可喂料",
        plan: "选择训练强度",
        planFull: "完整训练（蒸馏 → 建考题 → 候选 → 评测 → 上线）",
        planDistill: "只蒸馏（反馈 → 示例 / 套路 / 规则）",
        planEval: "只验证（建考题 → 回归评测 → 上线判定）",
        planPrompt: "提示词优化（GEPA 反思改写 role/goal/backstory → 评测门禁）",
        planTrajectory: "轨迹训练（问题→计划→工具调用→结果标准化 → 多轮指标 + 沙箱回放 → 配置固化）",
        trajTitle: "多轮轨迹指标",
        trajRuns: "标准化轨迹",
        trajToolAcc: "工具选择准确率",
        trajInvalid: "无效调用率",
        trajRounds: "平均轮数",
        trajSuccess: "任务成功率",
        trajReward: "平均奖励",
        trajClarify: "澄清收敛率",
        trajClarifyTrigger: "澄清触发率",
        trajNoSample: "无样本",
        replayTitle: "沙箱回放对比",
        replayChanged: "动作变化",
        replayCorpus: "回放语料",
        replayOld: "现配置",
        replayNew: "候选配置",
        replayActionOld: "旧动作",
        replayActionNew: "新动作",
        replayNoDiff: "回放无动作差异（配置已在前沿）",
        actionClarify: "反问",
        actionDirect: "直答",
        rlTitle: "RL 数据导出",
        rlDesc: "把标准化轨迹按规则奖励打成 JSONL，供外部 ART / verl 训练",
        rlRange: "导出范围",
        rlRangeAll: "全部轨迹",
        rlRangeFailed: "仅失败",
        rlRangeSuccess: "仅成功",
        rlRewardRule: "奖励规则",
        rlExport: "导出 RL 数据",
        rlExporting: "导出中...",
        rlHistory: "导出记录",
        rlEmpty: "暂无导出记录",
        rlDownload: "下载",
        rlRows: "行数",
        start: "开始训练",
        starting: "提交中...",
        pipeline: "训练流水线",
        noJob: "尚无训练工单 — 选择强度后点「开始训练」",
        progress: "总进度",
        live: "实时",
        offline: "未连接",
        history: "训练历史",
        emptyHistory: "暂无记录",
        retry: "从失败阶段重试",
        evalResult: "回归评测",
        baseline: "现役基线",
        candidate: "候选版本",
        evalSize: "考题",
        overall: "综合分",
        sqlRate: "SQL 成功率",
        consistency: "结果一致率",
        gate: "晋升门禁",
        gateOk: "达标",
        gateNo: "未达标",
        promoteResult: "上线判定",
        promoted: "已上线",
        kept: "保留现版",
        openFactory: "智能体工厂",
        openQuality: "质量看板",
        openDistill: "知识蒸馏",
        queued: "已入队",
        distilled: "已蒸馏",
        effective: "已生效",
        errorPrefix: "训练失败",
        loadFail: "加载失败",
      }
    : {
        title: "Training Center",
        subtitle: "Pick target → feed → train → verify → release: one pipeline turns feedback into capability",
        refresh: "Refresh",
        noSource: "Select a data source",
        step1: "Target",
        step2: "Feed",
        step3: "Train",
        step4: "Verify",
        step5: "Release",
        target: "Training target",
        agentBound: "Agent bound",
        agentNone: "No agent bound (candidate / release will be skipped)",
        signal: "Training signal",
        traces: "Traces",
        feedback: "Feedback",
        examples: "Examples",
        templates: "Templates",
        rules: "Rules",
        evalSet: "Eval set",
        recentFeedback: "Recent feedback status",
        noFeedback: "No feedback yet — use like / correct SQL / save example in chat",
        plan: "Training scope",
        planFull: "Full (distill → eval set → candidate → eval → release)",
        planDistill: "Distill only (feedback → examples / templates / rules)",
        planEval: "Verify only (eval set → regression → release gate)",
        planPrompt: "Prompt GEPA optimize (reflect → rewrite role/goal/backstory → eval gate)",
        planTrajectory: "Trajectory training (question→plan→tool calls→result → metrics + sandbox replay → config apply)",
        trajTitle: "Multi-turn trajectory metrics",
        trajRuns: "Trajectories",
        trajToolAcc: "Tool selection acc.",
        trajInvalid: "Invalid call rate",
        trajRounds: "Avg rounds",
        trajSuccess: "Task success",
        trajReward: "Avg reward",
        trajClarify: "Clarify convergence",
        trajClarifyTrigger: "Clarify trigger rate",
        trajNoSample: "no samples",
        replayTitle: "Sandbox replay diff",
        replayChanged: "Action changes",
        replayCorpus: "Corpus",
        replayOld: "Current",
        replayNew: "Candidate",
        replayActionOld: "Old action",
        replayActionNew: "New action",
        replayNoDiff: "No action diff (config already on frontier)",
        actionClarify: "clarify",
        actionDirect: "direct",
        rlTitle: "RL dataset export",
        rlDesc: "Export trajectories as JSONL with rule-based reward for ART / verl",
        rlRange: "Range",
        rlRangeAll: "All",
        rlRangeFailed: "Failed only",
        rlRangeSuccess: "Success only",
        rlRewardRule: "Reward rule",
        rlExport: "Export RL dataset",
        rlExporting: "Exporting...",
        rlHistory: "Exports",
        rlEmpty: "No exports yet",
        rlDownload: "Download",
        rlRows: "Rows",
        start: "Start training",
        starting: "Submitting...",
        pipeline: "Pipeline",
        noJob: "No training job yet — pick a scope and start",
        progress: "Progress",
        live: "live",
        offline: "disconnected",
        history: "History",
        emptyHistory: "No records",
        retry: "Retry from failed stage",
        evalResult: "Regression eval",
        baseline: "Production baseline",
        candidate: "Candidate version",
        evalSize: "Questions",
        overall: "Overall",
        sqlRate: "SQL success",
        consistency: "Consistency",
        gate: "Promotion gate",
        gateOk: "passed",
        gateNo: "not passed",
        promoteResult: "Release decision",
        promoted: "Released",
        kept: "Keep production",
        openFactory: "Agent factory",
        openQuality: "Quality board",
        openDistill: "Knowledge distill",
        queued: "queued",
        distilled: "distilled",
        effective: "effective",
        errorPrefix: "Training failed",
        loadFail: "Load failed",
      };

  const selected = useMemo(
    () => sources.find((s) => s.id === selectedDs) || null,
    [sources, selectedDs],
  );

  // 当前工单：优先 SSE 快照，其次历史记录
  const job: TrainJob | null = useMemo(() => {
    if (liveJob && liveJob.id === activeJobId) return liveJob;
    return jobs.find((j) => j.id === activeJobId) || jobs[0] || null;
  }, [liveJob, activeJobId, jobs]);

  const running = job?.status === "queued" || job?.status === "running";

  const fetchJobs = useCallback(async (ds: string) => {
    if (!ds) return [] as TrainJob[];
    const res = await trainCenterApi.list(ds, "ds", 20);
    const rows = (res.data || []) as TrainJob[];
    setJobs(rows);
    return rows;
  }, []);

  const fetchAll = useCallback(async (ds: string) => {
    if (!ds) return;
    setLoading(true);
    try {
      const [statsRes, qualityRes, fbRes, jobRows] = await Promise.all([
        dsDistillApi.stats(ds).catch(() => null),
        dsEvalApi.quality(ds).catch(() => null),
        dataAskApi.recentFeedback(ds, 8).catch(() => null),
        fetchJobs(ds).catch(() => [] as TrainJob[]),
      ]);
      setStats(statsRes?.data || null);
      setQuality(qualityRes?.data || null);
      setFeedbacks((fbRes?.data || []) as FeedbackStatus[]);
      if (jobRows.length > 0) {
        setActiveJobId((prev) => (prev && jobRows.some((j) => j.id === prev) ? prev : jobRows[0].id));
      } else {
        setActiveJobId("");
        setLiveJob(null);
      }
    } catch (err) {
      setToast(formatApiError(err, t.loadFail));
    } finally {
      setLoading(false);
    }
  }, [fetchJobs, t.loadFail]);

  useEffect(() => {
    dataSourcesApi.list()
      .then((res) => {
        const payload = res.data as { items?: DataSourceItem[] } | DataSourceItem[] | null;
        const rows = (Array.isArray(payload) ? payload : payload?.items || []) as DataSourceItem[];
        setSources(rows);
        if (rows.length > 0) setSelectedDs((prev) => prev || rows[0].id);
      })
      .catch((err) => setToast(formatApiError(err, t.loadFail)));
  }, [t.loadFail]);

  useEffect(() => {
    setLiveJob(null);
    void fetchAll(selectedDs);
  }, [selectedDs, fetchAll]);

  // SSE：单工单阶段进度实时快照
  useEffect(() => {
    if (!activeJobId) return;
    const ctrl = new AbortController();
    let closed = false;
    (async () => {
      try {
        const token = getAuthToken();
        const res = await fetch(
          `/api/v1/train/events?job_id=${encodeURIComponent(activeJobId)}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: ctrl.signal,
          },
        );
        if (!res.ok || !res.body) return;
        setLiveConnected(true);
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
              const snap = JSON.parse(line.slice(6)) as { job: TrainJob };
              if (snap.job) setLiveJob(snap.job);
            } catch {
              /* 忽略坏帧 */
            }
          }
        }
        if (!closed) setLiveConnected(false);
      } catch {
        if (!closed) setLiveConnected(false);
      }
    })();
    return () => {
      closed = true;
      ctrl.abort();
      setLiveConnected(false);
    };
  }, [activeJobId]);

  // 工单完成后刷新周边统计
  useEffect(() => {
    if (!liveJob) return;
    if (liveJob.status === "done" || liveJob.status === "partial" || liveJob.status === "failed") {
      const timer = setTimeout(() => {
        void fetchAll(selectedDs);
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [liveJob?.status, liveJob, fetchAll, selectedDs]);

  // P4: RL 导出记录
  const fetchRlExports = useCallback(async (dsId: string) => {
    if (!dsId) return;
    try {
      const res = await trainCenterApi.listRlExports(dsId, 20);
      setRlExports((res.data as any[]) || []);
    } catch {
      setRlExports([]);
    }
  }, []);

  useEffect(() => {
    void fetchRlExports(selectedDs);
  }, [selectedDs, fetchRlExports]);

  const doExportRl = async () => {
    if (!selectedDs || rlExporting) return;
    setRlExporting(true);
    setToast("");
    try {
      await trainCenterApi.exportRl({
        data_source_id: selectedDs,
        range: rlRange,
        reward_rule: rlRule,
      });
      await fetchRlExports(selectedDs);
    } catch (err) {
      setToast(formatApiError(err, t.loadFail));
    } finally {
      setRlExporting(false);
    }
  };

  const startTraining = async () => {
    if (!selectedDs || starting) return;
    setStarting(true);
    setToast("");
    try {
      const res = await trainCenterApi.create({ target_type: "ds", target_id: selectedDs, kind });
      const created = res.data as TrainJob;
      setActiveJobId(created.id);
      setLiveJob(created);
      setJobs((prev) => [created, ...prev.filter((j) => j.id !== created.id)]);
      setToast(lang === "zh" ? "训练已提交，流水线实时进度见下方" : "Training submitted, live pipeline below");
    } catch (err) {
      setToast(formatApiError(err, t.loadFail));
    } finally {
      setStarting(false);
    }
  };

  const retryJob = async (fromStage: string) => {
    if (!job) return;
    try {
      const res = await trainCenterApi.retry(job.id, fromStage);
      const updated = res.data as TrainJob;
      setLiveJob(updated);
      setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
    } catch (err) {
      setToast(formatApiError(err, t.loadFail));
    }
  };

  const stageOf = (key: string): TrainStage | undefined =>
    (job?.stages || []).find((s) => s.key === key);

  const groupState = (keys: string[]): string => {
    const rows = keys.map((k) => stageOf(k)).filter(Boolean) as TrainStage[];
    if (rows.length === 0) return "pending";
    if (rows.some((s) => s.status === "failed")) return "failed";
    if (rows.some((s) => s.status === "running")) return "running";
    if (rows.every((s) => s.status === "done" || s.status === "skipped")) {
      return rows.every((s) => s.status === "skipped") ? "skipped" : "done";
    }
    return "pending";
  };

  const steps = [
    { no: 1, label: t.step1, state: selectedDs ? "done" : "pending" },
    { no: 2, label: t.step2, state: groupState(["collect"]) },
    { no: 3, label: t.step3, state: groupState(["distill", "build_eval", "candidate", "prompt", "normalize"]) },
    { no: 4, label: t.step4, state: groupState(["eval", "metrics", "replay"]) },
    { no: 5, label: t.step5, state: groupState(["promote", "traj_promote"]) },
  ];

  const evalDetail = (job?.detail?.eval || {}) as Record<string, any>;
  const promoteDetail = (job?.detail?.promote || job?.detail?.traj_promote || {}) as Record<string, any>;
  const candidateDetail = (job?.detail?.candidate || {}) as Record<string, any>;
  const trajMetrics = (job?.detail?.metrics || {}) as Record<string, any>;
  const trajReplay = (job?.detail?.replay || {}) as Record<string, any>;

  const renderScoreCard = (label: string, block: Record<string, any> | undefined, cls: string) => {
    if (!block || !block.run_id) {
      return (
        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-3 text-xs text-gray-400">
          {label} · —
        </div>
      );
    }
    return (
      <div className={`rounded-lg border p-3 ${cls}`}>
        <div className="mb-2 flex items-center justify-between text-xs font-semibold">
          <span>{label}</span>
          <span className="font-mono text-[11px]">#{block.run_id}</span>
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div>
            <div className="text-gray-500">{t.overall}</div>
            <div className="text-base font-bold">{score(block.overall_score)}</div>
          </div>
          <div>
            <div className="text-gray-500">{t.sqlRate}</div>
            <div className="text-base font-bold">{rate(block.sql_success_rate)}</div>
          </div>
          <div>
            <div className="text-gray-500">{t.consistency}</div>
            <div className="font-semibold">{rate(block.consistency_rate)}</div>
          </div>
          <div>
            <div className="text-gray-500">passed / total</div>
            <div className="font-semibold">{block.passed ?? "—"} / {block.total ?? "—"}</div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Workflow className="h-7 w-7 text-indigo-500" />
            {t.title}
          </h1>
          <p className="mt-1 text-sm text-gray-500">{t.subtitle}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/agent-factory" className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:border-indigo-300 hover:text-indigo-600">
            {t.openFactory}
          </Link>
          <Link href="/agent-quality" className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:border-indigo-300 hover:text-indigo-600">
            {t.openQuality}
          </Link>
          <Link href="/knowledge-distill" className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:border-indigo-300 hover:text-indigo-600">
            {t.openDistill}
          </Link>
          <button
            onClick={() => void fetchAll(selectedDs)}
            className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:border-indigo-300 hover:text-indigo-600"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {t.refresh}
          </button>
        </div>
      </div>

      {toast && (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-700">
          {toast}
        </div>
      )}

      {/* 数据源选择 */}
      <div className="flex flex-wrap items-center gap-3">
        {sources.map((s) => (
          <button
            key={s.id}
            onClick={() => setSelectedDs(s.id)}
            className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
              selectedDs === s.id
                ? "border-indigo-300 bg-indigo-50 text-indigo-600"
                : "border-gray-200 hover:border-indigo-200"
            }`}
          >
            <Database className="mr-1 inline h-3.5 w-3.5" />
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
          {/* 五步向导 */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex flex-wrap items-center gap-1">
              {steps.map((s, i) => (
                <div key={s.no} className="flex items-center">
                  <div className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs ${STAGE_STATUS_CLS[s.state] || STAGE_STATUS_CLS.pending}`}>
                    <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                      s.state === "done" ? "bg-emerald-600 text-white"
                        : s.state === "running" ? "bg-blue-600 text-white"
                        : s.state === "failed" ? "bg-rose-600 text-white"
                        : "bg-gray-200 text-gray-600"
                    }`}>
                      {s.no}
                    </span>
                    {s.label}
                    {s.state === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
                    {s.state === "done" && <CheckCircle2 className="h-3 w-3" />}
                    {s.state === "failed" && <XCircle className="h-3 w-3" />}
                  </div>
                  {i < steps.length - 1 && <ChevronRight className="mx-1 h-4 w-4 text-gray-300" />}
                </div>
              ))}
              <span className={`ml-auto flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${
                liveConnected ? "border-emerald-200 bg-emerald-50 text-emerald-600" : "border-gray-200 text-gray-400"
              }`}>
                <span className={`h-1.5 w-1.5 rounded-full ${liveConnected ? "bg-emerald-500" : "bg-gray-300"}`} />
                {liveConnected ? t.live : t.offline}
              </span>
            </div>

            {/* 第1步：对象 */}
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              <div className="rounded-lg bg-gray-50 p-3">
                <div className="mb-1 flex items-center gap-1 text-[11px] text-gray-500">
                  <Database className="h-3.5 w-3.5" /> {t.target}
                </div>
                <div className="text-sm font-semibold">{selected?.name || selectedDs.slice(0, 8)}</div>
                <div className="mt-0.5 font-mono text-[10px] text-gray-400">{selectedDs}</div>
              </div>
              <div className="rounded-lg bg-gray-50 p-3">
                <div className="mb-1 flex items-center gap-1 text-[11px] text-gray-500">
                  <Sparkles className="h-3.5 w-3.5" /> {t.agentBound}
                </div>
                {selected?.agent_id ? (
                  <div className="font-mono text-xs text-emerald-600">{selected.agent_id.slice(0, 12)}…</div>
                ) : (
                  <div className="text-xs text-amber-600">{t.agentNone}</div>
                )}
              </div>
              <div className="rounded-lg bg-gray-50 p-3">
                <div className="mb-1 flex items-center gap-1 text-[11px] text-gray-500">
                  <FlaskConical className="h-3.5 w-3.5" /> {t.evalSet}
                </div>
                <div className="text-xl font-bold text-violet-600">{quality?.eval_set_size ?? "—"}</div>
                <div className="text-[10px] text-gray-400">
                  {quality?.latest_run
                    ? `${t.overall} ${score(quality.latest_run.overall_score)}`
                    : "—"}
                </div>
              </div>
            </div>
          </div>

          {/* 第2步：喂料 */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <MessageSquare className="h-4 w-4 text-indigo-500" />
              {t.signal}
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
              {[
                { label: t.traces, value: stats?.traces_total },
                { label: t.feedback, value: stats?.feedback_total },
                { label: t.examples, value: (stats?.examples_positive || 0) + (stats?.examples_negative || 0) },
                { label: t.templates, value: stats?.templates_active },
                { label: t.rules, value: stats?.rules_active },
                { label: t.evalSet, value: quality?.eval_set_size },
              ].map((item) => (
                <div key={item.label} className="rounded-lg bg-gray-50 p-3">
                  <div className="text-[11px] text-gray-500">{item.label}</div>
                  <div className="mt-0.5 text-xl font-bold text-gray-900">{item.value ?? "—"}</div>
                </div>
              ))}
            </div>

            <div className="mt-4">
              <div className="mb-2 text-[11px] text-gray-500">{t.recentFeedback}</div>
              {feedbacks.length === 0 ? (
                <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-xs text-gray-400">
                  {t.noFeedback}
                </div>
              ) : (
                <div className="space-y-1.5">
                  {feedbacks.map((fb) => (
                    <div key={fb.feedback_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs">
                      <span className="max-w-[46%] flex-1 truncate text-gray-700" title={fb.question || ""}>
                        {fb.question || `#${fb.feedback_id}`}
                      </span>
                      <span className="rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                        {fb.feedback_type}
                      </span>
                      {fb.steps.map((s) => (
                        <span
                          key={s.key}
                          className={`rounded-full border px-1.5 py-0.5 text-[10px] ${
                            s.done
                              ? "border-emerald-200 bg-emerald-50 text-emerald-600"
                              : "border-gray-200 bg-white text-gray-400"
                          }`}
                        >
                          {s.label}
                        </span>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 第3步：训练 */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                <Play className="h-4 w-4 text-indigo-500" />
                {t.plan}
              </div>
              <button
                onClick={() => void startTraining()}
                disabled={starting || running || selected?.can_manage === false}
                className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {starting || running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {starting ? t.starting : t.start}
              </button>
            </div>

            <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-5">
              {([
                { key: "full", label: t.planFull, icon: Rocket },
                { key: "distill", label: t.planDistill, icon: Sparkles },
                { key: "eval", label: t.planEval, icon: ShieldCheck },
                { key: "prompt", label: t.planPrompt, icon: BrainCircuit },
                { key: "trajectory", label: t.planTrajectory, icon: Workflow },
              ] as const).map((opt) => {
                const Icon = opt.icon;
                return (
                  <button
                    key={opt.key}
                    onClick={() => setKind(opt.key)}
                    className={`flex items-start gap-2 rounded-lg border p-3 text-left text-xs ${
                      kind === opt.key
                        ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                        : "border-gray-200 hover:border-indigo-200"
                    }`}
                  >
                    <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{opt.label}</span>
                  </button>
                );
              })}
            </div>

            {/* 流水线 */}
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[11px] text-gray-500">{t.pipeline}</div>
                {job && (
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className={`rounded-full border px-2 py-0.5 ${JOB_STATUS_CLS[job.status] || "border-gray-200 text-gray-500"}`}>
                      {job.status}
                    </span>
                    <span className="font-mono text-gray-400">#{job.id.slice(0, 8)}</span>
                    <span className="text-gray-500">{t.progress} {job.progress}%</span>
                  </div>
                )}
              </div>

              {job && (
                <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className={`h-full transition-all ${job.status === "failed" ? "bg-rose-500" : "bg-indigo-500"}`}
                    style={{ width: `${Math.min(job.progress, 100)}%` }}
                  />
                </div>
              )}

              {!job ? (
                <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-6 text-center text-xs text-gray-400">
                  {t.noJob}
                </div>
              ) : (
                <div className="space-y-1.5">
                  {job.stages.map((st) => (
                    <div key={st.key} className={`flex items-start gap-2 rounded-lg border px-3 py-2 ${STAGE_STATUS_CLS[st.status] || STAGE_STATUS_CLS.pending}`}>
                      <span className="mt-0.5">
                        {st.status === "running" ? <Loader2 className="h-4 w-4 animate-spin" />
                          : st.status === "done" ? <CheckCircle2 className="h-4 w-4" />
                          : st.status === "failed" ? <XCircle className="h-4 w-4" />
                          : st.status === "skipped" ? <AlertTriangle className="h-4 w-4" />
                          : <span className="block h-4 w-4 rounded-full border border-gray-300" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
                          <span>{st.label}</span>
                          <span className="font-mono text-[10px] opacity-60">{st.key}</span>
                          {st.status === "running" && (
                            <span className="ml-auto text-[10px]">{st.progress}%</span>
                          )}
                        </div>
                        {st.message && (
                          <div className="mt-0.5 break-words text-[11px] opacity-80">{st.message}</div>
                        )}
                      </div>
                      {job.status === "failed" || job.status === "partial" ? (
                        st.status === "failed" ? (
                          <button
                            onClick={() => void retryJob(st.key)}
                            className="shrink-0 rounded border border-current px-2 py-0.5 text-[10px] hover:bg-white/60"
                          >
                            {t.retry}
                          </button>
                        ) : null
                      ) : null}
                    </div>
                  ))}
                  {job.error && (
                    <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-600">
                      {t.errorPrefix}: {job.error}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* 第4步：验证 */}
          {job?.kind !== "trajectory" && (
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <FlaskConical className="h-4 w-4 text-violet-500" />
              {t.evalResult}
              {evalDetail.eval_set_size != null && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-normal text-gray-500">
                  {t.evalSize} {evalDetail.eval_set_size}
                </span>
              )}
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {renderScoreCard(t.baseline, evalDetail.baseline, "border-gray-200 bg-gray-50 text-gray-800")}
              {renderScoreCard(t.candidate, evalDetail.candidate, "border-violet-200 bg-violet-50 text-violet-800")}
            </div>
            {evalDetail.gate && (
              <div className={`mt-3 flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                evalDetail.gate.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
              }`}>
                <ShieldCheck className="h-4 w-4" />
                <span className="font-semibold">{t.gate}: {evalDetail.gate.ok ? t.gateOk : t.gateNo}</span>
                <span className="opacity-80">{evalDetail.gate.reason}</span>
              </div>
            )}
            {(evalDetail.candidate?.weak_categories || []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {evalDetail.candidate.weak_categories.map((w: any, i: number) => {
                  const label = typeof w === "string" ? w : (w?.category || `weak-${i}`);
                  return (
                    <span key={`${label}-${i}`} className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] text-rose-600">
                      {label}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
          )}

          {/* P3：轨迹指标 + 沙箱回放 */}
          {job?.kind === "trajectory" && (
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <FlaskConical className="h-4 w-4 text-violet-500" />
              {t.trajTitle}
              {trajMetrics.trajectories != null && (
                <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-normal text-gray-500">
                  {t.trajRuns} {trajMetrics.trajectories}
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {([
                { label: t.trajToolAcc, value: rate(trajMetrics.tool_selection_accuracy) },
                { label: t.trajInvalid, value: rate(trajMetrics.invalid_call_rate) },
                { label: t.trajRounds, value: trajMetrics.avg_rounds ?? "—" },
                { label: t.trajSuccess, value: rate(trajMetrics.success_rate) },
                { label: t.trajReward, value: score(trajMetrics.avg_reward) },
                { label: t.trajClarifyTrigger, value: rate(trajMetrics.clarify_trigger_rate) },
                { label: t.trajClarify, value: trajMetrics.clarify_convergence == null ? t.trajNoSample : rate(trajMetrics.clarify_convergence) },
              ]).map((m) => (
                <div key={m.label} className="rounded-lg border border-gray-200 bg-gray-50 p-2">
                  <div className="text-[10px] text-gray-500">{m.label}</div>
                  <div className="text-sm font-bold text-gray-900">{m.value}</div>
                </div>
              ))}
            </div>

            <div className="mt-4 border-t border-gray-100 pt-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-gray-900">
                <Workflow className="h-4 w-4 text-indigo-500" />
                {t.replayTitle}
                {trajReplay.corpus?.traces != null && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-normal text-gray-500">
                    {t.replayCorpus} {trajReplay.corpus.traces}
                  </span>
                )}
                {trajReplay.changed_count != null && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-normal text-indigo-600">
                    {t.replayChanged} {trajReplay.changed_count}
                  </span>
                )}
              </div>
              {trajReplay.current_knobs && (
                <div className="mb-2 grid grid-cols-1 gap-2 text-[11px] md:grid-cols-2">
                  <div className="rounded-lg border border-gray-200 bg-gray-50 p-2">
                    <div className="mb-1 font-semibold text-gray-600">{t.replayOld}</div>
                    <div className="break-words font-mono text-[10px] text-gray-600">
                      {Object.entries(trajReplay.current_knobs).map(([k, v]) => `${k}=${String(v)}`).join(" · ")}
                    </div>
                  </div>
                  <div className="rounded-lg border border-violet-200 bg-violet-50 p-2">
                    <div className="mb-1 font-semibold text-violet-700">{t.replayNew}</div>
                    <div className="break-words font-mono text-[10px] text-violet-700">
                      {trajReplay.candidate_knobs
                        ? Object.entries(trajReplay.candidate_knobs).map(([k, v]) => `${k}=${String(v)}`).join(" · ")
                        : t.replayNoDiff}
                    </div>
                  </div>
                </div>
              )}
              {trajReplay.gate && (
                <div className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                  trajReplay.gate.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
                }`}>
                  <ShieldCheck className="h-4 w-4" />
                  <span className="font-semibold">{t.gate}: {trajReplay.gate.ok ? t.gateOk : t.gateNo}</span>
                  <span className="opacity-80">{trajReplay.gate.reason}</span>
                </div>
              )}
              {(trajReplay.action_diffs || []).length === 0 ? (
                <div className="mt-2 rounded-lg border border-dashed border-gray-200 bg-gray-50 p-3 text-xs text-gray-400">
                  {t.replayNoDiff}
                </div>
              ) : (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-gray-200 text-[11px] text-gray-500">
                        <th className="py-2 pr-3">trace</th>
                        <th className="py-2 pr-3">question</th>
                        <th className="py-2 pr-3">{t.replayActionOld}</th>
                        <th className="py-2 pr-3">{t.replayActionNew}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trajReplay.action_diffs.slice(0, 20).map((d: any, i: number) => (
                        <tr key={`${d.trace_id}-${i}`} className="border-b border-gray-100">
                          <td className="py-1.5 pr-3 font-mono text-[10px] text-gray-500">#{d.trace_id}</td>
                          <td className="max-w-[420px] truncate py-1.5 pr-3 text-gray-700" title={d.question}>{d.question}</td>
                          <td className="py-1.5 pr-3">{d.old_action === "clarify" ? t.actionClarify : t.actionDirect}</td>
                          <td className="py-1.5 pr-3 font-semibold text-indigo-600">
                            {d.new_action === "clarify" ? t.actionClarify : t.actionDirect}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* P4：RL 数据导出 */}
            <div className="mt-4 border-t border-gray-100 pt-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-gray-900">
                <BrainCircuit className="h-4 w-4 text-emerald-500" />
                {t.rlTitle}
                <span className="text-[10px] font-normal text-gray-400">{t.rlDesc}</span>
              </div>
              <div className="mb-2 grid grid-cols-1 gap-2 md:grid-cols-3">
                <label className="flex flex-col gap-1 rounded-lg border border-gray-200 bg-gray-50 p-2 text-[11px]">
                  <span className="font-semibold text-gray-600">{t.rlRange}</span>
                  <select
                    value={rlRange}
                    onChange={(e) => setRlRange(e.target.value as "all" | "failed" | "success")}
                    className="rounded border border-gray-200 bg-white px-2 py-1 text-xs"
                  >
                    <option value="all">{t.rlRangeAll}</option>
                    <option value="failed">{t.rlRangeFailed}</option>
                    <option value="success">{t.rlRangeSuccess}</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 rounded-lg border border-gray-200 bg-gray-50 p-2 text-[11px] md:col-span-2">
                  <span className="font-semibold text-gray-600">{t.rlRewardRule}</span>
                  <input
                    type="text"
                    value={rlRule}
                    onChange={(e) => setRlRule(e.target.value)}
                    className="rounded border border-gray-200 bg-white px-2 py-1 font-mono text-xs"
                    placeholder="success=+1.0;invalid=-0.5;clarify=+0.2"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={() => void doExportRl()}
                disabled={rlExporting || !selectedDs}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {rlExporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BrainCircuit className="h-3.5 w-3.5" />}
                {rlExporting ? t.rlExporting : t.rlExport}
              </button>

              <div className="mt-3">
                <div className="mb-1 text-[11px] font-semibold text-gray-600">{t.rlHistory}</div>
                {rlExports.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-3 text-xs text-gray-400">
                    {t.rlEmpty}
                  </div>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-gray-200">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-gray-50">
                        <tr className="border-b border-gray-200 text-[11px] text-gray-500">
                          <th className="px-2 py-1.5">{t.rlRange}</th>
                          <th className="px-2 py-1.5">{t.rlRewardRule}</th>
                          <th className="px-2 py-1.5">{t.rlRows}</th>
                          <th className="px-2 py-1.5">format</th>
                          <th className="px-2 py-1.5"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {rlExports.map((r: any) => (
                          <tr key={r.id} className="border-b border-gray-100">
                            <td className="px-2 py-1.5 font-mono text-[10px] text-gray-600">{r.range}</td>
                            <td className="px-2 py-1.5 font-mono text-[10px] text-gray-600">{r.reward_rule}</td>
                            <td className="px-2 py-1.5 font-semibold text-gray-800">{r.row_count}</td>
                            <td className="px-2 py-1.5 text-gray-500">{r.format}</td>
                            <td className="px-2 py-1.5">
                              <a
                                href={`${trainCenterApi.rlExportDownloadUrl(r.id)}?token=${encodeURIComponent(getAuthToken() || "")}`}
                                className="text-emerald-600 hover:underline"
                              >
                                {t.rlDownload}
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </div>
          )}

          {/* 第5步：上线 */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <Rocket className="h-4 w-4 text-emerald-500" />
              {t.promoteResult}
            </div>
            {!promoteDetail || Object.keys(promoteDetail).length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-xs text-gray-400">
                {t.kept} · —
              </div>
            ) : (
              <div className={`flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-xs ${
                promoteDetail.promoted
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-gray-200 bg-gray-50 text-gray-600"
              }`}>
                {promoteDetail.promoted ? <CheckCircle2 className="h-4 w-4" /> : <History className="h-4 w-4" />}
                <span className="font-semibold">
                  {promoteDetail.promoted
                    ? `${t.promoted}${promoteDetail.version ? ` v${promoteDetail.version}` : ""}`
                    : `${t.kept}${promoteDetail.version ? ` v${promoteDetail.version}` : ""}`}
                </span>
                <span className="opacity-80">
                  {candidateDetail.version ? `候选 v${candidateDetail.version} · ` : ""}
                  {promoteDetail.reason || ""}
                </span>
                {promoteDetail.release_id && (
                  <span className="font-mono text-[10px] opacity-60">release {String(promoteDetail.release_id).slice(0, 8)}</span>
                )}
              </div>
            )}
          </div>

          {/* 历史 */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <History className="h-4 w-4 text-gray-500" />
              {t.history}
            </div>
            {jobs.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-4 text-center text-xs text-gray-400">
                {t.emptyHistory}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-gray-200 text-[11px] text-gray-500">
                      <th className="py-2 pr-3">ID</th>
                      <th className="py-2 pr-3">kind</th>
                      <th className="py-2 pr-3">status</th>
                      <th className="py-2 pr-3">stage</th>
                      <th className="py-2 pr-3">progress</th>
                      <th className="py-2">created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((j) => (
                      <tr
                        key={j.id}
                        onClick={() => setActiveJobId(j.id)}
                        className={`cursor-pointer border-b border-gray-100 hover:bg-indigo-50/40 ${
                          job?.id === j.id ? "bg-indigo-50/60" : ""
                        }`}
                      >
                        <td className="py-2 pr-3 font-mono text-[10px] text-gray-500">{j.id.slice(0, 8)}</td>
                        <td className="py-2 pr-3">{j.kind}</td>
                        <td className="py-2 pr-3">
                          <span className={`rounded-full border px-2 py-0.5 text-[10px] ${JOB_STATUS_CLS[j.status] || "border-gray-200 text-gray-500"}`}>
                            {j.status}
                          </span>
                        </td>
                        <td className="py-2 pr-3 font-mono text-[10px] text-gray-500">{j.stage}</td>
                        <td className="py-2 pr-3">{j.progress}%</td>
                        <td className="py-2 text-gray-400">
                          {j.created_at ? new Date(j.created_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
