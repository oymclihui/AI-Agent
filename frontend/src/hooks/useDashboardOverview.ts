"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { dashboardApi } from "@/lib/api";
import type { DashboardOverview } from "@/lib/dashboardTypes";

export function useDashboardOverview(pollIntervalMs = 30000) {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState<"sse" | "poll">("poll");
  const esRef = useRef<EventSource | null>(null);

  // 返回 false 表示 403 无权限：不视为错误，调用方应停止轮询且不再建立 SSE
  const fetchOnce = useCallback(async (): Promise<boolean> => {
    try {
      const { data: payload } = await dashboardApi.overview();
      setData(payload);
      setError(null);
      return true;
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        setError(null);
        return false;
      }
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
      return true;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let disposed = false;

    (async () => {
      const allowed = await fetchOnce();
      if (!allowed || disposed) return;

      const url = dashboardApi.streamUrl(Math.max(5, Math.round(pollIntervalMs / 1000)));
      es = new EventSource(url);
      esRef.current = es;

      es.onmessage = (event) => {
        try {
          setData(JSON.parse(event.data) as DashboardOverview);
          setLoading(false);
          setError(null);
          setLiveMode("sse");
        } catch {
          /* ignore parse errors */
        }
      };

      es.onerror = () => {
        setLiveMode("poll");
        es?.close();
        esRef.current = null;
      };

      timer = setInterval(async () => {
        const ok = await fetchOnce();
        if (!ok && timer) {
          clearInterval(timer);
          timer = null;
          es?.close();
          esRef.current = null;
        }
      }, pollIntervalMs);
    })();

    return () => {
      disposed = true;
      es?.close();
      if (timer) clearInterval(timer);
    };
  }, [fetchOnce, pollIntervalMs]);

  return { data, loading, error, liveMode, refresh: fetchOnce };
}
