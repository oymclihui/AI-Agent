"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Award,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  Database,
  FlaskConical,
  LayoutDashboard,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  Rocket,
  Sparkles,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import { dsDashboardApi, dsDistillApi, dsEvalApi, dsFactoryApi, dsProfileApi, formatApiError } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";

// ── 后端返回类型（与 app/schemas/ds_factory.py / ds_distill.py / ds_eval.py 对齐）──
interface ReadinessItem {
  key: string;
  label: string;
  value: number | string;
  target: number | string;
  ok: boolean;
}

interface Capability {
  key: string;
  label: string;
  enabled: boolean;
  reason: string;
}

interface CoachData {
  data_source_id: string;
  data_source_name?: string;
  driver?: string;
  profile: {
    status?: string;
    version?: number | null;
    total_rows?: number;
    quality_gaps?: string[];
  };
  semantic: { terms?: number; metrics?: number };
  distill: {
    examples_positive?: number;
    examples_negative?: number;
    examples_indexed?: number;
    templates_active?: number;
    rules_active?: number;
  };
  signal: { traces?: number; feedback?: number };
  capabilities: Capability[];
  readiness: { score: number; level: string; items: ReadinessItem[] };
  gaps: string[];
}

interface AgentSpec {
  name: string;
  role: string;
  goal: string;
  backstory?: string | null;
  temperature: number;
  tools_config: Record<string, unknown>[];
  skills_config: Record<string, unknown>[];
  memory_config: Record<string, unknown>;
  metadata_: Record<string, unknown>;
  opening_questions: string[];
}

interface TrialResult {
  success: boolean;
  sql?: string;
  row_count?: number;
  answer_excerpt?: string;
  error?: string | null;
}

interface DistillStats {
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

interface AnswerModeStats {
  days: number;
  total: number;
  modes: { answer_mode: string; count: number; ratio: number }[];
  feedback: { feedback_type: string; count: number }[];
  top_questions: { question: string; count: number }[];
}

interface ExampleRow {
  id: string;
  question: string;
  sql_text: string;
  kind: string;
  quality: number;
  use_count: number;
}

interface EvalRun {
  id: number;
  status: string;
  total: number;
  passed: number;
  overall_score?: number | null;
  sql_success_rate?: number | null;
  agent_version?: number | null;
  trigger?: string;
  error_message?: string | null;
  created_at?: string | null;
}

interface EvalQuality {
  eval_set_size: number;
  latest_run?: EvalRun | null;
  weak_categories: { category?: string; pass_rate?: number }[];
}

interface ReleaseRow {
  id: string;
  version: number;
  scope: string;
  active: boolean;
  note?: string | null;
  created_at?: string | null;
}

interface ProgressEvent {
  date: string;
  text: string;
}

interface DashboardRow {
  id: string;
  title: string;
  status: string;
  stage?: string | null;
  progress?: number;
  period_start?: string | null;
  period_end?: string | null;
  kpis?: { label: string; value: string }[];
  anchor_status?: string | null;
  error?: string | null;
  created_at?: string | null;
  view_url: string;
  widget_url: string;
}

interface Props {
  dsId: string;
  agentId?: string | null;
  canManage?: boolean;
  onPublished: () => void;
  onGoAsk: () => void;
  onGoSemantic: () => void;
}

export function GrowthPanel({ dsId, agentId, canManage, onPublished, onGoAsk, onGoSemantic }: Props) {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);

  const [loading, setLoading] = useState(true);
  const [coach, setCoach] = useState<CoachData | null>(null);
  const [stats, setStats] = useState<DistillStats | null>(null);
  const [modeStats, setModeStats] = useState<AnswerModeStats | null>(null);
  const [examples, setExamples] = useState<ExampleRow[]>([]);
  const [quality, setQuality] = useState<EvalQuality | null>(null);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [releases, setReleases] = useState<ReleaseRow[]>([]);
  const [boards, setBoards] = useState<DashboardRow[]>([]);

  const [spec, setSpec] = useState<AgentSpec | null>(null);
  const [specName, setSpecName] = useState("");
  const [specRole, setSpecRole] = useState("");
  const [specGoal, setSpecGoal] = useState("");
  const [trialQ, setTrialQ] = useState("");
  const [trialResult, setTrialResult] = useState<TrialResult | null>(null);

