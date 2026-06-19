"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, RefreshCw, Search, Upload } from "lucide-react";
import toast from "react-hot-toast";
import { dataSourcesApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { SegmentedControl } from "@/components/SegmentedControl";

type Step = 1 | 2 | 3 | 4;

type RemoteRelation = { name: string; object_type: "table" | "view" };

type RemoteListPayload = {
  ok: boolean;
  message: string;
  tables: string[];
  relations?: RemoteRelation[];
  total_count?: number;
  truncated?: boolean;
};

const DRIVERS = [
  { value: "excel_folder", label: "Excel 文件夹" },
  { value: "vastbase", label: "VastBase" },
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "doris", label: "Doris" },
  { value: "hana", label: "SAP HANA" },
  { value: "hive", label: "Hive / Kylin" },
];

export default function NewDataSourcePage() {
  const { lang } = useLangStore();
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [busy, setBusy] = useState(false);
  const [sourceId, setSourceId] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [driver, setDriver] = useState("vastbase");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState(5432);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [database, setDatabase] = useState("");
  const [dbSchema, setDbSchema] = useState("public");

  const [remoteRelations, setRemoteRelations] = useState<RemoteRelation[]>([]);
  const [selectedData, setSelectedData] = useState<string[]>([]);
  const [permissionObjectType, setPermissionObjectType] = useState<"table" | "view">("table");
  const [permissionTable, setPermissionTable] = useState("");
  const [nlPrompt, setNlPrompt] = useState("");
  const [cron, setCron] = useState("0 8 * * *");
  const [refreshingTables, setRefreshingTables] = useState(false);
  const [tableSearch, setTableSearch] = useState("");
  const [permSearch, setPermSearch] = useState("");
  const [dataTypeFilter, setDataTypeFilter] = useState<"all" | "table" | "view">("all");
  const [totalCount, setTotalCount] = useState(0);
  const [listTruncated, setListTruncated] = useState(false);
  const [uploading, setUploading] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  const isExcel = driver === "excel_folder";

  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);

  const applyRemoteList = (payload: RemoteListPayload) => {
    const relations =
      payload.relations?.length
        ? payload.relations
        : (payload.tables || []).map((name) => ({ name, object_type: "table" as const }));
    setRemoteRelations(relations);
    setTotalCount(payload.total_count ?? relations.length);
    setListTruncated(Boolean(payload.truncated));
    setSelectedData((prev) => prev.filter((n) => relations.some((r) => r.name === n)));
    setPermissionTable((prev) => {
      if (!prev) return prev;
      const match = relations.find((r) => r.name === prev && r.object_type === permissionObjectType);
      return match ? prev : "";
    });
  };

  const fetchRelations = useCallback(
    async (search: string, objectType?: "table" | "view", opts?: { silent?: boolean }) => {
      if (!sourceId && step !== 1) return;
      if (!opts?.silent) setRefreshingTables(true);
      try {
        if (sourceId) {
          const { data } = await dataSourcesApi.listRemoteTables(sourceId, {
            q: search.trim() || undefined,
            object_type: objectType,
            limit: search.trim() ? 200 : 120,
          });
          const payload = data as RemoteListPayload;
          if (!payload.ok) {
            if (!opts?.silent) toast.error(payload.message || t("刷新失败", "Refresh failed"));
            return;
          }
          applyRemoteList(payload);
        } else {
          const { data } = await dataSourcesApi.test({
            driver,
            host,
            port,
            username,
            password,
            database,
            db_schema: dbSchema,
            search: search.trim(),
            object_type: objectType,
            limit: search.trim() ? 200 : 120,
          });
          const payload = data as RemoteListPayload;
          if (!payload.ok) {
            if (!opts?.silent) toast.error(payload.message || t("刷新失败", "Refresh failed"));
            return;
          }
          applyRemoteList(payload);
        }
        if (!opts?.silent) toast.success(t("对象列表已刷新", "Object list refreshed"));
      } catch {
        if (!opts?.silent) toast.error(t("刷新失败", "Refresh failed"));
      } finally {
        if (!opts?.silent) setRefreshingTables(false);
      }
    },
    [sourceId, step, driver, host, port, username, password, database, dbSchema, lang],
  );

  const objectTypeLabel = (kind: "table" | "view") =>
    kind === "view" ? t("视图", "View") : t("表", "Table");

  const permissionCandidates = remoteRelations.filter((r) => r.object_type === permissionObjectType);

  const filteredDataRelations = useMemo(() => {
    let list = remoteRelations;
    if (dataTypeFilter !== "all") {
      list = list.filter((r) => r.object_type === dataTypeFilter);
    }
    const q = tableSearch.trim().toLowerCase();
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }
    return list;
  }, [remoteRelations, dataTypeFilter, tableSearch]);

  const filteredPermRelations = useMemo(() => {
    const q = permSearch.trim().toLowerCase();
    if (!q) return permissionCandidates;
    return permissionCandidates.filter((r) => r.name.toLowerCase().includes(q));
  }, [permissionCandidates, permSearch]);

  useEffect(() => {
    if (step !== 2 || !sourceId) return;
    const timer = window.setTimeout(() => {
      const ot = isExcel || dataTypeFilter === "all" ? undefined : dataTypeFilter;
      fetchRelations(tableSearch, ot, { silent: true });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [step, sourceId, tableSearch, dataTypeFilter, fetchRelations, isExcel]);

  const refreshRemoteTables = async () => {
    const ot = dataTypeFilter === "all" ? undefined : dataTypeFilter;
    await fetchRelations(tableSearch, ot);
  };

  const onDriverChange = (d: string) => {
    setDriver(d);
    if (d === "excel_folder") return;
    setPort(
      d === "mysql" ? 3306
        : d === "doris" ? 9030
          : d === "hive" ? 10000
            : d === "hana" ? 30015
              : 5432,
    );
    setDbSchema(
      d === "hive" ? "default"
        : d === "doris" ? ""
          : d === "hana" ? ""
            : "public",
    );
  };

  const createExcelSource = async () => {
    if (!name.trim()) {
      toast.error(t("请填写名称", "Name required"));
      return;
    }
    setBusy(true);
    try {
      const created = await dataSourcesApi.create({
        name: name.trim(),
        driver: "excel_folder",
        host: "local",
        port: 0,
        username: "-",
        password: "",
        database: name.trim(),
      });
      const id = (created.data as { id: string }).id;
      setSourceId(id);
      setStep(2);
      toast.success(t("Excel 文件夹已创建，请上传文件", "Excel folder created — upload files"));
    } catch {
      toast.error(t("创建失败", "Create failed"));
    } finally {
      setBusy(false);
    }
  };

  const testAndCreate = async () => {
    if (isExcel) {
      await createExcelSource();
      return;
    }
    setBusy(true);
    try {
      const test = await dataSourcesApi.test({
        driver,
        host,
        port,
        username,
        password,
        database,
        db_schema: dbSchema,
      });
      if (!(test.data as { ok: boolean }).ok) {
        toast.error((test.data as { message: string }).message);
        return;
      }
      const created = await dataSourcesApi.create({
        name: name || database,
        driver,
        host,
        port,
        username,
        password,
        database,
        db_schema: dbSchema,
      });
      const id = (created.data as { id: string }).id;
      setSourceId(id);
      applyRemoteList(test.data as RemoteListPayload);
      setStep(2);
      toast.success(t("连接成功", "Connected"));
    } catch {
      toast.error(t("连接失败", "Connection failed"));
    } finally {
      setBusy(false);
    }
  };

  const saveTables = async () => {
    if (!sourceId) return;
    if (isExcel) {
      if (selectedData.length < 1) {
        toast.error(t("请至少选择一个 Excel 文件", "Select at least one Excel file"));
        return;
      }
    } else if (selectedData.length < 1 || !permissionTable) {
      toast.error(t("请至少选一张数据表/视图，并指定权限表或视图", "Select data objects and a permission table or view"));
      return;
    }
    setBusy(true);
    try {
      const relationByName = new Map(remoteRelations.map((r) => [r.name, r]));
      const tables = selectedData.map((table_name) => ({
        table_name,
        role: "data",
        object_type: relationByName.get(table_name)?.object_type || "table",
      }));
      if (!isExcel && permissionTable) {
        tables.push({ table_name: permissionTable, role: "permission", object_type: permissionObjectType });
      }
      await dataSourcesApi.setTables(sourceId, { tables });
      setStep(3);
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("保存失败", "Save failed")));
    } finally {
      setBusy(false);
    }
  };

  const onUploadExcel = async (fileList: FileList | null) => {
    if (!sourceId || !fileList?.length) return;
    setUploading(true);
    try {
      await dataSourcesApi.uploadExcel(sourceId, Array.from(fileList));
      toast.success(t("上传成功", "Uploaded"));
      await fetchRelations("", undefined, { silent: true });
    } catch (e: unknown) {
      toast.error(String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t("上传失败", "Upload failed")));
    } finally {
      setUploading(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  };

  const bindAndEmployee = async () => {
    if (!sourceId) return;
    setBusy(true);
    try {
      await dataSourcesApi.bindAgent(sourceId, { nl_prompt: nlPrompt || undefined });
      await dataSourcesApi.createEmployee(sourceId, {
        nl_prompt: nlPrompt || undefined,
        cron_expression: cron,
        create_agent: false,
      });
      toast.success(t("配置完成", "Done"));
      router.push(`/data-sources/${sourceId}`);
    } catch {
      toast.error(t("生成失败", "Failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto min-w-0 max-w-2xl p-4 sm:p-6">
      <Link href="/data-sources" className="mb-4 inline-flex items-center gap-1 text-sm theme-muted hover:theme-text">
        <ArrowLeft className="h-4 w-4" />
        {t("返回列表", "Back")}
      </Link>
      <h1 className="text-xl font-semibold theme-text mb-6">{t("新建问数数据源", "New data source")}</h1>

      <div className="mb-8 flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {[1, 2, 3, 4].map((n) => (
          <span key={n} className={step === n ? "font-semibold text-blue-500" : "theme-muted"}>
            {n}. {t(["连接", "选表", "绑 Agent", "启用"][n - 1], ["Connect", "Tables", "Agent", "Enable"][n - 1])}
          </span>
        ))}
      </div>

      {step === 1 && (
        <div className="min-w-0 space-y-4 theme-surface rounded-xl border theme-border p-4 sm:p-5">
          <label className="block text-sm">{t("名称", "Name")}
            <input className="input mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("财务分析库", "Finance DB")} />
          </label>
          <label className="block min-w-0 text-sm">{t("数据库类型", "Driver")}
            <div className="mt-2 min-w-0">
              <SegmentedControl wrap size="sm" value={driver} onChange={onDriverChange} options={DRIVERS} />
            </div>
          </label>
          {isExcel ? (
            <p className="text-sm text-amber-600">
              {t(
                "临时 Excel 分析：上传 → 勾选 → 问数执行；成功后文件自动释放，不长期占用磁盘",
                "Ephemeral Excel: upload → select → run analysis; files auto-deleted after success",
              )}
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-sm">{t("主机", "Host")}
                  <input className="input mt-1 w-full" value={host} onChange={(e) => setHost(e.target.value)} />
                </label>
                <label className="block text-sm">{t("端口", "Port")}
                  <input type="number" className="input mt-1 w-full" value={port} onChange={(e) => setPort(Number(e.target.value))} />
                </label>
              </div>
              <label className="block text-sm">{t("用户名", "User")}
                <input className="input mt-1 w-full" value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label className="block text-sm">{t("密码", "Password")}
                <input type="password" className="input mt-1 w-full" value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <label className="block text-sm">{t("数据库", "Database")}
                <input className="input mt-1 w-full" value={database} onChange={(e) => setDatabase(e.target.value)} />
              </label>
              <label className="block text-sm">Schema
                <input className="input mt-1 w-full" value={dbSchema} onChange={(e) => setDbSchema(e.target.value)} />
              </label>
            </>
          )}
          <button disabled={busy} onClick={testAndCreate} className="btn-primary w-full py-2">
            {busy
              ? t("处理中…", "Working…")
              : isExcel
                ? t("创建并继续", "Create & continue")
                : t("测试并继续", "Test & continue")}
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4 theme-surface rounded-xl border theme-border p-5">
          {isExcel && (
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm theme-muted">{t("上传 Excel 并勾选问数范围", "Upload Excel and select files for analysis")}</p>
              <button
                type="button"
                disabled={uploading || busy}
                onClick={() => uploadRef.current?.click()}
                className="btn-primary inline-flex items-center gap-1 px-3 py-1.5 text-xs"
              >
                <Upload className="h-3.5 w-3.5" />
                {uploading ? t("上传中…", "Uploading…") : t("上传", "Upload")}
              </button>
              <input ref={uploadRef} type="file" accept=".xlsx,.xls,.csv" multiple className="hidden" onChange={(e) => onUploadExcel(e.target.files)} />
            </div>
          )}
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <p className="text-sm theme-muted">
              {isExcel ? t("Excel 文件（可多选）", "Excel files (multi)") : t("数据表/视图（可多选）", "Data tables/views (multi)")}
            </p>
            <span className="text-xs theme-muted">
              {t("已选", "Selected")} {selectedData.length}
              {totalCount > 0 && ` · ${t("共", "of")} ${totalCount}`}
            </span>
            <button
              type="button"
              disabled={refreshingTables || busy}
              onClick={refreshRemoteTables}
              className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs ml-auto"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshingTables ? "animate-spin" : ""}`} />
              {refreshingTables ? t("刷新中…", "Refreshing…") : t("刷新", "Refresh")}
            </button>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 theme-muted pointer-events-none" />
            <input
              className="input w-full pl-9"
              value={tableSearch}
              onChange={(e) => setTableSearch(e.target.value)}
              placeholder={isExcel ? t("搜索文件名…", "Search file name…") : t("搜索表名或视图名…", "Search table or view name…")}
            />
          </div>
          {!isExcel && (
          <SegmentedControl
            value={dataTypeFilter}
            onChange={(v) => setDataTypeFilter(v as "all" | "table" | "view")}
            options={[
              { value: "all", label: t("全部", "All") },
              { value: "table", label: t("表", "Table") },
              { value: "view", label: t("视图", "View") },
            ]}
          />
          )}
          {!isExcel && listTruncated && !tableSearch.trim() && (
            <p className="text-xs text-amber-600">
              {t("对象较多，仅显示前 120 条，请输入关键字搜索", "Many objects — showing first 120, use search")}
            </p>
          )}
          {remoteRelations.length === 0 ? (
            <p className="text-sm theme-muted py-4 text-center">
              {isExcel ? t("请先上传 Excel 文件", "Upload Excel files first") : t("暂无对象，请点击刷新", "No objects — click Refresh")}
            </p>
          ) : filteredDataRelations.length === 0 ? (
            <p className="text-sm theme-muted py-4 text-center">
              {t("无匹配结果，请换个关键字", "No matches — try another keyword")}
            </p>
          ) : (
            <div className="max-h-56 overflow-y-auto space-y-1 border theme-border rounded-lg p-2">
              {filteredDataRelations.map((rel) => (
                <label key={`${rel.object_type}:${rel.name}`} className="flex items-center gap-2 text-sm py-0.5 hover:bg-black/5 rounded px-1">
                  <input
                    type="checkbox"
                    checked={selectedData.includes(rel.name)}
                    onChange={(e) =>
                      setSelectedData((prev) =>
                        e.target.checked ? [...prev, rel.name] : prev.filter((x) => x !== rel.name),
                      )
                    }
                  />
                  <span className="truncate flex-1" title={rel.name}>{rel.name}</span>
                  <span className="text-xs theme-muted shrink-0">({objectTypeLabel(rel.object_type)})</span>
                </label>
              ))}
            </div>
          )}
          <p className="text-xs theme-muted">
            {t(`显示 ${filteredDataRelations.length} 条`, `Showing ${filteredDataRelations.length}`)}
            {tableSearch.trim() ? t("（已过滤）", " (filtered)") : ""}
          </p>
          {!isExcel && (
          <div className="space-y-2">
            <p className="text-sm">{t("权限来源（必选）", "Permission source (required)")}</p>
            <SegmentedControl
              value={permissionObjectType}
              onChange={(v) => {
                setPermissionObjectType(v as "table" | "view");
                setPermissionTable("");
                setPermSearch("");
              }}
              options={[
                { value: "table", label: t("表", "Table") },
                { value: "view", label: t("视图", "View") },
              ]}
            />
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 theme-muted pointer-events-none" />
              <input
                className="input w-full pl-9"
                value={permSearch}
                onChange={(e) => setPermSearch(e.target.value)}
                placeholder={t("搜索权限表/视图…", "Search permission table or view…")}
              />
            </div>
            {filteredPermRelations.length === 0 ? (
              <p className="text-xs theme-muted py-2">
                {permissionCandidates.length === 0
                  ? t(`当前类型下无可用${permissionObjectType === "view" ? "视图" : "表"}`, `No ${permissionObjectType === "view" ? "views" : "tables"} available`)
                  : t("无匹配权限对象", "No matching permission object")}
              </p>
            ) : (
              <div className="max-h-40 overflow-y-auto space-y-1 border theme-border rounded-lg p-2">
                {filteredPermRelations.map((rel) => (
                  <label
                    key={rel.name}
                    className={`flex items-center gap-2 text-sm py-1 px-1 rounded cursor-pointer ${
                      permissionTable === rel.name ? "bg-blue-500/10 ring-1 ring-blue-500/40" : "hover:bg-black/5"
                    }`}
                  >
                    <input
                      type="radio"
                      name="permissionTable"
                      checked={permissionTable === rel.name}
                      onChange={() => setPermissionTable(rel.name)}
                    />
                    <span className="truncate flex-1" title={rel.name}>{rel.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
          )}
          <button disabled={busy} onClick={saveTables} className="btn-primary w-full py-2">
            {t("保存并继续", "Save & continue")}
          </button>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4 theme-surface rounded-xl border theme-border p-5">
          <label className="block text-sm">{t("自然语言描述（可选）", "NL description (optional)")}
            <textarea
              className="input mt-1 w-full min-h-[100px]"
              value={nlPrompt}
              onChange={(e) => setNlPrompt(e.target.value)}
              placeholder={t("例如：分析各事业部周销量趋势，生成每日早报", "e.g. weekly sales trends, daily report")}
            />
          </label>
          <button onClick={() => setStep(4)} className="btn-primary w-full py-2">{t("继续", "Continue")}</button>
        </div>
      )}

      {step === 4 && (
        <div className="space-y-4 theme-surface rounded-xl border theme-border p-5">
          <label className="block text-sm">{t("定时 Cron", "Cron schedule")}
            <input className="input mt-1 w-full" value={cron} onChange={(e) => setCron(e.target.value)} />
          </label>
          <p className="text-sm theme-muted">
            {t("将创建绑定的智能体与数字员工，并启用 Chat 问数。", "Creates agent + employee and enables chat Q&A.")}
          </p>
          <button disabled={busy} onClick={bindAndEmployee} className="btn-primary w-full py-2">
            {busy ? t("生成中…", "Creating…") : t("完成配置", "Finish")}
          </button>
        </div>
      )}
    </div>
  );
}
