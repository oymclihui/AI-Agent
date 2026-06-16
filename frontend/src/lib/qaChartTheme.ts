"use client";

import { useEffect, useState } from "react";

export const QA_CHART_PALETTE = [
  "#3b82f6",
  "#22c55e",
  "#f59e0b",
  "#a855f7",
  "#ec4899",
  "#06b6d4",
] as const;

export interface QaChartThemeColors {
  heading: string;
  foreground: string;
  muted: string;
  border: string;
  surface: string;
  accent: string;
  tooltipBg: string;
  grid: string;
}

const FALLBACK_DARK: QaChartThemeColors = {
  heading: "#f1f5f9",
  foreground: "#e2e8f0",
  muted: "#94a3b8",
  border: "#2d2d4e",
  surface: "#1a1a2e",
  accent: "#3b82f6",
  tooltipBg: "#1a1a2e",
  grid: "#2d2d4e",
};

const FALLBACK_LIGHT: QaChartThemeColors = {
  heading: "#1e3a5f",
  foreground: "#334155",
  muted: "#5b7a9a",
  border: "#dbeafe",
  surface: "#f8fbff",
  accent: "#3b82f6",
  tooltipBg: "#ffffff",
  grid: "#e2e8f0",
};

function readTheme(): QaChartThemeColors {
  if (typeof document === "undefined") return FALLBACK_DARK;
  const root = document.documentElement;
  const isLight = root.getAttribute("data-theme") === "light";
  const fb = isLight ? FALLBACK_LIGHT : FALLBACK_DARK;
  const style = getComputedStyle(root);
  const pick = (varName: string, fallback: string) =>
    style.getPropertyValue(varName).trim() || fallback;
  return {
    heading: pick("--prose-heading", fb.heading),
    foreground: pick("--foreground", fb.foreground),
    muted: pick("--muted", fb.muted),
    border: pick("--border", fb.border),
    surface: pick("--surface", fb.surface),
    accent: pick("--primary", fb.accent),
    tooltipBg: pick("--surface-elevated", fb.tooltipBg),
    grid: pick("--border", fb.grid),
  };
}

export function useQaChartTheme(): QaChartThemeColors {
  const [theme, setTheme] = useState<QaChartThemeColors>(FALLBACK_DARK);

  useEffect(() => {
    const update = () => setTheme(readTheme());
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class"],
    });
    return () => observer.disconnect();
  }, []);

  return theme;
}

export function formatChartNum(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
