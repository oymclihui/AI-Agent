import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "react-hot-toast";
import AppShell from "@/components/layout/AppShell";

export const metadata: Metadata = {
  title: "AI-AGENT - AI Agent Network Platform",
  description: "Unified AI agent platform with multi-agent orchestration, visual workflow designer, and RAG knowledge base.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden bg-[#0d0d1a]">
        <AppShell>{children}</AppShell>
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: "#1a1a2e",
              color: "#e2e8f0",
              border: "1px solid #2d2d4e",
            },
          }}
        />
      </body>
    </html>
  );
}
