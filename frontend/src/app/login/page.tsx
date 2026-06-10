"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogIn } from "lucide-react";
import toast from "react-hot-toast";
import { authApi } from "@/lib/api";
import { useAuthStore } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const { lang } = useLangStore();
  const a = translations.auth;

  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!login.trim() || !password) return;
    setLoading(true);
    try {
      const { data } = await authApi.login(login.trim(), password);
      setAuth(data.access_token, data.user);
      router.replace("/");
      router.refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? a.loginFailed[lang]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0d0d1a] p-4">
      <div className="w-full max-w-md rounded-2xl border border-[#2d2d4e] bg-[#1a1a2e] p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-white font-bold">
            AI
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">{a.title[lang]}</h1>
            <p className="text-sm text-slate-400">{a.subtitle[lang]}</p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <input
            type="text"
            placeholder={a.loginPlaceholder[lang]}
            className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-4 py-3 text-sm text-white"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
          />
          <input
            type="password"
            placeholder={a.passwordPlaceholder[lang]}
            className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-4 py-3 text-sm text-white"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          <div className="text-right">
            <Link href="/login/forgot-password" className="text-xs text-blue-400 hover:underline">
              {a.forgotPassword[lang]}
            </Link>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <LogIn className="h-4 w-4" />
            {loading ? a.loggingIn[lang] : a.login[lang]}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-slate-500">{a.defaultHint[lang]}</p>
      </div>
    </div>
  );
}
