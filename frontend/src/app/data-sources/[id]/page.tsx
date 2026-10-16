"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Copy, FileSpreadsheet, MessageSquare, Pencil, Play, RefreshCw, Save, Search, Star, ThumbsDown, ThumbsUp, Trash2, Upload, Wand2 } from "lucide-react";
import toast from "react-hot-toast";
import { dataAskApi, dataSourcesApi, excelParserApi } from "@/lib/api";
import { ChartRenderer, type ChatChartData } from "@/components/ChartRenderer";
import { useLangStore } from "@/lib/langStore";
import { useClientAuth } from "@/hooks/useClientAuth";
import { SegmentedControl } from "@/components/SegmentedControl";
import ClarifyCard from "@/components/chat/ClarifyCard";

const ErDiagram = dynamic(() => import("./ErDiagram").then((mod) => mod.ErDiagram), { ssr: false });

type Tab = "overview" | "files" | "ask" | "semantic" | "audit" | "drift" | "access";

interface DataSourceDetail {
  id: string;
  name: string;
  driver: string;
  host: string;
  port?: number;
  username?: string;
  password_set?: boolean;
  database: string;
  db_schema?: string;
  ssl?: string;
  chat_enabled?: boolean;
  report_enabled?: boolean;
  agent_id?: string | null;
  employee_id?: string | null;
  can_manage?: boolean;
  tables: { table_name: string; role: string; object_type?: string; column_meta?: { columns?: { name: string; type: string }[] } }[];
  semantic_model?: Record<string, unknown>;
}

interface EditForm {
  name: string;
  host: string;
  port: string;
  username: string;
  password: string;
  database: string;
  db_schema: string;
  ssl: string;
  chat_enabled: boolean;
  report_enabled: boolean;
}

function formFromSource(ds: DataSourceDetail): EditForm {
  return {
    name: ds.name || "",
    host: ds.host || "",
    port: String(ds.port ?? ""),
    username: ds.username || "",
    password: "",
    database: ds.database || "",
    db_schema: ds.db_schema || "",
    ssl: ds.ssl || "prefer",
    chat_enabled: ds.chat_enabled !== false,
    report_enabled: ds.report_enabled !== false,
  };
}

interface GrantRow {
  id: string;
  user_id: string;
  login: string;
  display_name: string;
  can_ask: boolean;
  can_manage: boolean;
}

interface GraphData {
  nodes: { id: string; label: string }[];
  edges: { from: string; to: string; label: string; kind?: string }[];
  related?: { from: string; to: string; label: string; kind?: string }[];
  keys?: string[];
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

function toAskChart(chart: {
  type?: string;
  labels: string[];
  values?: number[];
  series?: string;
  datasets?: { label: string; data: number[] }[];
  horizontal?: boolean;
  title?: string;
} | null | undefined): ChatChartData | null {
  if (!chart?.labels?.length) return null;
  const datasets = chart.datasets?.length
    ? chart.datasets
    : [{ label: chart.series || "value", data: chart.values || [] }];
  const type = chart.type === "line" || chart.type === "pie" || chart.type === "area" || chart.type === "scatter"
    ? chart.type
    : "bar";
  return { type, title: chart.title, labels: chart.labels, datasets, horizontal: Boolean(chart.horizontal) };
}

export default function DataSourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { lang } = useLangStore();
  const { ready } = useClientAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [ds, setDs] = useState<DataSourceDetail | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [question, setQuestion] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [editSql, setEditSql] = useState("");
  const [askResult, setAskResult] = useState<{
    answer?: string;
    sql?: string;
    display_sql?: string;
    explanation?: string;
    columns?: string[];
    rows?: unknown[][];
    chart?: {
      type?: string;
      labels: string[];
      values?: number[];
      series?: string;
      datasets?: { label: string; data: number[] }[];
      horizontal?: boolean;
      title?: string;
    };
    clarification?: string;
    files_released?: boolean;
    trace_id?: number | null;
  } | null>(null);
  const [fbState, setFbState] = useState<{ traceId: number; type: string } | null>(null);
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [correctionSql, setCorrectionSql] = useState("");
  const [asking, setAsking] = useState(false);
  const [mdlText, setMdlText] = useState(DEFAULT_MDL);
  const [savingMdl, setSavingMdl] = useState(false);
  const [auditRows, setAuditRows] = useState<AuditRow[]>([]);
  const [drift, setDrift] = useState<DriftData | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [excelFiles, setExcelFiles] = useState<{ name: string; size_bytes: number }[]>([]);
  const [uploading, setUploading] = useState(false);
  const [excelPreload, setExcelPreload] = useState<{
    status?: string;
    sheet_count?: number;
    total_rows?: number;
    error?: string | null;
  } | null>(null);
  const [parsingTemplate, setParsingTemplate] = useState(false);
  const [templateStatus, setTemplateStatus] = useState<{
    parse_status?: string;
    template_id?: string | null;
    input_file_count?: number;
    output_file_count?: number;
  } | null>(null);
  const [grants, setGrants] = useState<GrantRow[]>([]);
  const [grantLogin, setGrantLogin] = useState("");
  const [grantCanAsk, setGrantCanAsk] = useState(true);
  const [grantCanManage, setGrantCanManage] = useState(false);
  const [savingGrants, setSavingGrants] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const openedEdit = useRef(false);
  const [editing, setEditing] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const [copying, setCopying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editingTables, setEditingTables] = useState(false);
  const [remoteRels, setRemoteRels] = useState<{ name: string; object_type: string }[]>([]);
  const [selDataTables, setSelDataTables] = useState<string[]>([]);
  const [selPermTable, setSelPermTable] = useState("");
  const [tblSearch, setTblSearch] = useState("");
  const [tblLoading, setTblLoading] = useState(false);
  const [tblSaving, setTblSaving] = useState(false);
  const [editForm, setEditForm] = useState<EditForm | null>(null);

