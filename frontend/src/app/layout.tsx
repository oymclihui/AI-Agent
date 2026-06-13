import type { Metadata, Viewport } from "next";
import "./globals.css";
import AppShell from "@/components/layout/AppShell";
import ThemeProvider from "@/components/ThemeProvider";
import ThemedToaster from "@/components/ThemedToaster";

export const metadata: Metadata = {
  title: "AI-AGENT - AI Agent Network Platform",
  description: "Unified AI agent platform with multi-agent orchestration, visual workflow designer, and RAG knowledge base.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning data-theme="dark">
      <body className="flex h-screen overflow-hidden theme-bg theme-text">
        <ThemeProvider>
          <AppShell>{children}</AppShell>
          <ThemedToaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
