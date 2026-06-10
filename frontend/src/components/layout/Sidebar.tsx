"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot, Workflow, MessageSquare, Database,
  Cpu, Zap, Home, Settings, Languages, BookOpen, Briefcase, Monitor,
} from "lucide-react";
import { clsx } from "clsx";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { SegmentedControl } from "@/components/SegmentedControl";

export default function Sidebar() {
  const pathname = usePathname();
  const { lang, setLang } = useLangStore();
  const nav = translations.nav;

  const navItems = [
    { href: "/",          icon: Home,          labelKey: "dashboard" as const },
    { href: "/screen",    icon: Monitor,       labelKey: "screen" as const },
    { href: "/employees", icon: Briefcase,      labelKey: "employees" as const },
    { href: "/agents",    icon: Bot,           labelKey: "agents" as const },
    { href: "/skills",    icon: BookOpen,       labelKey: "skills" as const },
    { href: "/workflows", icon: Workflow,       labelKey: "workflows" as const },
    { href: "/knowledge", icon: Database,      labelKey: "knowledge" as const },
    { href: "/chat",      icon: MessageSquare,  labelKey: "chat" as const },
    { href: "/models",    icon: Cpu,            labelKey: "models" as const },
    { href: "/tools",     icon: Zap,            labelKey: "tools" as const },
  ];

  return (
    <aside className="theme-surface flex h-screen w-16 flex-col items-center border-r theme-border py-4 lg:w-56 lg:items-start lg:px-3">
      {/* Logo */}
      <div className="mb-8 flex items-center gap-2 px-1">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500 text-on-primary font-bold text-sm shrink-0 shadow-sm">
          AI
        </div>
        <span className="hidden font-semibold theme-text lg:block">AI-AGENT</span>
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
                active ? "nav-item-active" : "nav-item-idle",
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
          <Languages className="h-4 w-4 shrink-0 theme-muted" />
          <SegmentedControl
            size="sm"
            value={lang}
            onChange={setLang}
            options={[
              { value: "zh", label: "中文" },
              { value: "en", label: "EN" },
            ]}
          />
        </div>

        {/* Mobile language toggle (icon only) */}
        <button
          onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          className="nav-item-idle lg:hidden flex items-center justify-center w-full py-2 transition-colors"
          title={lang === "zh" ? "Switch to English" : "切换中文"}
        >
          <Languages className="h-5 w-5" />
        </button>

        <Link
          href="/settings"
          className={clsx(
            "flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
            pathname === "/settings" || pathname.startsWith("/settings/")
              ? "nav-item-active"
              : "nav-item-idle",
          )}
        >
          <Settings className="h-5 w-5 shrink-0" />
          <span className="hidden lg:block">{nav.settings[lang]}</span>
        </Link>
      </div>
    </aside>
  );
}
