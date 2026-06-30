"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogIn, UserPlus } from "lucide-react";
import toast from "react-hot-toast";
import { authApi, formatApiError } from "@/lib/api";
import { useAuthStore } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { useClientAuth } from "@/hooks/useClientAuth";
import { BrandMark } from "@/components/BrandMark";
import { useBrandingStore } from "@/lib/brandingStore";

type AuthMode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const { ready, token } = useClientAuth();
  const { lang } = useLangStore();
  const a = translations.auth;
  const systemName = useBrandingStore((s) => s.systemName);

  const [mode, setMode] = useState<AuthMode>("login");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [employeeNo, setEmployeeNo] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!ready || !token) return;
    router.replace("/chat");
  }, [ready, token, router]);

  const submitLogin = async (e: React.FormEvent) => {
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
      toast.error(formatApiError(err, a.loginFailed[lang]));
    } finally {
      setLoading(false);
    }
  };

  const submitRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!employeeNo.trim()) {
      toast.error(a.employeeNoRequired[lang]);
      return;
    }
    if (!displayName.trim()) {
      toast.error(a.displayNameRequired[lang]);
      return;
    }
    if (password.length < 6) {
      toast.error(a.passwordTooShort[lang]);
      return;
    }
    if (password !== confirmPassword) {
      toast.error(a.passwordMismatch[lang]);
      return;
    }
    setLoading(true);
    try {
      const { data } = await authApi.register({
        employee_no: employeeNo.trim(),
        email: email.trim() || undefined,
        display_name: displayName.trim(),
        password,
      });
      setAuth(data.access_token, data.user);
      toast.success(a.registerOk[lang]);
      router.replace("/chat");
    } catch (err: unknown) {
      toast.error(formatApiError(err, a.registerFailed[lang]));
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setPassword("");
    setConfirmPassword("");
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center theme-bg p-4">
      <div className="w-full max-w-md rounded-2xl border theme-border theme-surface p-8 shadow-lg">
        <div className="mb-6 flex items-center gap-3">
          <BrandMark size="lg" showName={false} />
          <div>
            <h1 className="text-xl font-bold theme-text">
              {systemName}{lang === "zh" ? " 登录" : " Sign In"}
            </h1>
            <p className="text-sm theme-muted">
              {mode === "login" ? a.subtitle[lang] : a.registerSubtitle[lang]}
            </p>
          </div>
        </div>

        <div className="mb-5 grid grid-cols-2 gap-1 rounded-lg border theme-border p-1">
            <button
              type="button"
              onClick={() => switchMode("login")}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                mode === "login"
                  ? "bg-blue-600 text-white"
                  : "theme-muted hover:bg-white/5"
              }`}
            >
              {a.loginTab[lang]}
            </button>
            <button
              type="button"
              onClick={() => switchMode("register")}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                mode === "register"
                  ? "bg-blue-600 text-white"
                  : "theme-muted hover:bg-white/5"
              }`}
            >
            {a.registerTab[lang]}
          </button>
        </div>

        {mode === "login" ? (
          <form onSubmit={submitLogin} className="space-y-4">
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
            <p className="text-center text-xs theme-muted">
              {a.noAccount[lang]}{" "}
              <button
                type="button"
                onClick={() => switchMode("register")}
                className="text-blue-500 hover:underline"
              >
                {a.registerTab[lang]}
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={submitRegister} className="space-y-4">
            <input
              type="text"
              placeholder={a.employeeNoPlaceholder[lang]}
              className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
              value={employeeNo}
              onChange={(e) => setEmployeeNo(e.target.value)}
              autoComplete="username"
            />
            <input
              type="text"
              placeholder={a.displayNamePlaceholder[lang]}
              className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
            />
            <input
              type="email"
              placeholder={a.emailOptionalPlaceholder[lang]}
              className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
            <input
              type="password"
              placeholder={a.passwordPlaceholder[lang]}
              className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
            <input
              type="password"
              placeholder={a.confirmPasswordPlaceholder[lang]}
              className="theme-input w-full rounded-lg border px-4 py-3 text-sm outline-none focus:border-blue-500"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
            />
            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <UserPlus className="h-4 w-4" />
              {loading ? a.registering[lang] : a.register[lang]}
            </button>
            <p className="text-center text-xs theme-muted">
              {a.hasAccount[lang]}{" "}
              <button
                type="button"
                onClick={() => switchMode("login")}
                className="text-blue-500 hover:underline"
              >
                {a.loginTab[lang]}
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
