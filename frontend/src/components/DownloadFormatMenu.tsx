"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Download, Loader2 } from "lucide-react";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";

export type DownloadFormat = "md" | "docx" | "xlsx" | "pptx";

export function formatsForFilename(filename: string): DownloadFormat[] {
  const ext = filename.split(".").pop()?.toLowerCase();
  if (ext === "pptx") return ["pptx"];
  if (ext === "xlsx") return ["xlsx"];
  if (ext === "docx") return ["docx"];
  return ["md", "docx", "xlsx", "pptx"];
}

export function formatLabel(fmt: DownloadFormat, lang: Lang): string {
  return translations.downloadFormats[fmt][lang];
}

type Props = {
  lang: Lang;
  formats: DownloadFormat[];
  onDownload: (format: DownloadFormat) => Promise<void>;
  label?: string;
  variant?: "primary" | "compact" | "secondary";
  className?: string;
};

export function DownloadFormatMenu({
  lang,
  formats,
  onDownload,
  label,
  variant = "compact",
  className = "",
}: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState<DownloadFormat | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const handlePick = async (fmt: DownloadFormat) => {
    setOpen(false);
    setLoading(fmt);
    try {
      await onDownload(fmt);
    } finally {
      setLoading(null);
    }
  };

  const base =
    variant === "primary"
      ? "inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-teal-900/30 hover:bg-teal-500 disabled:opacity-50"
      : variant === "secondary"
        ? "inline-flex items-center gap-1 rounded-lg bg-slate-700 px-4 py-2 text-sm text-white hover:bg-slate-600 disabled:opacity-50"
        : "inline-flex items-center gap-1.5 rounded-lg bg-slate-600/20 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-600/30 disabled:opacity-50";

  if (formats.length === 1) {
    const fmt = formats[0];
    return (
      <button
        type="button"
        onClick={() => handlePick(fmt)}
        disabled={loading !== null}
        className={`${base} ${className}`}
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
        {label ?? formatLabel(fmt, lang)}
      </button>
    );
  }

  return (
    <div ref={ref} className={`relative inline-block ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={loading !== null}
        className={base}
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
        {label ?? translations.downloadAs[lang]}
        <ChevronDown className="h-3.5 w-3.5 opacity-70" />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 min-w-[9rem] rounded-lg border border-[#2d2d4e] bg-[#1a1a2e] py-1 shadow-xl">
          {formats.map((fmt) => (
            <button
              key={fmt}
              type="button"
              onClick={() => handlePick(fmt)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-200 hover:bg-[#2d2d4e]"
            >
              <Download className="h-3.5 w-3.5 text-teal-400" />
              {formatLabel(fmt, lang)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
