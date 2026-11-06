/** 看板图表统一主题：调色板、坐标轴、数值格式化。颜色全部走 CSS 变量，随明暗主题自动切换。 */

/** 8 色序列：在深色/浅色背景上都有足够对比度 */
export const CHART_PALETTE = [
  "#3b82f6",
  "#14b8a6",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#84cc16",
  "#ec4899",
];

export const GRID_COLOR = "var(--border)";
export const TEXT_COLOR = "var(--muted)";

/** 坐标轴刻度样式 */
export const AXIS_TICK = { fill: "var(--muted)", fontSize: 10 } as const;

/** 稳定散列：同一标题始终拿到同一强调色 */
export function accentOf(key: string): string {
  let hash = 5381;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 33 + key.charCodeAt(i)) % 100000007;
  }
  return CHART_PALETTE[hash % CHART_PALETTE.length];
}

export function numOf(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function isNumLike(value: unknown): boolean {
  return value !== null && value !== "" && Number.isFinite(Number(value));
}

/** 千分位 + 最多 2 位小数 */
export function fmtNumber(value: unknown, maxFractionDigits = 2): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isFinite(n)) {
    return n.toLocaleString("zh-CN", { maximumFractionDigits: maxFractionDigits });
  }
  return String(value);
}

/** 坐标轴紧凑格式：万 / 亿 */
export function compactNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 100000000) return `${(value / 100000000).toFixed(1)}亿`;
  if (abs >= 10000) return `${(value / 10000).toFixed(1)}万`;
  if (abs >= 1000) return value.toFixed(0);
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** X 轴标签裁剪：长日期只保留后半段 */
export function axisLabel(value: unknown): string {
  const text = String(value ?? "");
  return text.length > 10 ? text.slice(5) : text;
}
