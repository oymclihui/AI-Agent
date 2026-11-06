"use client";

import { useEffect } from "react";
import { downloadArtifact } from "@/lib/artifacts";
import type { Lang } from "@/lib/i18n";
import { openArtifact, registerArtifact } from "@/lib/artifactResultStore";

type Props = {
  filename: string;
  previewUrl: string;
  lang: Lang;
};

export default function HtmlPreviewCard({ filename, previewUrl, lang }: Props) {
  const zh = lang !== "en";
  const preview = previewUrl.split("?")[0];

  useEffect(() => registerArtifact({ filename, previewUrl: preview }), [filename, preview]);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => openArtifact(filename)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openArtifact(filename);
        }
      }}
      className="theme-card my-2 flex w-full cursor-pointer items-center gap-3 px-3 py-2 text-left hover:border-blue-400"
    >
      <span className="shrink-0 rounded bg-blue-600/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
        {zh ? "网页" : "Web"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="theme-text block truncate text-sm">{filename}</span>
        <span className="theme-muted text-[11px]">{zh ? "在右侧结果区预览" : "Open in the result panel"}</span>
      </span>
      <button
        type="button"
        className="theme-muted shrink-0 rounded px-2 py-1 text-xs hover:bg-[var(--hover)]"
        onClick={(event) => {
          event.stopPropagation();
          downloadArtifact(`${preview}?download=1`, filename).catch(() => {
            window.open(`${preview}?download=1`, "_blank", "noopener,noreferrer");
          });
        }}
      >
        {zh ? "下载" : "Download"}
      </button>
    </div>
  );
}
