"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  FileX,
  RefreshCw,
  ScrollText,
  Search,
  XCircle,
} from "lucide-react";
import { useExcelParserStore } from "@/lib/excelParser/store";
import { useLangStore } from "@/lib/langStore";

export default function ExcelParserLogsPage() {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const { errorLogs, logsLoading, parseTask, fetchErrorLogs } = useExcelParserStore();

  const [taskIdInput, setTaskIdInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");

  const filtered = errorLogs.filter(
    (log) =>
      !searchFilter ||
      log.file.toLowerCase().includes(searchFilter.toLowerCase()) ||
      log.error.toLowerCase().includes(searchFilter.toLowerCase()),
  );

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold theme-text">{t("错误日志", "Error logs")}</h1>
        <p className="mt-1 text-sm theme-muted">{t("查看解析过程中的错误记录", "Inspect parse failures")}</p>
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { label: t("总文件数", "Total files"), value: parseTask.total, icon: Search, color: "bg-blue-500" },
          { label: t("成功数", "Success"), value: parseTask.success_count, icon: CheckCircle, color: "bg-emerald-600" },
          { label: t("失败数", "Failed"), value: parseTask.failed_count, icon: XCircle, color: "bg-red-600" },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="theme-card flex items-center gap-4">
            <div className={`rounded-xl p-3 ${color}`}>
              <Icon className="h-5 w-5 text-white" />
            </div>
            <div>
              <p className="text-sm theme-muted">{label}</p>
              <p className="text-2xl font-bold theme-text">{value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="theme-card mb-6">
        <h3 className="mb-3 text-sm font-semibold theme-text">{t("查询日志", "Query logs")}</h3>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[250px] flex-1">
            <label className="mb-1 block text-sm theme-muted">{t("任务 ID", "Task ID")}</label>
            <input
              type="text"
              value={taskIdInput}
              onChange={(e) => setTaskIdInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && taskIdInput.trim() && fetchErrorLogs(taskIdInput.trim())}
              className="input w-full font-mono text-sm"
              placeholder={t("请输入解析任务 ID", "Enter job ID")}
            />
          </div>
          <button type="button" onClick={() => taskIdInput.trim() && fetchErrorLogs(taskIdInput.trim())} disabled={!taskIdInput.trim()} className="btn-primary flex items-center gap-1 px-4 py-2 text-sm">
            <Search className="h-4 w-4" />
            {t("查询", "Search")}
          </button>
          {parseTask.task_id && (
            <button
              type="button"
              onClick={() => {
                setTaskIdInput(parseTask.task_id);
                fetchErrorLogs(parseTask.task_id);
              }}
              className="btn-secondary flex items-center gap-1 px-4 py-2 text-sm"
            >
              <RefreshCw className="h-4 w-4" />
              {t("使用当前任务", "Current job")}
            </button>
          )}
        </div>
      </div>

      <div className="theme-card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold theme-text">{t("错误记录", "Errors")}</h3>
          {errorLogs.length > 0 && (
            <input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder={t("搜索文件或错误…", "Filter…")}
              className="input w-60 py-1.5 text-xs"
            />
          )}
        </div>

        {logsLoading ? (
          <div className="flex items-center justify-center py-12 theme-muted">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
            <span className="ml-3 text-sm">{t("加载中…", "Loading…")}</span>
          </div>
        ) : errorLogs.length === 0 ? (
          <div className="flex flex-col items-center py-12 theme-muted">
            <ScrollText className="mb-3 h-12 w-12 opacity-40" />
            <p className="text-sm">{taskIdInput ? t("未找到错误日志", "No error logs") : t("请输入任务 ID", "Enter a task ID")}</p>
          </div>
        ) : filtered.length === 0 ? (
          <p className="py-8 text-center text-sm theme-muted">{t("无匹配记录", "No matches")}</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b theme-border">
                    <th className="w-12 px-2 py-2 theme-muted">#</th>
                    <th className="px-3 py-2 text-left theme-muted">{t("文件", "File")}</th>
                    <th className="px-3 py-2 text-left theme-muted">{t("错误信息", "Error")}</th>
                    <th className="w-44 px-3 py-2 text-left theme-muted">{t("时间", "Time")}</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((log, idx) => (
                    <tr key={idx} className="border-t theme-border">
                      <td className="px-2 py-2 text-center text-xs theme-muted">{idx + 1}</td>
                      <td className="px-3 py-2 font-mono text-xs theme-text">{log.file}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-start gap-1.5">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                          <span className="text-red-400">{log.error}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs theme-muted">{log.time}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center gap-2 border-t theme-border pt-4 text-sm theme-muted">
              <FileX className="h-4 w-4 text-red-400" />
              {t("共", "Total")} {filtered.length} {t("条错误", "errors")}
            </div>
          </>
        )}
      </div>
    </>
  );
}
