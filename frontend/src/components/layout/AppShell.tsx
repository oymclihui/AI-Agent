"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/layout/Sidebar";
import { useAuthStore } from "@/lib/authStore";
import { authApi } from "@/lib/api";
import { canReadEmployees, canViewDashboard, canManageOrg, canDelegateDept, canDelegateExec } from "@/lib/permissions";

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
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useAuthStore((s) => s.logout);
  const [hydrated, setHydrated] = useState(
    () => typeof window !== "undefined" && useAuthStore.persist.hasHydrated(),
  );

  const isPublic =
    pathname === "/login" ||
    pathname.startsWith("/login/");

  const isLowcodeDesigner = /\/inspiration\/[^/]+\/designer/.test(pathname);

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
    authApi.me()
      .then(({ data }) => setUser(data))
      .catch((err: unknown) => {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 401) {
          logout();
          router.replace("/login");
        }
      });
  }, [hydrated, isPublic, token, router, logout, setUser]);

  useEffect(() => {
    if (!hydrated || !token || !user || isPublic) return;
    const guardKey = routeNeedsGuard(pathname);
    if (!guardKey) return;
    if (guardKey === "/settings/organization") {
      const canManage = canManageOrg(user);
      if (!canManage) router.replace("/settings");
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
      router.replace("/");
    }
  }, [hydrated, token, user, pathname, isPublic, router]);

  if (!hydrated && !isPublic) {
    return (
      <div className="flex h-screen w-full items-center justify-center theme-bg theme-muted">
        Loading…
      </div>
    );
  }

  if (pathname === "/login" || pathname.startsWith("/login/")) {
    return <>{children}</>;
  }

  if (isLowcodeDesigner) {
    return <main className="h-screen w-full overflow-hidden">{children}</main>;
  }

  if (!hydrated || !token) {
    return (
      <div className="flex h-screen w-full items-center justify-center theme-bg theme-muted">
        Loading…
      </div>
    );
  }

  const isScreen = pathname === "/screen" || pathname.startsWith("/screen/");
  if (isScreen) {
    return <main className="h-screen w-full overflow-auto">{children}</main>;
  }

  return (
    <>
      <Sidebar />
      <main className="flex-1 overflow-auto">{children}</main>
    </>
  );
}
