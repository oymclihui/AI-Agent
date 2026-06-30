"use client";

import { useEffect, useRef, useState } from "react";
import { useLangStore } from "@/lib/langStore";
import { useThemeStore } from "@/lib/themeStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { authApi, systemApi } from "@/lib/api";
import toast from "react-hot-toast";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SegmentedControl } from "@/components/SegmentedControl";
import { ModelKeysPanel } from "@/components/ModelKeysPanel";
import { BrandMark } from "@/components/BrandMark";
import { canManageOrg, canDelegateDept, canDelegateExec } from "@/lib/permissions";
import { useBrandingStore } from "@/lib/brandingStore";

export default function SettingsPage() {
  const router = useRouter();
  const { lang, setLang } = useLangStore();
  const { theme, setTheme } = useThemeStore();
  const { user, logout } = useAuthStore();
  const s = translations.settings;
  const c = translations.common;

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [resetLogin, setResetLogin] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [mailboxEmail, setMailboxEmail] = useState("");
  const [mailboxPassword, setMailboxPassword] = useState("");
  const [mailboxSaved, setMailboxSaved] = useState<{ email: string; password_preview: string; imap_host: string; imap_port: number } | null>(null);
  const { systemName, systemIcon, setBranding } = useBrandingStore();
  const [brandName, setBrandName] = useState("AI-AGENT");
  const [brandIconPreview, setBrandIconPreview] = useState<string | null>(null);
  const [savingBrand, setSavingBrand] = useState(false);
  const brandIconRef = useRef<HTMLInputElement>(null);

  const loadMailbox = () => {
    authApi.getMailbox().then(({ data }) => {
      if (data) {
        setMailboxSaved(data);
        setMailboxEmail(data.email);
      }
    }).catch(() => {});
  };

  useEffect(() => { loadMailbox(); }, []);

  useEffect(() => {
    setBrandName(systemName);
    setBrandIconPreview(systemIcon);
  }, [systemName, systemIcon]);

  useEffect(() => {
    authApi.me().then(({ data }) => {
      const token = useAuthStore.getState().token;
      if (token) useAuthStore.getState().setUser(data);
      if (data.email && !mailboxEmail) setMailboxEmail(data.email);
    }).catch(() => {});
  }, []);

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

  const handleSaveBrand = async () => {
    if (!brandName.trim()) {
      toast.error(lang === "zh" ? "系统名称不能为空" : "System name is required");
      return;
    }
    setSavingBrand(true);
    try {
      const { data } = await systemApi.updateBranding({
        system_name: brandName.trim(),
        system_icon: brandIconPreview,
      });
      const saved = data as { system_name: string; system_icon?: string | null };
      setBranding(saved);
      toast.success(s.brandingSaved[lang]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : s.brandingSaveFail[lang]);
    } finally {
      setSavingBrand(false);
    }
  };

  const handleBrandIconFile = (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error(lang === "zh" ? "请选择图片文件" : "Please select an image file");
      return;
    }
    if (file.size > 512 * 1024) {
      toast.error(lang === "zh" ? "图标不能超过 512KB" : "Icon must be under 512KB");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setBrandIconPreview(String(reader.result || ""));
    reader.readAsDataURL(file);
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

      {user?.is_admin && (
        <div className="theme-card mb-6 border-blue-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{s.brandingTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{s.brandingDesc[lang]}</p>
          <div className="mb-4 flex flex-wrap items-center gap-4">
            <BrandMark size="lg" name={brandName} icon={brandIconPreview} />
            <div className="text-xs theme-muted">{s.brandingIconHint[lang]}</div>
          </div>
          <div className="mb-4 grid gap-3 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm theme-muted">{s.brandingName[lang]}</label>
              <input
                className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400"
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
                placeholder="AI-AGENT"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm theme-muted">{s.brandingIcon[lang]}</label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => brandIconRef.current?.click()}
                  className="rounded-lg border theme-border px-4 py-2 text-sm hover:bg-white/5"
                >
                  {s.brandingUpload[lang]}
                </button>
                {brandIconPreview && (
                  <button
                    type="button"
                    onClick={() => setBrandIconPreview(null)}
                    className="rounded-lg border border-red-500/30 px-4 py-2 text-sm text-red-400 hover:bg-red-500/10"
                  >
                    {s.brandingRemoveIcon[lang]}
                  </button>
                )}
                <input
                  ref={brandIconRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  className="hidden"
                  onChange={(e) => handleBrandIconFile(e.target.files?.[0])}
                />
              </div>
            </div>
          </div>
          <button
            type="button"
            disabled={savingBrand}
            onClick={handleSaveBrand}
            className="theme-btn-primary"
          >
            {savingBrand ? "…" : s.brandingSave[lang]}
          </button>
        </div>
      )}

      <div className="theme-card mb-6 border-violet-500/20 p-6">
        <ModelKeysPanel lang={lang} />
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

      {canManageOrg(user) && (
        <div className="theme-card mb-6 border-emerald-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{s.databaseLinkTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{s.databaseLinkDesc[lang]}</p>
          <Link href="/settings/database" className="theme-btn-primary inline-block">{s.orgLinkBtn[lang]}</Link>
        </div>
      )}

      {canManageOrg(user) && (
        <div className="theme-card mb-6 border-cyan-500/20 p-6">
          <h2 className="mb-2 text-lg font-semibold theme-text">{s.integrationsLinkTitle[lang]}</h2>
          <p className="mb-4 text-sm theme-muted">{s.integrationsLinkDesc[lang]}</p>
          <Link href="/settings/integrations" className="theme-btn-primary inline-block">{s.orgLinkBtn[lang]}</Link>
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
