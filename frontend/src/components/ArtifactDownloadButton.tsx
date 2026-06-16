"use client";

import { downloadArtifact, formatsForFilename, type RunArtifact } from "@/lib/artifacts";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { DownloadFormatMenu, formatLabel, type DownloadFormat } from "@/components/DownloadFormatMenu";

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
  const lang = useLangStore((s) => s.lang);
  const formats = formatsForFilename(artifact.filename);
  const e = translations.employees;

  const defaultLabel = (() => {
    const lower = artifact.filename.toLowerCase();
    if (lower.endsWith(".pptx")) return e.downloadPptx[lang];
    if (lower.endsWith(".md")) return e.downloadMd[lang];
    return e.downloadFile[lang];
  })();

  return (
    <DownloadFormatMenu
      lang={lang}
      formats={formats}
      label={label ?? (formats.length === 1 ? defaultLabel : `${translations.downloadAs[lang]} · ${artifact.filename}`)}
      variant={variant}
      className={className}
      onDownload={async (fmt) => {
        try {
          await downloadArtifact(artifact.download_url, artifact.filename, fmt);
        } catch {
          window.open(
            fmt === formats[0] ? artifact.download_url : `${artifact.download_url}?format=${fmt}`,
            "_blank",
            "noopener,noreferrer",
          );
        }
      }}
    />
  );
}

export { formatLabel, type DownloadFormat };
