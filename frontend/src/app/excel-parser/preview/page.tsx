"use client";

import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileSpreadsheet,
  FileText,
  Loader2,
  Table2,
} from "lucide-react";
import { useExcelParserStore } from "@/lib/excelParser/store";
import { useLangStore } from "@/lib/langStore";

const PAGE_SIZE = 50;

function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  t,
}: {
  currentPage: number;
  totalPages: number;
  onPageChange: (p: number) => void;
  t: (zh: string, en: string) => string;
}) {
  return (
    <div className="flex items-center justify-between py-3">
      <span className="text-sm theme-muted">{t("第", "Page")} {currentPage} / {totalPages}</span>
      <div className="flex items-center gap-1">
        <button type="button" onClick={() => onPageChange(Math.max(1, currentPage - 1))} disabled={currentPage <= 1} className="btn-secondary p-1.5 disabled:opacity-40">
          <ChevronLeft className="h-4 w-4" />
        </button>
        {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
          let pageNum: number;
          if (totalPages <= 5) pageNum = i + 1;
          else if (currentPage <= 3) pageNum = i + 1;
          else if (currentPage >= totalPages - 2) pageNum = totalPages - 4 + i;
          else pageNum = currentPage - 2 + i;
          return (
            <button
              key={pageNum}
              type="button"
              onClick={() => onPageChange(pageNum)}
              className={`rounded-lg px-3 py-1 text-xs ${pageNum === currentPage ? "bg-blue-600 text-white" : "theme-muted hover:bg-black/5"}`}
            >
              {pageNum}
            </button>
          );
        })}
        <button type="button" onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))} disabled={currentPage >= totalPages} className="btn-secondary p-1.5 disabled:opacity-40">
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export default function ExcelParserPreviewPage() {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const { parseResult, parseTask, exportFile, fetchParseResult } = useExcelParserStore();

  const [currentPage, setCurrentPage] = useState(1);
  const [exportFormat, setExportFormat] = useState<"excel" | "csv">("excel");
  const [filename, setFilename] = useState(t("解析结果", "parsed_result"));
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (parseTask.task_id && parseTask.status === "completed" && parseResult.data.length === 0) {
      fetchParseResult(parseTask.task_id);
    }
  }, [parseTask.task_id, parseTask.status, parseResult.data.length, fetchParseResult]);

  const totalPages = Math.max(1, Math.ceil(parseResult.data.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const startIdx = (safePage - 1) * PAGE_SIZE;
  const pageData = parseResult.data.slice(startIdx, startIdx + PAGE_SIZE);

  const handleExport = async () => {
    if (!parseTask.task_id) return;
    setExporting(true);
    try {
      await exportFile(parseTask.task_id, exportFormat, filename);
    } finally {
      setExporting(false);
    }
  };

  if (parseResult.data.length === 0) {
    return (
      <>
        <div className="mb-6">
          <h1 className="text-2xl font-semibold theme-text">{t("数据预览", "Preview")}</h1>
          <p className="mt-1 text-sm theme-muted">{t("查看解析结果并导出", "View parsed data and export")}</p>
        </div>
        <div className="theme-card flex flex-col items-center py-16 theme-muted">
          <Table2 className="mb-4 h-16 w-16 opacity-30" />
          <p className="text-sm">{t("暂无解析结果", "No results yet")}</p>
          <p className="mt-1 text-xs">{t("请先完成文件解析", "Run a parse job first")}</p>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold theme-text">{t("数据预览", "Preview")}</h1>
        <p className="mt-1 text-sm theme-muted">
          {t("共", "Total")} {parseResult.total} {t("条", "rows")}，{parseResult.columns.length} {t("列", "columns")}
        </p>
      </div>

      <div className="theme-card mb-6 overflow-hidden !p-0">
        <div className="max-h-[600px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[var(--surface-elevated)]">
              <tr className="border-b theme-border">
                <th className="w-12 px-2 py-2 text-center theme-muted">#</th>
                {parseResult.columns.map((col) => (
                  <th key={col} className="whitespace-nowrap px-3 py-2 text-left theme-muted">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageData.map((row, rowIdx) => (
                <tr key={rowIdx} className="border-t theme-border hover:bg-black/5 dark:hover:bg-white/5">
                  <td className="px-2 py-2 text-center text-xs theme-muted">{startIdx + rowIdx + 1}</td>
                  {parseResult.columns.map((col) => (
                    <td key={col} className="whitespace-nowrap px-3 py-2 theme-text">
                      {row[col] !== null && row[col] !== undefined ? String(row[col]) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border-t theme-border px-4">
          <Pagination currentPage={safePage} totalPages={totalPages} onPageChange={setCurrentPage} t={t} />
        </div>
      </div>

      <div className="theme-card">
        <h3 className="mb-4 text-sm font-semibold theme-text">{t("导出数据", "Export")}</h3>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-sm theme-muted">{t("格式", "Format")}</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setExportFormat("excel")}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm ${exportFormat === "excel" ? "border-blue-500 bg-blue-500/10 text-blue-400" : "theme-border theme-muted"}`}
              >
                <FileSpreadsheet className="h-4 w-4" /> Excel
              </button>
              <button
                type="button"
                onClick={() => setExportFormat("csv")}
                className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm ${exportFormat === "csv" ? "border-blue-500 bg-blue-500/10 text-blue-400" : "theme-border theme-muted"}`}
              >
                <FileText className="h-4 w-4" /> CSV
              </button>
            </div>
          </div>
          <div className="min-w-[200px] flex-1">
            <label className="mb-1 block text-sm theme-muted">{t("文件名", "Filename")}</label>
            <input type="text" value={filename} onChange={(e) => setFilename(e.target.value)} className="input w-full" />
          </div>
          <button type="button" onClick={handleExport} disabled={exporting || !parseTask.task_id} className="btn-primary flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50">
            {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {exporting ? t("导出中…", "Exporting…") : t("下载文件", "Download")}
          </button>
        </div>
      </div>
    </>
  );
}
