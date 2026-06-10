"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { downloadArtifact, type RunArtifact } from "@/lib/artifacts";

type Props = {
  artifact: RunArtifact;
  label?: string;
  variant?: "primary" | "compact";
  className?: string;
};

export function ArtifactDownloadButton({
  artifact,
  label,
  variant = "primary",
  className = "",
}: Props) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      await downloadArtifact(artifact.download_url, artifact.filename);
    } catch {
      window.open(artifact.download_url, "_blank", "noopener,noreferrer");
    } finally {
      setLoading(false);
    }
  };

  const text = label ?? artifact.filename;

  if (variant === "compact") {
    return (
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className={`inline-flex items-center gap-1.5 rounded-lg bg-teal-600/20 px-3 py-1.5 text-xs text-teal-300 hover:bg-teal-600/30 disabled:opacity-50 ${className}`}
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
        {text}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className={`inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-teal-900/30 hover:bg-teal-500 disabled:opacity-50 ${className}`}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
      {text}
    </button>
  );
}
