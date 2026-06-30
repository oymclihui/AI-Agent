"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  CheckCircle,
  FileSearch,
  Loader2,
  Play,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { dataSourcesApi } from "@/lib/api";
import { useExcelParserStore } from "@/lib/excelParser/store";
import { useLangStore } from "@/lib/langStore";
import { useClientAuth } from "@/hooks/useClientAuth";

const STATUS_CFG = {
  idle: { zh: "待命", en: "Idle", className: "bg-slate-500/15 text-slate-400", spin: false },
  running: { zh: "解析中", en: "Running", className: "bg-blue-500/15 text-blue-400", spin: true },
  completed: { zh: "已完成", en: "Completed", className: "bg-emerald-500/15 text-emerald-400", spin: false },
  failed: { zh: "失败", en: "Failed", className: "bg-red-500/15 text-red-400", spin: false },
};

export default function ExcelParserParsePage() {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const { ready } = useClientAuth();
  const { templates, parseTask, parseLoading, fetchTemplates, startParse, pollParseStatus } = useExcelParserStore();

  const [templateId, setTemplateId] = useState("");
  const [folderPath, setFolderPath] = useState("");
  const [dataSourceId, setDataSourceId] = useState("");
  const [recursive, setRecursive] = useState(true);
  const [outputFilename, setOutputFilename] = useState("");
  const [templateSources, setTemplateSources] = useState<{ id: string; name: string }[]>([]);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const loadSources = useCallback(() => {
    if (!ready) return;
    dataSourcesApi.list().then(({ data }) => {
      const items = (data as { items: { id: string; name: string; driver: string }[] }).items || [];
      setTemplateSources(items.filter((x) => x.driver === "excel_template").map((x) => ({ id: x.id, name: x.name })));
    }).catch(() => {});
  }, [ready]);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  useEffect(() => {
    if (parseTask.status === "running" && parseTask.task_id) {
      if (pollingRef.current) clearInterval(pollingRef.current);
      pollingRef.current = setInterval(() => pollParseStatus(parseTask.task_id), 2000);
    } else if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [parseTask.status, parseTask.task_id, pollParseStatus]);

  const canStart = templateId && (folderPath.trim() || dataSourceId);

  const handleStart = async () => {
    if (!canStart) return;
    await startParse({
      templateId,
      folderPath: folderPath.trim() || undefined,
      dataSourceId: dataSourceId || undefined,
      recursive,
      outputFilename: outputFilename.trim() || undefined,
    });
  };

  const st = STATUS_CFG[parseTask.status];
  const progressPercent = parseTask.progress;

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold theme-text">{t("文件解析", "Batch parse")}</h1>
        <p className="mt-1 text-sm theme-muted">{t("选择模板与数据源/文件夹，批量解析 Excel", "Pick template and source folder to parse")}</p>
      </div>

      <div className="theme-card mb-6">
        <h3 className="mb-4 text-sm font-semibold theme-text">{t("解析配置", "Configuration")}</h3>
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm theme-muted">{t("选择模板", "Template")}</label>
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} className="input w-full">
              <option value="">{t("-- 请选择 --", "-- Select --")}</option>
              {templates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>{tpl.name} ({tpl.type})</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-sm theme-muted">{t("模板数据源（可选）", "Template data source (optional)")}</label>
            <select value={dataSourceId} onChange={(e) => setDataSourceId(e.target.value)} className="input w-full">
              <option value="">{t("不使用数据源", "None — use folder path")}</option>
              {templateSources.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <p className="mt-1 text-xs theme-muted">
              {t("选择后从该数据源的 input/ 目录读取已上传的原始 Excel", "Reads uploaded raw Excel from the source input/ folder")}
            </p>
          </div>

          <div>
            <label className="mb-1 block text-sm theme-muted">{t("服务器文件夹路径（可选）", "Server folder path (optional)")}</label>
            <input
              type="text"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              placeholder={t("例如：E:\\data\\reports", "e.g. E:\\data\\reports")}
              className="input w-full font-mono text-sm"
            />
            <p className="mt-1 text-xs theme-muted">
              {t("后端可访问的绝对路径；与数据源二选一或同时填（优先数据源 input/）", "Absolute path on the backend host")}
            </p>
          </div>

          <div>
            <label className="mb-1 block text-sm theme-muted">{t("输出文件名（可选）", "Output filename (optional)")}</label>
            <input type="text" value={outputFilename} onChange={(e) => setOutputFilename(e.target.value)} placeholder={t("解析结果", "parsed_wide")} className="input w-full" />
          </div>

          <label className="flex items-center gap-2 text-sm theme-text">
            <input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} className="rounded" />
            {t("递归扫描子文件夹", "Scan subfolders recursively")}
          </label>

          <button
            type="button"
            onClick={handleStart}
            disabled={parseLoading || !canStart}
            className="btn-primary flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
          >
            {parseLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {parseLoading ? t("解析中…", "Parsing…") : t("开始解析", "Start parse")}
          </button>
        </div>
      </div>

      <div className="theme-card">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold theme-text">{t("解析进度", "Progress")}</h3>
          <button type="button" onClick={() => parseTask.task_id && pollParseStatus(parseTask.task_id)} disabled={!parseTask.task_id} className="btn-secondary flex items-center gap-1 px-2 py-1 text-xs">
            <RefreshCw className="h-3.5 w-3.5" />
            {t("刷新", "Refresh")}
          </button>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm ${st.className}`}>
            {parseTask.status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
            {lang === "zh" ? st.zh : st.en}
          </span>
          {parseTask.task_id && (
            <span className="font-mono text-xs theme-muted">ID: {parseTask.task_id.slice(0, 8)}…</span>
          )}
        </div>

        {parseTask.status !== "idle" && (
          <div className="space-y-3">
            <div className="h-3 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
              <div
                className={`h-full rounded-full transition-all ${parseTask.status === "failed" ? "bg-red-500" : parseTask.status === "completed" ? "bg-emerald-500" : "bg-blue-500"}`}
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <p className="text-sm theme-muted">
              {t("进度", "Progress")}: {progressPercent}% ({parseTask.success_count + parseTask.failed_count} / {parseTask.total || "?"})
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400">
                <CheckCircle className="h-4 w-4" />
                {t("成功", "OK")}: <strong>{parseTask.success_count}</strong>
              </div>
              <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400">
                <XCircle className="h-4 w-4" />
                {t("失败", "Fail")}: <strong>{parseTask.failed_count}</strong>
              </div>
            </div>
            {parseTask.status === "failed" && parseTask.error_message && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{parseTask.error_message}</div>
            )}
            {parseTask.status === "completed" && (
              <div className="flex flex-wrap gap-2 pt-2">
                <Link href="/excel-parser/preview" className="btn-primary px-4 py-2 text-sm">{t("查看结果", "View results")}</Link>
                <Link href="/excel-parser/logs" className="btn-secondary px-4 py-2 text-sm">{t("查看日志", "View logs")}</Link>
              </div>
            )}
          </div>
        )}

        {parseTask.status === "idle" && !parseTask.task_id && (
          <div className="flex flex-col items-center py-10 theme-muted">
            <FileSearch className="mb-3 h-12 w-12 opacity-40" />
            <p className="text-sm">{t("尚未启动解析任务", "No parse job yet")}</p>
          </div>
        )}
      </div>
    </>
  );
}
