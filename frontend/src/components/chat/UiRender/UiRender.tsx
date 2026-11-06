"use client";

import { Component, useMemo, type ReactNode } from "react";
import type { UiRenderData, UiNode } from "./types";
import { CardComponent } from "./components/CardComponent";
import { StackComponent, GridComponent } from "./components/StackComponent";
import { TableComponent } from "./components/TableComponent";
import {
  StatComponent, TextComponent, AlertComponent,
  BadgeComponent, DividerComponent, ListComponent,
} from "./components/MiscComponents";
import { ChoiceComponent } from "./components/ChoiceComponent";
import { ChartComponent } from "./components/ChartComponent";
import { MermaidComponent } from "./components/MermaidComponent";
import { ProgressComponent, TimelineComponent } from "./components/ProgressTimelineComponents";

/** 组件数据由 LLM 生成，可能缺字段；单节点渲染失败时兜底，避免整页崩溃。 */
class UiTreeBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">
          UI 渲染失败：组件数据不完整
        </div>
      );
    }
    return this.props.children;
  }
}

/** 根据组件 type 分发渲染 */
function renderNode(node: UiNode, byId: Record<string, UiNode>, depth = 0): React.ReactNode {
  if (depth > 12) return null;
  const childNodes = (node.children || [])
    .map((id) => byId[id])
    .filter(Boolean) as UiNode[];
  const children: React.ReactNode = childNodes.map((c) => renderNode(c, byId, depth + 1));

  switch (node.type) {
    case "Card":
      return <CardComponent key={node.id} node={node}>{children}</CardComponent>;
    case "Stack":
      return <StackComponent key={node.id} node={node}>{children}</StackComponent>;
    case "Grid":
      return <GridComponent key={node.id} node={node}>{children}</GridComponent>;
    case "Table":
      return <TableComponent key={node.id} node={node} />;
    case "Stat":
      return <StatComponent key={node.id} node={node} />;
    case "Text":
      return <TextComponent key={node.id} node={node} />;
    case "Alert":
      return <AlertComponent key={node.id} node={node} />;
    case "Badge":
      return <BadgeComponent key={node.id} node={node} />;
    case "Divider":
      return <DividerComponent key={node.id} node={node} />;
    case "Choice":
      return <ChoiceComponent key={node.id} node={node} />;
    case "List":
      return <ListComponent key={node.id} node={node} />;
    case "Chart":
      return <ChartComponent key={node.id} node={node} />;
    case "Progress":
      return <ProgressComponent key={node.id} node={node} />;
    case "Timeline":
      return <TimelineComponent key={node.id} node={node} />;
    case "Mermaid":
      return <MermaidComponent key={node.id} node={node} />;
    default:
      return (
        <div key={node.id} className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700">
          未支持组件类型: {node.type}
        </div>
      );
  }
}

const CONTAINER_TYPES = new Set(["Card", "Stack", "Grid", "Tabs"]);

/** 主入口：接收 ui_render tool call 的完整数据，渲染整个组件树 */
export function UiRender({ data }: { data: UiRenderData }) {
  const { root, title } = data;
  const components = Array.isArray(data.components) ? data.components : [];

  const byId = useMemo(() => {
    const map: Record<string, UiNode> = {};
    for (const c of components) map[c.id] = c;

    const rootNode = map[root];
    if (!rootNode) return map;

    // 可达性修复：LLM 常漏写 root 的 children，把未挂载的组件自动挂到根容器，避免整块空白
    const reached = new Set<string>();
    const walk = (id: string, depth: number) => {
      if (reached.has(id) || depth > 12) return;
      reached.add(id);
      for (const c of map[id]?.children || []) {
        if (map[c]) walk(c, depth + 1);
      }
    };
    walk(root, 0);
    const orphans = components.map((c) => c.id).filter((id) => !reached.has(id));
    if (orphans.length && CONTAINER_TYPES.has(rootNode.type)) {
      map[root] = {
        ...rootNode,
        children: [...(rootNode.children || []), ...orphans.filter((id) => id !== root)],
      };
    }
    return map;
  }, [components, root]);

  if (!components.length) {
    return (
      <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">
        UI 渲染失败：组件列表为空
      </div>
    );
  }

  const rootNode = byId[root];
  if (!rootNode) {
    return (
      <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-700">
        UI 渲染失败：找不到根节点 <code className="text-xs">{root}</code>
      </div>
    );
  }

  return (
    <div className="my-3 rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4 shadow-sm">
      {title && (
        <h3 className="mb-3 text-sm font-semibold text-slate-800">{title}</h3>
      )}
      <div className="ui-render-tree">
        <UiTreeBoundary>{renderNode(rootNode, byId)}</UiTreeBoundary>
      </div>
    </div>
  );
}

export default UiRender;
