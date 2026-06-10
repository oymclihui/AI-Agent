"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/lib/themeStore";

function applyTheme(theme: "dark" | "light") {
  document.documentElement.setAttribute("data-theme", theme);
}

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    applyTheme(useThemeStore.getState().theme);
    return useThemeStore.persist.onFinishHydration(() => {
      applyTheme(useThemeStore.getState().theme);
    });
  }, []);

  return <>{children}</>;
}
