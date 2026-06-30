"use client";

import { useEffect } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle,
  Clock,
  FileSearch,
  FileSpreadsheet,
  Settings,
  Table2,
  XCircle,
} from "lucide-react";
import { useExcelParserStore } from "@/lib/excelParser/store";
import { getFieldCount, getSheetNames } from "@/lib/excelParser/utils";
import { useLangStore } from "@/lib/langStore";

function StatCard({
  title,
  value,
  icon: Icon,
  iconClass,
  subtitle,
}: {
  title: string;
  value: string | number;
  icon: React.ElementType;
  iconClass: string;
  subtitle?: string;
}) {
  return (
    <div className="theme-card flex items-start gap-4">
      <div className={`rounded-xl p-3 ${iconClass}`}>
        <Icon className="h-6 w-6 text-white" />
      </div>
      <div>
        <p className="text-sm theme-muted">{title}</p>
        <p className="mt-1 text-2xl font-bold theme-text">{value}</p>
        {subtitle && <p className="mt-0.5 text-xs theme-muted">{subtitle}</p>}
      </div>
    </div>
  );
}

export default function ExcelParserDashboardPage() {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const { templates, stats, fetchTemplates, fetchStats } = useExcelParserStore();

  useEffect(() => {
    fetchTemplates();
    fetchStats();
  }, [fetchTemplates, fetchStats]);

  const successRate = stats.total > 0 ? ((stats.success / stats.total) * 100).toFixed(1) : "0.0";

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold theme-text">{t("Excel 批量解析", "Excel batch parser")}</h1>
        <p className="mt-1 text-sm theme-muted">{t("模板配置 · 批量解析 · 预览导出 · 错误日志", "Templates · parse · preview · logs")}</p>
      </div>

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard title={t("模板总数", "Templates")} value={templates.length} icon={FileSpreadsheet} iconClass="bg-indigo-600" />
        <StatCard title={t("已解析文件", "Files parsed")} value={stats.total} icon={FileSearch} iconClass="bg-blue-500" />
        <StatCard
          title={t("成功率", "Success rate")}
          value={`${successRate}%`}
          icon={CheckCircle}
          iconClass="bg-emerald-600"
          subtitle={`${stats.success} ${t("成功", "ok")} / ${stats.failed} ${t("失败", "fail")}`}
        />
        <StatCard title={t("最近解析", "Last parse")} value={stats.last_parse_time || t("暂无", "None")} icon={Clock} iconClass="bg-amber-600" />
      </div>

      <div className="mb-8">
        <h3 className="mb-3 text-lg font-semibold theme-text">{t("快捷操作", "Quick actions")}</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { href: "/excel-parser/config", icon: Settings, title: t("配置模板", "Configure templates"), desc: t("创建和管理解析模板", "Create and edit templates") },
            { href: "/excel-parser/parse", icon: FileSearch, title: t("开始解析", "Start parse"), desc: t("选择文件夹批量解析", "Batch parse Excel files") },
            { href: "/excel-parser/preview", icon: Table2, title: t("预览数据", "Preview data"), desc: t("查看结果并导出", "View and export results") },
          ].map(({ href, icon: Icon, title, desc }) => (
            <Link key={href} href={href} className="theme-card flex items-center gap-4 hover:ring-1 hover:ring-blue-500/40">
              <div className="rounded-lg bg-blue-500/10 p-2.5 text-blue-400">
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold theme-text">{title}</p>
                <p className="text-xs theme-muted">{desc}</p>
              </div>
              <ArrowRight className="h-4 w-4 theme-muted" />
            </Link>
          ))}
        </div>
      </div>

      <div className="mb-8">
        <h3 className="mb-3 text-lg font-semibold theme-text">{t("模板概览", "Template overview")}</h3>
        {templates.length === 0 ? (
          <div className="theme-card py-12 text-center">
            <FileSpreadsheet className="mx-auto h-12 w-12 theme-muted opacity-40" />
            <Link href="/excel-parser/config" className="btn-primary mt-4 inline-flex px-4 py-2 text-sm">{t("创建模板", "Create template")}</Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {templates.slice(0, 6).map((tpl) => (
              <div key={tpl.id} className="theme-card">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-semibold theme-text truncate">{tpl.name}</h4>
                  <span className="shrink-0 rounded bg-blue-500/15 px-2 py-0.5 text-xs text-blue-400">{tpl.type}</span>
                </div>
                <p className="mt-1 text-xs theme-muted">
                  {getSheetNames(tpl)} · {getFieldCount(tpl)} {t("字段", "fields")}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-3 text-lg font-semibold theme-text">{t("解析状态", "Parse status")}</h3>
        <div className="theme-card">
          {stats.total === 0 ? (
            <div className="flex items-center gap-3 py-4 theme-muted">
              <Clock className="h-5 w-5" />
              <span className="text-sm">{t("暂无解析记录", "No parse history yet")}</span>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-2xl font-bold theme-text">{stats.total}</p>
                <p className="text-xs theme-muted">{t("总文件数", "Total files")}</p>
              </div>
              <div>
                <div className="flex items-center justify-center gap-1">
                  <CheckCircle className="h-4 w-4 text-emerald-500" />
                  <p className="text-2xl font-bold text-emerald-500">{stats.success}</p>
                </div>
                <p className="text-xs theme-muted">{t("成功", "Success")}</p>
              </div>
              <div>
                <div className="flex items-center justify-center gap-1">
                  <XCircle className="h-4 w-4 text-red-500" />
                  <p className="text-2xl font-bold text-red-500">{stats.failed}</p>
                </div>
                <p className="text-xs theme-muted">{t("失败", "Failed")}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