  const [generating, setGenerating] = useState(false);
  const [trialing, setTrialing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [distilling, setDistilling] = useState(false);
  const [miningTpl, setMiningTpl] = useState(false);
  const [miningRule, setMiningRule] = useState(false);
  const [runningEval, setRunningEval] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadAll = useCallback(async () => {
    if (!dsId) return;
    setLoading(true);
    const [coachR, statsR, exR, qualityR, runsR, releasesR, modeR, boardsR] = await Promise.allSettled([
      dsFactoryApi.coach(dsId),
      dsDistillApi.stats(dsId),
      dsDistillApi.examples(dsId),
      dsEvalApi.quality(dsId),
      dsEvalApi.runs(dsId, 10),
      agentId ? dsFactoryApi.releases(agentId) : Promise.reject(new Error("no agent")),
      dsDistillApi.answerModeStats(dsId, 14),
      dsDashboardApi.list(dsId),
    ]);
    if (coachR.status === "fulfilled") setCoach(coachR.value.data as CoachData);
    if (statsR.status === "fulfilled") setStats(statsR.value.data as DistillStats);
    if (exR.status === "fulfilled") setExamples(((exR.value.data as ExampleRow[]) || []).slice(0, 8));
    if (qualityR.status === "fulfilled") setQuality(qualityR.value.data as EvalQuality);
    if (runsR.status === "fulfilled") setRuns((runsR.value.data as EvalRun[]) || []);
    if (releasesR.status === "fulfilled") setReleases((releasesR.value.data as ReleaseRow[]) || []);
    if (modeR.status === "fulfilled") setModeStats(modeR.value.data as AnswerModeStats);
    if (boardsR.status === "fulfilled") {
      const body = boardsR.value.data as { items?: DashboardRow[] };
      setBoards(body?.items || []);
    }
    setLoading(false);
  }, [dsId, agentId]);

  useEffect(() => {
    void loadAll();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (profilePollRef.current) clearInterval(profilePollRef.current);
    };
  }, [loadAll]);

  // ── 一键读懂数据（Schema 画像构建，Celery 异步 → 轮询状态）──
  const [building, setBuilding] = useState(false);
  const profilePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopProfilePoll = () => {
    if (profilePollRef.current) {
      clearInterval(profilePollRef.current);
      profilePollRef.current = null;
    }
  };
  const onBuildProfile = async () => {
    setBuilding(true);
    try {
      const { data } = await dsProfileApi.build(dsId);
      const d = data as { status?: string; message?: string };
      toast.success(d.message || t("已开始读懂数据，完成后自动刷新", "Profile build started"));
      stopProfilePoll();
      profilePollRef.current = setInterval(async () => {
        try {
          const { data: st } = await dsProfileApi.status(dsId);
          const s = st as { status?: string; error?: string | null };
          if (s.status === "ready" || s.status === "failed") {
            stopProfilePoll();
            setBuilding(false);
            if (s.status === "ready") {
              toast.success(t("数据已读懂，就绪度已更新", "Data understood — readiness updated"));
            } else {
              toast.error(t("读懂数据失败：", "Profile build failed: ") + (s.error || t("未知错误", "unknown")));
            }
            await loadAll();
          }
        } catch { /* keep polling */ }
      }, 4000);
      // 最长轮询 10 分钟
      setTimeout(() => {
        if (profilePollRef.current) {
          stopProfilePoll();
          setBuilding(false);
        }
      }, 600000);
    } catch (e) {
      toast.error(formatApiError(e, t("触发读懂数据失败", "Trigger failed")));
      setBuilding(false);
    }
  };

  // ── 生成 ──
  const onGenerate = async () => {
    setGenerating(true);
    setTrialResult(null);
    try {
      const { data } = await dsFactoryApi.generate(dsId, {});
      const out = data as { spec: AgentSpec; coach: CoachData };
      setSpec(out.spec);
      setSpecName(out.spec.name || "");
      setSpecRole(out.spec.role || "");
      setSpecGoal(out.spec.goal || "");
      if (out.coach) setCoach(out.coach);
      toast.success(t("草案已生成，可微调后试跑", "Draft generated — tweak then trial"));
    } catch (e) {
      toast.error(formatApiError(e, t("生成失败", "Generate failed")));
    } finally {
      setGenerating(false);
    }
  };

  const onTrial = async () => {
    if (!trialQ.trim()) return;
    setTrialing(true);
    setTrialResult(null);
    try {
      const { data } = await dsFactoryApi.trial(dsId, trialQ.trim());
      setTrialResult(data as TrialResult);
      if ((data as TrialResult).success) {
        toast.success(t("试跑成功", "Trial succeeded"));
      } else {
        toast.error(t("试跑未成功，可换个问法再试", "Trial failed — try another question"));
      }
    } catch (e) {
      toast.error(formatApiError(e, t("试跑失败", "Trial failed")));
    } finally {
      setTrialing(false);
    }
  };

