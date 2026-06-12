import type { InspirationCategory, InspirationItem } from "@/lib/inspirationCatalog";
import { INSPIRATION_ITEMS } from "@/lib/inspirationCatalog";
import type { InspirationDocument } from "@/lib/inspirationDocument";
import { getItemPreviewHtml, renderDocumentToHtml } from "@/lib/inspirationDocument";
import type { LowcodeInspirationPayload } from "@/lib/lowcodeBridge";

const STORAGE_KEY = "aiagnet_inspiration_overrides";
const FAVORITES_KEY = "aiagnet_inspiration_favorites";
const CUSTOM_KEY = "aiagnet_inspiration_custom";

type Lang = "zh" | "en";

export type InspirationOverrides = Record<
  string,
  {
    document?: Partial<Record<Lang, InspirationDocument>>;
    previewHtml?: Partial<Record<Lang, string>>;
    prompt?: Partial<Record<Lang, string>>;
    lowcode?: Partial<Record<Lang, LowcodeInspirationPayload>>;
  }
>;

function readOverrides(): InspirationOverrides {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as InspirationOverrides) : {};
  } catch {
    return {};
  }
}

function writeOverrides(data: InspirationOverrides) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function readCustomRaw(): InspirationItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(CUSTOM_KEY);
    return raw ? (JSON.parse(raw) as InspirationItem[]) : [];
  } catch {
    return [];
  }
}

function writeCustomRaw(items: InspirationItem[]) {
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(items));
}

export function blankInspirationDocument(format: "html" | "markdown" = "html"): InspirationDocument {
  return {
    version: 1,
    format,
    theme: { mode: "light", accent: "#3b82f6" },
    root: {
      id: "root",
      type: "root",
      children: [
        {
          id: "wrap",
          type: "section",
          style: {
            fontFamily: "system-ui,sans-serif",
            padding: "14px",
            gradient: "linear-gradient(135deg,#eff6ff,#f5f3ff)",
            borderRadius: "10px",
            fontSize: "11px",
            color: "#334155",
            minHeight: "120px",
            border: "1px solid #e2e8f0",
          },
          children: [
            {
              id: "h",
              type: "heading",
              content: "✨ 我的灵感模板",
              style: { fontWeight: 700, fontSize: "12px", marginBottom: "6px", color: "#2563eb" },
            },
            {
              id: "t",
              type: "text",
              content: "在此编辑 JSON 或 HTML，或点击「做同款」让 AI 生成完整页面",
              style: { fontSize: "10px", color: "#64748b" },
            },
          ],
        },
      ],
    },
  };
}

