"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import {
  LayoutDashboard,
  Settings,
  FileSearch,
  Table2,
  ScrollText,
} from "lucide-react";
import { useLangStore } from "@/lib/langStore";

const NAV = [
  { href: "/excel-parser", icon: LayoutDashboard, zh: "仪表盘", en: "Dashboard", exact: true },
  { href: "/excel-parser/config", icon: Settings, zh: "模板配置", en: "Templates" },
  { href: "/excel-parser/parse", icon: FileSearch, zh: "文件解析", en: "Parse" },
  { href: "/excel-parser/preview", icon: Table2, zh: "数据预览", en: "Preview" },
  { href: "/excel-parser/logs", icon: ScrollText, zh: "错误日志", en: "Logs" },
];

export default function ExcelParserNav() {
  const pathname = usePathname();
  const { lang } = useLangStore();

  return (
    <nav className="mb-6 flex flex-wrap gap-2 border-b theme-border pb-3">
      {NAV.map(({ href, icon: Icon, zh, en, exact }) => {
        const active = exact ? pathname === href : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
              active ? "nav-item-active" : "nav-item-idle",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {lang === "zh" ? zh : en}
          </Link>
        );
      })}
    </nav>
  );
}
