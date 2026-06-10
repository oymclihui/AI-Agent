"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import toast from "react-hot-toast";
import { authApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export default function ForgotPasswordPage() {
  const { lang } = useLangStore();
  const f = translations.forgotPassword;
  const [login, setLogin] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!login.trim()) return;
    setLoading(true);
    try {
      await authApi.forgotPassword(login.trim());
      setSent(true);
      toast.success(f.sentOk[lang]);
    } catch {
      toast.error(f.sentFail[lang]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center theme-bg p-4">
      <div className="w-full max-w-lg rounded-2xl border theme-border theme-surface p-8 shadow-lg">
        <Link href="/login" className="mb-6 inline-flex items-center gap-2 text-sm theme-muted hover:text-[var(--foreground)]">
          <ArrowLeft className="h-4 w-4" />
          {f.backToLogin[lang]}
        </Link>

        <h1 className="mb-2 text-xl font-bold theme-text">{f.title[lang]}</h1>
        <p className="mb-6 text-sm theme-muted">{f.emailSubtitle[lang]}</p>

        {sent ? (
          <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-4 text-sm text-green-300">
            {f.sentHint[lang]}
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <input
              type="text"
              placeholder={f.loginPlaceholder[lang]}
              className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
            />
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-blue-600 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? f.sending[lang] : f.sendLink[lang]}
            </button>
          </form>
        )}

        <p className="mt-6 text-xs text-slate-500">{f.noteRegisteredEmail[lang]}</p>
      </div>
    </div>
  );
}
