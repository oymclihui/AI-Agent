"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Bot, Workflow, MessageSquare, Database, Cpu, Zap, Users, BookOpen, Briefcase,
  Inbox, RefreshCw,
} from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { canReadEmployees, canViewDashboard } from "@/lib/permissions";
import { api } from "@/lib/api";

type AttentionTask = {
  id: string;
  user_id: string;
  channel: string;
  question: string;
  status: string;
  stage: string;
  error: string;
  would_do: string;
  mandate: { basis?: string; via?: string; accept_mode?: string } | null;
  created_at: string | null;
};

type AttentionData = {
  waiting: AttentionTask[];
  inflight: AttentionTask[];
  failed: AttentionTask[];
  outbox_failed: number;
  observe: AttentionTask[];
};

const STATUS_LABEL: Record<string, { zh: string; en: string; cls: string }> = {
  "person/answer": { zh: "待回答", en: "Answer", cls: "text-amber-300 border-amber-500/40 bg-amber-500/10" },
  "person/review": { zh: "待确认", en: "Review", cls: "text-blue-300 border-blue-500/40 bg-blue-500/10" },
  queued: { zh: "排队中", en: "Queued", cls: "text-slate-300 border-slate-500/40 bg-slate-500/10" },
  working: { zh: "处理中", en: "Working", cls: "text-cyan-300 border-cyan-500/40 bg-cyan-500/10" },
  failed: { zh: "失败", en: "Failed", cls: "text-red-300 border-red-500/40 bg-red-500/10" },
};

