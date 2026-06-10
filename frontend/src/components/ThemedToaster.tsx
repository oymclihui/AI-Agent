"use client";

import { Toaster } from "react-hot-toast";
import { useThemeStore } from "@/lib/themeStore";

export default function ThemedToaster() {
  const theme = useThemeStore((s) => s.theme);
  const isLight = theme === "light";

  return (
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: isLight ? "#f8fbff" : "#1a1a2e",
          color: isLight ? "#1e3a5f" : "#e2e8f0",
          border: isLight ? "1px solid #dbeafe" : "1px solid #2d2d4e",
        },
      }}
    />
  );
}
