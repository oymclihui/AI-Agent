"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Database, KeyRound, LogIn, Rocket, Server } from "lucide-react";
import toast from "react-hot-toast";
import { setupApi, SETUP_TOKEN_STORAGE_KEY } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { SegmentedControl } from "@/components/SegmentedControl";

interface DbPreset {
  driver: string;
  label_zh: string;
  label_en: string;
  port: number;
  db_schema: string;
  ssl: string;
  hint_zh: string;
  hint_en: string;
}

interface SetupStatus {
  setup_required: boolean;
  setup_token_required: boolean;
  db_connected: boolean;
  connection_message: string;
  default_admin_login: string;
  db_host: string;
  db_port: number;
  db_user: string;
  db_name: string;
  db_schema: string;
}

export default function SetupPage() {
  const router = useRouter();
  const { lang } = useLangStore();
  const s = translations.setup;
  const d = translations.databaseSettings;

  const [loading, setLoading] = useState(true);
  const [tokenRequired, setTokenRequired] = useState(true);
  const [setupToken, setSetupToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [tokenVerified, setTokenVerified] = useState(false);
  const [presets, setPresets] = useState<DbPreset[]>([]);
  const [done, setDone] = useState<{ login: string; password: string } | null>(null);

  const [driver, setDriver] = useState("postgresql");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState(5432);
  const [dbUser, setDbUser] = useState("aiagnet");
  const [password, setPassword] = useState("");
  const [database, setDatabase] = useState("aiagnet");
  const [schema, setSchema] = useState("public");
  const [ssl, setSsl] = useState("prefer");
  const [busy, setBusy] = useState<string | null>(null);

  const applyPreset = useCallback((preset: DbPreset) => {
    setDriver(preset.driver);
    setPort(preset.port);
    setSchema(preset.db_schema);
    setSsl(preset.ssl);
  }, []);

  const loadPresets = useCallback(async (token: string) => {
    const { data } = await setupApi.presets(token);
    const list = data as DbPreset[];
    setPresets(list);
    const match = list.find((p) => p.driver === driver) ?? list[0];
    if (match) applyPreset(match);
    setTokenVerified(true);
    sessionStorage.setItem(SETUP_TOKEN_STORAGE_KEY, token);
  }, [applyPreset, driver]);

  useEffect(() => {
    setupApi.status()
      .then(({ data }) => {
        const st = data as SetupStatus;
        if (!st.setup_required) {
          router.replace("/login");
          return;
        }
        setTokenRequired(st.setup_token_required);
        if (st.db_host) setHost(st.db_host);
        if (st.db_port) setPort(st.db_port);
        if (st.db_user) setDbUser(st.db_user);
        if (st.db_name) setDatabase(st.db_name);
        if (st.db_schema) setSchema(st.db_schema);

        const saved = sessionStorage.getItem(SETUP_TOKEN_STORAGE_KEY) ?? "";
        if (!st.setup_token_required) {
          setTokenVerified(true);
          return loadPresets("");
        }
        if (saved) {
          setSetupToken(saved);
          return loadPresets(saved).catch(() => {
            sessionStorage.removeItem(SETUP_TOKEN_STORAGE_KEY);
            setSetupToken("");
          });
        }
        return undefined;
      })
      .catch(() => toast.error(s.loadFail[lang]))
      .finally(() => setLoading(false));
  }, [lang, loadPresets, router, s.loadFail]);

  const verifyToken = async () => {
    const token = tokenInput.trim();
    if (!token) {
      toast.error(s.tokenInvalid[lang]);
      return;
    }
    setBusy("token");
    try {
      await loadPresets(token);
      setSetupToken(token);
      toast.success(lang === "zh" ? "验证通过" : "Verified");
    } catch {
      toast.error(s.tokenInvalid[lang]);
    } finally {
      setBusy(null);
    }
  };

  const onDriverChange = (value: string) => {
    setDriver(value);
    const preset = presets.find((p) => p.driver === value);
    if (preset) applyPreset(preset);
  };

  const testConnection = async () => {
    setBusy("test");
    try {
      const { data } = await setupApi.test({
        driver,
        host,
        port,
        user: dbUser,
        password,
        database,
        ssl,
        db_schema: schema,
      }, setupToken);
      if (data.ok) toast.success(d.testOk[lang]);
      else toast.error(`${d.testFail[lang]}: ${data.message}`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : d.testFail[lang]);
    } finally {
      setBusy(null);
    }
  };

  const initialize = async () => {
    if (!password) {
      toast.error(lang === "zh" ? "请填写数据库密码" : "Enter database password");
      return;
    }
    setBusy("init");
    try {
      const { data } = await setupApi.initialize({
        driver,
        host,
        port,
        user: dbUser,
        password,
        database,
        ssl,
        db_schema: schema,
        seed_test_data: true,
        use_stored_config: false,
      }, setupToken);
      if (data.status === "conflict") {
        toast.error(data.message);
        return;
      }
      if (data.status === "created") {
        setDone({ login: data.admin_login, password: data.admin_password });
        toast.success(d.initOk[lang]);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : d.initFail[lang]);
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center theme-bg theme-muted text-sm">
        {s.loading[lang]}
      </div>
    );
  }

  if (done) {
    return (
      <div className="flex min-h-screen items-center justify-center theme-bg p-4">
        <div className="w-full max-w-lg rounded-2xl border theme-border theme-surface p-8 shadow-lg">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-500/15 text-green-500">
              <Rocket className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold theme-text">{s.doneTitle[lang]}</h1>
              <p className="text-sm theme-muted">{s.doneSubtitle[lang]}</p>
            </div>
          </div>
          <div className="mb-6 rounded-xl border theme-border bg-blue-500/5 p-4 text-sm">
            <p className="mb-2 font-medium theme-text">{s.credentialsTitle[lang]}</p>
            <p className="theme-muted">
              {s.loginLabel[lang]}: <span className="font-mono font-semibold theme-text">{done.login}</span>
            </p>
            <p className="theme-muted">
              {s.passwordLabel[lang]}: <span className="font-mono font-semibold theme-text">{done.password}</span>
            </p>
            <p className="mt-3 text-xs theme-muted">{s.changePasswordHint[lang]}</p>
          </div>
          <p className="mb-4 text-sm text-amber-600 dark:text-amber-400">{s.restartHint[lang]}</p>
          <Link
            href="/login"
            className="theme-btn-primary inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium"
          >
            <LogIn className="h-4 w-4" />
            {s.goLogin[lang]}
          </Link>
        </div>
      </div>
    );
  }

  if (!tokenVerified && tokenRequired) {
    return (
      <div className="flex min-h-screen items-center justify-center theme-bg p-4">
        <div className="w-full max-w-md rounded-2xl border theme-border theme-surface p-8 shadow-lg">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-500">
              <KeyRound className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold theme-text">{s.tokenTitle[lang]}</h1>
              <p className="text-sm theme-muted">{s.tokenSubtitle[lang]}</p>
            </div>
          </div>
          <input
            type="password"
            className="theme-input mb-4 w-full rounded-lg px-3 py-2.5 text-sm"
            placeholder={s.tokenLabel[lang]}
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && verifyToken()}
          />
          <button
            type="button"
            disabled={busy === "token"}
            onClick={verifyToken}
            className="theme-btn-primary mb-4 w-full rounded-lg py-2.5 text-sm font-medium"
          >
            {busy === "token" ? "…" : s.tokenSubmit[lang]}
          </button>
          <p className="text-xs theme-muted">{s.adminOnlyNote[lang]}</p>
          <Link href="/login" className="mt-4 inline-block text-xs text-blue-500 hover:underline">
            {s.goLogin[lang]}
          </Link>
        </div>
      </div>
    );
  }

  const activePreset = presets.find((p) => p.driver === driver);

  return (
    <div className="flex min-h-screen items-center justify-center theme-bg p-4">
      <div className="w-full max-w-2xl rounded-2xl border theme-border theme-surface p-6 shadow-lg md:p-8">
        <div className="mb-6 flex items-start gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-500/15 text-blue-500">
            <Database className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold theme-text">{s.title[lang]}</h1>
            <p className="mt-1 text-sm theme-muted">{s.subtitle[lang]}</p>
          </div>
        </div>

        <div className="mb-6 rounded-xl border border-blue-500/25 bg-blue-500/5 p-4 text-sm theme-muted">
          <div className="mb-1 flex items-center gap-2 font-medium theme-text">
            <Server className="h-4 w-4 text-blue-500" />
            {s.noVastbaseTitle[lang]}
          </div>
          <p>{s.noVastbaseBody[lang]}</p>
          <p className="mt-2 text-xs">{s.adminOnlyNote[lang]}</p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium theme-muted">{d.driver[lang]}</label>
            <SegmentedControl
              value={driver}
              onChange={onDriverChange}
              options={[
                { value: "postgresql", label: d.presetPg[lang] },
                { value: "vastbase", label: d.presetVast[lang] },
              ]}
            />
            {activePreset && (
              <p className="mt-2 text-xs theme-muted">
                {lang === "zh" ? activePreset.hint_zh : activePreset.hint_en}
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-xs theme-muted">{d.host[lang]}</span>
              <input className="theme-input w-full rounded-lg px-3 py-2 text-sm" value={host} onChange={(e) => setHost(e.target.value)} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs theme-muted">{d.port[lang]}</span>
              <input type="number" className="theme-input w-full rounded-lg px-3 py-2 text-sm" value={port} onChange={(e) => setPort(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs theme-muted">{d.database[lang]}</span>
              <input className="theme-input w-full rounded-lg px-3 py-2 text-sm" value={database} onChange={(e) => setDatabase(e.target.value)} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs theme-muted">{d.user[lang]}</span>
              <input className="theme-input w-full rounded-lg px-3 py-2 text-sm" value={dbUser} onChange={(e) => setDbUser(e.target.value)} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs theme-muted">{d.password[lang]}</span>
              <input type="password" className="theme-input w-full rounded-lg px-3 py-2 text-sm" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-xs theme-muted">{d.schema[lang]}</span>
              <input className="theme-input w-full rounded-lg px-3 py-2 text-sm" value={schema} onChange={(e) => setSchema(e.target.value)} />
              <span className="mt-1 block text-xs theme-muted">{d.schemaHint[lang]}</span>
            </label>
          </div>

          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={testConnection}
              className="rounded-lg border theme-border px-4 py-2 text-sm theme-text hover:bg-blue-500/10"
            >
              {busy === "test" ? "…" : d.test[lang]}
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={initialize}
              className="theme-btn-primary rounded-lg px-4 py-2 text-sm font-medium"
            >
              {busy === "init" ? "…" : s.initAndLogin[lang]}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
