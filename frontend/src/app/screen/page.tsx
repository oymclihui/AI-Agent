"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { format } from "date-fns";
import {
  ArrowLeft, Maximize2, Minimize2, Pause, Play, Printer, RefreshCw,
  Bot, Workflow, MessageSquare, Database, Cpu, Zap, Users, BookOpen, Briefcase,
} from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { useDashboardOverview } from "@/hooks/useDashboardOverview";
import type { DashboardEmployeeCard, DashboardOverview, DashboardRecentRun } from "@/lib/dashboardTypes";

const CAROUSEL_KEY = "aiagnet-screen-carousel-ms";
const DEFAULT_CAROUSEL_MS = 10000;

const STATUS_COLORS: Record<string, string> = {
  running: "bg-blue-500",
  idle: "bg-slate-500",
  completed: "bg-green-500",
  failed: "bg-red-500",
  paused: "bg-slate-600",
};

function formatDuration(ms: number | null | undefined, lang: "zh" | "en") {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  return lang === "zh" ? `${s} 秒` : `${s}s`;
}

function statusLabel(status: string, s: typeof translations.screen, lang: "zh" | "en") {
  const map: Record<string, keyof typeof translations.screen> = {
    running: "statusRunning",
    idle: "statusIdle",
    completed: "statusCompleted",
    failed: "statusFailed",
    paused: "statusPaused",
  };
  const key = map[status];
  return key ? s[key][lang] : status;
}

function KpiCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-3xl font-bold tabular-nums theme-text">{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function HourlyChart({ data, lang }: { data: DashboardOverview["hourly_runs"]; lang: "zh" | "en" }) {
  const max = Math.max(1, ...data.map((h) => h.count));
  return (
    <div className="flex h-48 items-end gap-1 px-2">
      {data.map((h) => (
        <div key={h.hour} className="flex flex-1 flex-col items-center gap-1">
          <div className="flex w-full flex-col justify-end" style={{ height: "160px" }}>
            <div
              className="w-full rounded-t bg-gradient-to-t from-cyan-600 to-cyan-400/80 transition-all"
              style={{ height: `${(h.count / max) * 100}%`, minHeight: h.count ? 4 : 0 }}
              title={`${h.hour}:00 — ${h.count}`}
            />
          </div>
          <span className="text-[10px] text-slate-500">{h.hour}</span>
        </div>
      ))}
      {data.every((h) => h.count === 0) && (
        <p className="w-full text-center text-sm text-slate-500">
          {lang === "zh" ? "今日暂无数据" : "No data today"}
        </p>
      )}
    </div>
  );
}

function EmployeeCard({
  emp, lang, s,
}: { emp: DashboardEmployeeCard; lang: "zh" | "en"; s: typeof translations.screen }) {
  const dot = STATUS_COLORS[emp.operational_status] || STATUS_COLORS.idle;
  return (
    <Link
      href={`/employees/${emp.id}`}
      className="block rounded-lg border theme-border ops-card p-3 transition-colors hover:border-cyan-500/40"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`h-2 w-2 shrink-0 rounded-full ${dot} ${emp.operational_status === "running" ? "animate-pulse" : ""}`} />
          <span className="truncate font-medium theme-text">{emp.name}</span>
        </div>
        <span className="shrink-0 text-xs text-slate-500">{statusLabel(emp.operational_status, s, lang)}</span>
      </div>
      {emp.title && <p className="mb-1 text-xs text-cyan-400/80">{emp.title}</p>}
      <p className="mb-2 truncate text-xs text-slate-500">{emp.agent_name}</p>
      <div className="flex flex-wrap gap-2 text-[10px] text-slate-400">
        <span>{s.todayCount[lang]}: {emp.today_runs}</span>
        <span className="text-green-400">✓{emp.today_success}</span>
        {emp.today_failed > 0 && <span className="text-red-400">✗{emp.today_failed}</span>}
      </div>
      {emp.next_run_at && (
        <p className="mt-2 text-[10px] text-slate-500">
          {s.nextRun[lang]}: {format(new Date(emp.next_run_at), "HH:mm")}
        </p>
      )}
    </Link>
  );
}

function TaskFeedItem({ run, lang }: { run: DashboardRecentRun; lang: "zh" | "en" }) {
  const ok = run.status === "completed";
  return (
    <div className="flex shrink-0 items-center gap-4 border-r theme-border px-6 py-2 text-sm">
      <span className="text-slate-500 tabular-nums">{format(new Date(run.created_at), "HH:mm:ss")}</span>
      <span className="font-medium theme-text">{run.employee_name}</span>
      <span className="text-slate-400">· {run.task_name || run.task_id.slice(0, 8)}</span>
      <span className={ok ? "text-green-400" : run.status === "failed" ? "text-red-400" : "text-blue-400"}>
        {ok ? "✓" : run.status === "failed" ? "✗" : "…"}
      </span>
      <span className="max-w-md truncate text-slate-400">
        {run.output_summary || run.prompt_summary || "—"}
      </span>
      <span className="text-xs text-slate-600">{formatDuration(run.duration_ms, lang)}</span>
    </div>
  );
}

