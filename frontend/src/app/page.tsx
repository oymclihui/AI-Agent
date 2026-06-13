"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useClientAuth } from "@/hooks/useClientAuth";
import { setupApi } from "@/lib/api";

export default function RootPage() {
  const router = useRouter();
  const { ready, token } = useClientAuth();

  useEffect(() => {
    if (!ready) return;
    setupApi.status()
      .then(({ data }) => {
        if (data.setup_required) {
          router.replace("/login");
          return;
        }
        router.replace(token ? "/chat" : "/login");
      })
      .catch(() => {
        router.replace(token ? "/chat" : "/login");
      });
  }, [ready, token, router]);

  return (
    <div className="flex h-full w-full items-center justify-center theme-muted text-sm">
      Loading…
    </div>
  );
}
