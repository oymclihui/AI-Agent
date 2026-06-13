"use client";

import { useEffect, useLayoutEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import { useAuthStore } from "@/lib/authStore";
import { authApi } from "@/lib/api";
import { useClientAuth } from "@/hooks/useClientAuth";
import { canReadEmployees, canViewDashboard, canManageOrg, canDelegateDept, canDelegateExec } from "@/lib/permissions";
import { useIsMobile } from "@/hooks/useMediaQuery";

const ROUTE_PERMISSIONS: Record<string, (user: ReturnType<typeof useAuthStore.getState>["user"]) => boolean> = {
  "/screen": canViewDashboard,
  "/employees": canReadEmployees,
};

function routeNeedsGuard(pathname: string): string | null {
  if (pathname === "/screen" || pathname.startsWith("/screen/")) return "/screen";
  if (pathname === "/employees" || pathname.startsWith("/employees/")) return "/employees";
  if (pathname === "/settings/organization" || pathname.startsWith("/settings/organization/")) {
    return "/settings/organization";
  }
  if (pathname.startsWith("/settings/delegation/dept")) return "/settings/delegation/dept";
  if (pathname.startsWith("/settings/delegation/executive")) return "/settings/delegation/executive";
  return null;
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { ready, token } = useClientAuth();
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useAuthStore((s) => s.logout);
  const isMobile = useIsMobile();

  const isPublic =
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname === "/setup";

  useLayoutEffect(() => {
    if (!ready || isPublic) return;
    if (!token) router.replace("/login");
  }, [ready, isPublic, token, router]);

  useEffect(() => {
    if (!ready || isPublic || !token) return;
    authApi.me()
      .then(({ data }) => setUser(data))
      .catch((err: unknown) => {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 401) {
          logout();
          router.replace("/login");
        }
      });
  }, [ready, isPublic, token, router, logout, setUser]);

  useEffect(() => {
    if (!ready || !token || !user || isPublic) return;
    const guardKey = routeNeedsGuard(pathname);
    if (!guardKey) return;
    if (guardKey === "/settings/organization") {
      if (!canManageOrg(user)) router.replace("/settings");
      return;
    }
    if (guardKey === "/settings/delegation/dept") {
      if (!canDelegateDept(user)) router.replace("/settings");
      return;
    }
    if (guardKey === "/settings/delegation/executive") {
      if (!canDelegateExec(user)) router.replace("/settings");
      return;
    }
    const check = ROUTE_PERMISSIONS[guardKey];
    if (check && !check(user)) {
      router.replace("/chat");
    }
  }, [ready, token, user, pathname, isPublic, router]);

  if (isPublic) {
    return <>{children}</>;
  }

  if (!ready) {
    return (
      <div className="flex h-screen w-full items-center justify-center theme-bg theme-muted">
        Loading…
      </div>
    );
  }

  if (!token) {
    return (
      <div className="flex h-screen w-full flex-col items-center justify-center gap-3 theme-bg theme-muted">
        <p className="text-sm">Redirecting to login…</p>
        <a href="/login" className="text-sm text-blue-400 underline">Go to login</a>
      </div>
    );
  }

  const isScreen = pathname === "/screen" || pathname.startsWith("/screen/");
  if (isScreen) {
    return <main className="h-screen w-full overflow-auto">{children}</main>;
  }

  const isChat = pathname === "/chat" || pathname.startsWith("/chat/");
  if (isChat && isMobile) {
    return <main className="flex h-[100dvh] w-full flex-col overflow-hidden">{children}</main>;
  }

  if (isChat) {
    return (
      <>
        <Sidebar />
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</main>
      </>
    );
  }

  return (
    <>
      <Sidebar />
      <main className="flex-1 overflow-auto">{children}</main>
    </>
  );
}
