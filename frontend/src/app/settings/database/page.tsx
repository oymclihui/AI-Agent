"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Copy, Database, FileCode, Shield, X } from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { databaseApi } from "@/lib/api";
import { canManageOrg } from "@/lib/permissions";
import { useClientAuth } from "@/hooks/useClientAuth";
import { SegmentedControl } from "@/components/SegmentedControl";

interface DbStatus {
  driver: string;
  host: string;
  port: number;
  user: string;
  password_set: boolean;
  password_preview: string;
  database: string;
  ssl: string;
  db_schema: string;
  connected: boolean;
  connection_message: string;
  existing_tables: string[];
  app_table_count: number;
}

interface DbPreset {
  driver: string;
  label_zh: string;
  label_en: string;
  port: number;
  schema: string;
  ssl: string;
  hint_zh: string;
  hint_en: string;
}

interface DbInitSqlPreview {
  db_schema: string;
  table_count: number;
  seed_test_data: boolean;
  full_sql: string;
  seed_steps: { zh: string; en: string }[];
}

export default function DatabaseSettingsPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const { ready: authReady } = useClientAuth();
  const d = translations.databaseSettings;
  const o = translations.organization;
  const c = translations.common;
  const allowed = authReady && canManageOrg(user);

  const [status, setStatus] = useState<DbStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [driver, setDriver] = useState("postgresql");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState(5432);
  const [dbUser, setDbUser] = useState("aiagnet");
  const [password, setPassword] = useState("");
  const [database, setDatabase] = useState("aiagnet");
  const [schema, setSchema] = useState("public");
  const [ssl, setSsl] = useState("prefer");
  const [busy, setBusy] = useState<string | null>(null);
  const [sqlModalOpen, setSqlModalOpen] = useState(false);
  const [sqlPreview, setSqlPreview] = useState<DbInitSqlPreview | null>(null);
  const [sqlPreviewSeed, setSqlPreviewSeed] = useState(true);

  const loadStatus = useCallback(() => {
    if (!allowed) return;
    setLoading(true);
    databaseApi.status()
      .then(({ data }) => {
        const s = data as DbStatus;
        setStatus(s);
        setDriver(s.driver === "vastbase" ? "vastbase" : "postgresql");
        setHost(s.host || "127.0.0.1");
        setPort(s.port || 5432);
        setDbUser(s.user || "aiagnet");
        setDatabase(s.database || "aiagnet");
        setSchema(s.db_schema || "public");
        setSsl(s.ssl || "prefer");
      })
      .catch(() => toast.error(o.loadFail[lang]))
      .finally(() => setLoading(false));
  }, [allowed, lang, o.loadFail]);

  useEffect(() => {
    if (!authReady) return;
    loadStatus();
  }, [authReady, loadStatus]);

  const formPayload = () => ({
    driver,
    host: host.trim(),
    port,
    user: dbUser.trim(),
    password: password.trim(),
    database: database.trim(),
    ssl,
    db_schema: schema.trim() || "public",
  });

  const handleTest = async () => {
    setBusy("test");
    try {
      const { data } = await databaseApi.test(formPayload());
      if (data.ok) toast.success(d.testOk[lang]);
      else toast.error(data.message || d.testFail[lang]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : d.testFail[lang]);
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    setBusy("save");
    try {
      const { data } = await databaseApi.saveConfig({
        ...formPayload(),
        password: password.trim() || null,
      });
      toast.success(data.message || d.saveOk[lang], { duration: 5000 });
      setPassword("");
      loadStatus();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : c.saveFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const loadSqlPreview = useCallback(async (seed: boolean, openModal = false) => {
    if (openModal) setBusy("sql");
    try {
      const { data } = await databaseApi.initSqlPreview({
        db_schema: schema.trim() || "public",
        seed_test_data: seed,
      });
      setSqlPreview(data as DbInitSqlPreview);
      setSqlPreviewSeed(seed);
      if (openModal) setSqlModalOpen(true);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (status === 404) {
        toast.error(d.restartHint[lang], { duration: 6000 });
        return;
      }
      toast.error(typeof detail === "string" ? detail : c.loadFailed[lang]);
    } finally {
      if (openModal) setBusy(null);
    }
  }, [schema, lang, c.loadFailed]);

  const handleViewInitSql = () => loadSqlPreview(sqlPreviewSeed, true);

  const handleCopyInitSql = async () => {
    if (!sqlPreview?.full_sql) return;
    try {
      await navigator.clipboard.writeText(sqlPreview.full_sql);
      toast.success(d.initSqlCopied[lang]);
    } catch {
      toast.error(c.actionFailed[lang]);
    }
  };

  const handleInit = async (seed: boolean) => {
    if (!user?.is_admin) {
      toast.error(d.adminOnlyInit[lang]);
      return;
    }
    const msg = lang === "zh"
      ? `将在 schema「${schema}」中创建表${seed ? "并写入测试数据" : ""}。若表已存在将跳过。继续？`
      : `Create tables in schema "${schema}"${seed ? " with test data" : ""}? Skips if tables exist. Continue?`;
    if (!confirm(msg)) return;

    setBusy("init");
    try {
      const { data } = await databaseApi.initialize({
        ...formPayload(),
        password: password.trim() || undefined,
        seed_test_data: seed,
        use_stored_config: false,
      });
      if (data.status === "conflict") {
        toast.error(`${d.initConflict[lang]}: ${data.existing_tables?.join(", ") || ""}`, { duration: 6000 });
      } else {
        toast.success(data.message || d.initOk[lang], { duration: 5000 });
        loadStatus();
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  if (!authReady) {
    return <div className="p-8"><p className="theme-muted">{c.loading[lang]}</p></div>;
  }

  if (!allowed) {
    return (
      <div className="p-8">
        <Link href="/settings" className="mb-6 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
          <ArrowLeft className="h-4 w-4" /> {d.backSettings[lang]}
        </Link>
        <div className="theme-card p-8 text-center">
          <Shield className="mx-auto mb-4 h-10 w-10 text-amber-400" />
          <p className="theme-muted">{o.forbidden[lang]}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8 max-w-3xl">
      <Link href="/settings" className="mb-4 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
        <ArrowLeft className="h-4 w-4" /> {d.backSettings[lang]}
      </Link>
      <h1 className="flex items-center gap-2 text-2xl font-bold theme-text">
        <Database className="h-7 w-7" /> {d.title[lang]}
      </h1>
      <p className="mt-1 text-sm theme-muted">{d.subtitle[lang]}</p>
      <p className="mt-3 rounded-lg border border-red-500/25 bg-red-500/5 px-4 py-3 text-sm text-red-600 dark:text-red-300">
        {d.restartHint[lang]}
      </p>

      {loading ? (
        <p className="mt-8 theme-muted">{c.loading[lang]}</p>
      ) : (
        <>
          {status && (
            <div className="theme-card mt-6 p-5">
              <h2 className="mb-3 text-sm font-semibold theme-text">{d.statusTitle[lang]}</h2>
              <div className="flex flex-wrap gap-2 text-sm">
                <span className={`rounded-full px-2 py-0.5 text-xs ${status.connected ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
                  {status.connected ? d.connected[lang] : d.disconnected[lang]}
                </span>
                <span className="theme-muted">{status.driver} · {status.host}:{status.port}/{status.database}</span>
                <span className="theme-muted">schema={status.db_schema}</span>
              </div>
              {status.existing_tables.length > 0 && (
                <div className="mt-3 rounded-lg border border-red-500/25 bg-red-500/5 p-3 text-xs">
                  <p className="font-medium text-red-600 dark:text-red-300">{d.existingTables[lang]} ({status.existing_tables.length}/{status.app_table_count})</p>
                  <p className="mt-1 text-red-600/90 dark:text-red-300/90">{status.existing_tables.slice(0, 12).join(", ")}{status.existing_tables.length > 12 ? "…" : ""}</p>
                  <p className="mt-2 text-red-600 dark:text-red-400">{d.schemaHint[lang]}</p>
                </div>
              )}
            </div>
          )}

          <div className="theme-card mt-6 space-y-4 p-6">
            <div>
              <label className="mb-2 block text-xs theme-muted">{d.driver[lang]}</label>
              <SegmentedControl
                value={driver}
                onChange={(v) => setDriver(v)}
                options={[
                  { value: "postgresql", label: d.presetPg[lang] },
                  { value: "vastbase", label: d.presetVast[lang] },
                ]}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block sm:col-span-2">
                <span className="text-xs theme-muted">{d.host[lang]}</span>
                <input className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={host} onChange={(e) => setHost(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs theme-muted">{d.port[lang]}</span>
                <input type="number" className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={port} onChange={(e) => setPort(Number(e.target.value))} />
              </label>
              <label className="block">
                <span className="text-xs theme-muted">{d.database[lang]}</span>
                <input className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={database} onChange={(e) => setDatabase(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs theme-muted">{d.user[lang]}</span>
                <input className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={dbUser} onChange={(e) => setDbUser(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs theme-muted">{d.password[lang]}{status?.password_set ? ` (${status.password_preview})` : ""}</span>
                <input type="password" placeholder={d.passwordKeep[lang]} className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs theme-muted">{d.schema[lang]}</span>
                <input className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={schema} onChange={(e) => setSchema(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs theme-muted">{d.ssl[lang]}</span>
                <select className="theme-input mt-1 w-full rounded-lg border px-3 py-2 text-sm" value={ssl} onChange={(e) => setSsl(e.target.value)}>
                  <option value="prefer">prefer</option>
                  <option value="disable">disable</option>
                  <option value="require">require</option>
                </select>
              </label>
            </div>
            <p className="text-xs theme-muted">{d.schemaHint[lang]}</p>
            <div className="flex flex-wrap gap-2 pt-2">
              <button type="button" disabled={!!busy} onClick={() => void handleTest()} className="theme-btn-primary">
                {busy === "test" ? c.loading[lang] : d.test[lang]}
              </button>
              <button type="button" disabled={!!busy} onClick={() => void handleSave()} className="rounded-lg border theme-border px-4 py-2 text-sm hover:bg-white/5">
                {busy === "save" ? c.loading[lang] : d.save[lang]}
              </button>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => void handleViewInitSql()}
                className="inline-flex items-center gap-1.5 rounded-lg border theme-border px-4 py-2 text-sm hover:bg-white/5"
              >
                <FileCode className="h-4 w-4" />
                {busy === "sql" ? c.loading[lang] : d.viewInitSql[lang]}
              </button>
              {user?.is_admin && (
                <>
                  <button type="button" disabled={!!busy} onClick={() => void handleInit(true)} className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-300 hover:bg-emerald-500/20">
                    {busy === "init" ? c.loading[lang] : d.init[lang]}
                  </button>
                  <button type="button" disabled={!!busy} onClick={() => void handleInit(false)} className="rounded-lg border theme-border px-4 py-2 text-sm text-slate-400 hover:bg-white/5">
                    {d.initNoSeed[lang]}
                  </button>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {sqlModalOpen && sqlPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card flex max-h-[90vh] w-full max-w-4xl flex-col p-6">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold theme-text">{d.initSqlTitle[lang]}</h2>
                <p className="mt-1 text-sm theme-muted">{d.initSqlHint[lang]}</p>
                <p className="mt-2 text-xs theme-muted">
                  schema={sqlPreview.db_schema} · {d.initSqlTables[lang]}: {sqlPreview.table_count}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSqlModalOpen(false)}
                className="rounded-lg p-1 theme-muted hover:bg-white/5 hover:theme-text"
                aria-label={c.cancel[lang]}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <label className="mb-3 flex items-center gap-2 text-sm theme-muted">
              <input
                type="checkbox"
                checked={sqlPreviewSeed}
                onChange={(e) => {
                  const next = e.target.checked;
                  setSqlPreviewSeed(next);
                  void loadSqlPreview(next);
                }}
              />
              {d.initSqlIncludeSeed[lang]}
            </label>

            <pre className="min-h-0 flex-1 overflow-auto rounded-lg border theme-border bg-black/30 p-4 text-xs leading-relaxed text-emerald-100/90">
              {sqlPreview.full_sql}
            </pre>

            {sqlPreview.seed_steps.length > 0 && (
              <div className="mt-4 rounded-lg border theme-border bg-white/[0.02] p-4">
                <h3 className="mb-2 text-sm font-medium theme-text">{d.initSqlSeedTitle[lang]}</h3>
                <ol className="list-decimal space-y-1 pl-5 text-sm theme-muted">
                  {sqlPreview.seed_steps.map((step, idx) => (
                    <li key={idx}>{lang === "zh" ? step.zh : step.en}</li>
                  ))}
                </ol>
              </div>
            )}

            <div className="mt-4 flex justify-end gap-3">
              <button type="button" onClick={() => setSqlModalOpen(false)} className="text-sm theme-muted">
                {c.cancel[lang]}
              </button>
              <button
                type="button"
                onClick={() => void handleCopyInitSql()}
                className="inline-flex items-center gap-1.5 rounded-lg border theme-border px-4 py-2 text-sm hover:bg-white/5"
              >
                <Copy className="h-4 w-4" />
                {d.initSqlCopy[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
