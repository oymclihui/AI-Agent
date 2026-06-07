"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot, Workflow, MessageSquare, Database,
  Cpu, Zap, Home, Settings, Languages, BookOpen, Briefcase,
} from "lucide-react";
import { clsx } from "clsx";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export default function Sidebar() {
  const pathname = usePathname();
  const { lang, setLang } = useLangStore();
  const nav = translations.nav;

  const navItems = [
    { href: "/",          icon: Home,         labelKey: "dashboard" as const },
    { href: "/agents",    icon: Bot,          labelKey: "agents" as const },
    { href: "/employees", icon: Briefcase,     labelKey: "employees" as const },
    { href: "/workflows", icon: Workflow,      labelKey: "workflows" as const },
    { href: "/chat",      icon: MessageSquare, labelKey: "chat" as const },
    { href: "/knowledge", icon: Database,      labelKey: "knowledge" as const },
    { href: "/skills",    icon: BookOpen,        labelKey: "skills" as const },
    { href: "/models",    icon: Cpu,           labelKey: "models" as const },
    { href: "/tools",     icon: Zap,           labelKey: "tools" as const },
  ];

  return (
    <aside className="flex h-screen w-16 flex-col items-center border-r border-[#2d2d4e] bg-[#1a1a2e] py-4 lg:w-56 lg:items-start lg:px-3">
      {/* Logo */}
      <div className="mb-8 flex items-center gap-2 px-1">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white font-bold text-sm shrink-0">
          AI
        </div>
        <span className="hidden text-white font-semibold lg:block">AI-AGENT</span>
      </div>

      {/* Nav */}
      <nav className="flex w-full flex-col gap-1">
        {navItems.map(({ href, icon: Icon, labelKey }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
                active
                  ? "bg-blue-600/20 text-blue-400"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              )}
            >
              <Icon className="h-5 w-5 shrink-0" />
              <span className="hidden lg:block">{nav[labelKey][lang]}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom area */}
      <div className="mt-auto w-full space-y-1">
        {/* Language toggle */}
        <div className="hidden lg:flex items-center gap-2 rounded-lg px-2 py-2">
          <Languages className="h-4 w-4 shrink-0 text-slate-500" />
          <div className="flex rounded-lg overflow-hidden border border-[#2d2d4e] text-xs">
            <button
              onClick={() => setLang("zh")}
              className={clsx(
                "px-2.5 py-1 transition-colors",
                lang === "zh"
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              )}
            >
              中文
            </button>
            <button
              onClick={() => setLang("en")}
              className={clsx(
                "px-2.5 py-1 transition-colors border-l border-[#2d2d4e]",
                lang === "en"
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              )}
            >
              EN
            </button>
          </div>
        </div>

        {/* Mobile language toggle (icon only) */}
        <button
          onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          className="lg:hidden flex items-center justify-center w-full py-2 text-slate-400 hover:text-slate-200 transition-colors"
          title={lang === "zh" ? "Switch to English" : "切换中文"}
        >
          <Languages className="h-5 w-5" />
        </button>

        <Link
          href="/settings"
          className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm text-slate-400 hover:bg-white/5 hover:text-slate-200 transition-colors"
        >
          <Settings className="h-5 w-5 shrink-0" />
          <span className="hidden lg:block">{nav.settings[lang]}</span>
        </Link>
      </div>
    </aside>
  );
}
