"use client";

import Link from "next/link";
import { Bot, Workflow, MessageSquare, Database, Cpu, Zap } from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export default function HomePage() {
  const { lang } = useLangStore();
  const d = translations.dashboard;
  const f = d.features;

  const features = [
    { icon: Bot,          titleKey: "multiAgent",  descKey: "multiAgentD",  href: "/agents",    color: "text-blue-400",   bg: "bg-blue-400/10" },
    { icon: Workflow,     titleKey: "workflow",    descKey: "workflowD",    href: "/workflows", color: "text-purple-400", bg: "bg-purple-400/10" },
    { icon: MessageSquare,titleKey: "chat",        descKey: "chatD",        href: "/chat",      color: "text-green-400",  bg: "bg-green-400/10" },
    { icon: Database,     titleKey: "rag",         descKey: "ragD",         href: "/knowledge", color: "text-yellow-400", bg: "bg-yellow-400/10" },
    { icon: Cpu,          titleKey: "modelHub",    descKey: "modelHubD",    href: "/models",    color: "text-pink-400",   bg: "bg-pink-400/10" },
    { icon: Zap,          titleKey: "tools",       descKey: "toolsD",       href: "/tools",     color: "text-orange-400", bg: "bg-orange-400/10" },
  ] as const;

  return (
    <div className="min-h-screen p-8">
      <div className="mb-12 text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-1.5 text-sm text-blue-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
          {d.badge[lang]}
        </div>
        <h1 className="mb-4 text-5xl font-bold text-white">{d.title[lang]}</h1>
        <p className="mx-auto max-w-2xl text-lg text-slate-400">{d.subtitle[lang]}</p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
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
            <span>{d.step1[lang]} <Link href="/models" className="text-blue-400 hover:underline">Model Hub</Link> {d.step1b[lang]}</span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">2</span>
            <span>{d.step2[lang]} <Link href="/agents" className="text-blue-400 hover:underline">Agents</Link> {d.step2b[lang]}</span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">3</span>
            <span>{d.step3[lang]}</span>
          </li>
          <li className="flex items-start gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-500/20 text-xs font-bold text-blue-400">4</span>
            <span>{d.step4[lang]}</span>
          </li>
        </ol>
      </div>
    </div>
  );
}
