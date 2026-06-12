/**
 * Inspiration page document schema (JSON → HTML).
 * Lightweight block tree inspired by AppFlowy / low-code page JSON;
 * no external engine dependency — renders to standalone inline HTML for card previews.
 */

export type InspBlockType =
  | "root"
  | "section"
  | "heading"
  | "text"
  | "list"
  | "grid"
  | "cell"
  | "kpi"
  | "chart-bar"
  | "badge"
  | "code"
  | "divider";

export interface InspBlockStyle {
  background?: string;
  color?: string;
  padding?: string;
  borderRadius?: string;
  fontSize?: string;
  fontWeight?: string | number;
  textAlign?: "left" | "center" | "right";
  gradient?: string;
  border?: string;
  minHeight?: string;
  height?: string;
  lineHeight?: string | number;
  fontFamily?: string;
  display?: "flex" | "grid" | "block" | "inline-block";
  flexDirection?: "row" | "column";
  alignItems?: string;
  justifyContent?: string;
  gridTemplateColumns?: string;
  gap?: string;
  flex?: string | number;
  margin?: string;
  marginTop?: string;
  marginBottom?: string;
  paddingLeft?: string;
  overflow?: string;
  boxShadow?: string;
}

export interface InspBlock {
  id: string;
  type: InspBlockType;
  content?: string;
  items?: string[];
  children?: InspBlock[];
  style?: InspBlockStyle;
  props?: Record<string, string | number | boolean>;
}

export interface InspirationDocument {
  version: 1;
  /** Output artifact type when user clones / exports */
  format: "html" | "markdown";
  theme?: { mode?: "light" | "dark"; accent?: string };
  root: InspBlock;
}

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function styleToCss(style?: InspBlockStyle): string {
  if (!style) return "";
  const parts: string[] = [];
  if (style.gradient) parts.push(`background:${style.gradient}`);
  else if (style.background) parts.push(`background:${style.background}`);
  if (style.color) parts.push(`color:${style.color}`);
  if (style.padding) parts.push(`padding:${style.padding}`);
  if (style.borderRadius) parts.push(`border-radius:${style.borderRadius}`);
  if (style.fontSize) parts.push(`font-size:${style.fontSize}`);
  if (style.fontWeight) parts.push(`font-weight:${style.fontWeight}`);
  if (style.textAlign) parts.push(`text-align:${style.textAlign}`);
  if (style.border) parts.push(`border:${style.border}`);
  if (style.minHeight) parts.push(`min-height:${style.minHeight}`);
  if (style.height) parts.push(`height:${style.height}`);
  if (style.lineHeight) parts.push(`line-height:${style.lineHeight}`);
  if (style.fontFamily) parts.push(`font-family:${style.fontFamily}`);
  if (style.display) parts.push(`display:${style.display}`);
  if (style.flexDirection) parts.push(`flex-direction:${style.flexDirection}`);
  if (style.alignItems) parts.push(`align-items:${style.alignItems}`);
  if (style.justifyContent) parts.push(`justify-content:${style.justifyContent}`);
  if (style.gridTemplateColumns) parts.push(`grid-template-columns:${style.gridTemplateColumns}`);
  if (style.gap) parts.push(`gap:${style.gap}`);
  if (style.flex) parts.push(`flex:${style.flex}`);
  if (style.margin) parts.push(`margin:${style.margin}`);
  if (style.marginTop) parts.push(`margin-top:${style.marginTop}`);
  if (style.marginBottom) parts.push(`margin-bottom:${style.marginBottom}`);
  if (style.paddingLeft) parts.push(`padding-left:${style.paddingLeft}`);
  if (style.overflow) parts.push(`overflow:${style.overflow}`);
  if (style.boxShadow) parts.push(`box-shadow:${style.boxShadow}`);
  return parts.join(";");
}

function renderBlock(block: InspBlock): string {
  const css = styleToCss(block.style);
  const styleAttr = css ? ` style="${css}"` : "";

  switch (block.type) {
    case "root":
    case "section":
      return (block.children ?? []).map(renderBlock).join("");
    case "heading":
      return `<div${styleAttr}>${esc(block.content ?? "")}</div>`;
    case "text":
      return `<p${styleAttr}>${esc(block.content ?? "")}</p>`;
    case "badge":
      return `<span${styleAttr}>${esc(block.content ?? "")}</span>`;
    case "code":
      return `<div${styleAttr}>${esc(block.content ?? "")}</div>`;
    case "divider":
      return `<div${styleAttr}></div>`;
    case "list": {
      const items = (block.items ?? []).map((i) => `<li>${esc(i)}</li>`).join("");
      return `<ul${styleAttr}>${items}</ul>`;
    }
    case "grid":
      return `<div${styleAttr}>${(block.children ?? []).map(renderBlock).join("")}</div>`;
    case "cell": {
      const inner = (block.children ?? []).map(renderBlock).join("");
      const text = block.content ? esc(block.content) : "";
      return `<div${styleAttr}>${text}${inner}</div>`;
    }
    case "kpi":
      return `<div${styleAttr}><div style="font-size:10px;opacity:0.72;font-weight:600;letter-spacing:0.04em">${esc(String(block.props?.label ?? ""))}</div><div style="font-weight:800;font-size:20px;margin-top:6px;letter-spacing:-0.03em;line-height:1.1">${esc(block.content ?? "")}</div></div>`;
    case "chart-bar": {
      const pct = Number(block.props?.percent ?? 70);
      return `<div${styleAttr}><div style="height:100%;width:${pct}%;background:${block.props?.barColor ?? "linear-gradient(90deg,#3b82f6,#06b6d4)"};border-radius:4px"></div></div>`;
    }
    default:
      return "";
  }
}

/** Compile JSON document → inline HTML snippet for card preview or export */
export function renderDocumentToHtml(doc: InspirationDocument): string {
  return renderBlock(doc.root);
}

/** Parse user JSON; returns null if invalid */
export function parseInspirationDocument(raw: string): InspirationDocument | null {
  try {
    const parsed = JSON.parse(raw) as InspirationDocument;
    if (parsed?.version !== 1 || !parsed.root?.type) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function documentToJson(doc: InspirationDocument, pretty = true): string {
  return JSON.stringify(doc, null, pretty ? 2 : 0);
}

/** Wrap rendered HTML as a full exportable document */
export function exportFullHtml(doc: InspirationDocument, title: string): string {
  const body = renderDocumentToHtml(doc);
  const isDark = doc.theme?.mode === "dark";
  return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>${esc(title)}</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, sans-serif; background: ${isDark ? "#0f172a" : "#f8fafc"}; }
  </style>
</head>
<body>${body}</body>
</html>`;
}

/** Preview: structured JSON first, else legacy HTML string */
export function resolvePreviewHtml(
  document: InspirationDocument | undefined,
  fallbackHtml: string,
): string {
  if (document?.root) return renderDocumentToHtml(document);
  return fallbackHtml;
}

export function getItemPreviewHtml(
  item: { document?: Partial<Record<"zh" | "en", InspirationDocument>>; previewHtml: Record<"zh" | "en", string> },
  lang: "zh" | "en",
): string {
  return resolvePreviewHtml(item.document?.[lang], item.previewHtml[lang]);
}
