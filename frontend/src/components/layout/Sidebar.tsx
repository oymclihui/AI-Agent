"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot, Workflow, MessageSquare,
  Cpu, Zap, Home, Settings, Languages, BookOpen, Briefcase, Monitor,
  Library, Lightbulb, MousePointer2, Shield,
  Building2, Crown, Database, FileSpreadsheet,
} from "lucide-react";
import { clsx } from "clsx";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { SegmentedControl } from "@/components/SegmentedControl";
import { BrandMark } from "@/components/BrandMark";
import { canManageOrg, canReadEmployees, canViewDashboard, canDelegateDept, canDelegateExec } from "@/lib/permissions";

export default function Sidebar() {
  const pathname = usePathname();
  const { lang, setLang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const nav = translations.nav;

  const navItems = [
    { href: "/chat",        icon: MessageSquare,  labelKey: "chat" as const, show: true },
    { href: "/home",      icon: Home,          labelKey: "dashboard" as const, show: true },
    { href: "/screen",    icon: Monitor,       labelKey: "screen" as const, show: canViewDashboard(user) },
    { href: "/employees", icon: Briefcase,      labelKey: "employees" as const, show: canReadEmployees(user) },
    { href: "/agents",    icon: Bot,           labelKey: "agents" as const, show: true },
    { href: "/skills",    icon: BookOpen,       labelKey: "skills" as const, show: true },
    { href: "/workflows", icon: Workflow,       labelKey: "workflows" as const, show: true },
    { href: "/knowledge",   icon: Library,        labelKey: "knowledge" as const, show: true },
    { href: "/inspiration", icon: Lightbulb,      labelKey: "inspiration" as const, show: true },
    { href: "/models",      icon: Cpu,            labelKey: "models" as const, show: true },
    { href: "/tools",       icon: Zap,            labelKey: "tools" as const, show: true },
    { href: "/data-sources", icon: Database, labelKey: "dataSources" as const, show: true },
    { href: "/excel-parser", icon: FileSpreadsheet, labelKey: "excelParser" as const, show: true },
    { href: "/desktop-automation", icon: MousePointer2, labelKey: "desktopAutomation" as const, show: true },
  ].filter((item) => item.show);

  return (
    <aside className="theme-surface flex h-screen min-h-0 w-16 shrink-0 flex-col items-center overflow-hidden border-r theme-border py-4 lg:w-56 lg:items-start lg:px-3">
      <div className="mb-4 flex shrink-0 items-center gap-2 px-1 lg:mb-6">
        <BrandMark showName={false} className="lg:hidden" />
        <BrandMark className="hidden lg:flex" nameClassName="hidden lg:block" />
      </div>

      <nav className="sidebar-nav-scroll flex min-h-0 w-full flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden pr-0.5">
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

      <div className="mt-auto w-full shrink-0 space-y-1 pt-2">
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

        <button
          onClick={() => setLang(lang === "zh" ? "en" : "zh")}
          className="nav-item-idle lg:hidden flex items-center justify-center w-full py-2 transition-colors"
          title={lang === "zh" ? "Switch to English" : "切换中文"}
        >
          <Languages className="h-5 w-5" />
        </button>

        {canDelegateDept(user) && (
          <Link
            href="/settings/delegation/dept"
            className={clsx(
              "flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
              pathname.startsWith("/settings/delegation/dept")
                ? "nav-item-active"
                : "nav-item-idle",
            )}
          >
            <Building2 className="h-5 w-5 shrink-0" />
            <span className="hidden lg:block">{translations.delegation.deptTitle[lang]}</span>
          </Link>
        )}

        {canDelegateExec(user) && (
          <Link
            href="/settings/delegation/executive"
            className={clsx(
              "flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
              pathname.startsWith("/settings/delegation/executive")
                ? "nav-item-active"
                : "nav-item-idle",
            )}
          >
            <Crown className="h-5 w-5 shrink-0" />
            <span className="hidden lg:block">{translations.delegation.execTitle[lang]}</span>
          </Link>
        )}

        {canManageOrg(user) && (
          <Link
            href="/settings/organization"
            className={clsx(
              "flex items-center gap-3 rounded-lg px-2 py-2 text-sm transition-colors",
              pathname.startsWith("/settings/organization")
                ? "nav-item-active"
                : "nav-item-idle",
            )}
          >
            <Shield className="h-5 w-5 shrink-0" />
            <span className="hidden lg:block">{translations.organization.title[lang]}</span>
          </Link>
        )}

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
