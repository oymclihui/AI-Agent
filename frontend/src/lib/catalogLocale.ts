import type { Lang } from "./i18n";

export type LocalizedText = string | { zh: string; en: string };

export function pickText(value: LocalizedText | undefined, lang: Lang, fallback = ""): string {
  if (!value) return fallback;
  if (typeof value === "string") return value;
  return value[lang] || value.en || value.zh || fallback;
}

export interface RawCatalogNode {
  id: string;
  type: string;
  category: string;
  name: LocalizedText;
  description: LocalizedText;
  icon: string;
  color: string;
  properties: Array<Record<string, unknown>>;
}

export interface RawCatalogCategory {
  id: string;
  name: LocalizedText;
  color: string;
}

export function localizeCatalogNode(node: RawCatalogNode, lang: Lang) {
  return {
    ...node,
    name: pickText(node.name, lang),
    description: pickText(node.description, lang),
    properties: node.properties.map((p) => ({
      ...p,
      displayName: pickText(p.displayName as LocalizedText, lang, String(p.name || "")),
      description: p.description ? pickText(p.description as LocalizedText, lang) : undefined,
      placeholder: p.placeholder ? pickText(p.placeholder as LocalizedText, lang) : undefined,
      options: Array.isArray(p.options)
        ? (p.options as Array<{ name: LocalizedText; value: string }>).map((o) => ({
            name: pickText(o.name, lang, o.value),
            value: o.value,
          }))
        : undefined,
    })),
  };
}

export function localizeCatalogCategory(cat: RawCatalogCategory, lang: Lang) {
  return { ...cat, name: pickText(cat.name, lang) };
}

export function localizeCatalog(
  data: { nodes: RawCatalogNode[]; categories: RawCatalogCategory[] },
  lang: Lang,
) {
  return {
    nodes: data.nodes.map((n) => localizeCatalogNode(n, lang)),
    categories: data.categories.map((c) => localizeCatalogCategory(c, lang)),
    total: data.nodes.length,
  };
}

/** Map legacy designer / engine types to n8n catalog node ids */
export const LEGACY_CATALOG_ID: Record<string, string> = {
  agentNode: "aiAgent",
  llmNode: "llmChain",
  toolNode: "toolCall",
  conditionNode: "if",
  humanNode: "humanInTheLoop",
  httpNode: "httpRequest",
  codeNode: "code",
  startNode: "start",
  endNode: "end",
  noteNode: "stickyNote",
  agent: "aiAgent",
  llm: "llmChain",
  tool: "toolCall",
  condition: "if",
  human: "humanInTheLoop",
  http: "httpRequest",
  note: "stickyNote",
  trigger: "manualTrigger",
  switch: "switch",
  set: "set",
  merge: "merge",
  split: "splitInBatches",
  filter: "filter",
  wait: "wait",
  transform: "json",
  integration: "slack",
  subworkflow: "executeWorkflow",
};

export interface ResolvedCatalogNode {
  id: string;
  type: string;
  category: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  properties: Array<Record<string, unknown>>;
}

export function resolveCatalogNode(
  catalogId: string,
  execType: string,
  label: string,
  icon: string,
  color: string,
  localizedCatalog: ResolvedCatalogNode[],
  rawCatalog: RawCatalogNode[],
  lang: Lang,
): ResolvedCatalogNode {
  const candidates = [
    catalogId,
    LEGACY_CATALOG_ID[catalogId],
    execType,
    LEGACY_CATALOG_ID[execType],
  ].filter(Boolean);

  for (const id of candidates) {
    const hit = localizedCatalog.find((c) => c.id === id);
    if (hit) return hit;
  }

  const byType = localizedCatalog.find((c) => c.type === execType);
  if (byType) return byType;

  for (const id of candidates) {
    const raw = rawCatalog.find((c) => c.id === id);
    if (raw) return localizeCatalogNode(raw, lang) as ResolvedCatalogNode;
  }

  const rawByType = rawCatalog.find((c) => c.type === execType);
  if (rawByType) return localizeCatalogNode(rawByType, lang) as ResolvedCatalogNode;

  return {
    id: catalogId || execType || "unknown",
    type: execType || "note",
    category: "core",
    name: label || catalogId || execType,
    description: "",
    icon: icon || "box",
    color: color || "#6366f1",
    properties: [],
  };
}

export function normalizeGraphCatalogId(catalogId: string | undefined, graphType: string): string {
  if (catalogId) {
    if (LEGACY_CATALOG_ID[catalogId]) return LEGACY_CATALOG_ID[catalogId];
    return catalogId;
  }
  if (LEGACY_CATALOG_ID[graphType]) return LEGACY_CATALOG_ID[graphType];
  const bare = graphType.replace(/Node$/, "");
  if (LEGACY_CATALOG_ID[bare]) return LEGACY_CATALOG_ID[bare];
  return bare;
}
