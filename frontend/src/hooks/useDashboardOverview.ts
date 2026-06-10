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

  const fetchOnce = useCallback(async () => {
    try {
      const { data: payload } = await dashboardApi.overview();
      setData(payload);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOnce();

    const url = dashboardApi.streamUrl(Math.max(5, Math.round(pollIntervalMs / 1000)));
    const es = new EventSource(url);
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
      es.close();
      esRef.current = null;
    };

    const timer = setInterval(fetchOnce, pollIntervalMs);

    return () => {
      es.close();
      clearInterval(timer);
    };
  }, [fetchOnce, pollIntervalMs]);

  return { data, loading, error, liveMode, refresh: fetchOnce };
}
