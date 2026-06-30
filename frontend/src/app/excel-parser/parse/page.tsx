"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  CheckCircle,
  FileSearch,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  Upload,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import { dataSourcesApi, formatApiError } from "@/lib/api";
import { pickLocalExcelFiles, uploadExcelFilesInBatches } from "@/lib/excelParser/localFolder";
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
  const [templateSources, setTemplateSources] = useState<{ id: string; name: string; can_manage?: boolean }[]>([]);
  const [uploadingLocal, setUploadingLocal] = useState(false);
  const [localFolderLabel, setLocalFolderLabel] = useState("");
  const [uploadedFileCount, setUploadedFileCount] = useState(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const selectedSource = templateSources.find((s) => s.id === dataSourceId);
  const canUploadLocal = !!dataSourceId && !!selectedSource?.can_manage;

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const loadSources = useCallback(() => {
    if (!ready) return;
    dataSourcesApi.list().then(({ data }) => {
      const items = (data as { items: { id: string; name: string; driver: string; can_manage?: boolean }[] }).items || [];
      setTemplateSources(
        items
          .filter((x) => x.driver === "excel_template")
          .map((x) => ({ id: x.id, name: x.name, can_manage: x.can_manage })),
      );
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

  const uploadLocalFiles = async (files: File[], folderLabel: string) => {
    if (!dataSourceId) return;
    setUploadingLocal(true);
    try {
      let uploaded = 0;
      await uploadExcelFilesInBatches(async (batch) => {
        await dataSourcesApi.uploadExcel(dataSourceId, batch);
        uploaded += batch.length;
        setUploadedFileCount(uploaded);
      }, files);
      setLocalFolderLabel(folderLabel);
      toast.success(
        t(`已从「${folderLabel || "本地文件夹"}」上传 ${uploaded} 个 Excel 文件`, `Uploaded ${uploaded} Excel file(s) from local folder`),
      );
    } catch (err) {
      toast.error(formatApiError(err, t("上传失败", "Upload failed")));
    } finally {
      setUploadingLocal(false);
    }
  };

  const handlePickLocalFolder = async () => {
    if (!dataSourceId) {
      toast.error(t("请先选择模板数据源", "Select a template data source first"));
      return;
    }
    if (!selectedSource?.can_manage) {
      toast.error(t("您没有该数据源的上传权限", "No upload permission for this data source"));
      return;
    }
    try {
      const { files, folderLabel } = await pickLocalExcelFiles(recursive);
      if (files.length === 0) return;
      setUploadedFileCount(0);
      await uploadLocalFiles(files, folderLabel);
    } catch (err) {
      toast.error(formatApiError(err, t("选择文件夹失败", "Failed to pick folder")));
    }
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
            <label className="mb-1 block text-sm theme-muted">{t("模板数据源", "Template data source")}</label>
            <select value={dataSourceId} onChange={(e) => { setDataSourceId(e.target.value); setLocalFolderLabel(""); setUploadedFileCount(0); }} className="input w-full">
              <option value="">{t("-- 请选择（本地上传必填）--", "-- Select (required for local upload) --")}</option>
              {templateSources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}{s.can_manage ? "" : t("（仅问数）", " (ask only)")}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs theme-muted">
              {t("从该数据源 input/ 读取 Excel；选择本地文件夹会先上传到此数据源", "Reads from source input/; local folder uploads go here first")}
            </p>
          </div>

          <div className="rounded-lg border theme-border p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium theme-text">{t("本机 Excel 文件夹", "Local Excel folder")}</p>
                <p className="text-xs theme-muted mt-0.5">
                  {t("在浏览器中选择您电脑上的文件夹，自动上传后解析", "Pick a folder on your PC — files upload to the server first")}
                </p>
              </div>
              <button
                type="button"
                onClick={handlePickLocalFolder}
                disabled={uploadingLocal || parseLoading || !canUploadLocal}
                className="btn-secondary flex items-center gap-2 px-3 py-2 text-sm disabled:opacity-50"
              >
                {uploadingLocal ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
                {uploadingLocal ? t("上传中…", "Uploading…") : t("选择本地文件夹", "Pick local folder")}
              </button>
            </div>
            {!dataSourceId && (
              <p className="text-xs text-amber-600">{t("请先选择模板数据源", "Select a template data source first")}</p>
            )}
            {dataSourceId && !selectedSource?.can_manage && (
              <p className="text-xs text-amber-600">{t("当前数据源仅有问数权限，无法上传本地文件", "Ask-only access — cannot upload local files")}</p>
            )}
            {localFolderLabel && uploadedFileCount > 0 && (
              <p className="text-xs text-green-600 flex items-center gap-1">
                <Upload className="h-3.5 w-3.5" />
                {t(`已上传「${localFolderLabel}」中 ${uploadedFileCount} 个文件`, `${uploadedFileCount} file(s) uploaded from "${localFolderLabel}"`)}
              </p>
            )}
          </div>

          <details className="group">
            <summary className="cursor-pointer text-sm theme-muted hover:theme-text">
              {t("高级：服务器文件夹路径", "Advanced: server folder path")}
            </summary>
            <div className="mt-2">
              <input
                type="text"
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
                placeholder={t("例如：/data/reports（服务器上的路径）", "e.g. /data/reports (on server)")}
                className="input w-full font-mono text-sm"
              />
              <p className="mt-1 text-xs theme-muted">
                {t("仅后端主机可访问的绝对路径；普通用户请用上方「选择本地文件夹」", "Absolute path on backend host only; use local folder picker above")}
              </p>
            </div>
          </details>

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