export default function ScreenPage() {
  const { lang } = useLangStore();
  const d = translations.dashboard;
  const s = translations.screen;
  const f = d.features;

  const [carouselMs, setCarouselMs] = useState(DEFAULT_CAROUSEL_MS);
  const [carouselPaused, setCarouselPaused] = useState(false);
  const [slide, setSlide] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  const { data, loading, error, liveMode, refresh } = useDashboardOverview(30000);

  useEffect(() => {
    const stored = localStorage.getItem(CAROUSEL_KEY);
    if (stored) setCarouselMs(Number(stored) || DEFAULT_CAROUSEL_MS);
  }, []);

  useEffect(() => {
    if (carouselPaused) return;
    const t = setInterval(() => setSlide((n) => (n + 1) % 5), carouselMs);
    return () => clearInterval(t);
  }, [carouselMs, carouselPaused]);

  useEffect(() => {
    const onFs = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  };

  const successRate = useMemo(() => {
    if (!data?.today.total_runs) return "—";
    return `${Math.round((data.today.completed / data.today.total_runs) * 100)}%`;
  }, [data]);

  const filteredEmployees = useMemo(() => {
    if (!data) return [];
    if (!employeeFilter) return data.employees;
    return data.employees.filter((e) => e.id === employeeFilter);
  }, [data, employeeFilter]);

  const filteredRuns = useMemo(() => {
    if (!data) return [];
    if (!employeeFilter) return data.recent_runs;
    return data.recent_runs.filter((r) => r.employee_id === employeeFilter);
  }, [data, employeeFilter]);

  const rankedEmployees = useMemo(() => {
    if (!data) return [];
    return [...data.employees].sort((a, b) => b.today_runs - a.today_runs).slice(0, 8);
  }, [data]);

  const featureItems = [
    { icon: Users, title: f.employees, desc: f.employeesD, color: "text-cyan-400" },
    { icon: Bot, title: f.agents, desc: f.agentsD, color: "text-blue-400" },
    { icon: BookOpen, title: f.skills, desc: f.skillsD, color: "text-indigo-400" },
    { icon: Workflow, title: f.workflow, desc: f.workflowD, color: "text-purple-400" },
    { icon: Database, title: f.rag, desc: f.ragD, color: "text-yellow-400" },
    { icon: MessageSquare, title: f.chat, desc: f.chatD, color: "text-green-400" },
    { icon: Cpu, title: f.modelHub, desc: f.modelHubD, color: "text-pink-400" },
    { icon: Zap, title: f.tools, desc: f.toolsD, color: "text-orange-400" },
  ];

  const slides = [
    { title: s.slide1Title[lang], content: "features" as const },
    { title: s.slide2Title[lang], content: "pipeline" as const },
    { title: s.slide3Title[lang], content: "hourly" as const },
    { title: s.slide4Title[lang], content: "ranking" as const },
    { title: s.slide5Title[lang], content: "outputs" as const },
  ];

  const nowStr = format(new Date(), lang === "zh" ? "yyyy-MM-dd HH:mm:ss" : "yyyy-MM-dd HH:mm:ss");

  return (
    <div id="ops-screen" className="ops-bg fixed inset-0 z-40 flex flex-col overflow-hidden theme-text print:static print:min-h-screen">
      {/* Header */}
      <header className="ops-header flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-cyan-500/20 px-6 py-3 print:hidden">
        <div className="flex items-center gap-4">
          <Link href="/home" className="flex items-center gap-1 text-sm theme-muted hover-theme-text">
            <ArrowLeft className="h-4 w-4" /> {s.back[lang]}
          </Link>
          <h1 className="text-lg font-bold theme-text md:text-xl">{s.title[lang]}</h1>
          <span className="hidden text-sm text-slate-500 md:inline tabular-nums">{nowStr}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
            data?.scheduler.running ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
          }`}>
            <span className={`h-1.5 w-1.5 rounded-full ${data?.scheduler.running ? "bg-green-400 animate-pulse" : "bg-red-400"}`} />
            {data?.scheduler.running ? s.schedulerOk[lang] : s.schedulerOff[lang]}
          </span>
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
            {liveMode === "sse" ? s.live[lang] : s.polling[lang]}
          </span>
          <select
            className="theme-input rounded-lg border px-2 py-1 text-xs"
            value={employeeFilter}
            onChange={(e) => setEmployeeFilter(e.target.value)}
          >
            <option value="">{s.allEmployees[lang]}</option>
            {data?.employees.map((e) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-xs text-slate-400">
            {s.carouselSpeed[lang]}
            <input
              type="range"
              min={6000}
              max={15000}
              step={1000}
              value={carouselMs}
              onChange={(e) => {
                const v = Number(e.target.value);
                setCarouselMs(v);
                localStorage.setItem(CAROUSEL_KEY, String(v));
              }}
              className="w-20"
            />
          </label>
          <button
            onClick={() => setCarouselPaused((p) => !p)}
            className="rounded-lg border theme-border p-2 hover:bg-white/5"
            title={carouselPaused ? s.resumeCarousel[lang] : s.pauseCarousel[lang]}
          >
            {carouselPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
          </button>
          <button onClick={refresh} className="rounded-lg border theme-border p-2 hover:bg-white/5">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button onClick={() => window.print()} className="rounded-lg border theme-border p-2 hover:bg-white/5">
            <Printer className="h-4 w-4" />
          </button>
          <button onClick={toggleFullscreen} className="rounded-lg border border-cyan-500/40 bg-cyan-500/10 p-2 text-cyan-300 hover:bg-cyan-500/20">
            {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-red-500/10 px-6 py-2 text-center text-sm text-red-400">{error}</div>
      )}

      {/* Main grid */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 xl:grid-cols-12 xl:grid-rows-[auto_1fr_auto]">
        {/* KPI strip */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5 xl:col-span-12">
          <KpiCard label={s.todayRuns[lang]} value={data?.today.total_runs ?? "—"} sub={`✓ ${data?.today.completed ?? 0} / ✗ ${data?.today.failed ?? 0}`} />
          <KpiCard label={s.successRate[lang]} value={successRate} />
          <KpiCard label={s.activeEmployees[lang]} value={data?.today.active_employees ?? "—"} />
          <KpiCard label={s.avgDuration[lang]} value={formatDuration(data?.today.avg_duration_ms, lang)} />
          <KpiCard label={s.tokens[lang]} value={data?.today.token_usage?.total_tokens ?? 0} />
        </div>

        {/* Carousel */}
        <div className="ops-surface relative overflow-hidden rounded-xl border theme-border xl:col-span-8 xl:row-span-1">
          <div className="absolute right-4 top-4 z-10 flex gap-1">
            {slides.map((_, i) => (
              <button
                key={i}
                onClick={() => setSlide(i)}
                className={`h-1.5 w-6 rounded-full transition-colors ${slide === i ? "bg-cyan-400" : "bg-slate-600"}`}
              />
            ))}
          </div>

          {slides.map((sl, i) => (
            <div
              key={sl.content}
              className={`absolute inset-0 p-6 transition-opacity duration-700 ${slide === i ? "opacity-100" : "pointer-events-none opacity-0"}`}
            >
              <h2 className="mb-4 text-xl font-semibold theme-text">{sl.title}</h2>

              {sl.content === "features" && data && (
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {featureItems.map(({ icon: Icon, title, desc, color }) => (
                    <div key={title[lang]} className="rounded-lg border theme-border ops-card p-3">
                      <Icon className={`mb-2 h-5 w-5 ${color}`} />
                      <p className="text-sm font-medium theme-text">{title[lang]}</p>
                      <p className="mt-1 line-clamp-2 text-[10px] text-slate-500">{desc[lang]}</p>
                    </div>
                  ))}
                  <div className="col-span-2 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3 md:col-span-4">
                    <p className="text-xs text-cyan-400">{s.platformStats[lang]}</p>
                    <div className="mt-2 flex flex-wrap gap-4 text-sm tabular-nums">
                      <span><Briefcase className="mr-1 inline h-3 w-3" />{data.platform.employees} {f.employees[lang]}</span>
                      <span><Bot className="mr-1 inline h-3 w-3" />{data.platform.agents} {f.agents[lang]}</span>
                      <span><BookOpen className="mr-1 inline h-3 w-3" />{data.platform.skills} {f.skills[lang]}</span>
                      <span><Workflow className="mr-1 inline h-3 w-3" />{data.platform.workflows} {f.workflow[lang]}</span>
                      <span><Database className="mr-1 inline h-3 w-3" />{data.platform.knowledge_bases} {f.rag[lang]}</span>
                    </div>
                  </div>
                </div>
              )}

              {sl.content === "pipeline" && (
                <ol className="space-y-3 text-sm">
                  {[d.step1, d.step2, d.step3, d.step4, d.step5].map((step, idx) => (
                    <li key={idx} className="flex gap-3 rounded-lg border theme-border ops-card p-3">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-cyan-500/20 text-sm font-bold text-cyan-400">
                        {idx + 1}
                      </span>
                      <span className="text-slate-300">
                        {step[lang]}
                        {idx === 0 && ` Model Hub ${d.step1b[lang]}`}
                        {idx === 1 && ` Agents ${d.step2b[lang]} Skills${d.step2c[lang]}`}
                        {idx === 2 && ` ${lang === "zh" ? "数字员工" : "Employees"} ${d.step3b[lang]}`}
                        {idx === 3 && ` Workflows ${d.step4b[lang]} ${f.rag[lang]} ${d.step4c[lang]}`}
                        {idx === 4 && ` Chat ${d.step5b[lang]}`}
                      </span>
                    </li>
                  ))}
                </ol>
              )}

              {sl.content === "hourly" && data && <HourlyChart data={data.hourly_runs} lang={lang} />}

              {sl.content === "ranking" && data && (
                <div className="space-y-2">
                  {rankedEmployees.map((emp, idx) => (
                    <div key={emp.id} className="flex items-center gap-3 rounded-lg border theme-border ops-card px-4 py-2">
                      <span className="w-6 text-lg font-bold text-cyan-400">{idx + 1}</span>
                      <span className="min-w-[80px] font-medium theme-text">{emp.name}</span>
                      <div className="flex-1">
                        <div className="h-3 overflow-hidden rounded-full bg-slate-800">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-cyan-600 to-blue-400"
                            style={{
                              width: `${Math.max(5, (emp.today_runs / Math.max(1, rankedEmployees[0]?.today_runs || 1)) * 100)}%`,
                            }}
                          />
                        </div>
                      </div>
                      <span className="tabular-nums text-sm text-slate-400">{emp.today_runs} {lang === "zh" ? "次" : "runs"}</span>
                    </div>
                  ))}
                  {rankedEmployees.length === 0 && <p className="text-slate-500">{s.noRuns[lang]}</p>}
                </div>
              )}

              {sl.content === "outputs" && data && (
                <div className="space-y-2 overflow-y-auto max-h-[280px]">
                  {filteredRuns.slice(0, 8).map((run) => (
                    <div key={run.id} className="rounded-lg border theme-border ops-card p-3">
                      <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                        <span>{run.employee_name} · {run.task_name}</span>
                        <span>{format(new Date(run.created_at), "HH:mm")}</span>
                      </div>
                      <p className={`text-sm text-slate-300 ${expandedRun === run.id ? "" : "line-clamp-2"}`}>
                        {run.output_summary || run.prompt_summary || "—"}
                      </p>
                      <button
                        className="mt-1 text-xs text-cyan-400 hover:underline"
                        onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
                      >
                        {expandedRun === run.id ? (lang === "zh" ? "收起" : "Collapse") : (lang === "zh" ? "展开" : "Expand")}
                      </button>
                      <Link href={`/employees/${run.employee_id}`} className="ml-3 text-xs text-slate-500 hover-theme-text">
                        →
                      </Link>
                    </div>
                  ))}
                  {filteredRuns.length === 0 && <p className="text-slate-500">{s.noRuns[lang]}</p>}
                </div>
              )}
            </div>
          ))}
          <div className="h-[340px]" />
        </div>

        {/* Employee wall */}
        <div className="ops-surface flex flex-col overflow-hidden rounded-xl border theme-border xl:col-span-4">
          <h3 className="border-b theme-border px-4 py-3 text-sm font-semibold theme-text">{s.employeeWall[lang]}</h3>
          <div className="flex-1 space-y-2 overflow-y-auto p-3">
            {filteredEmployees.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500">
                {s.noEmployees[lang]}
                <Link href="/employees" className="mt-2 block text-cyan-400 hover:underline">/employees</Link>
              </p>
            ) : (
              filteredEmployees.map((emp) => (
                <EmployeeCard key={emp.id} emp={emp} lang={lang} s={s} />
              ))
            )}
          </div>
        </div>

        {/* Task ticker */}
        <div className="ops-surface overflow-hidden rounded-xl border theme-border xl:col-span-12">
          <h3 className="border-b theme-border px-4 py-2 text-sm font-semibold theme-text">{s.taskFeed[lang]}</h3>
          <div className="flex animate-[scroll_40s_linear_infinite] hover:[animation-play-state:paused]">
            {[...filteredRuns, ...filteredRuns].map((run, i) => (
              <TaskFeedItem key={`${run.id}-${i}`} run={run} lang={lang} />
            ))}
            {filteredRuns.length === 0 && (
              <p className="px-6 py-3 text-sm text-slate-500">{s.noRuns[lang]}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