  const loadTemplateStatus = useCallback(() => {
    if (!id) return;
    dataSourcesApi.excelTemplateStatus(id).then(({ data }) => {
      setTemplateStatus(data as {
        parse_status?: string;
        template_id?: string | null;
        input_file_count?: number;
        output_file_count?: number;
      });
    }).catch(() => {});
  }, [id]);

  const loadGrants = useCallback(() => {
    if (!id) return;
    dataSourcesApi.listGrants(id).then(({ data }) => {
      setGrants((data as { items: GrantRow[] }).items || []);
    }).catch(() => setGrants([]));
  }, [id]);

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

  const refreshExcelPreload = useCallback(async () => {
    if (!id || !ds?.driver || !["excel_folder", "excel_template"].includes(ds.driver)) return;
    if (excelFiles.length === 0) {
      setExcelPreload(null);
      return;
    }
    setExcelPreload((prev) => prev?.status === "ready" ? prev : { status: "loading" });
    try {
      const { data } = await dataSourcesApi.preloadExcel(id);
      setExcelPreload(data);
    } catch {
      try {
        const { data } = await dataSourcesApi.excelLoadStatus(id);
        setExcelPreload(data);
      } catch {
        setExcelPreload({ status: "error", error: t("Excel 加载失败", "Excel preload failed") });
      }
    }
  }, [id, ds?.driver, excelFiles.length, lang]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  useEffect(() => {
    if (ds?.driver && ["excel_folder", "excel_template"].includes(ds.driver) && excelFiles.length > 0) {
      void refreshExcelPreload();
    }
  }, [ds?.driver, excelFiles.length, refreshExcelPreload]);

  useEffect(() => {
    if (ds?.driver === "excel_template") loadTemplateStatus();
  }, [ds?.driver, loadTemplateStatus]);

  useEffect(() => {
    if (tab === "audit") loadAudit();
    if (tab === "drift") loadDrift();
    if (tab === "files") loadExcelFiles();
    if (tab === "access" && ds?.can_manage) loadGrants();
    if (tab === "ask" && id) {
      void dataSourcesApi.recommendedQuestions(id).then(({ data }) => {
        setSuggestions((data as { questions?: string[] }).questions || []);
      }).catch(() => setSuggestions([]));
    }
  }, [tab, loadAudit, loadDrift, loadExcelFiles, loadGrants, ds?.can_manage, id]);

  const onGenerateSql = async () => {
    if (!id || !question.trim()) return;
    setAsking(true);
    try {
      const { data } = await dataAskApi.query({
        data_source_id: id,
        question: question.trim(),
        execute: false,
      });
      const payload = data as { sql?: string; display_sql?: string; explanation?: string; answer?: string; clarification?: string };
      setEditSql(payload.display_sql || payload.sql || "");
      setAskResult({
        explanation: payload.explanation,
        sql: payload.sql,
        answer: payload.clarification ? "" : payload.answer,
        clarification: payload.clarification,
      });
      toast.success(payload.clarification
        ? t("需要补充问题", "Need a more specific question")
        : t("SQL 已生成，可编辑后执行", "SQL generated — edit then run"));
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

  const onFeedback = async (type: "like" | "dislike" | "example") => {
    if (!id || !askResult?.trace_id) return;
    try {
      const { data } = await dataAskApi.feedback({
        data_source_id: id,
        feedback_type: type,
        trace_id: askResult.trace_id,
        question: question.trim(),
        original_sql: askResult.sql || "",
      });
      setFbState({ traceId: askResult.trace_id, type });
      toast.success((data as { message?: string })?.message || t("反馈已保存", "Feedback saved"));
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("反馈失败", "Feedback failed")));
    }
  };

  const openCorrection = () => {
    setCorrectionSql(askResult?.sql || editSql || "");
    setCorrectionOpen(true);
  };

  const onSubmitCorrection = async () => {
    if (!id || !askResult?.trace_id || !correctionSql.trim()) return;
    try {
      const { data } = await dataAskApi.feedback({
        data_source_id: id,
        feedback_type: "correction",
        trace_id: askResult.trace_id,
        question: question.trim(),
        original_sql: askResult.sql || "",
        corrected_sql: correctionSql.trim(),
      });
      setFbState({ traceId: askResult.trace_id, type: "correction" });
      setCorrectionOpen(false);
      toast.success((data as { message?: string })?.message || t("纠正已保存", "Correction saved"));
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("提交失败", "Submit failed")));
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
      setExcelPreload({ status: "loading" });
      try {
        const { data } = await dataSourcesApi.preloadExcel(id);
        setExcelPreload(data);
      } catch {
        setExcelPreload({ status: "error", error: t("Excel 加载失败", "Excel preload failed") });
      }
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
      setExcelPreload({ status: "loading" });
      try {
        const { data } = await dataSourcesApi.preloadExcel(id);
        setExcelPreload(data);
      } catch {
        setExcelPreload({ status: "error", error: t("Excel 加载失败", "Excel preload failed") });
      }
      load();
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("保存失败", "Save failed")));
    }
  };

  useEffect(() => {
    if (!ds || openedEdit.current || typeof window === "undefined") return;
    if (new URLSearchParams(window.location.search).get("edit") !== "1") return;
    openedEdit.current = true;
    setEditForm(formFromSource(ds));
    setEditing(true);
  }, [ds]);

  const openEdit = () => {
    if (!ds) return;
    setEditForm(formFromSource(ds));
    setEditing(true);
  };

  const saveEdit = async () => {
    if (!id || !editForm) return;
    const name = editForm.name.trim();
    if (!name) {
      toast.error(t("请填写名称", "Name is required"));
      return;
    }
    const body: Record<string, unknown> = { name };
    if (!["excel_folder", "excel_template"].includes(ds?.driver || "")) {
      const port = Number(editForm.port);
      if (!editForm.host.trim() || !editForm.database.trim() || !Number.isFinite(port)) {
        toast.error(t("请填写主机、端口和数据库", "Host, port and database are required"));
        return;
      }
      body.host = editForm.host.trim();
      body.port = port;
      body.username = editForm.username.trim();
      body.database = editForm.database.trim();
      body.db_schema = editForm.db_schema.trim();
      body.ssl = editForm.ssl || "prefer";
      body.chat_enabled = editForm.chat_enabled;
      body.report_enabled = editForm.report_enabled;
      if (editForm.password) body.password = editForm.password;
    }
    setSavingEdit(true);
    try {
      await dataSourcesApi.update(id, body);
      toast.success(t("已保存", "Saved"));
      setEditing(false);
      load();
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("保存失败", "Save failed")));
    } finally {
      setSavingEdit(false);
    }
  };

  const onCopy = async () => {
    if (!id) return;
    setCopying(true);
    try {
      const { data } = await dataSourcesApi.duplicate(id);
      toast.success(t("已复制连接、表和已确认 SQL", "Connection, tables and confirmed SQL copied"));
      router.push(`/data-sources/${(data as { id: string }).id}`);
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("复制失败", "Copy failed")));
    } finally {
      setCopying(false);
    }
  };

  const onDelete = async () => {
    if (!id || !confirm(t("确定删除？", "Delete?"))) return;
    setDeleting(true);
    try {
      await dataSourcesApi.delete(id);
      toast.success(t("已删除", "Deleted"));
      router.push("/data-sources");
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("删除失败", "Delete failed")));
    } finally {
      setDeleting(false);
    }
  };

  if (!ds) {
    return <div className="p-6 theme-muted text-sm">{t("加载中…", "Loading…")}</div>;
  }

  const dataTables = ds.tables.filter((x) => x.role === "data");
  const permTable = ds.tables.find((x) => x.role === "permission");
  const isExcel = ds.driver === "excel_folder";
  const isExcelTemplate = ds.driver === "excel_template";
  const isExcelLike = isExcel || isExcelTemplate;
  const excelAskBlocked = isExcelLike && excelFiles.length > 0 && excelPreload?.status !== "ready";
  const templateAskBlocked = isExcelTemplate && templateStatus?.parse_status !== "ready";
  const askBlocked = excelAskBlocked || templateAskBlocked;
  const tabs: { value: Tab; label: string }[] = [
    { value: "overview", label: t("概览", "Overview") },
    ...(isExcelLike ? [{ value: "files" as Tab, label: t("Excel 文件", "Excel files") }] : []),
    { value: "ask", label: t("问数", "Ask") },
    { value: "semantic", label: t("语义模型", "Semantic") },
    { value: "audit", label: t("审计", "Audit") },
    ...(ds.can_manage ? [{ value: "access" as Tab, label: t("权限", "Access") }] : []),
    ...(isExcelLike ? [] : [{ value: "drift" as Tab, label: t("Schema", "Schema") }]),
  ];

  const filteredRels = remoteRels.filter(
    (r) => !tblSearch.trim() || r.name.toLowerCase().includes(tblSearch.toLowerCase()),
  );

  const loadRemoteTables = async () => {
    if (!id) return;
    setTblLoading(true);
    try {
      const { data } = await dataSourcesApi.listRemoteTables(id, { limit: 200 });
      const p = data as { tables?: string[]; relations?: { name: string; object_type: string }[] };
      setRemoteRels(p.relations || (p.tables || []).map((n) => ({ name: n, object_type: "table" })));
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("加载表列表失败", "Failed to load tables")));
    } finally {
      setTblLoading(false);
    }
  };

  const openEditTables = () => {
    if (!ds) return;
    setSelDataTables(dataTables.map((tbl) => tbl.table_name));
    setSelPermTable(permTable?.table_name || "");
    setTblSearch("");
    setEditingTables(true);
    loadRemoteTables();
  };

  const saveTables = async () => {
    if (!id) return;
    if (selDataTables.length === 0) {
      toast.error(t("请至少选择一张数据表", "Select at least one data table"));
      return;
    }
    const tables = [
      ...selDataTables.map((name) => {
        const rel = remoteRels.find((r) => r.name === name);
        return { table_name: name, role: "data", object_type: rel?.object_type || "table" };
      }),
      ...(selPermTable ? [{ table_name: selPermTable, role: "permission", object_type: "table" }] : []),
    ];
    setTblSaving(true);
    try {
      await dataSourcesApi.setTables(id, { tables });
      toast.success(t("表已更新", "Tables updated"));
      setEditingTables(false);
      load();
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("保存失败", "Save failed")));
    } finally {
      setTblSaving(false);
    }
  };

  const runTemplateParse = async () => {
    if (!id) return;
    setParsingTemplate(true);
    try {
      const { data: jobData } = await dataSourcesApi.parseExcelTemplate(id, {
        template_id: templateStatus?.template_id || undefined,
        recursive: true,
      });
      const jobId = (jobData as { id: string }).id;
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const { data: status } = await excelParserApi.getJob(jobId);
        const st = status as { status: string; error_message?: string };
        if (st.status === "completed") {
          toast.success(t("批量解析完成", "Batch parse completed"));
          loadExcelFiles();
          loadTemplateStatus();
          load();
          return;
        }
        if (st.status === "failed") throw new Error(st.error_message || "failed");
      }
      toast.error(t("解析超时", "Parse timeout"));
    } catch (e: unknown) {
      toast.error(String((e as Error)?.message || t("解析失败", "Parse failed")));
    } finally {
      setParsingTemplate(false);
    }
  };

  return (
    <div className="mx-auto min-w-0 max-w-6xl p-4 sm:p-6 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/data-sources" className="mb-2 inline-flex items-center gap-1 text-sm theme-muted">
            <ArrowLeft className="h-4 w-4" />{t("返回", "Back")}
          </Link>
          <h1 className="text-2xl font-semibold theme-text">{ds.name}</h1>
          <p className="text-sm theme-muted mt-1">
            {isExcelTemplate
              ? t("模板批量解析 · 上传原始 Excel → 解析宽表 → 问数", "Template parse · upload → wide table → Q&A")
              : isExcel
                ? t("临时分析 · 执行完成后自动释放 Excel，不占服务器空间", "Ephemeral · Excel released after each run")
                : `${ds.driver} · ${ds.host} / ${ds.database}`}
          </p>
        </div>
        {ds.can_manage && (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onCopy} disabled={copying} className="btn-secondary flex items-center gap-1 px-3 py-2 text-sm">
              <Copy className="h-4 w-4" />{copying ? t("复制中…", "Copying…") : t("复制", "Copy")}
            </button>
            <button type="button" onClick={openEdit} className="btn-secondary flex items-center gap-1 px-3 py-2 text-sm">
              <Pencil className="h-4 w-4" />{t("修改", "Edit")}
            </button>
            <button type="button" onClick={onDelete} disabled={deleting} className="btn-secondary text-red-500 flex items-center gap-1 px-3 py-2 text-sm">
              <Trash2 className="h-4 w-4" />{deleting ? t("删除中…", "Deleting…") : t("删除", "Delete")}
            </button>
          </div>
        )}
      </div>

      {editing && editForm && (
        <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
          <h2 className="font-medium">{t("修改数据源", "Edit data source")}</h2>
          <label className="block text-xs theme-muted">
            {t("名称", "Name")}
            <input className="input mt-1 w-full text-sm" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
          </label>
          {!isExcelLike && (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-xs theme-muted">
                {t("主机", "Host")}
                <input className="input mt-1 w-full text-sm" value={editForm.host} onChange={(e) => setEditForm({ ...editForm, host: e.target.value })} />
              </label>
              <label className="block text-xs theme-muted">
                {t("端口", "Port")}
                <input className="input mt-1 w-full text-sm" value={editForm.port} onChange={(e) => setEditForm({ ...editForm, port: e.target.value })} />
              </label>
              <label className="block text-xs theme-muted">
                {t("用户名", "Username")}
                <input className="input mt-1 w-full text-sm" value={editForm.username} onChange={(e) => setEditForm({ ...editForm, username: e.target.value })} />
              </label>
              <label className="block text-xs theme-muted">
                {t("密码", "Password")}
                <input className="input mt-1 w-full text-sm" type="password" value={editForm.password} placeholder={ds.password_set ? t("留空则不修改", "Leave blank to keep") : ""} onChange={(e) => setEditForm({ ...editForm, password: e.target.value })} />
              </label>
              <label className="block text-xs theme-muted">
                {t("数据库", "Database")}
                <input className="input mt-1 w-full text-sm" value={editForm.database} onChange={(e) => setEditForm({ ...editForm, database: e.target.value })} />
              </label>
              <label className="block text-xs theme-muted">
                Schema
                <input className="input mt-1 w-full text-sm" value={editForm.db_schema} onChange={(e) => setEditForm({ ...editForm, db_schema: e.target.value })} />
              </label>
              <label className="block text-xs theme-muted">
                SSL
                <select className="input mt-1 w-full text-sm" value={editForm.ssl} onChange={(e) => setEditForm({ ...editForm, ssl: e.target.value })}>
                  <option value="disable">disable</option>
                  <option value="prefer">prefer</option>
                  <option value="require">require</option>
                </select>
              </label>
              <div className="flex items-end gap-4 pb-2 text-sm">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={editForm.chat_enabled} onChange={(e) => setEditForm({ ...editForm, chat_enabled: e.target.checked })} />
                  {t("允许问数", "Chat")}
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={editForm.report_enabled} onChange={(e) => setEditForm({ ...editForm, report_enabled: e.target.checked })} />
                  {t("允许报告", "Reports")}
                </label>
              </div>
            </div>
          )}
          <div className="flex gap-2">
            <button type="button" onClick={saveEdit} disabled={savingEdit} className="btn-primary px-3 py-1.5 text-sm">
              {savingEdit ? t("保存中…", "Saving…") : t("保存", "Save")}
            </button>
            <button type="button" onClick={() => setEditing(false)} className="btn-secondary px-3 py-1.5 text-sm">
              {t("取消", "Cancel")}
            </button>
          </div>
        </div>
      )}

      <SegmentedControl wrap size="sm" value={tab} onChange={(v) => setTab(v as Tab)} options={tabs} />

      {tab === "overview" && (
        <>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="theme-surface rounded-xl border theme-border p-4">
              <div className="flex items-center justify-between mb-2">
                <h2 className="font-medium">{isExcelLike ? t("已选 Excel", "Selected Excel files") : t("数据表", "Data tables")}</h2>
                {ds.can_manage && !isExcelLike && (
                  <button type="button" onClick={openEditTables} className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs">
                    <Pencil className="h-3.5 w-3.5" />{t("修改表", "Edit tables")}
                  </button>
                )}
              </div>
              {editingTables ? (
                <div className="space-y-3">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 theme-muted pointer-events-none" />
                    <input
                      className="input w-full pl-9 text-sm"
                      value={tblSearch}
                      onChange={(e) => setTblSearch(e.target.value)}
                      placeholder={t("搜索表名…", "Search tables…")}
                    />
                  </div>
                  {tblLoading ? (
                    <p className="text-xs theme-muted py-2">{t("加载中…", "Loading…")}</p>
                  ) : filteredRels.length === 0 ? (
                    <p className="text-xs theme-muted py-2">{t("无匹配结果", "No matches")}</p>
                  ) : (
                    <div className="max-h-56 overflow-y-auto space-y-1 border theme-border rounded-lg p-2">
                      {filteredRels.map((rel) => (
                        <label key={rel.name} className="flex items-center gap-2 text-sm py-0.5 hover:bg-black/5 rounded px-1">
                          <input
                            type="checkbox"
                            checked={selDataTables.includes(rel.name)}
                            onChange={(e) =>
                              setSelDataTables((prev) =>
                                e.target.checked ? [...prev, rel.name] : prev.filter((x) => x !== rel.name),
                              )
                            }
                          />
                          <span className="truncate flex-1" title={rel.name}>{rel.name}</span>
                          <span className="text-xs theme-muted shrink-0">({rel.object_type})</span>
                        </label>
                      ))}
                    </div>
                  )}
                  <div>
                    <label className="block text-xs theme-muted mb-1">{t("权限表（可选）", "Permission table (optional)")}</label>
                    <select
                      className="input w-full text-sm"
                      value={selPermTable}
                      onChange={(e) => setSelPermTable(e.target.value)}
                    >
                      <option value="">{t("不设置", "None")}</option>
                      {filteredRels.map((rel) => (
                        <option key={rel.name} value={rel.name}>{rel.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={saveTables} disabled={tblSaving} className="btn-primary px-3 py-1.5 text-sm">
                      {tblSaving ? t("保存中…", "Saving…") : t("保存", "Save")}
                    </button>
                    <button type="button" onClick={() => setEditingTables(false)} className="btn-secondary px-3 py-1.5 text-sm">
                      {t("取消", "Cancel")}
                    </button>
                  </div>
                </div>
              ) : (
                <>
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
                </>
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
          {!isExcelLike && (
          <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
            <h2 className="font-medium">{t("ER 图", "ER diagram")}</h2>
            <p className="text-xs theme-muted">
              {t(
                "按编号、代码这类关联键画出已选表。虚线表是库里同键的参考表，只作血缘，不会自动加入问数。",
                "Selected tables are linked by key columns. Dashed tables share a key in the database and stay reference-only.",
              )}
            </p>
            <ErDiagram
              tables={dataTables}
              edges={graph?.edges || []}
              related={graph?.related || []}
              keys={graph?.keys || []}
              referenceBadge={t("参考", "ref")}
            />
          </div>
          )}
          <div className="theme-surface rounded-xl border theme-border p-4">
            <h2 className="font-medium mb-1">{t("表血缘", "Table lineage")}</h2>
            <p className="mb-3 text-xs theme-muted">
              {t(
                "按编号、代码这类关联键连接已选表。库里同键的其他表只作血缘参考，不会自动加入问数。",
                "Links selected tables by key columns. Other tables with the same key are reference only.",
              )}
            </p>
            {graph && (graph.keys || []).length > 0 && (
              <p className="mb-2 text-xs theme-text">{t("关联键", "Keys")}: {(graph.keys || []).join("、")}</p>
            )}
            {graph && graph.edges.length > 0 ? (
              <ul className="space-y-1 text-xs theme-text">
                {graph.edges.map((e, i) => (
                  <li key={`edge-${i}`}>{e.from}.{e.label} = {e.to}.{e.label}</li>
                ))}
              </ul>
            ) : (
              <p className="text-xs theme-muted">{t("已选表之间还没有共同的关联键。", "No shared key among selected tables.")}</p>
            )}
            {graph && (graph.related || []).length > 0 && (
              <div className="mt-3">
                <h3 className="mb-1 text-sm font-medium">{t("库内同键表", "Same-key tables")}</h3>
                <ul className="max-h-48 space-y-1 overflow-auto text-xs theme-muted">
                  {(graph.related || []).map((e, i) => (
                    <li key={`rel-${i}`}>{e.from}.{e.label} ↔ {e.to}.{e.label}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </>
      )}

      {tab === "files" && isExcelLike && (
        <>
          {isExcelTemplate && (
            <div className="theme-surface rounded-xl border theme-border p-4 flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm theme-muted">
                <p>{t("解析状态", "Parse status")}: <span className="font-medium theme-text">{templateStatus?.parse_status || "idle"}</span></p>
                <p className="text-xs mt-1">
                  {t("原始文件", "Raw")}: {templateStatus?.input_file_count ?? 0} · {t("宽表", "Output")}: {templateStatus?.output_file_count ?? 0}
                </p>
              </div>
              <button
                type="button"
                disabled={parsingTemplate}
                onClick={runTemplateParse}
                className="btn-primary px-3 py-1.5 text-sm"
              >
                {parsingTemplate ? t("解析中…", "Parsing…") : t("批量解析", "Batch parse")}
              </button>
            </div>
          )}
          <ExcelFilesTab
            lang={lang}
            files={excelFiles}
            selected={dataTables.map((x) => x.table_name)}
            uploading={uploading}
            fileInputRef={fileInputRef}
            onUpload={onUploadExcel}
            onSaveSelection={onSaveExcelSelection}
            onRefresh={loadExcelFiles}
            isTemplate={isExcelTemplate}
            canManage={!!ds.can_manage}
          />
        </>
      )}

      {tab === "ask" && (
        <div className="min-w-0 theme-surface rounded-xl border theme-border p-4 space-y-3">
          <h2 className="font-medium">{t("即时问数", "Quick ask")}</h2>
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {suggestions.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="rounded-full border theme-border px-3 py-1 text-xs theme-text"
                  onClick={() => setQuestion(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          )}
          {(isExcelLike && excelFiles.length > 0) && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
              {excelPreload?.status === "ready" ? (
                <span>
                  {t("Excel 已就绪", "Excel ready")} · {excelPreload.sheet_count ?? 0}{" "}
                  {t("表", "sheets")} · {excelPreload.total_rows ?? 0} {t("行", "rows")}
                </span>
              ) : excelPreload?.status === "error" ? (
                <span>{excelPreload.error || t("Excel 加载失败", "Excel preload failed")}</span>
              ) : (
                <span>{t("正在加载 Excel 全量数据，请稍候再提问…", "Loading full Excel data — wait before asking…")}</span>
              )}
            </div>
          )}
          {isExcelTemplate && templateAskBlocked && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
              {t("请先上传原始 Excel 并执行批量解析，再提问。", "Upload raw Excel and run batch parse before asking.")}
            </div>
          )}
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
            disabled={askBlocked}
            placeholder={
              askBlocked
                ? t("正在加载 Excel 数据…", "Loading Excel data…")
                : isExcel
                  ? t("例如：对各 Excel 销量做聚类分析", "e.g. cluster sales across Excel files")
                  : t("输入分析问题…", "Ask a question…")
            }
          />
          <div className="flex flex-wrap gap-2">
            <button disabled={asking || askBlocked} onClick={onGenerateSql} className="btn-secondary inline-flex items-center gap-1 px-3 py-2 text-sm">
              <Wand2 className="h-4 w-4" />{asking ? "…" : isExcel ? t("生成 Python", "Generate Python") : t("生成 SQL", "Generate SQL")}
            </button>
            <button disabled={asking || askBlocked || !editSql.trim()} onClick={onRunSql} className="btn-primary inline-flex items-center gap-1 px-3 py-2 text-sm">
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
              readOnly={askBlocked}
              placeholder={isExcel ? t("先生成 Python 或直接编写", "Generate or write Python") : t("先生成 SQL 或直接编写", "Generate or write SQL")}
            />
          </label>
          {askResult?.clarification && (
            <ClarifyCard
              payload={{ questions: [{ text: askResult.clarification, options: [] }], round: 1, max_rounds: 1 }}
              lang={lang}
            />
          )}
          {askResult?.explanation && (
            <p className="text-xs theme-muted">{askResult.explanation}</p>
          )}
          {askResult?.answer && askResult.answer !== askResult.clarification && (
            <div className="whitespace-pre-wrap text-sm theme-text">{askResult.answer}</div>
          )}
          {toAskChart(askResult?.chart) && (
            <ChartRenderer chart={toAskChart(askResult?.chart)!} />
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
          {askResult?.trace_id ? (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border theme-border px-3 py-2">
              <span className="text-xs theme-muted">{t("本次回答有帮助吗？", "Was this answer helpful?")}</span>
              <button
                onClick={() => onFeedback("like")}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs ${fbState?.traceId === askResult.trace_id && fbState.type === "like" ? "bg-green-500/15 text-green-600" : "theme-muted hover:text-green-600"}`}
              >
                <ThumbsUp className="h-3.5 w-3.5" />{t("有用", "Good")}
              </button>
              <button
                onClick={() => onFeedback("dislike")}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs ${fbState?.traceId === askResult.trace_id && fbState.type === "dislike" ? "bg-red-500/15 text-red-600" : "theme-muted hover:text-red-600"}`}
              >
                <ThumbsDown className="h-3.5 w-3.5" />{t("有误", "Bad")}
              </button>
              <button
                onClick={openCorrection}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs ${fbState?.traceId === askResult.trace_id && fbState.type === "correction" ? "bg-blue-500/15 text-blue-600" : "theme-muted hover:text-blue-600"}`}
              >
                <Pencil className="h-3.5 w-3.5" />{t("纠正 SQL", "Fix SQL")}
              </button>
              <button
                onClick={() => onFeedback("example")}
                className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs ${fbState?.traceId === askResult.trace_id && fbState.type === "example" ? "bg-amber-500/15 text-amber-600" : "theme-muted hover:text-amber-600"}`}
              >
                <Star className="h-3.5 w-3.5" />{t("存为示例", "Save as example")}
              </button>
              {fbState?.traceId === askResult.trace_id && (
                <span className="text-xs text-green-600">{t("已反馈，感谢！", "Thanks for the feedback!")}</span>
              )}
            </div>
          ) : null}
          {correctionOpen && askResult?.trace_id ? (
            <div className="space-y-2 rounded-lg border theme-border p-3">
              <p className="text-xs theme-muted">
                {t("修正后的 SQL 将写入问数记忆，下次自动作为参考示例", "The corrected SQL will be saved to query memory as a few-shot example")}
              </p>
              <textarea
                className="input w-full min-h-[120px] font-mono text-xs"
                value={correctionSql}
                onChange={(e) => setCorrectionSql(e.target.value)}
              />
              <div className="flex gap-2">
                <button onClick={onSubmitCorrection} className="btn-primary px-3 py-1.5 text-xs">
                  {t("提交纠正", "Submit correction")}
                </button>
                <button onClick={() => setCorrectionOpen(false)} className="btn-secondary px-3 py-1.5 text-xs">
                  {t("取消", "Cancel")}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {tab === "semantic" && (
        <div className="theme-surface rounded-xl border theme-border p-4 space-y-3">
          <h2 className="font-medium">{t("MDL Lite 语义模型", "MDL Lite semantic model")}</h2>
          <p className="text-xs theme-muted">
            {t("定义 metrics / dimensions / relationships / columns.sensitivity", "Define metrics, dimensions, relationships, column sensitivity")}
          </p>
          <textarea className="input w-full min-h-[320px] font-mono text-xs" value={mdlText} onChange={(e) => setMdlText(e.target.value)} readOnly={!ds.can_manage} />
          {ds.can_manage ? (
            <button disabled={savingMdl} onClick={onSaveMdl} className="btn-primary px-4 py-2 text-sm">
              {savingMdl ? "…" : t("保存", "Save")}
            </button>
          ) : (
            <p className="text-xs theme-muted">{t("仅管理员可编辑语义模型", "Only managers can edit the semantic model")}</p>
          )}
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

      {tab === "access" && ds.can_manage && (
        <div className="theme-surface rounded-xl border theme-border p-4 space-y-4">
          <div>
            <h2 className="font-medium">{t("访问权限", "Access control")}</h2>
            <p className="text-sm theme-muted mt-1">
              {t(
                "为其他用户分配问数 / Excel 解析权限；部门负责人默认可查看本部门成员的数据源",
                "Grant ask/parse access to others; dept leaders can see team sources by default",
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[200px] flex-1">
              <label className="block text-xs theme-muted mb-1">{t("用户账号", "Username")}</label>
              <input
                className="input w-full"
                value={grantLogin}
                onChange={(e) => setGrantLogin(e.target.value)}
                placeholder={t("登录名", "login")}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={grantCanAsk} onChange={(e) => setGrantCanAsk(e.target.checked)} />
              {t("问数/解析", "Ask/Parse")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={grantCanManage} onChange={(e) => setGrantCanManage(e.target.checked)} />
              {t("管理", "Manage")}
            </label>
            <button
              type="button"
              className="btn-primary px-3 py-2 text-sm"
              disabled={!grantLogin.trim()}
              onClick={() => {
                if (!grantLogin.trim()) return;
                setGrants((prev) => [
                  ...prev.filter((g) => g.login !== grantLogin.trim()),
                  {
                    id: `draft-${grantLogin.trim()}`,
                    user_id: "",
                    login: grantLogin.trim(),
                    display_name: grantLogin.trim(),
                    can_ask: grantCanAsk,
                    can_manage: grantCanManage,
                  },
                ]);
                setGrantLogin("");
              }}
            >
              {t("添加", "Add")}
            </button>
          </div>
          {grants.length === 0 ? (
            <p className="text-sm theme-muted">{t("尚未授权给其他用户", "No grants yet")}</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {grants.map((g) => (
                <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 rounded border theme-border px-3 py-2">
                  <span>{g.display_name || g.login} <span className="text-xs theme-muted">({g.login})</span></span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs theme-muted">{g.can_ask ? t("问数", "Ask") : ""}{g.can_manage ? ` · ${t("管理", "Manage")}` : ""}</span>
                    <button
                      type="button"
                      className="text-red-400 text-xs"
                      onClick={() => setGrants((prev) => prev.filter((x) => x.login !== g.login))}
                    >
                      {t("移除", "Remove")}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            disabled={savingGrants}
            className="btn-primary px-4 py-2 text-sm"
            onClick={async () => {
              if (!id) return;
              setSavingGrants(true);
              try {
                await dataSourcesApi.setGrants(id, {
                  grants: grants.map((g) => ({
                    login: g.login,
                    user_id: g.user_id || undefined,
                    can_ask: g.can_ask,
                    can_manage: g.can_manage,
                  })),
                });
                toast.success(t("权限已保存", "Grants saved"));
                loadGrants();
              } catch {
                toast.error(t("保存失败", "Save failed"));
              } finally {
                setSavingGrants(false);
              }
            }}
          >
            {savingGrants ? "…" : t("保存权限", "Save grants")}
          </button>
        </div>
      )}

      {tab === "drift" && !isExcelLike && (
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
  isTemplate = false,
  canManage = true,
}: {
  lang: string;
  files: { name: string; size_bytes: number }[];
  selected: string[];
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onUpload: (files: FileList | null) => void;
  onSaveSelection: (names: string[]) => void;
  onRefresh: () => void;
  isTemplate?: boolean;
  canManage?: boolean;
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
          {isTemplate ? t("Excel 模板 · 宽表输出", "Excel template · wide table output") : t("Excel 文件夹", "Excel folder")}
        </h2>
        <div className="flex gap-2">
          <button type="button" onClick={onRefresh} className="btn-secondary text-xs px-2 py-1 inline-flex items-center gap-1">
            <RefreshCw className="h-3.5 w-3.5" />{t("刷新", "Refresh")}
          </button>
          {canManage && (
            <>
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
            </>
          )}
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
                disabled={!canManage}
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
      {canManage && (
        <button
          type="button"
          disabled={picked.length < 1}
          onClick={() => onSaveSelection(picked)}
          className="btn-primary w-full py-2 text-sm"
        >
          {t(`保存问数范围（已选 ${picked.length} 个）`, `Save selection (${picked.length} file(s))`)}
        </button>
      )}
    </div>
  );
}
