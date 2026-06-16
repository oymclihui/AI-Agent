export interface RunArtifact {
  filename: string;
  download_url: string;
  mime_type?: string;
}

export type DownloadFormat = "md" | "docx" | "xlsx" | "pptx";

export function formatsForFilename(filename: string): DownloadFormat[] {
  const ext = filename.split(".").pop()?.toLowerCase();
  if (ext === "pptx") return ["pptx"];
  if (ext === "xlsx") return ["xlsx"];
  if (ext === "docx") return ["docx"];
  return ["md", "docx", "xlsx", "pptx"];
}

export function artifactDownloadUrl(baseUrl: string, format?: DownloadFormat): string {
  if (!format) return baseUrl;
  const sep = baseUrl.includes("?") ? "&" : "?";
  return `${baseUrl}${sep}format=${format}`;
}

export function runReportFilename(base: string, format: DownloadFormat): string {
  const stem = base.replace(/\.[^.]+$/, "") || "report";
  return `${stem}.${format}`;
}

const ARTIFACT_URL_RE = /\/api\/v1\/artifacts\/([A-Za-z0-9._-]+)/g;

/** Merge structured artifacts with URLs parsed from agent output text. */
export function resolveRunArtifacts(
  outputData?: { output?: string; artifacts?: RunArtifact[] } | null,
): RunArtifact[] {
  const fromMeta = outputData?.artifacts ?? [];
  const seen = new Set(fromMeta.map((a) => a.download_url));
  const merged = [...fromMeta];

  const text = outputData?.output ?? "";
  let match: RegExpExecArray | null;
  ARTIFACT_URL_RE.lastIndex = 0;
  while ((match = ARTIFACT_URL_RE.exec(text)) !== null) {
    const filename = match[1];
    const download_url = `/api/v1/artifacts/${filename}`;
    if (seen.has(download_url)) continue;
    seen.add(download_url);
    merged.push({ filename, download_url });
  }
  return merged;
}

export async function downloadArtifact(
  url: string,
  filename: string,
  format?: DownloadFormat,
): Promise<void> {
  const targetUrl = artifactDownloadUrl(url, format);
  const res = await fetch(targetUrl, { credentials: "same-origin" });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  const outName = format ? runReportFilename(filename, format) : filename;
  await saveBlobResponse(res, outName);
}

export async function downloadAuthed(url: string, filename: string, token?: string | null): Promise<void> {
  const headers: HeadersInit = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { credentials: "same-origin", headers });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  await saveBlobResponse(res, filename);
}

async function saveBlobResponse(res: Response, filename: string): Promise<void> {
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}
