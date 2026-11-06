// UiRender 组件类型定义（对标 intelligent-ui Catalog 精简版）
export type ComponentType =
  | "Card" | "Stack" | "Grid" | "Tabs" | "Text" | "Code"
  | "Alert" | "Badge" | "Divider" | "Stat" | "Progress"
  | "List" | "Table" | "Chart" | "Choice" | "Timeline" | "JsonView" | "Mermaid";

export interface UiNode {
  id: string;
  type: ComponentType;
  props?: Record<string, unknown>;
  children?: string[];
}

export interface UiRenderData {
  root: string;
  components: UiNode[];
  title?: string;
  /** 递增版本号，用于 ui_patch 的 baseVersion 并发保护 */
  version?: number;
}

export interface TableProps {
  columns?: string[];
  rows: unknown[][];
  columnTypes?: ("text" | "number" | "date" | "boolean")[];
  sortable?: boolean;
  exportable?: boolean;
  caption?: string;
}

export interface StatProps {
  label: string;
  value: string | number;
  delta?: string;
  trend?: "up" | "down" | "flat";
  unit?: string;
}

export interface ChoiceOption {
  id: string;
  label: string;
  description?: string;
  prompt?: string;
}

export interface ChoiceProps {
  question: string;
  options: ChoiceOption[];
  recommended?: string;
}

export type UiTone = "default" | "muted" | "info" | "success" | "warning" | "error";

export interface ChartSeries {
  name: string;
  values: number[];
}

export interface ChartProps {
  kind: "bar" | "line" | "area" | "pie";
  labels: (string | number)[];
  series: ChartSeries[];
  title?: string;
  unit?: string;
  stacked?: boolean;
  height?: number;
}

export interface ProgressProps {
  value: number;
  max?: number;
  label?: string;
  tone?: UiTone;
}

export interface TimelineItem {
  title: string;
  time?: string;
  text?: string;
  tone?: UiTone;
}

export interface TimelineProps {
  items: TimelineItem[];
}

export interface MermaidProps {
  code: string;
}

export interface JsonViewProps {
  data: unknown;
  title?: string;
  expandDepth?: number;
}

export interface TabsProps {
  labels: string[];
}
