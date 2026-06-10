"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import { useAuthStore } from "@/lib/authStore";
import { authApi } from "@/lib/api";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const logout = useAuthStore((s) => s.logout);
  const [hydrated, setHydrated] = useState(false);

  const isPublic =
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname === "/screen" ||
    pathname.startsWith("/screen/");

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true);
      return;
    }
    return useAuthStore.persist.onFinishHydration(() => setHydrated(true));
  }, []);

  useEffect(() => {
    if (!hydrated || isPublic) return;
    if (!token) {
      router.replace("/login");
      return;
    }
    authApi.me().catch((err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        logout();
        router.replace("/login");
      }
    });
  }, [hydrated, isPublic, token, router, logout]);

  if (pathname === "/login" || pathname.startsWith("/login/")) {
    return <>{children}</>;
  }

  if (isPublic) {
    return <>{children}</>;
  }

  if (!hydrated || !token) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-[#0d0d1a] text-slate-400">
        Loading…
      </div>
    );
  }

  return (
    <>
      <Sidebar />
      <main className="flex-1 overflow-auto">{children}</main>
    </>
  );
}
