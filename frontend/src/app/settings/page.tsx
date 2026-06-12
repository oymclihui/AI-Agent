"use client";

import { useEffect, useState } from "react";
import { useLangStore } from "@/lib/langStore";
import { useThemeStore } from "@/lib/themeStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { authApi } from "@/lib/api";
import toast from "react-hot-toast";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SegmentedControl } from "@/components/SegmentedControl";
import { canManageOrg, canDelegateDept, canDelegateExec } from "@/lib/permissions";

export default function SettingsPage() {
  const router = useRouter();
  const { lang, setLang } = useLangStore();
  const { theme, setTheme } = useThemeStore();
  const { user, logout } = useAuthStore();
  const s = translations.settings;
  const c = translations.common;

  const [provider, setProvider] = useState("openai");
  const [modelId, setModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [keys, setKeys] = useState<Array<{ id: string; provider: string; model_id?: string; api_key_preview: string }>>([]);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [resetLogin, setResetLogin] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [mailboxEmail, setMailboxEmail] = useState("");
  const [mailboxPassword, setMailboxPassword] = useState("");
  const [mailboxSaved, setMailboxSaved] = useState<{ email: string; password_preview: string; imap_host: string; imap_port: number } | null>(null);

  const loadKeys = () => {
    authApi.listModelKeys().then(({ data }) => setKeys(data)).catch(() => {});
  };

  const loadMailbox = () => {
    authApi.getMailbox().then(({ data }) => {
      if (data) {
        setMailboxSaved(data);
        setMailboxEmail(data.email);
      }
    }).catch(() => {});
  };

  useEffect(() => { loadKeys(); loadMailbox(); }, []);

  useEffect(() => {
    authApi.me().then(({ data }) => {
      const token = useAuthStore.getState().token;
      if (token) useAuthStore.getState().setUser(data);
      if (data.email && !mailboxEmail) setMailboxEmail(data.email);
    }).catch(() => {});
  }, []);

  const saveKey = async () => {
    if (!apiKey.trim()) return;
    try {
      await authApi.saveModelKey({
        provider,
        model_id: modelId.trim() || null,
        api_key: apiKey.trim(),
        base_url: baseUrl.trim() || null,
      });
      setApiKey("");
      toast.success(s.keySaved[lang]);
      loadKeys();
    } catch {
      toast.error(lang === "zh" ? "保存失败" : "Save failed");
    }
  };

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  const handleChangePassword = async () => {
    if (newPassword.length < 6) {
      toast.error(lang === "zh" ? "新密码至少 6 位" : "New password must be at least 6 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error(s.pwdMismatch[lang]);
      return;
    }
    try {
      await authApi.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      toast.success(s.changePwdOk[lang]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? s.changePwdFail[lang]);
    }
  };

  const handleAdminReset = async () => {
    if (!resetLogin.trim() || resetPassword.length < 6) {
      toast.error(lang === "zh" ? "请填写用户与新密码（至少 6 位）" : "Enter user and new password (min 6 chars)");
      return;
    }
    if (!confirm(lang === "zh" ? `确认为 ${resetLogin} 重置密码？` : `Reset password for ${resetLogin}?`)) return;
    try {
      await authApi.adminResetPassword(resetLogin.trim(), resetPassword);
      setResetLogin("");
      setResetPassword("");
      toast.success(s.resetPwdOk[lang]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? s.resetPwdFail[lang]);
    }
  };

  const handleSaveMailbox = async () => {
    if (!mailboxPassword.trim()) {
      toast.error(lang === "zh" ? "请填写邮箱密码" : "Enter mailbox password");
      return;
    }
    try {
      await authApi.saveMailbox({
        email: mailboxEmail.trim() || user?.email || null,
        mailbox_password: mailboxPassword.trim(),
      });
      setMailboxPassword("");
      toast.success(s.mailboxSaved[lang]);
      loadMailbox();
    } catch {
      toast.error(lang === "zh" ? "保存失败" : "Save failed");
    }
  };

  const handleTestMailbox = async () => {
    try {
      const { data } = await authApi.testMailbox();
      if (data.ok) toast.success(`${s.mailboxTestOk[lang]} (${data.sample_count})`);
      else toast.error(data.message || s.mailboxTestFail[lang]);
    } catch {
      toast.error(s.mailboxTestFail[lang]);
    }
  };

  const handleDeleteMailbox = async () => {
    try {
      await authApi.deleteMailbox();
      setMailboxSaved(null);
      setMailboxEmail("");
      toast.success(lang === "zh" ? "已删除" : "Removed");
    } catch {
      toast.error(lang === "zh" ? "删除失败" : "Delete failed");
    }
  };

  return (
    <div className="p-8">
      <h1 className="mb-2 text-2xl font-bold theme-text">{s.title[lang]}</h1>
      <p className="mb-8 theme-muted">{s.subtitle[lang]}</p>

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-2 text-lg font-semibold theme-text">{s.accountTitle[lang]}</h2>
        <p className="mb-3 text-sm text-slate-400">{user?.display_name} ({user?.employee_no || user?.email})</p>
        <button onClick={handleLogout} className="rounded-lg border border-red-500/30 px-4 py-2 text-sm text-red-400 hover:bg-red-500/10">
          {s.logout[lang]}
        </button>
      </div>

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-2 text-lg font-semibold theme-text">{s.changePwdTitle[lang]}</h2>
        <p className="mb-4 text-sm theme-muted">{s.changePwdDesc[lang]}</p>
        <div className="mb-4 grid gap-2">
          <input type="password" placeholder={s.currentPassword[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
          <input type="password" placeholder={s.newPassword[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          <input type="password" placeholder={s.confirmPassword[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
        </div>
        <button onClick={handleChangePassword} className="theme-btn-primary">{s.changePwdBtn[lang]}</button>
      </div>

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-2 text-lg font-semibold theme-text">{s.mailboxTitle[lang]}</h2>
        <p className="mb-2 text-sm text-slate-400">{s.mailboxDesc[lang]}</p>
        <p className="mb-4 text-xs text-slate-500">{s.mailboxImapHint[lang]}</p>
        {mailboxSaved && (
          <p className="mb-3 text-xs text-slate-400">
            {lang === "zh" ? "已配置：" : "Configured: "}{mailboxSaved.email} · {mailboxSaved.password_preview}
          </p>
        )}
        <div className="mb-4 grid gap-2 md:grid-cols-2">
          <input placeholder={s.mailboxEmail[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400 md:col-span-2" value={mailboxEmail} onChange={(e) => setMailboxEmail(e.target.value)} />
          <input type="password" placeholder={s.mailboxPassword[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400 md:col-span-2" value={mailboxPassword} onChange={(e) => setMailboxPassword(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={handleSaveMailbox} className="theme-btn-primary">{s.mailboxSave[lang]}</button>
          <button onClick={handleTestMailbox} className="rounded-lg border theme-border px-4 py-2 text-sm text-slate-300 hover:bg-white/5">{s.mailboxTest[lang]}</button>
          {mailboxSaved && (
            <button onClick={handleDeleteMailbox} className="rounded-lg border border-red-500/30 px-4 py-2 text-sm text-red-400 hover:bg-red-500/10">{s.mailboxDelete[lang]}</button>
          )}
        </div>
      </div>

      {canManageOrg(user) && (
        <div className="theme-card mb-6 border-violet-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{s.orgLinkTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{s.orgLinkDesc[lang]}</p>
          <Link href="/settings/organization" className="theme-btn-primary inline-block">{s.orgLinkBtn[lang]}</Link>
        </div>
      )}

      {canDelegateDept(user) && !canManageOrg(user) && (
        <div className="theme-card mb-6 border-cyan-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{translations.delegation.deptTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{translations.delegation.deptSubtitle[lang]}</p>
          <Link href="/settings/delegation/dept" className="theme-btn-primary inline-block">{s.orgLinkBtn[lang]}</Link>
        </div>
      )}

      {canDelegateExec(user) && (
        <div className="theme-card mb-6 border-amber-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{translations.delegation.execTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{translations.delegation.execSubtitle[lang]}</p>
          <Link href="/settings/delegation/executive" className="theme-btn-primary inline-block">{s.orgLinkBtn[lang]}</Link>
        </div>
      )}

      {user?.is_admin && (
        <div className="theme-card mb-6 border-amber-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{s.adminResetTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{s.adminResetDesc[lang]}</p>
          <div className="mb-4 grid gap-2 md:grid-cols-2">
            <input placeholder={s.resetLogin[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={resetLogin} onChange={(e) => setResetLogin(e.target.value)} />
            <input type="password" placeholder={s.newPassword[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} />
          </div>
          <button onClick={handleAdminReset} className="rounded-lg border border-amber-500/40 px-4 py-2 text-sm text-amber-300 hover:bg-amber-500/10">{s.resetPwdBtn[lang]}</button>
        </div>
      )}

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-2 text-lg font-semibold theme-text">{s.modelKeysTitle[lang]}</h2>
        <p className="mb-4 text-sm theme-muted">{s.modelKeysDesc[lang]}</p>
        <div className="mb-4 grid gap-2 md:grid-cols-2">
          <input placeholder={s.keyProvider[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={provider} onChange={(e) => setProvider(e.target.value)} />
          <input placeholder={s.keyModelId[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400" value={modelId} onChange={(e) => setModelId(e.target.value)} />
          <input placeholder={s.keyValue[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400 md:col-span-2" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          <input placeholder={s.keyBaseUrl[lang]} className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400 md:col-span-2" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </div>
        <button onClick={saveKey} className="theme-btn-primary">{c.save[lang]}</button>
        {keys.length > 0 && (
          <ul className="mt-4 space-y-2 text-xs theme-muted">
            {keys.map((k) => (
              <li key={k.id} className="flex justify-between rounded border theme-border px-3 py-2">
                <span>{k.provider}{k.model_id ? ` / ${k.model_id}` : ""} · {k.api_key_preview}</span>
                <button onClick={() => authApi.deleteModelKey(k.id).then(loadKeys)} className="text-red-400">{c.delete[lang]}</button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-2 text-lg font-semibold theme-text">{s.langTitle[lang]}</h2>
        <p className="mb-4 text-sm theme-muted">{s.langDesc[lang]}</p>
        <SegmentedControl
          value={lang}
          onChange={setLang}
          options={[
            { value: "zh", label: c.chinese[lang] },
            { value: "en", label: c.english[lang] },
          ]}
        />
      </div>

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-2 text-lg font-semibold theme-text">{s.themeTitle[lang]}</h2>
        <p className="mb-4 text-sm theme-muted">{s.themeDesc[lang]}</p>
        <SegmentedControl
          value={theme}
          onChange={setTheme}
          options={[
            { value: "dark", label: s.themeDark[lang] },
            { value: "light", label: s.themeLight[lang] },
          ]}
        />
      </div>

      <div className="theme-card mb-6 p-6">
        <h2 className="mb-4 text-lg font-semibold theme-text">{s.envVars[lang]}</h2>
        <p className="mb-4 text-sm text-slate-400">{s.envDesc[lang]}</p>
        <div className="space-y-3 font-mono text-sm">
          {[
            { key: "OPENAI_API_KEY", desc: "OpenAI API key for GPT models" },
            { key: "OLLAMA_BASE_URL", desc: "Local Ollama server URL (default: http://localhost:11434)" },
            { key: "VECTOR_STORE_TYPE", desc: "milvus or chroma" },
            { key: "MILVUS_URI", desc: "Remote Milvus server URI" },
            { key: "SECRET_KEY", desc: "Application secret key (min 32 chars)" },
          ].map(({ key, desc }) => (
            <div key={key} className="flex items-start gap-4 rounded-lg border theme-border p-3">
              <code className="w-48 shrink-0 text-slate-500">{key}</code>
              <span className="mt-0.5 text-xs text-slate-400">{desc}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="theme-card mt-6 p-6">
        <h2 className="mb-4 text-lg font-semibold theme-text">{s.apiRef[lang]}</h2>
        <p className="text-sm theme-muted">
          {s.apiDesc[lang]}{" "}
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer" className="text-slate-600 underline decoration-slate-300 underline-offset-2 hover:text-slate-900">
            http://localhost:8000/docs
          </a>
        </p>
      </div>
    </div>
  );
}
