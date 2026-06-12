"use client";

import { useEffect, useState } from "react";
import { useAuthStore } from "@/lib/authStore";

/** True after zustand-persist rehydration (with short timeout fallback). */
export function useAuthReady(): boolean {
  const [ready, setReady] = useState(
    () => typeof window !== "undefined" && useAuthStore.persist.hasHydrated(),
  );

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setReady(true);
      return;
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => setReady(true));
    void useAuthStore.persist.rehydrate();
    const timer = window.setTimeout(() => setReady(true), 400);
    return () => {
      unsub();
      window.clearTimeout(timer);
    };
  }, []);

  return ready;
}
