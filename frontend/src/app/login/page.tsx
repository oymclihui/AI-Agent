"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogIn, ShieldAlert } from "lucide-react";
import toast from "react-hot-toast";
import { authApi, setupApi } from "@/lib/api";
import { useAuthStore } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { useClientAuth } from "@/hooks/useClientAuth";

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const { ready, token } = useClientAuth();
  const { lang } = useLangStore();
  const a = translations.auth;

  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingSetup, setPendingSetup] = useState(false);

  useEffect(() => {
    setupApi.status()
      .then(({ data }) => setPendingSetup(Boolean(data.setup_required)))
      .catch(() => setPendingSetup(false));
  }, []);

  useEffect(() => {
    if (!ready || !token) return;
    router.replace("/chat");
  }, [ready, token, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!login.trim() || !password) {
      toast.error(lang === "zh" ? "请输入账号和密码" : "Enter username and password");
      return;
    }
    setLoading(true);
    try {
      const { data } = await authApi.login(login.trim(), password);
      setAuth(data.access_token, data.user);
      router.replace("/chat");
    } catch (err: unknown) {
      const ax = err as {
        response?: { data?: { detail?: unknown }; status?: number };
        message?: string;
        code?: string;
      };
      const detail = ax.response?.data?.detail;
      let msg: string = a.loginFailed[lang];
      if (typeof detail === "string") {
        msg = detail;
      } else if (Array.isArray(detail)) {
        msg = detail
          .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d)))
          .join("; ");
      } else if (!ax.response) {
        msg = lang === "zh" ? "无法连接服务器，请确认服务已启动" : "Cannot reach server — check the server is running";
      } else if (ax.response.status === 502 || ax.response.status === 503) {
        msg = lang === "zh" ? "后端服务未就绪，请等待 30 秒后重试" : "Backend not ready — wait ~30s and retry";
      }
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center theme-bg p-4">
      <div className="w-full max-w-md rounded-2xl border theme-border theme-surface p-8 shadow-lg">
        {pendingSetup && (
          <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
            <div className="mb-1 flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300">
              <ShieldAlert className="h-4 w-4 shrink-0" />
              {a.pendingSetupTitle[lang]}
            </div>
            <p className="theme-muted">{a.pendingSetupBody[lang]}</p>
            <Link href="/setup" className="mt-3 inline-block text-xs font-medium text-blue-500 hover:underline">
              {a.adminSetupLink[lang]}
            </Link>
          </div>
        )}

        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 font-bold text-white">
            AI
          </div>
          <div>
            <h1 className="text-xl font-bold theme-text">{a.title[lang]}</h1>
            <p className="text-sm theme-muted">{a.subtitle[lang]}</p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <input
            type="text"
            placeholder={a.loginPlaceholder[lang]}
            className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
          />
          <input
            type="password"
            placeholder={a.passwordPlaceholder[lang]}
            className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          <div className="text-right">
            <Link href="/login/forgot-password" className="text-xs text-blue-500 hover:underline">
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
          {!pendingSetup && (
            <p className="text-center text-xs theme-muted">{a.defaultHint[lang]}</p>
          )}
        </form>
      </div>
    </div>
  );
}
