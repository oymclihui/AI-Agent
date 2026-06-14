"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useClientAuth } from "@/hooks/useClientAuth";
import { setupApi } from "@/lib/api";

export default function RootPage() {
  const router = useRouter();
  const { ready, token } = useClientAuth();
  const [backendError, setBackendError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setupApi.status()
      .then(({ data }) => {
        if (cancelled) return;
        if (data.setup_required) {
          router.replace("/login");
          return;
        }
        router.replace(token ? "/chat" : "/login");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const ax = err as { code?: string; message?: string; response?: { status?: number } };
        if (ax.code === "ERR_NETWORK" || !ax.response) {
          setBackendError(
            "无法连接后端服务（默认端口 8000）。请确认 AI-AGENT.bat 已启动且后端窗口无报错。"
          );
          return;
        }
        router.replace(token ? "/chat" : "/login");
      });
    return () => {
      cancelled = true;
    };
  }, [ready, token, router]);

  if (backendError) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 px-6 text-center theme-bg theme-text">
        <p className="text-sm theme-muted max-w-md">{backendError}</p>
        <div className="flex flex-wrap justify-center gap-3 text-sm">
          <Link href="/login" className="text-blue-400 underline">尝试打开登录页</Link>
          <a href="http://127.0.0.1:8000/docs" className="text-blue-400 underline" target="_blank" rel="noreferrer">
            检查 API 文档
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full items-center justify-center theme-muted text-sm">
      Loading…
    </div>
  );
}