  const onPublish = async () => {
    if (!spec) return;
    setPublishing(true);
    try {
      const { data } = await dsFactoryApi.publish(dsId, {
        spec: {
          name: specName.trim() || spec.name,
          role: specRole.trim() || spec.role,
          goal: specGoal.trim() || spec.goal,
          backstory: spec.backstory,
          temperature: spec.temperature,
          tools_config: spec.tools_config,
          skills_config: spec.skills_config,
          memory_config: spec.memory_config,
          metadata_: spec.metadata_,
        },
        coach: coach ? { readiness: coach.readiness } : undefined,
      });
      const out = data as { agent_id: string; version: number; message?: string };
      toast.success(out.message || t(`已发布为智能体 v${out.version}`, `Published as agent v${out.version}`));
      setSpec(null);
      setTrialResult(null);
      onPublished();
    } catch (e) {
      toast.error(formatApiError(e, t("发布失败", "Publish failed")));
    } finally {
      setPublishing(false);
    }
  };

  // ── 喂养 ──
  const onDistill = async () => {
    setDistilling(true);
    try {
      const { data } = await dsDistillApi.distillExamples(dsId);
      const d = data as { message?: string; created?: number; indexed?: number };
      toast.success(d.message || t(`已学习：新增 ${d.created ?? 0} 条范例`, `Learned: ${d.created ?? 0} new examples`));
      await loadAll();
    } catch (e) {
      toast.error(formatApiError(e, t("学习失败", "Distill failed")));
    } finally {
      setDistilling(false);
    }
  };

  const onMineTemplates = async () => {
    setMiningTpl(true);
    try {
      const { data } = await dsDistillApi.mineTemplates(dsId);
      const d = data as { message?: string; templates?: number };
      toast.success(d.message || t(`挖掘到 ${d.templates ?? 0} 个分析套路`, `Mined ${d.templates ?? 0} templates`));
      await loadAll();
    } catch (e) {
      toast.error(formatApiError(e, t("挖掘失败", "Mine failed")));
    } finally {
      setMiningTpl(false);
    }
  };

  const onMineRules = async () => {
    setMiningRule(true);
    try {
      const { data } = await dsDistillApi.mineRules(dsId);
      const d = data as { message?: string; rules?: number };
      toast.success(d.message || t(`挖掘到 ${d.rules ?? 0} 条业务习惯`, `Mined ${d.rules ?? 0} rules`));
      await loadAll();
    } catch (e) {
      toast.error(formatApiError(e, t("挖掘失败", "Mine failed")));
    } finally {
      setMiningRule(false);
    }
  };

