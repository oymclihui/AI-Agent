"use client";

import Link from "next/link";
import {
  Bot, Workflow, MessageSquare, Database, Cpu, Zap, Users, BookOpen, Briefcase,
} from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export default function HomePage() {
  const { lang } = useLangStore();
  const d = translations.dashboard;
  const f = d.features;

  const features = [
    { icon: Users,         titleKey: "employees", descKey: "employeesD", href: "/employees", color: "text-cyan-400",   bg: "bg-cyan-400/10" },
    { icon: Bot,           titleKey: "agents",    descKey: "agentsD",    href: "/agents",    color: "text-blue-400",   bg: "bg-blue-400/10" },
    { icon: BookOpen,      titleKey: "skills",    descKey: "skillsD",    href: "/skills",    color: "text-indigo-400", bg: "bg-indigo-400/10" },
    { icon: Workflow,      titleKey: "workflow",  descKey: "workflowD",  href: "/workflows", color: "text-purple-400", bg: "bg-purple-400/10" },
    { icon: Database,      titleKey: "rag",       descKey: "ragD",       href: "/knowledge", color: "text-yellow-400", bg: "bg-yellow-400/10" },
    { icon: MessageSquare, titleKey: "chat",      descKey: "chatD",      href: "/chat",      color: "text-green-400",  bg: "bg-green-400/10" },
    { icon: Cpu,           titleKey: "modelHub",  descKey: "modelHubD",  href: "/models",    color: "text-pink-400",   bg: "bg-pink-400/10" },
    { icon: Zap,           titleKey: "tools",     descKey: "toolsD",     href: "/tools",     color: "text-orange-400", bg: "bg-orange-400/10" },
  ] as const;

  return (
    <div className="min-h-screen p-8">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-6">
        <div className="text-center md:text-left">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-1.5 text-sm text-blue-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
            {d.badge[lang]}
          </div>
          <h1 className="mb-4 text-5xl font-bold text-white">{d.title[lang]}</h1>
          <p className="max-w-2xl text-lg text-slate-400">{d.subtitle[lang]}</p>
        </div>
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
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
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
              {f[titleKey][lang]}
            </h3>
            <p className="text-sm leading-relaxed text-slate-400">{f[descKey][lang]}</p>
          </Link>
        ))}
      </div>

      <div className="mt-12 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-8">
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