function TaskRow({ t, lang }: { t: AttentionTask; lang: string }) {
  const meta = STATUS_LABEL[t.status] ?? { zh: t.status, en: t.status, cls: "text-slate-300 border-slate-500/40 bg-slate-500/10" };
  const time = t.created_at ? new Date(t.created_at).toLocaleString() : "";
  return (
    <li className="flex items-center gap-3 rounded-lg border border-[#2d2d4e] bg-[#16162a] px-4 py-2.5">
      <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs ${meta.cls}`}>
        {lang === "zh" ? meta.zh : meta.en}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-slate-200" title={t.question}>
        {t.question || (lang === "zh" ? "（无内容）" : "(empty)")}
      </span>
      <span className="shrink-0 text-xs text-slate-500">{t.user_id}</span>
      <span className="shrink-0 text-xs text-slate-600">{time}</span>
      {t.error && (
        <span className="shrink-0 max-w-[220px] truncate text-xs text-red-400" title={t.error}>
          {t.error}
        </span>
      )}
    </li>
  );
}

/** 组件健康条（蓝图阶段四）：与企微 /状态 同源，管理员可见。 */
type HealthItem = { status: string; detail: string };
type HealthData = { overall: string; items: Record<string, HealthItem> };

const HEALTH_LABEL: Record<string, { zh: string; en: string }> = {
  db: { zh: "数据库", en: "DB" },
  redis: { zh: "Redis", en: "Redis" },
  wecom: { zh: "企微连接", en: "WeCom" },
  outbox: { zh: "发件箱", en: "Outbox" },
  proactive: { zh: "主动引擎", en: "Engine" },
};
const HEALTH_CLS: Record<string, string> = {
  ok: "bg-emerald-400",
  degraded: "bg-amber-400",
  down: "bg-red-400",
};

function HealthStrip({ lang }: { lang: string }) {
  const [data, setData] = useState<HealthData | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const { data } = await api.get<HealthData>("/health/board");
        if (!cancelled) setData(data);
      } catch {
        /* 静默：健康条不阻塞首页 */
      }
    };
    load();
    const timer = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (!data) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] px-5 py-3">
      {Object.entries(data.items).map(([key, item]) => (
        <span
          key={key}
          className="flex items-center gap-1.5 text-xs text-slate-300"
          title={item.detail || undefined}
        >
          <span className={`h-2 w-2 rounded-full ${HEALTH_CLS[item.status] ?? "bg-slate-500"}`} />
          {HEALTH_LABEL[key]?.[lang === "zh" ? "zh" : "en"] ?? key}
          {item.detail && <span className="text-slate-500">{item.detail}</span>}
        </span>
      ))}
    </div>
  );
}

/** observe 记录行（蓝图阶段三）：展示「本会做什么」与准入依据，供评审后再开 auto。 */
function ObserveRow({ t, lang }: { t: AttentionTask; lang: string }) {
  const time = t.created_at ? new Date(t.created_at).toLocaleString() : "";
  // 准入记录：via ∈ whitelist/rule/default；预警记录：basis=proactive
  const key = t.mandate?.basis === "proactive" ? "proactive" : (t.mandate?.via || "");
  const basisLabel =
    key === "whitelist" ? (lang === "zh" ? "白名单" : "whitelist")
    : key === "rule" ? (lang === "zh" ? "准入规则" : "rule")
    : key === "proactive" ? (lang === "zh" ? "预警规则" : "proactive")
    : key === "subscription" ? (lang === "zh" ? "续作" : "subscription")
    : key === "default" ? (lang === "zh" ? "默认兜底" : "default")
    : key;
  return (
    <li className="flex items-center gap-3 rounded-lg border border-[#2d2d4e] bg-[#16162a] px-4 py-2.5">
      <span className="shrink-0 rounded-full border border-violet-500/40 bg-violet-500/10 px-2.5 py-0.5 text-xs text-violet-300">
        observe
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-slate-200" title={t.would_do || t.question}>
        {t.would_do || t.question || (lang === "zh" ? "（无内容）" : "(empty)")}
      </span>
      {basisLabel && (
        <span className="shrink-0 rounded border border-slate-600/50 px-1.5 py-0.5 text-[10px] text-slate-400">
          {basisLabel}
        </span>
      )}
      <span className="shrink-0 text-xs text-slate-500">{t.user_id}</span>
      <span className="shrink-0 text-xs text-slate-600">{time}</span>
    </li>
  );
}

/** 待人工面板（蓝图阶段二/三）：只列需要人介入的工单 + observe 评审记录；没有时不占位。 */
function AttentionBoard({ lang }: { lang: string }) {
  const [data, setData] = useState<AttentionData | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get<AttentionData>("/tasks/attention");
      setData(data);
    } catch {
      /* 静默：面板不阻塞首页 */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  if (!data) return null;
  const observe = data.observe ?? [];
  const empty =
    data.waiting.length === 0 && data.inflight.length === 0 && data.failed.length === 0;
  if (empty && data.outbox_failed === 0 && observe.length === 0) return null;

  return (
    <div className="mb-8 rounded-xl border border-amber-500/30 bg-[#1a1a2e] p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
          <Inbox className="h-5 w-5 text-amber-400" />
          {lang === "zh" ? "待人工" : "Needs Attention"}
          <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300">
            {data.waiting.length + data.failed.length}
          </span>
          {data.outbox_failed > 0 && (
            <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-xs text-red-300">
              {lang === "zh" ? `投递失败 ${data.outbox_failed}` : `Delivery failed ${data.outbox_failed}`}
            </span>
          )}
        </h2>
        <button
          onClick={load}
          className="flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-200"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {lang === "zh" ? "刷新" : "Refresh"}
        </button>
      </div>
      {empty ? (
        <p className="text-sm text-slate-500">
          {lang === "zh" ? "没有需要处理的任务。" : "Nothing needs attention."}
        </p>
      ) : (
        <ul className="space-y-2">
          {data.waiting.map((t) => <TaskRow key={t.id} t={t} lang={lang} />)}
          {data.failed.map((t) => <TaskRow key={t.id} t={t} lang={lang} />)}
          {data.inflight.map((t) => <TaskRow key={t.id} t={t} lang={lang} />)}
        </ul>
      )}
      {observe.length > 0 && (
        <div className="mt-4 border-t border-[#2d2d4e] pt-3">
          <p className="mb-2 text-xs font-medium text-violet-300">
            {lang === "zh"
              ? `observe 记录（${observe.length}）— 本会做什么，评审通过后再开 auto`
              : `observe records (${observe.length}) — review before switching to auto`}
          </p>
          <ul className="space-y-2">
            {observe.slice(0, 10).map((t) => <ObserveRow key={t.id} t={t} lang={lang} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const d = translations.dashboard;
  const f = d.features;
  type FeatureCopyKey = keyof typeof f;

  const features = [
    { icon: Users,         titleKey: "employees", descKey: "employeesD", href: "/employees", color: "text-cyan-400",   bg: "bg-cyan-400/10", show: canReadEmployees(user) },
    { icon: Bot,           titleKey: "agents",    descKey: "agentsD",    href: "/agents",    color: "text-blue-400",   bg: "bg-blue-400/10", show: true },
    { icon: BookOpen,      titleKey: "skills",    descKey: "skillsD",    href: "/skills",    color: "text-indigo-400", bg: "bg-indigo-400/10", show: true },
    { icon: Workflow,      titleKey: "workflow",  descKey: "workflowD",  href: "/workflows", color: "text-purple-400", bg: "bg-purple-400/10", show: true },
    { icon: Database,      titleKey: "rag",       descKey: "ragD",       href: "/knowledge", color: "text-yellow-400", bg: "bg-yellow-400/10", show: true },
    { icon: MessageSquare, titleKey: "chat",      descKey: "chatD",      href: "/chat",      color: "text-green-400",  bg: "bg-green-400/10", show: true },
    { icon: Cpu,           titleKey: "modelHub",  descKey: "modelHubD",  href: "/models",    color: "text-pink-400",   bg: "bg-pink-400/10", show: true },
    { icon: Zap,           titleKey: "tools",     descKey: "toolsD",     href: "/tools",     color: "text-orange-400", bg: "bg-orange-400/10", show: true },
  ].filter((item) => item.show);

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-6">
        <div className="text-center md:text-left">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-1.5 text-sm text-blue-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
            {d.badge[lang]}
          </div>
          <h1 className="mb-4 text-3xl font-bold text-white md:text-5xl">{d.title[lang]}</h1>
          <p className="max-w-2xl text-base text-slate-400 md:text-lg">{d.subtitle[lang]}</p>
        </div>
        {canViewDashboard(user) && (
        <Link
          href="/screen"
          className="group flex items-center gap-3 rounded-xl border border-cyan-500/40 bg-gradient-to-r from-cyan-500/10 to-blue-500/10 px-5 py-3 transition-all hover:border-cyan-400/60 hover:from-cyan-500/20"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/20">
            <Briefcase className="h-5 w-5 text-cyan-400" />
          </div>
          <div className="text-left">
            <p className="font-semibold text-cyan-300">{d.enterScreen[lang]}</p>
            <p className="text-xs text-slate-500">{d.screenHint[lang]}</p>
          </div>
        </Link>
        )}
      </div>

      {user?.is_admin && <HealthStrip lang={lang} />}

      {user?.is_admin && <AttentionBoard lang={lang} />}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6 lg:grid-cols-4">
        {features.map(({ icon: Icon, titleKey, descKey, href, color, bg }) => (
          <Link
            key={href}
            href={href}
            className="group rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6 transition-all hover:border-blue-500/50 hover:bg-[#1e1e36]"
          >
            <div className={`mb-4 inline-flex rounded-lg p-2.5 ${bg}`}>
              <Icon className={`h-6 w-6 ${color}`} />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-white transition-colors group-hover:text-blue-300">
              {f[titleKey as FeatureCopyKey][lang]}
            </h3>
            <p className="text-sm leading-relaxed text-slate-400">{f[descKey as FeatureCopyKey][lang]}</p>
          </Link>
        ))}
      </div>

      <div className="mt-8 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5 md:mt-12 md:p-8">
        <h2 className="mb-4 text-xl font-semibold text-white">{d.quickStart[lang]}</h2>
        <ol className="space-y-3 text-slate-400">
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">1</span>
            <span>
              {d.step1[lang]}{" "}
              <Link href="/models" className="text-blue-400 hover:underline">Model Hub</Link>{" "}
              {d.step1b[lang]}
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">2</span>
            <span>
              {d.step2[lang]}{" "}
              <Link href="/agents" className="text-blue-400 hover:underline">Agents</Link>{" "}
              {d.step2b[lang]}{" "}
              <Link href="/skills" className="text-blue-400 hover:underline">Skills</Link>
              {d.step2c[lang]}
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">3</span>
            <span>
              {d.step3[lang]}{" "}
              <Link href="/employees" className="text-blue-400 hover:underline">
                {lang === "zh" ? "数字员工" : "Digital Employees"}
              </Link>{" "}
              {d.step3b[lang]}
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">4</span>
            <span>
              {d.step4[lang]}{" "}
              <Link href="/workflows" className="text-blue-400 hover:underline">Workflows</Link>{" "}
              {d.step4b[lang]}{" "}
              <Link href="/knowledge" className="text-blue-400 hover:underline">
                {lang === "zh" ? "知识库" : "Knowledge"}
              </Link>{" "}
              {d.step4c[lang]}
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">5</span>
            <span>
              {d.step5[lang]}{" "}
              <Link href="/chat" className="text-blue-400 hover:underline">Chat</Link>{" "}
              {d.step5b[lang]}
            </span>
          </li>
        </ol>
      </div>
    </div>
  );
}