  // ── 验收 ──
  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const onRunEval = async () => {
    setRunningEval(true);
    try {
      const { data } = await dsEvalApi.runEval(dsId);
      const trig = data as { run_id: number; message?: string };
      toast.success(trig.message || t("自测已开始，完成后自动刷新", "Eval started — will refresh when done"));
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const [{ data: runsData }, { data: qualityData }] = await Promise.all([
            dsEvalApi.runs(dsId, 10),
            dsEvalApi.quality(dsId),
          ]);
          const list = (runsData as EvalRun[]) || [];
          setRuns(list);
          setQuality(qualityData as EvalQuality);
          const latest = list.find((r) => r.id === trig.run_id) || list[0];
          if (latest && latest.status !== "pending" && latest.status !== "running") {
            stopPolling();
            setRunningEval(false);
            if (latest.status === "done") {
              toast.success(t(`自测完成：${latest.passed}/${latest.total} 通过`, `Eval done: ${latest.passed}/${latest.total} passed`));
            } else {
              toast.error(t("自测未完成，请查看历史记录", "Eval did not complete"));
            }
          }
        } catch { /* keep polling */ }
      }, 5000);
      // 最长轮询 5 分钟
      setTimeout(() => {
        if (pollRef.current) {
          stopPolling();
          setRunningEval(false);
        }
      }, 300000);
    } catch (e) {
      toast.error(formatApiError(e, t("启动自测失败", "Eval trigger failed")));
      setRunningEval(false);
    }
  };

  if (loading && !coach && !stats) {
    return (
      <div className="theme-surface rounded-xl border theme-border p-8 text-center text-sm theme-muted">
        <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" />
        {t("加载养成面板…", "Loading growth panel…")}
      </div>
    );
  }

  const score = coach?.readiness?.score ?? 0;
  const level = coach?.readiness?.level ?? "insufficient";
  const levelLabel = level === "good" ? t("状态很好", "Good") : level === "basic" ? t("基本可用", "Basic") : t("还需积累", "Needs work");
  const levelColor = level === "good" ? "text-emerald-500" : level === "basic" ? "text-amber-500" : "text-rose-500";
  const items = coach?.readiness?.items ?? [];
  const okCount = items.filter((it) => it.ok).length;
  const isExcel = coach?.driver === "excel_folder" || coach?.driver === "excel_template";
  const profileReady = coach?.profile?.status === "ready";

  // P4：系统在进步 —— 发布/回滚事件 + 每周自测分变化（全部来自真实接口数据）
  const events: ProgressEvent[] = [];
  (releases || []).slice(0, 8).forEach((r) => {
    const note = r.note || "";
    const date = (r.created_at || "").slice(0, 10);
    if (note.includes("回滚")) {
      events.push({ date, text: t(`回滚到 v${r.version}`, `Rolled back to v${r.version}`) });
    } else if (note.includes("每周") || note.includes("自动")) {
      events.push({ date, text: t(`v${r.version} 已自动上线`, `v${r.version} auto-promoted`) });
    } else {
      events.push({ date, text: t(`v${r.version} 发布上线`, `v${r.version} released`) });
    }
  });
  const weeklyScored = runs.filter((r) => r.trigger === "weekly" && r.overall_score != null);
  const toScore = (v: number) => String(Math.round(v * 100));
  if (weeklyScored.length > 0) {
    const latest = weeklyScored[0];
    const latestScore = toScore(latest.overall_score as number);
    const prev = weeklyScored[1];
    const cmp =
      prev && prev.overall_score != null
        ? `${toScore(prev.overall_score)}→${latestScore}`
        : latestScore;
    events.push({
      date: (latest.created_at || "").slice(0, 10),
      text: t(`每周自测：综合 ${cmp} 分（${latest.passed}/${latest.total} 通过）`, `Weekly self-test: ${cmp} (${latest.passed}/${latest.total} passed)`),
    });
  }
  events.sort((a, b) => (a.date < b.date ? 1 : -1));
  const recentEvents = events.slice(0, 5);

  // P2：缺什么给什么 —— 每个未达标项给出对应的引导动作
  const actionFor = (key: string) => {
    const cls = "btn-secondary inline-flex items-center gap-1 px-2 py-1 text-[11px] shrink-0";
    switch (key) {
      case "profile":
        if (isExcel) {
          return <span className="text-[11px] theme-muted shrink-0">{t("Excel 源暂不支持", "N/A for Excel")}</span>;
        }
        return (
          <button type="button" onClick={() => void onBuildProfile()} disabled={building || !canManage} className="btn-primary inline-flex items-center gap-1 px-2 py-1 text-[11px] shrink-0">
            {building ? <Loader2 className="h-3 w-3 animate-spin" /> : <Database className="h-3 w-3" />}
            {building ? t("正在读取…", "Reading…") : t("一键读懂数据", "Read my data")}
          </button>
        );
      case "semantic":
        return (
          <button type="button" onClick={onGoSemantic} className={cls}>
            {t("补术语词典", "Add terms")}
          </button>
        );
      case "examples":
        return (
          <button type="button" onClick={onGoAsk} className={cls}>
            {t("去问数喂养", "Ask to feed")}
          </button>
        );
      case "templates":
        return (
          <button type="button" onClick={() => void onMineTemplates()} disabled={miningTpl || !canManage} className={cls}>
            {miningTpl ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            {t("挖掘分析套路", "Mine templates")}
          </button>
        );
      case "volume":
        return <span className="text-[11px] theme-muted shrink-0">{profileReady ? t("数据量不足，无法解锁总体分析", "Not enough rows") : t("读懂数据后自动统计", "Auto after reading data")}</span>;
      case "traces":
        return (
          <button type="button" onClick={onGoAsk} className={cls}>
            {t("去问数", "Ask")}
          </button>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-5">
      {/* ── 段一：生成智能体 ── */}
      <div className="theme-surface rounded-xl border theme-border p-4 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="font-medium inline-flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-emerald-500" />
            {t("① 生成智能体", "① Generate agent")}
          </h2>
          <button type="button" onClick={() => void loadAll()} className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs">
            <RefreshCw className="h-3.5 w-3.5" />{t("刷新", "Refresh")}
          </button>
        </div>

        {/* 就绪度 */}
        {coach && (
          <>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="text-center">
                <div className={`text-3xl font-bold ${levelColor}`}>{score}</div>
                <div className="text-xs theme-muted mt-0.5">{t("就绪度", "Readiness")} · {levelLabel}</div>
              </div>
              <div className="flex-1 min-w-[220px]">
                <div className="h-2 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${level === "good" ? "bg-emerald-500" : level === "basic" ? "bg-amber-500" : "bg-rose-500"}`}
                    style={{ width: `${score}%` }}
                  />
                </div>
                <p className="mt-1.5 text-xs theme-muted">
                  {t(`${okCount}/${items.length} 项达标 · 每完成一项，智能体就变强一点`, `${okCount}/${items.length} checks passed · each one makes your agent smarter`)}
                </p>
              </div>
            </div>

            {/* 养成清单（P2：缺什么给什么，未达标项直接给动作） */}
            <div>
              <p className="text-xs theme-muted mb-1.5">{t("养成清单", "Growth checklist")}</p>
              <ul className="space-y-1">
                {items.map((it) => (
                  <li key={it.key} className="flex items-center gap-2 text-xs rounded-lg border theme-border px-2.5 py-1.5">
                    {it.ok ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 text-rose-400 shrink-0" />
                    )}
                    <span className="truncate flex-1">
                      {it.label}：<b>{String(it.value)}</b>
                      {!it.ok && <span className="theme-muted">（{t("目标", "target")} {String(it.target)}）</span>}
                    </span>
                    {it.ok ? (
                      <span className="text-[11px] text-emerald-600 dark:text-emerald-400 shrink-0">{t("已达成", "done")}</span>
                    ) : (
                      actionFor(it.key)
                    )}
                  </li>
                ))}
              </ul>
            </div>

            {/* 能力清单 */}
            <div>
              <p className="text-xs theme-muted mb-1.5">{t("智能体将具备的能力", "Agent capabilities")}</p>
              <div className="flex flex-wrap gap-1.5">
                {(coach.capabilities || []).map((cap) => (
                  <span
                    key={cap.key}
                    title={cap.reason}
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs border ${
                      cap.enabled
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                        : "border-black/10 dark:border-white/10 theme-muted"
                    }`}
                  >
                    {cap.enabled ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                    {cap.label}
                  </span>
                ))}
              </div>
            </div>

            {/* 回答模式分布：L1/L2/L3 占比 + 反馈构成（支撑冗长度与词表观测） */}
            <div className="rounded-lg border border-black/10 dark:border-white/10 p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-medium">{t("回答模式分布（近 14 天）", "Answer modes (last 14 days)")}</p>
                <span className="text-xs theme-muted">
                  {t("共", "Total")} {modeStats?.total ?? 0} {t("次问数", "asks")}
                </span>
              </div>
              {modeStats && modeStats.total > 0 ? (
                <>
                  <div className="space-y-1.5">
                    {modeStats.modes.map((m) => (
                      <div key={m.answer_mode} className="flex items-center gap-2 text-xs">
                        <span className="w-8 shrink-0 font-mono">{m.answer_mode}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
                          <div
                            className="h-full rounded-full bg-emerald-500/70"
                            style={{ width: `${Math.min(100, m.ratio)}%` }}
                          />
                        </div>
                        <span className="w-24 shrink-0 text-right theme-muted tabular-nums">
                          {m.count} · {m.ratio}%
                        </span>
                      </div>
                    ))}
                  </div>
                  {modeStats.feedback.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                      {modeStats.feedback.map((f) => {
                        const label =
                          f.feedback_type === "like" ? t("点赞", "Like")
                          : f.feedback_type === "dislike" ? t("点踩", "Dislike")
                          : f.feedback_type === "example" ? t("存为示例", "Saved")
                          : f.feedback_type === "correction" ? t("纠正 SQL", "Corrected")
                          : f.feedback_type === "verbose" ? t("仍觉冗余", "Too verbose")
                          : f.feedback_type;
                        return (
                          <span
                            key={f.feedback_type}
                            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 border ${
                              f.feedback_type === "verbose"
                                ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                                : "border-black/10 dark:border-white/10 theme-muted"
                            }`}
                          >
                            {label} <b className="tabular-nums">{f.count}</b>
                          </span>
                        );
                      })}
                    </div>
                  )}
                </>
              ) : (
                <p className="text-xs theme-muted">{t("近 14 天暂无问数记录", "No asks in the last 14 days")}</p>
              )}
            </div>

            {/* 数据质量提示（来自真实画像，非就绪度项） */}
            {(coach.profile?.quality_gaps?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <p className="text-xs font-medium text-amber-600 dark:text-amber-400 mb-1">
                  {t("数据质量提示", "Data quality notes")}
                </p>
                <ul className="text-xs theme-muted space-y-0.5 list-disc pl-4">
                  {(coach.profile.quality_gaps ?? []).slice(0, 8).map((g, i) => <li key={i}>{g}</li>)}
                </ul>
              </div>
            )}

            {/* 系统在进步（P4：进化/晋升/回滚事件回写，让用户看得见系统在进步） */}
            <div>
              <p className="text-xs theme-muted mb-1.5">{t("系统在进步", "Your agent keeps improving")}</p>
              {recentEvents.length > 0 ? (
                <ul className="space-y-1">
                  {recentEvents.map((ev, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs">
                      <Sparkles className="h-3 w-3 text-emerald-500 shrink-0" />
                      <span className="theme-muted shrink-0">{ev.date}</span>
                      <span className="truncate">{ev.text}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs theme-muted">
                  {t("还没有进化记录 —— 系统会定期自动进化并自测，出分后在这里告诉你", "No evolution records yet — the system improves periodically and reports here")}
                </p>
              )}
            </div>
          </>
        )}

        {/* 已绑定提示 / 生成按钮 */}
        {agentId && !spec && (
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3 flex items-center justify-between flex-wrap gap-2">
            <div className="text-sm">
              {t("已绑定智能体", "Agent bound")}{" "}
              <Link href="/agents" className="text-blue-500 text-xs">#{agentId.slice(0, 8)}…</Link>
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={onGoAsk} className="btn-primary inline-flex items-center gap-1 px-2.5 py-1 text-xs">
                <MessageSquare className="h-3.5 w-3.5" />{t("去问数", "Ask data")}
              </button>
              {canManage && (
                <button type="button" onClick={onGenerate} disabled={generating} className="btn-secondary inline-flex items-center gap-1 px-2.5 py-1 text-xs">
                  {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {t("重新生成草案", "Regenerate draft")}
                </button>
              )}
            </div>
          </div>
        )}
        {!agentId && !spec && canManage && (
          <button type="button" onClick={onGenerate} disabled={generating} className="btn-primary inline-flex items-center gap-1.5 px-4 py-2 text-sm">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {generating ? t("正在生成…", "Generating…") : t("生成我的智能体", "Generate my agent")}
          </button>
        )}
        {!canManage && (
          <p className="text-xs theme-muted">{t("生成与发布需要数据源管理权限。", "Generate/publish requires manage permission.")}</p>
        )}

        {/* 草案预览 + 试跑 + 发布 */}
        {spec && (
          <div className="rounded-lg border theme-border p-3 space-y-3">
            <p className="text-sm font-medium">{t("智能体草案（可微调）", "Agent draft (editable)")}</p>
            <div className="grid sm:grid-cols-2 gap-2">
              <label className="text-xs theme-muted">
                {t("名称", "Name")}
                <input className="input mt-0.5 w-full text-sm" value={specName} onChange={(e) => setSpecName(e.target.value)} />
              </label>
              <label className="text-xs theme-muted">
                {t("角色", "Role")}
                <input className="input mt-0.5 w-full text-sm" value={specRole} onChange={(e) => setSpecRole(e.target.value)} />
              </label>
            </div>
            <label className="block text-xs theme-muted">
              {t("目标", "Goal")}
              <textarea className="input mt-0.5 w-full text-sm" rows={3} value={specGoal} onChange={(e) => setSpecGoal(e.target.value)} />
            </label>
            {spec.opening_questions?.length > 0 && (
              <div>
                <p className="text-xs theme-muted mb-1">{t("开场问题", "Opening questions")}</p>
                <div className="flex flex-wrap gap-1.5">
                  {spec.opening_questions.slice(0, 4).map((q, i) => (
                    <button key={i} type="button" onClick={() => setTrialQ(q)} className="rounded-full border theme-border px-2.5 py-1 text-xs hover:bg-black/5 dark:hover:bg-white/5">
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="border-t theme-border pt-3 space-y-2">
              <p className="text-xs theme-muted">{t("试跑一下（真实问数链路）", "Trial run (real query)")}</p>
              <div className="flex gap-2">
                <input
                  className="input flex-1 text-sm"
                  value={trialQ}
                  onChange={(e) => setTrialQ(e.target.value)}
                  placeholder={t("输入一个业务问题，如：上月各门店销量对比", "Ask a business question…")}
                  onKeyDown={(e) => { if (e.key === "Enter" && !trialing) void onTrial(); }}
                />
                <button type="button" onClick={() => void onTrial()} disabled={trialing || !trialQ.trim()} className="btn-secondary inline-flex items-center gap-1 px-3 py-1.5 text-sm">
                  {trialing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
                  {t("试跑", "Trial")}
                </button>
              </div>
              {trialResult && (
                <div className={`rounded-lg border p-2.5 text-xs ${trialResult.success ? "border-emerald-500/40 bg-emerald-500/5" : "border-rose-500/40 bg-rose-500/5"}`}>
                  {trialResult.success ? (
                    <>
                      <p className="font-medium text-emerald-600 dark:text-emerald-400">
                        {t(`成功，返回 ${trialResult.row_count ?? 0} 行`, `OK, ${trialResult.row_count ?? 0} rows`)}
                      </p>
                      {trialResult.answer_excerpt && <p className="mt-1 theme-muted whitespace-pre-wrap">{trialResult.answer_excerpt.slice(0, 400)}</p>}
                      {trialResult.sql && (
                        <pre className="mt-1 overflow-x-auto rounded bg-black/5 dark:bg-white/5 p-2 font-mono">{trialResult.sql.slice(0, 500)}</pre>
                      )}
                    </>
                  ) : (
                    <p className="text-rose-500">{trialResult.error || t("试跑失败", "Trial failed")}</p>
                  )}
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={() => void onPublish()} disabled={publishing} className="btn-primary inline-flex items-center gap-1.5 px-4 py-2 text-sm">
                {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
                {publishing ? t("发布中…", "Publishing…") : t("发布为智能体", "Publish as agent")}
              </button>
              <button type="button" onClick={() => { setSpec(null); setTrialResult(null); }} className="btn-secondary px-3 py-1.5 text-sm">
                {t("放弃草案", "Discard")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── 段二：喂养训练 ── */}
      <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
        <h2 className="font-medium inline-flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-sky-500" />
          {t("② 喂养训练", "② Feed & train")}
        </h2>
        <p className="text-xs theme-muted">
          {t("平时问数时的点赞、纠错、存示例都会被自动学习。也可以手动触发一次集中学习。", "Feedback from daily asking is learned automatically. You can also trigger learning manually.")}
        </p>
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { label: t("问数范例", "Examples"), value: `${stats.examples_indexed}/${stats.examples_positive + stats.examples_negative}`, hint: t("已向量化/总数", "indexed/total") },
              { label: t("分析套路", "Templates"), value: `${stats.templates_active}/${stats.templates_total}`, hint: t("启用/总数", "active/total") },
              { label: t("业务习惯", "Rules"), value: `${stats.rules_active}/${stats.rules_total}`, hint: t("启用/总数", "active/total") },
              { label: t("收到反馈", "Feedback"), value: `${stats.feedback_total}`, hint: t("问数轨迹", "traces") + ` ${stats.traces_total}` },
            ].map((k) => (
              <div key={k.label} className="rounded-lg border theme-border p-2.5 text-center">
                <div className="text-lg font-semibold">{k.value}</div>
                <div className="text-xs">{k.label}</div>
                <div className="text-[11px] theme-muted">{k.hint}</div>
              </div>
            ))}
          </div>
        )}
        {canManage && (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void onDistill()} disabled={distilling} className="btn-secondary inline-flex items-center gap-1 px-3 py-1.5 text-xs">
              {distilling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookOpen className="h-3.5 w-3.5" />}
              {t("从历史问答学习", "Learn from history")}
            </button>
            <button type="button" onClick={() => void onMineTemplates()} disabled={miningTpl} className="btn-secondary inline-flex items-center gap-1 px-3 py-1.5 text-xs">
              {miningTpl ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ClipboardList className="h-3.5 w-3.5" />}
              {t("挖掘分析套路", "Mine templates")}
            </button>
            <button type="button" onClick={() => void onMineRules()} disabled={miningRule} className="btn-secondary inline-flex items-center gap-1 px-3 py-1.5 text-xs">
              {miningRule ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              {t("挖掘业务习惯", "Mine rules")}
            </button>
            <Link href="/knowledge-distill" className="btn-secondary inline-flex items-center gap-1 px-3 py-1.5 text-xs">
              {t("管理问数范文集", "Manage examples")} →
            </Link>
            <Link href="/training-center" className="btn-secondary inline-flex items-center gap-1 px-3 py-1.5 text-xs">
              {t("进入训练中心", "Training center")} →
            </Link>
          </div>
        )}
        {examples.length > 0 && (
          <div>
            <p className="text-xs theme-muted mb-1.5">{t("最近学到的范例", "Recent examples")}</p>
            <ul className="space-y-1">
              {examples.map((ex) => (
                <li key={ex.id} className="flex items-center gap-2 text-xs rounded-lg border theme-border px-2.5 py-1.5">
                  <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] ${ex.kind === "positive" ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-rose-500/10 text-rose-500"}`}>
                    {ex.kind === "positive" ? t("好答案", "good") : t("反面例", "bad")}
                  </span>
                  <span className="truncate flex-1" title={ex.sql_text}>{ex.question}</span>
                  <span className="theme-muted shrink-0">×{ex.use_count}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* ── 段三：验收 ── */}
      <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
        <h2 className="font-medium inline-flex items-center gap-2">
          <Award className="h-4 w-4 text-amber-500" />
          {t("③ 验收质量", "③ Quality check")}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div className="rounded-lg border theme-border p-2.5 text-center">
            <div className="text-lg font-semibold">{quality?.eval_set_size ?? 0}</div>
            <div className="text-xs">{t("自测题数", "Eval questions")}</div>
          </div>
          <div className="rounded-lg border theme-border p-2.5 text-center">
            <div className="text-lg font-semibold">
              {quality?.latest_run?.overall_score != null ? `${Math.round(quality.latest_run.overall_score)}` : "—"}
            </div>
            <div className="text-xs">{t("最近得分", "Latest score")}</div>
          </div>
          <div className="rounded-lg border theme-border p-2.5 text-center">
            <div className="text-lg font-semibold">
              {quality?.latest_run ? `${quality.latest_run.passed}/${quality.latest_run.total}` : "—"}
            </div>
            <div className="text-xs">{t("最近通过率", "Latest pass rate")}</div>
          </div>
        </div>
        {quality?.weak_categories && quality.weak_categories.length > 0 && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            {t("弱项提示：", "Weak areas: ")}
            {quality.weak_categories.slice(0, 3).map((w) => w.category).filter(Boolean).join("、")}
          </p>
        )}
        {canManage && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void onRunEval()}
              disabled={runningEval || (quality?.eval_set_size ?? 0) === 0}
              className="btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
              title={
                (quality?.eval_set_size ?? 0) === 0
                  ? t("考题库为空，请先到质量看板构建自测卷", "Eval set is empty — build one on the quality board first")
                  : undefined
              }
            >
              {runningEval ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {runningEval ? t("自测进行中…", "Eval running…") : t("跑一次自测", "Run an eval")}
            </button>
            {(quality?.eval_set_size ?? 0) === 0 && (
              <span className="text-[11px] text-amber-600 dark:text-amber-400">
                {t("考题库为空 → 去", "No eval set → go to")}
                <Link href="/agent-quality" className="underline hover:text-amber-700">{t("质量看板", "quality board")}</Link>
              </span>
            )}
          </div>
        )}
        {runs.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left theme-muted">
                  <th className="py-1.5 pr-3 font-medium">{t("时间", "Time")}</th>
                  <th className="py-1.5 pr-3 font-medium">{t("状态", "Status")}</th>
                  <th className="py-1.5 pr-3 font-medium">{t("得分", "Score")}</th>
                  <th className="py-1.5 pr-3 font-medium">{t("通过率", "Pass")}</th>
                  <th className="py-1.5 font-medium">{t("版本", "Ver.")}</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-t theme-border">
                    <td className="py-1.5 pr-3 whitespace-nowrap">{r.created_at ? new Date(r.created_at).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
                    <td className="py-1.5 pr-3">
                      <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] ${
                        r.status === "done" ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                        : r.status === "failed" ? "bg-rose-500/10 text-rose-500"
                        : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                      }`}>
                        {r.status === "done" ? t("完成", "done") : r.status === "failed" ? t("失败", "failed") : t("进行中", "running")}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3">{r.overall_score != null ? Math.round(r.overall_score) : "—"}</td>
                    <td className="py-1.5 pr-3">{r.status === "done" ? `${r.passed}/${r.total}` : "—"}</td>
                    <td className="py-1.5">{r.agent_version != null ? `v${r.agent_version}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[11px] theme-muted">
          {t("系统每周会自动学习并自测，达标后才晋升新版本。", "The system learns and self-tests weekly; new versions are promoted only when they pass.")}{" "}
          <Link href="/agent-quality" className="text-blue-500">{t("质量看板", "Quality board")} →</Link>
        </p>
      </div>

      {/* ── 段五：我的看板（组件化视图入口）── */}
      <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-medium inline-flex items-center gap-2">
            <LayoutDashboard className="h-4 w-4 text-blue-500" />
            {t("我的看板", "My dashboards")}
          </h2>
          <div className="flex items-center gap-3">
            <Link href={`/dashboards/studio?ds=${dsId}`} className="text-[11px] text-blue-500 hover:underline">
              {t("自助看板", "Dashboard studio")} →
            </Link>
            <span className="text-[11px] theme-muted">{boards.length}</span>
          </div>
        </div>
        {boards.length === 0 ? (
          <p className="text-xs theme-muted">
            {t("还没有看板，在对话里说「生成经营看板」即可创建。", "No dashboards yet — ask in chat to generate one.")}
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {boards.map((b) => {
              const badge =
                b.status === "done"
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : b.status === "failed"
                    ? "bg-rose-500/10 text-rose-500"
                    : "bg-amber-500/10 text-amber-600 dark:text-amber-400";
              const label =
                b.status === "done"
                  ? t("已完成", "done")
                  : b.status === "failed"
                    ? t("失败", "failed")
                    : t("生成中", "running");
              return (
                <div key={b.id} className="rounded-lg border theme-border p-2.5">
                  <div className="flex items-center gap-2">
                    <Link href={b.widget_url} className="min-w-0 flex-1 truncate text-xs font-medium hover:text-blue-500">
                      {b.title || t("未命名看板", "Untitled dashboard")}
                    </Link>
                    <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] ${badge}`}>{label}</span>
                  </div>
                  <div className="mt-1 text-[11px] theme-muted">
                    {b.period_start && b.period_end ? `${b.period_start} ~ ${b.period_end}` : b.created_at ? b.created_at.slice(0, 16).replace("T", " ") : "—"}
                  </div>
                  {b.kpis && b.kpis.length > 0 && (
                    <div className="mt-1.5 grid grid-cols-2 gap-1">
                      {b.kpis.slice(0, 4).map((k) => (
                        <div key={k.label} className="rounded bg-black/5 dark:bg-white/5 px-1.5 py-1">
                          <div className="text-[10px] theme-muted">{k.label}</div>
                          <div className="truncate font-mono text-[11px] font-semibold">{k.value}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {b.status === "failed" && b.error && (
                    <p className="mt-1 truncate text-[11px] text-rose-500">{b.error}</p>
                  )}
                  <div className="mt-1.5">
                    <Link href={b.widget_url} className="text-[11px] text-blue-500">
                      {t("打开组件视图", "Open widget view")} →
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
