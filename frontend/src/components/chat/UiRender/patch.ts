// ui_patch 增量更新：对标 intelligent-ui 的 4 类 op + baseVersion 并发保护
import type { UiRenderData, UiNode } from "./types";

export interface UiPatchOp {
  op?: "setProps" | "replaceNode" | "insertChild" | "removeNode";
  type?: string; // 兼容 LLM 用 type 代替 op
  operation?: string; // 兼容 LLM 用 operation 代替 op
  id?: string;
  target?: string; // 兼容 LLM 用 target/targetId/componentId 代替 id
  targetId?: string;
  componentId?: string;
  parentId?: string;
  props?: Record<string, unknown>;
  node?: UiNode;
  index?: number;
  merge?: boolean;
}

export interface UiPatch {
  baseVersion?: number;
  title?: string;
  ops?: UiPatchOp[];
}

function cloneNode(n: UiNode): UiNode {
  return {
    ...n,
    props: n.props ? { ...n.props } : undefined,
    children: n.children ? [...n.children] : undefined,
  };
}

/** 应用补丁，返回新的 UiRenderData（不修改入参）。补丁无法应用时返回原数据。 */
export function applyUiPatch(data: UiRenderData, patch: UiPatch): UiRenderData {
  if (!data || !data.components || !patch || !Array.isArray(patch.ops)) return data;

  // baseVersion 并发保护：版本不匹配说明基准已过期，直接忽略本次补丁
  if (
    typeof patch.baseVersion === "number" &&
    typeof data.version === "number" &&
    patch.baseVersion !== data.version
  ) {
    return data;
  }

  const components = data.components.map(cloneNode);
  const index = new Map<string, number>();
  components.forEach((c, i) => index.set(c.id, i));

  let root = data.root;
  const replaceAt = (i: number, node: UiNode) => {
    components[i] = cloneNode({ ...node, id: components[i].id });
    index.set(components[i].id, i);
  };

  for (const raw of patch.ops) {
    const kind = (raw.op || raw.type || raw.operation || "") as string;
    const id = raw.id || raw.node?.id || raw.target || raw.targetId || raw.componentId || "";

    if (kind === "setProps") {
      const found = index.get(id);
      const i = found === undefined ? index.get(root) : found;
      if (i === undefined || !raw.props) continue;
      const current = components[i];
      current.props =
        raw.merge === false ? { ...raw.props } : { ...(current.props || {}), ...raw.props };
    } else if (kind === "replaceNode") {
      const i = index.get(id);
      if (i === undefined || !raw.node) continue;
      const oldId = components[i].id;
      replaceAt(i, { ...raw.node, id: oldId });
      // 继承旧的 children（除非新节点自带）
      if (!raw.node.children) components[i].children = data.components[i]?.children
        ? [...(data.components[i].children as string[])]
        : undefined;
    } else if (kind === "insertChild") {
      const parentId = raw.parentId || id;
      const pi = index.get(parentId);
      if (pi === undefined || !raw.node || !raw.node.id) continue;
      if (index.has(raw.node.id)) continue; // 已存在则跳过
      const child = cloneNode(raw.node);
      components.push(child);
      index.set(child.id, components.length - 1);
      const parent = components[pi];
      const kids = parent.children ? [...parent.children] : [];
      const at = typeof raw.index === "number" ? Math.max(0, Math.min(raw.index, kids.length)) : kids.length;
      kids.splice(at, 0, child.id);
      parent.children = kids;
    } else if (kind === "removeNode") {
      const i = index.get(id);
      if (i === undefined || id === root) continue;
      components.splice(i, 1);
      index.clear();
      components.forEach((c, k) => index.set(c.id, k));
      for (const c of components) {
        if (c.children?.includes(id)) c.children = c.children.filter((x) => x !== id);
      }
    }
  }

  return {
    ...data,
    root,
    components,
    title: patch.title !== undefined ? patch.title : data.title,
    version: (data.version ?? 0) + 1,
  };
}
