"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { clsx } from "clsx";
import toast from "react-hot-toast";
import type { Lang } from "@/lib/i18n";
import { translations } from "@/lib/i18n";

async function copyText(text: string): Promise<boolean> {
  if (!text.trim()) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

type Props = {
  text: string;
  lang: Lang;
  variant?: "user" | "assistant";
  className?: string;
};

export function MessageCopyButton({ text, lang, variant = "assistant", className }: Props) {
  const [copied, setCopied] = useState(false);
  const t = translations.chat;

  const handleCopy = async () => {
    const ok = await copyText(text);
    if (ok) {
      setCopied(true);
      toast.success(t.copyOk[lang]);
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error(t.copyFailed[lang]);
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={t.copyMessage[lang]}
      aria-label={t.copyMessage[lang]}
      className={clsx(
        "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition",
        "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
        "max-md:opacity-60",
        variant === "user"
          ? "text-blue-100 hover:bg-blue-500/40"
          : "text-slate-400 hover:bg-slate-700/60 hover:text-slate-200",
        className,
      )}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}
