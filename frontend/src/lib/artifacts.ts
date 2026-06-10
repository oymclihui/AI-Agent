export interface RunArtifact {
  filename: string;
  download_url: string;
  mime_type?: string;
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

export async function downloadArtifact(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  await saveBlobResponse(res, filename);
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
