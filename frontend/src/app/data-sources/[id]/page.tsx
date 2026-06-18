"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, FileSpreadsheet, MessageSquare, Play, RefreshCw, Save, Trash2, Upload, Wand2 } from "lucide-react";
import toast from "react-hot-toast";
import { dataAskApi, dataSourcesApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { useClientAuth } from "@/hooks/useClientAuth";
import { SegmentedControl } from "@/components/SegmentedControl";

type Tab = "overview" | "files" | "ask" | "semantic" | "audit" | "drift";

interface DataSourceDetail {
  id: string;
  name: string;
  driver: string;
  host: string;
  database: string;
  agent_id?: string | null;
  employee_id?: string | null;
  tables: { table_name: string; role: string; object_type?: string; column_meta?: { columns?: { name: string; type: string }[] } }[];
  semantic_model?: Record<string, unknown>;
}

interface GraphData {
  nodes: { id: string; label: string }[];
  edges: { from: string; to: string; label: string }[];
}

interface AuditRow {
  id: string;
  question?: string | null;
  sql_text: string;
  row_count: number;
  success: boolean;
  error_message?: string | null;
  created_at: string;
}

interface DriftData {
  changed: boolean;
  tables: { table_name: string; added_columns: string[]; removed_columns: string[] }[];
}

const DEFAULT_MDL = `{
  "metrics": [
    { "name": "销量", "expr": "SUM(sales_amount)" }
  ],
  "dimensions": [
    { "name": "国家", "column": "country_code", "description": "国家代码" }
  ],
  "relationships": [],
  "columns": [
    { "table": "test", "name": "internal_cost", "sensitivity": "core" }
  ],
  "notes": ["只统计权限范围内数据"]
}`;

export default function DataSourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { lang } = useLangStore();
  const { ready } = useClientAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [ds, setDs] = useState<DataSourceDetail | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [question, setQuestion] = useState("");
  const [editSql, setEditSql] = useState("");
  const [askResult, setAskResult] = useState<{
    answer?: string;
    sql?: string;
    display_sql?: string;
    explanation?: string;
    columns?: string[];
    rows?: unknown[][];
    chart?: { labels: string[]; values: number[]; series: string };
    files_released?: boolean;
  } | null>(null);
  const [asking, setAsking] = useState(false);
  const [mdlText, setMdlText] = useState(DEFAULT_MDL);
  const [savingMdl, setSavingMdl] = useState(false);
  const [auditRows, setAuditRows] = useState<AuditRow[]>([]);
  const [drift, setDrift] = useState<DriftData | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [excelFiles, setExcelFiles] = useState<{ name: string; size_bytes: number }[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);

  const load = useCallback(() => {
    if (!id) return;
    dataSourcesApi.get(id).then(({ data }) => {
      const detail = data as DataSourceDetail;
      setDs(detail);
      if (detail.semantic_model && Object.keys(detail.semantic_model).length > 0) {
        setMdlText(JSON.stringify(detail.semantic_model, null, 2));
      }
    }).catch(() => toast.error(t("加载失败", "Load failed")));
    dataSourcesApi.schemaGraph(id).then(({ data }) => setGraph(data as GraphData)).catch(() => {});
  }, [id, lang]);

  const loadAudit = useCallback(() => {
    if (!id) return;
    dataSourcesApi.auditLogs(id, { limit: 50 }).then(({ data }) => {
      setAuditRows((data as { items: AuditRow[] }).items || []);
    }).catch(() => {});
  }, [id]);

  const loadDrift = useCallback(() => {
    if (!id) return;
    dataSourcesApi.schemaDrift(id).then(({ data }) => setDrift(data as DriftData)).catch(() => {});
  }, [id]);

  const loadExcelFiles = useCallback(() => {
    if (!id) return;
    dataSourcesApi.listExcelFiles(id).then(({ data }) => {
      setExcelFiles((data as { items: { name: string; size_bytes: number }[] }).items || []);
    }).catch(() => {});
  }, [id]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  useEffect(() => {
    if (tab === "audit") loadAudit();
    if (tab === "drift") loadDrift();
    if (tab === "files") loadExcelFiles();
  }, [tab, loadAudit, loadDrift, loadExcelFiles]);

  const onGenerateSql = async () => {
    if (!id || !question.trim()) return;
    setAsking(true);
    try {
      const { data } = await dataAskApi.query({
        data_source_id: id,
        question: question.trim(),
        execute: false,
      });
      const payload = data as { sql?: string; display_sql?: string; explanation?: string };
      setEditSql(payload.display_sql || payload.sql || "");
      setAskResult({ explanation: payload.explanation, sql: payload.sql });
      toast.success(t("SQL 已生成，可编辑后执行", "SQL generated — edit then run"));
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Error"));
    } finally {
      setAsking(false);
    }
  };

  const onRunSql = async () => {
    if (!id || !editSql.trim()) return;
    setAsking(true);
    try {
      const { data } = await dataAskApi.query({
        data_source_id: id,
        question: question.trim() || t("执行 SQL", "Run SQL"),
        sql_override: editSql.trim(),
        execute: true,
      });
      setAskResult(data as typeof askResult);
      if ((data as { files_released?: boolean }).files_released) {
        toast.success(t("分析完成，临时 Excel 已从服务器释放", "Analysis done — temporary Excel files released"));
        loadExcelFiles();
        load();
      }
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Error"));
    } finally {
      setAsking(false);
    }
  };

  const onSaveGolden = async () => {
    if (!id || !question.trim() || !editSql.trim()) {
      toast.error(t("需要问题和 SQL", "Question and SQL required"));
      return;
    }
    try {
      await dataSourcesApi.saveGoldenQuery(id, { question: question.trim(), sql_text: editSql.trim() });
      toast.success(t("已保存为记忆问答", "Saved to query memory"));
    } catch {
      toast.error(t("保存失败", "Save failed"));
    }
  };

  const onSaveMdl = async () => {
    if (!id) return;
    setSavingMdl(true);
    try {
      const parsed = JSON.parse(mdlText);
      await dataSourcesApi.updateSemanticModel(id, { semantic_model: parsed });
      toast.success(t("语义模型已保存", "Semantic model saved"));
      load();
    } catch {
      toast.error(t("JSON 无效或保存失败", "Invalid JSON or save failed"));
    } finally {
      setSavingMdl(false);
    }
  };

  const onReindex = async () => {
    if (!id) return;
    setReindexing(true);
    try {
      await dataSourcesApi.reindexSchema(id);
      toast.success(t("Schema 已同步", "Schema reindexed"));
      load();
      loadDrift();
    } catch {
      toast.error(t("同步失败", "Reindex failed"));
    } finally {
      setReindexing(false);
    }
  };

  const onUploadExcel = async (fileList: FileList | null) => {
    if (!id || !fileList?.length) return;
    setUploading(true);
    try {
      await dataSourcesApi.uploadExcel(id, Array.from(fileList));
      toast.success(t("上传成功", "Uploaded"));
      loadExcelFiles();
      load();
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("上传失败", "Upload failed")));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onSaveExcelSelection = async (selected: string[]) => {
    if (!id || selected.length < 1) {
      toast.error(t("请至少选择一个 Excel 文件", "Select at least one Excel file"));
      return;
    }
    try {
      await dataSourcesApi.setTables(id, {
        tables: selected.map((table_name) => ({ table_name, role: "data", object_type: "table" })),
      });
      toast.success(t("已更新问数文件", "Analysis files updated"));
      load();
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("保存失败", "Save failed")));
    }
  };

  const onDelete = async () => {
    if (!id || !confirm(t("确定删除？", "Delete?"))) return;
    await dataSourcesApi.delete(id);
    router.push("/data-sources");
  };

  if (!ds) {
    return <div className="p-6 theme-muted text-sm">{t("加载中…", "Loading…")}</div>;
  }

  const dataTables = ds.tables.filter((x) => x.role === "data");
  const permTable = ds.tables.find((x) => x.role === "permission");
  const isExcel = ds.driver === "excel_folder";
  const tabs: { value: Tab; label: string }[] = [
    { value: "overview", label: t("概览", "Overview") },
    ...(isExcel ? [{ value: "files" as Tab, label: t("Excel 文件", "Excel files") }] : []),
    { value: "ask", label: t("问数", "Ask") },
    { value: "semantic", label: t("语义模型", "Semantic") },
    { value: "audit", label: t("审计", "Audit") },
    ...(isExcel ? [] : [{ value: "drift" as Tab, label: t("Schema", "Schema") }]),
  ];

  return (
    <div className="mx-auto max-w-6xl p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/data-sources" className="mb-2 inline-flex items-center gap-1 text-sm theme-muted">
            <ArrowLeft className="h-4 w-4" />{t("返回", "Back")}
          </Link>
          <h1 className="text-2xl font-semibold theme-text">{ds.name}</h1>
          <p className="text-sm theme-muted mt-1">
            {isExcel
              ? t("临时分析 · 执行完成后自动释放 Excel，不占服务器空间", "Ephemeral · Excel released after each run")
              : `${ds.driver} · ${ds.host} / ${ds.database}`}
          </p>
        </div>
        <button onClick={onDelete} className="btn-secondary text-red-500 flex items-center gap-1 px-3 py-2 text-sm">
          <Trash2 className="h-4 w-4" />{t("删除", "Delete")}
        </button>
      </div>

      <SegmentedControl value={tab} onChange={(v) => setTab(v as Tab)} options={tabs} />

      {tab === "overview" && (
        <>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="theme-surface rounded-xl border theme-border p-4">
              <h2 className="font-medium mb-2">{isExcel ? t("已选 Excel", "Selected Excel files") : t("数据表", "Data tables")}</h2>
              <ul className="text-sm space-y-1">
                {dataTables.map((tbl) => (
                  <li key={tbl.table_name}>
                    · {tbl.table_name}
                    {tbl.object_type === "view" && (
                      <span className="text-xs theme-muted ml-1">({t("视图", "View")})</span>
                    )}
                  </li>
                ))}
              </ul>
              {permTable && (
                <p className="mt-3 text-sm">
                  <span className="theme-muted">
                    {permTable.object_type === "view" ? t("权限视图", "Permission view") : t("权限表", "Permission table")}:{" "}
                  </span>
                  {permTable.table_name}
                </p>
              )}
            </div>
            <div className="theme-surface rounded-xl border theme-border p-4">
              <h2 className="font-medium mb-2">{t("关联", "Links")}</h2>
              {ds.agent_id && <p className="text-sm">Agent: <Link href="/agents" className="text-blue-500">{ds.agent_id.slice(0, 8)}…</Link></p>}
              {ds.employee_id && <p className="text-sm mt-1">Employee: <Link href={`/employees/${ds.employee_id}`} className="text-blue-500">{t("查看", "View")}</Link></p>}
              <Link href={`/chat?data_source_id=${ds.id}`} className="mt-3 inline-flex items-center gap-1 text-sm text-blue-500">
                <MessageSquare className="h-4 w-4" />{t("在对话中问数", "Ask in Chat")}
              </Link>
            </div>
          </div>
          {graph && graph.edges.length > 0 && (
            <div className="theme-surface rounded-xl border theme-border p-4">
              <h2 className="font-medium mb-2">{t("表关系", "Schema graph")}</h2>
              <ul className="text-xs theme-muted space-y-1">
                {graph.edges.map((e, i) => (
                  <li key={i}>{e.from} —[{e.label}]→ {e.to}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {tab === "files" && isExcel && (
        <ExcelFilesTab
          lang={lang}
          files={excelFiles}
          selected={dataTables.map((x) => x.table_name)}
          uploading={uploading}
          fileInputRef={fileInputRef}
          onUpload={onUploadExcel}
          onSaveSelection={onSaveExcelSelection}
          onRefresh={loadExcelFiles}
        />
      )}

      {tab === "ask" && (
        <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
          <h2 className="font-medium">{t("即时问数", "Quick ask")}</h2>
          {isExcel && (
            <p className="text-xs text-amber-600">
              {t(
                "临时分析模式：点击「执行」并成功返回结果后，服务器上的 Excel 将自动删除。下次分析需重新上传。",
                "Ephemeral mode: Excel files are deleted from the server after a successful run. Re-upload for the next analysis.",
              )}
            </p>
          )}
          <input
            className="input w-full"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={isExcel ? t("例如：对各 Excel 销量做聚类分析", "e.g. cluster sales across Excel files") : t("输入分析问题…", "Ask a question…")}
          />
          <div className="flex flex-wrap gap-2">
            <button disabled={asking} onClick={onGenerateSql} className="btn-secondary inline-flex items-center gap-1 px-3 py-2 text-sm">
              <Wand2 className="h-4 w-4" />{asking ? "…" : isExcel ? t("生成 Python", "Generate Python") : t("生成 SQL", "Generate SQL")}
            </button>
            <button disabled={asking || !editSql.trim()} onClick={onRunSql} className="btn-primary inline-flex items-center gap-1 px-3 py-2 text-sm">
              <Play className="h-4 w-4" />{asking ? "…" : t("执行", "Run")}
            </button>
            <button disabled={!editSql.trim()} onClick={onSaveGolden} className="btn-secondary inline-flex items-center gap-1 px-3 py-2 text-sm">
              <Save className="h-4 w-4" />{t("保存记忆", "Save memory")}
            </button>
          </div>
          <label className="block text-sm theme-muted">
            {isExcel ? t("Python 代码（可编辑）", "Python code (editable)") : t("SQL（可编辑）", "SQL (editable)")}
            <textarea
              className="input mt-1 w-full min-h-[320px] font-mono text-sm leading-relaxed"
              value={editSql}
              onChange={(e) => setEditSql(e.target.value)}
              placeholder={isExcel ? t("先生成 Python 或直接编写", "Generate or write Python") : t("先生成 SQL 或直接编写", "Generate or write SQL")}
            />
          </label>
          {askResult?.explanation && (
            <p className="text-xs theme-muted">{askResult.explanation}</p>
          )}
          {askResult?.answer && (
            <div className="whitespace-pre-wrap text-sm theme-text">{askResult.answer}</div>
          )}
          {askResult?.columns && askResult.rows && askResult.rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs border theme-border">
                <thead><tr>{askResult.columns.map((c) => <th key={c} className="border px-2 py-1">{c}</th>)}</tr></thead>
                <tbody>
                  {askResult.rows.slice(0, 20).map((row, i) => (
                    <tr key={i}>{row.map((cell, j) => <td key={j} className="border px-2 py-1">{String(cell ?? "")}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "semantic" && (
        <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
          <h2 className="font-medium">{t("MDL Lite 语义模型", "MDL Lite semantic model")}</h2>
          <p className="text-xs theme-muted">
            {t("定义 metrics / dimensions / relationships / columns.sensitivity", "Define metrics, dimensions, relationships, column sensitivity")}
          </p>
          <textarea className="input w-full min-h-[320px] font-mono text-xs" value={mdlText} onChange={(e) => setMdlText(e.target.value)} />
          <button disabled={savingMdl} onClick={onSaveMdl} className="btn-primary px-4 py-2 text-sm">
            {savingMdl ? "…" : t("保存", "Save")}
          </button>
        </div>
      )}

      {tab === "audit" && (
        <div className="theme-surface rounded-xl border theme-border p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-medium">{t("查询审计", "Query audit")}</h2>
            <button onClick={loadAudit} className="btn-secondary text-xs px-2 py-1">{t("刷新", "Refresh")}</button>
          </div>
          {auditRows.length === 0 ? (
            <p className="text-sm theme-muted">{t("暂无记录", "No logs")}</p>
          ) : (
            <div className="space-y-3 max-h-[480px] overflow-y-auto">
              {auditRows.map((row) => (
                <div key={row.id} className="rounded border theme-border p-3 text-xs">
                  <div className="flex justify-between gap-2 mb-1">
                    <span className={row.success ? "text-green-600" : "text-red-500"}>
                      {row.success ? t("成功", "OK") : t("失败", "Fail")} · {row.row_count} rows
                    </span>
                    <span className="theme-muted">{new Date(row.created_at).toLocaleString()}</span>
                  </div>
                  {row.question && <p className="theme-text mb-1">{row.question}</p>}
                  <pre className="overflow-x-auto bg-black/5 p-2 rounded">{row.sql_text}</pre>
                  {row.error_message && <p className="text-red-500 mt-1">{row.error_message}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "drift" && !isExcel && (
        <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">{t("Schema 漂移检测", "Schema drift")}</h2>
            <button disabled={reindexing} onClick={onReindex} className="btn-primary inline-flex items-center gap-1 px-3 py-1 text-sm">
              <RefreshCw className={`h-3.5 w-3.5 ${reindexing ? "animate-spin" : ""}`} />
              {reindexing ? "…" : t("同步 Schema", "Reindex")}
            </button>
          </div>
          {!drift ? (
            <p className="text-sm theme-muted">{t("检测中…", "Checking…")}</p>
          ) : drift.changed ? (
            <ul className="text-sm space-y-2">
              {drift.tables.map((tbl) => (
                <li key={tbl.table_name} className="rounded border theme-border p-2">
                  <strong>{tbl.table_name}</strong>
                  {tbl.added_columns.length > 0 && (
                    <p className="text-green-600 text-xs mt-1">+ {tbl.added_columns.join(", ")}</p>
                  )}
                  {tbl.removed_columns.length > 0 && (
                    <p className="text-red-500 text-xs">− {tbl.removed_columns.join(", ")}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-green-600">{t("Schema 与注册元数据一致", "Schema matches registered metadata")}</p>
          )}
        </div>
      )}
    </div>
  );
}

function ExcelFilesTab({
  lang,
  files,
  selected,
  uploading,
  fileInputRef,
  onUpload,
  onSaveSelection,
  onRefresh,
}: {
  lang: string;
  files: { name: string; size_bytes: number }[];
  selected: string[];
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onUpload: (files: FileList | null) => void;
  onSaveSelection: (names: string[]) => void;
  onRefresh: () => void;
}) {
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const [picked, setPicked] = useState<string[]>(selected);

  useEffect(() => {
    setPicked(selected);
  }, [selected]);

  const formatSize = (n: number) => (n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

  return (
    <div className="theme-surface rounded-xl border theme-border p-4 space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="font-medium flex items-center gap-2">
          <FileSpreadsheet className="h-5 w-5 text-green-600" />
          {t("Excel 文件夹", "Excel folder")}
        </h2>
        <div className="flex gap-2">
          <button type="button" onClick={onRefresh} className="btn-secondary text-xs px-2 py-1 inline-flex items-center gap-1">
            <RefreshCw className="h-3.5 w-3.5" />{t("刷新", "Refresh")}
          </button>
          <button
            type="button"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
            className="btn-primary text-xs px-3 py-1 inline-flex items-center gap-1"
          >
            <Upload className="h-3.5 w-3.5" />
            {uploading ? t("上传中…", "Uploading…") : t("上传 Excel", "Upload Excel")}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            multiple
            className="hidden"
            onChange={(e) => onUpload(e.target.files)}
          />
        </div>
      </div>
      <p className="text-xs text-amber-600">
        {t(
          "临时分析：问数「执行」成功后文件自动从服务器删除（单文件 ≤50MB，文件夹 ≤200MB）",
          "Ephemeral: files auto-deleted after a successful run (50MB/file, 200MB/folder)",
        )}
      </p>
      {files.length === 0 ? (
        <p className="text-sm theme-muted py-6 text-center">{t("暂无文件，请上传 Excel", "No files — upload Excel")}</p>
      ) : (
        <div className="max-h-72 overflow-y-auto space-y-1 border theme-border rounded-lg p-2">
          {files.map((f) => (
            <label key={f.name} className="flex items-center gap-2 text-sm py-1 px-1 rounded hover:bg-black/5">
              <input
                type="checkbox"
                checked={picked.includes(f.name)}
                onChange={(e) =>
                  setPicked((prev) => (e.target.checked ? [...prev, f.name] : prev.filter((x) => x !== f.name)))
                }
              />
              <span className="truncate flex-1" title={f.name}>{f.name}</span>
              <span className="text-xs theme-muted shrink-0">{formatSize(f.size_bytes)}</span>
            </label>
          ))}
        </div>
      )}
      <button
        type="button"
        disabled={picked.length < 1}
        onClick={() => onSaveSelection(picked)}
        className="btn-primary w-full py-2 text-sm"
      >
        {t(`保存问数范围（已选 ${picked.length} 个）`, `Save selection (${picked.length} file(s))`)}
      </button>
    </div>
  );
}
