/**
 * data-qa-intent structured blocks embedded in assistant Markdown.
 * @see backend/app/core/skills/bundled/data-qa-intent.md
 */

export interface QaKpiTrend {
  value: number;
  direction: "up" | "down" | "flat";
  label?: string;
}

export interface QaKpiPayload {
  label: string;
  value: string | number;
  prefix?: string;
  suffix?: string;
  trend?: QaKpiTrend;
  sparkline?: number[];
}

export interface QaChartYKey {
  key: string;
  name?: string;
  color?: string;
}

export interface QaChartPayload {
  type: "line" | "area" | "bar" | "pie" | "stacked_bar";
  title?: string;
  data: Record<string, unknown>[];
  xKey?: string;
  yKeys?: QaChartYKey[];
}

export type QaSegment =
  | { kind: "text"; text: string }
  | { kind: "kpi"; data: QaKpiPayload }
  | { kind: "chart"; data: QaChartPayload }
  | { kind: "choices"; options: string[] }
  | { kind: "choices-multiple"; options: string[] }
  | { kind: "actions"; options: string[] }
  | { kind: "switch"; persona: string };

const BLOCK_TAGS = ["kpi", "chart", "choices-multiple", "choices", "actions", "switch"] as const;
type BlockTag = (typeof BLOCK_TAGS)[number];

function isBlockTag(tag: string): tag is BlockTag {
  return (BLOCK_TAGS as readonly string[]).includes(tag);
}

function parseJsonObject(raw: string, start: number): { json: string; end: number } | null {
  if (raw[start] !== "{") return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < raw.length; i++) {
    const ch = raw[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (inString) {
      if (ch === "\\") escape = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth++;
    if (ch === "}") {
      depth--;
      if (depth === 0) return { json: raw.slice(start, i + 1), end: i + 1 };
    }
  }
  return null;
}

function splitPipeOptions(payload: string): string[] {
  return payload
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);
}

function safeParseKpi(json: string): QaKpiPayload | null {
  try {
    const o = JSON.parse(json) as QaKpiPayload;
    if (!o?.label || o.value === undefined || o.value === null) return null;
    return o;
  } catch {
    return null;
  }
}

function safeParseChart(json: string): QaChartPayload | null {
  try {
    const o = JSON.parse(json) as QaChartPayload;
    if (!o?.data?.length) return null;
    if (!o.type) o.type = "bar";
    return o;
  } catch {
    return null;
  }
}

/** Split assistant content into markdown text + structured QA blocks. */
export function parseQaIntentContent(content: string): QaSegment[] {
  const segments: QaSegment[] = [];
  let i = 0;

  while (i < content.length) {
    const open = content.indexOf("[", i);
    if (open === -1) {
      const tail = content.slice(i);
      if (tail) segments.push({ kind: "text", text: tail });
      break;
    }
    if (open > i) {
      segments.push({ kind: "text", text: content.slice(i, open) });
    }

    const head = content.slice(open);
    const tagMatch = head.match(/^\[(kpi|chart|choices-multiple|choices|actions|switch):/);
    if (!tagMatch || !isBlockTag(tagMatch[1])) {
      segments.push({ kind: "text", text: content[open] });
      i = open + 1;
      continue;
    }

    const tag = tagMatch[1];
    const payloadStart = open + tagMatch[0].length;

    if (tag === "kpi" || tag === "chart") {
      const parsed = parseJsonObject(content, payloadStart);
      if (!parsed || content[payloadStart + parsed.end] !== "]") {
        segments.push({ kind: "text", text: content[open] });
        i = open + 1;
        continue;
      }
      const data =
        tag === "kpi"
          ? safeParseKpi(parsed.json)
          : safeParseChart(parsed.json);
      if (data) {
        if (tag === "kpi") {
          segments.push({ kind: "kpi", data: data as QaKpiPayload });
        } else {
          segments.push({ kind: "chart", data: data as QaChartPayload });
        }
        i = payloadStart + parsed.end + 1;
      } else {
        segments.push({ kind: "text", text: content.slice(open, payloadStart + parsed.end + 1) });
        i = payloadStart + parsed.end + 1;
      }
      continue;
    }

    const close = content.indexOf("]", payloadStart);
    if (close === -1) {
      segments.push({ kind: "text", text: content.slice(open) });
      break;
    }
    const payload = content.slice(payloadStart, close);
    const options = splitPipeOptions(payload);
    if (tag === "switch") {
      if (payload.trim()) segments.push({ kind: "switch", persona: payload.trim() });
    } else if (options.length) {
      segments.push({ kind: tag, options } as QaSegment);
    } else {
      segments.push({ kind: "text", text: content.slice(open, close + 1) });
    }
    i = close + 1;
  }

  return segments;
}

/** Hide trailing incomplete structured blocks while streaming. */
export function stripIncompleteQaBlocks(content: string): string {
  let cut = content.length;
  for (const tag of BLOCK_TAGS) {
    const idx = content.lastIndexOf(`[${tag}:`);
    if (idx === -1) continue;
    const tail = content.slice(idx);
    if (tag === "kpi" || tag === "chart") {
      const brace = tail.indexOf("{");
      if (brace === -1) {
        cut = Math.min(cut, idx);
        continue;
      }
      const parsed = parseJsonObject(tail, brace);
      if (!parsed || tail[parsed.end] !== "]") cut = Math.min(cut, idx);
    } else if (!tail.includes("]")) {
      cut = Math.min(cut, idx);
    }
  }
  return content.slice(0, cut);
}

export function hasQaIntentBlocks(content: string): boolean {
  return /\[(kpi|chart|choices-multiple|choices|actions|switch):/.test(content);
}
