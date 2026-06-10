"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import toast from "react-hot-toast";
import { authApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

function ResetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") || "";
  const { lang } = useLangStore();
  const r = translations.resetPassword;

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [valid, setValid] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setValid(false);
      return;
    }
    authApi.validateResetToken(token).then(() => setValid(true)).catch(() => setValid(false));
  }, [token]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 6) {
      toast.error(r.tooShort[lang]);
      return;
    }
    if (password !== confirm) {
      toast.error(r.mismatch[lang]);
      return;
    }
    setLoading(true);
    try {
      await authApi.resetPassword(token, password);
      toast.success(r.success[lang]);
      router.replace("/login");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? r.fail[lang]);
    } finally {
      setLoading(false);
    }
  };

  if (valid === null) {
    return <p className="text-sm text-slate-400">{r.checking[lang]}</p>;
  }

  if (!valid) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
        {r.invalidToken[lang]}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <input
        type="password"
        placeholder={r.newPassword[lang]}
        className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <input
        type="password"
        placeholder={r.confirmPassword[lang]}
        className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-blue-600 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {loading ? r.saving[lang] : r.submit[lang]}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  const { lang } = useLangStore();
  const r = translations.resetPassword;

  return (
    <div className="fixed inset-0 flex items-center justify-center theme-bg p-4">
      <div className="w-full max-w-md rounded-2xl border theme-border theme-surface p-8 shadow-lg">
        <Link href="/login" className="mb-6 inline-flex items-center gap-2 text-sm theme-muted hover:text-[var(--foreground)]">
          <ArrowLeft className="h-4 w-4" />
          {r.backToLogin[lang]}
        </Link>
        <h1 className="mb-2 text-xl font-bold theme-text">{r.title[lang]}</h1>
        <p className="mb-6 text-sm theme-muted">{r.subtitle[lang]}</p>
        <Suspense fallback={<p className="text-sm text-slate-400">{r.checking[lang]}</p>}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </div>
  );
}
