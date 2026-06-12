"use client";

import { useEffect, useState } from "react";
import { readStoredAuth, useAuthStore } from "@/lib/authStore";

/**
 * Client auth bootstrap: read token from zustand or localStorage without blocking on persist.
 * Returns { ready, token } — ready=true after first client effect (≤1 frame).
 */
export function useClientAuth(): { ready: boolean; token: string | null } {
  const storeToken = useAuthStore((s) => s.token);
  const [ready, setReady] = useState(false);
  const [lsToken, setLsToken] = useState<string | null>(null);

  useEffect(() => {
    void useAuthStore.persist.rehydrate();
    setLsToken(readStoredAuth().token);
    setReady(true);
  }, []);

  useEffect(() => {
    if (storeToken) setLsToken(storeToken);
  }, [storeToken]);

  return { ready, token: storeToken ?? lsToken };
}
