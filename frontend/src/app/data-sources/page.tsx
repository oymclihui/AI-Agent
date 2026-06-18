"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Database, Plus, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";
import { dataSourcesApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { useClientAuth } from "@/hooks/useClientAuth";

interface DataSourceItem {
  id: string;
  name: string;
  driver: string;
  host: string;
  database: string;
  status: string;
  agent_id?: string | null;
  employee_id?: string | null;
  tables: { table_name: string; role: string }[];
}

const DRIVER_LABEL: Record<string, string> = {
  postgresql: "PostgreSQL",
  vastbase: "VastBase",
  mysql: "MySQL",
  doris: "Doris",
  hive: "Hive / Kylin",
  hana: "SAP HANA",
  excel_folder: "Excel 文件夹",
};

export default function DataSourcesPage() {
  const { lang } = useLangStore();
  const { ready } = useClientAuth();
  const [items, setItems] = useState<DataSourceItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    dataSourcesApi
      .list()
      .then(({ data }) => setItems((data as { items: DataSourceItem[] }).items || []))
      .catch(() => toast.error(lang === "zh" ? "加载失败" : "Load failed"))
      .finally(() => setLoading(false));
  }, [lang]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold theme-text flex items-center gap-2">
            <Database className="h-7 w-7 text-blue-500" />
            {lang === "zh" ? "问数数据源" : "Data Sources"}
          </h1>
          <p className="mt-1 text-sm theme-muted">
            {lang === "zh"
              ? "连接业务库 · 多表 + 权限表 · Chat 问数 · 数字员工报告"
              : "Business DB · tables + permission · chat Q&A · scheduled reports"}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="btn-secondary flex items-center gap-1 px-3 py-2 text-sm">
            <RefreshCw className="h-4 w-4" />
            {lang === "zh" ? "刷新" : "Refresh"}
          </button>
          <Link href="/data-sources/new" className="btn-primary flex items-center gap-1 px-3 py-2 text-sm">
            <Plus className="h-4 w-4" />
            {lang === "zh" ? "新建" : "New"}
          </Link>
        </div>
      </div>

      {loading ? (
        <p className="theme-muted text-sm">{lang === "zh" ? "加载中…" : "Loading…"}</p>
      ) : items.length === 0 ? (
        <div className="theme-surface rounded-xl border theme-border p-10 text-center">
          <p className="theme-muted mb-4">{lang === "zh" ? "暂无数据源" : "No data sources yet"}</p>
          <Link href="/data-sources/new" className="btn-primary inline-flex px-4 py-2 text-sm">
            {lang === "zh" ? "创建第一个数据源" : "Create first data source"}
          </Link>
        </div>
      ) : (
        <div className="grid gap-4">
          {items.map((ds) => (
            <Link
              key={ds.id}
              href={`/data-sources/${ds.id}`}
              className="theme-surface block rounded-xl border theme-border p-4 transition hover:border-blue-400/50"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-medium theme-text">{ds.name}</h2>
                  <p className="mt-1 text-sm theme-muted">
                    {DRIVER_LABEL[ds.driver] || ds.driver} · {ds.host} / {ds.database}
                  </p>
                  <p className="mt-2 text-xs theme-muted">
                    {ds.tables?.length || 0} {lang === "zh" ? "张表" : "tables"}
                    {ds.agent_id ? " · Agent" : ""}
                    {ds.employee_id ? " · Employee" : ""}
                  </p>
                </div>
                <span className="rounded-full bg-green-500/10 px-2 py-0.5 text-xs text-green-600">
                  {ds.status}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