export function createCustomInspiration(input: {
  title: string;
  subtitle?: string;
  category: InspirationCategory;
  format?: "html" | "markdown";
  prompt: string;
  tone?: InspirationItem["tone"];
  scene?: InspirationItem["scene"];
  agentHint?: string;
}): InspirationItem {
  const format = input.format ?? "html";
  const doc = blankInspirationDocument(format);
  const html = renderDocumentToHtml(doc);
  const title = input.title.trim() || "未命名灵感";
  const subtitle = input.subtitle?.trim() || title;

  const item: InspirationItem = {
    id: `custom-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    custom: true,
    category: input.category === "all" ? "office" : input.category,
    format,
    tone: input.tone ?? "blue",
    title: { zh: title, en: title },
    subtitle: { zh: subtitle, en: subtitle },
    scene: input.scene,
    agentHint: input.agentHint,
    document: { zh: doc, en: doc },
    previewHtml: { zh: html, en: html },
    prompt: { zh: input.prompt.trim(), en: input.prompt.trim() },
  };

  const all = readCustomRaw();
  all.unshift(item);
  writeCustomRaw(all);
  return item;
}

export function updateCustomInspiration(id: string, patch: Partial<InspirationItem>): InspirationItem | undefined {
  const all = readCustomRaw();
  const idx = all.findIndex((i) => i.id === id);
  if (idx === -1) return undefined;
  all[idx] = { ...all[idx], ...patch };
  writeCustomRaw(all);
  return all[idx];
}

export function deleteCustomInspiration(id: string): boolean {
  const all = readCustomRaw();
  const next = all.filter((i) => i.id !== id);
  if (next.length === all.length) return false;
  writeCustomRaw(next);
  resetInspirationOverride(id);
  const fav = readFavoriteIds();
  if (fav.has(id)) {
    fav.delete(id);
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...fav]));
  }
  return true;
}

export function mergeInspiration(item: InspirationItem): InspirationItem {
  const overrides = readOverrides()[item.id];
  if (!overrides) {
    return {
      ...item,
      previewHtml: {
        zh: getItemPreviewHtml(item, "zh"),
        en: getItemPreviewHtml(item, "en"),
      },
    };
  }

  const document = {
    zh: overrides.document?.zh ?? item.document?.zh,
    en: overrides.document?.en ?? item.document?.en,
  };

  const lowcode = {
    zh: overrides.lowcode?.zh ?? item.lowcode?.zh,
    en: overrides.lowcode?.en ?? item.lowcode?.en,
  };

  const merged: InspirationItem = {
    ...item,
    document: document.zh || document.en ? document : item.document,
    lowcode: lowcode.zh || lowcode.en ? lowcode : item.lowcode,
    prompt: { ...item.prompt, ...overrides.prompt },
  };

  merged.previewHtml = {
    zh: overrides.previewHtml?.zh
      ?? (merged.document?.zh ? renderDocumentToHtml(merged.document.zh) : getItemPreviewHtml(item, "zh")),
    en: overrides.previewHtml?.en
      ?? (merged.document?.en ? renderDocumentToHtml(merged.document.en) : getItemPreviewHtml(item, "en")),
  };

  return merged;
}

export function listInspirationsMerged(): InspirationItem[] {
  const custom = readCustomRaw().map(mergeInspiration);
  const official = INSPIRATION_ITEMS.map(mergeInspiration);
  return [...custom, ...official];
}

export function getInspirationMerged(id: string): InspirationItem | undefined {
  return listInspirationsMerged().find((i) => i.id === id);
}

export function saveInspirationOverride(
  id: string,
  lang: Lang,
  data: {
    document?: InspirationDocument;
    previewHtml?: string;
    prompt?: string;
    lowcode?: LowcodeInspirationPayload;
  },
) {
  const custom = readCustomRaw().find((i) => i.id === id);
  if (custom) {
    const doc = data.document ?? custom.document?.[lang];
    const html = data.previewHtml ?? (doc ? renderDocumentToHtml(doc) : custom.previewHtml[lang]);
    updateCustomInspiration(id, {
      document: doc
        ? { ...custom.document, [lang]: doc }
        : custom.document,
      previewHtml: { ...custom.previewHtml, [lang]: html },
      prompt: data.prompt !== undefined
        ? { ...custom.prompt, [lang]: data.prompt }
        : custom.prompt,
      lowcode: data.lowcode !== undefined
        ? { ...custom.lowcode, [lang]: data.lowcode }
        : custom.lowcode,
    });
    return;
  }

  const all = readOverrides();
  const prev = all[id] || {};
  all[id] = {
    document: data.document !== undefined
      ? { ...prev.document, [lang]: data.document }
      : prev.document,
    previewHtml: data.previewHtml !== undefined
      ? { ...prev.previewHtml, [lang]: data.previewHtml }
      : prev.previewHtml,
    prompt: data.prompt !== undefined
      ? { ...prev.prompt, [lang]: data.prompt }
      : prev.prompt,
    lowcode: data.lowcode !== undefined
      ? { ...prev.lowcode, [lang]: data.lowcode }
      : prev.lowcode,
  };
  writeOverrides(all);
}

export function resetInspirationOverride(id: string) {
  if (readCustomRaw().some((i) => i.id === id)) return;
  const all = readOverrides();
  delete all[id];
  writeOverrides(all);
}

export function readFavoriteIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function toggleFavorite(id: string): boolean {
  const set = readFavoriteIds();
  const wasFav = set.has(id);
  if (wasFav) set.delete(id);
  else set.add(id);
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...set]));
  return !wasFav;
}

export function getLowcodePayload(item: InspirationItem, lang: Lang): LowcodeInspirationPayload | undefined {
  return item.lowcode?.[lang];
}
