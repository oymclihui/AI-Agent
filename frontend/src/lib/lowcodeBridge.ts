/** PostMessage bridge between Next.js inspiration page and LowcodeEngine iframe */

export const LOWCODE_DESIGNER_STATIC = "/lowcode/designer/index.html";

export const INSPIRE_LCE_MSG = {
  READY: 'INSPIRE_LCE_READY',
  REQUEST_INIT: 'INSPIRE_LCE_REQUEST_INIT',
  INIT: 'INSPIRE_LCE_INIT',
  SAVE: 'INSPIRE_LCE_SAVE',
  SAVED_ACK: 'INSPIRE_LCE_SAVED_ACK',
} as const;

export interface LowcodeInspirationPayload {
  projectSchema?: Record<string, unknown>;
  pageSchema?: Record<string, unknown>;
}

export function designerUrl(inspireId: string, lang: string): string {
  const base =
    process.env.NEXT_PUBLIC_LOWCODE_DESIGNER_URL ?? LOWCODE_DESIGNER_STATIC;
  const params = new URLSearchParams({ inspireId, lang });
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}${params.toString()}`;
}

/** True when using a dev server URL (always attempt load). */
export function isLowcodeDevMode(): boolean {
  const url = process.env.NEXT_PUBLIC_LOWCODE_DESIGNER_URL;
  return !!url && !url.startsWith("/");
}

/** Probe whether the static lowcode bundle exists (client-side). */
export async function probeLowcodeDesigner(): Promise<boolean> {
  if (isLowcodeDevMode()) return true;
  try {
    const res = await fetch(LOWCODE_DESIGNER_STATIC, { method: "HEAD", cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export function isLowcodeMessage(data: unknown): data is { type: string; inspireId?: string } {
  return !!data && typeof data === 'object' && 'type' in data;
}

export interface LowcodeSaveMessage {
  type: typeof INSPIRE_LCE_MSG.SAVE;
  inspireId: string;
  projectSchema?: Record<string, unknown>;
  pageSchema?: Record<string, unknown>;
}

export function isLowcodeSaveMessage(data: unknown): data is LowcodeSaveMessage {
  return (
    isLowcodeMessage(data) &&
    data.type === INSPIRE_LCE_MSG.SAVE &&
    typeof data.inspireId === 'string'
  );
}
