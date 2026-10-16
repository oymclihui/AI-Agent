"use client";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";

interface ErColumn {
  name: string;
  type?: string;
}

interface ErLink {
  from: string;
  to: string;
  label: string;
}

interface ErTable {
  table_name: string;
  column_meta?: { columns?: ErColumn[] };
}

interface ErNodeData {
  title: string;
  columns: ErColumn[];
  keys: string[];
  reference: boolean;
  badge: string;
}

function ErTableNode({ data }: NodeProps<ErNodeData>) {
  const keyset = new Set((data.keys || []).map((key) => key.toLowerCase()));
  return (
    <div className={`w-[220px] overflow-hidden rounded-lg border text-xs shadow-sm theme-border theme-surface ${data.reference ? "border-dashed" : ""}`}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-blue-500" />
      <div className={`px-2 py-1.5 font-medium text-white ${data.reference ? "bg-slate-500" : "bg-blue-600"}`}>
        {data.title}
        {data.badge ? ` · ${data.badge}` : ""}
      </div>
      <ul>
        {data.columns.length === 0 && <li className="px-2 py-1 theme-muted">—</li>}
        {data.columns.map((col) => {
          const isKey = keyset.has(col.name.toLowerCase());
          return (
            <li key={col.name} className={`flex items-center justify-between gap-2 border-t px-2 py-1 theme-border ${isKey ? "font-medium" : ""}`}>
              <span className="truncate">{isKey ? "◆ " : ""}{col.name}</span>
              <span className="shrink-0 theme-muted">{col.type || ""}</span>
            </li>
          );
        })}
      </ul>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-blue-500" />
    </div>
  );
}

const nodeTypes = { erTable: ErTableNode };

function columnsOf(table: ErTable | undefined): ErColumn[] {
  return (table?.column_meta?.columns || [])
    .filter((col) => col?.name)
    .slice(0, 18)
    .map((col) => ({ name: col.name, type: col.type || "" }));
}

export function ErDiagram({
  tables,
  edges,
  related,
  keys,
  referenceBadge,
}: {
  tables: ErTable[];
  edges: ErLink[];
  related: ErLink[];
  keys: string[];
  referenceBadge: string;
}) {
  const graph = useMemo(() => {
    const selected = tables.map((table) => table.table_name).filter(Boolean);
    const selectedSet = new Set(selected);
    const refNames: string[] = [];
    const seenRef = new Set<string>();
    for (const link of related) {
      for (const name of [link.from, link.to]) {
        if (!name || selectedSet.has(name) || seenRef.has(name)) continue;
        seenRef.add(name);
        refNames.push(name);
      }
    }
    const refColumns = new Map<string, ErColumn[]>();
    for (const link of related) {
      for (const name of [link.from, link.to]) {
        if (!name || selectedSet.has(name) || !link.label) continue;
        const cols = refColumns.get(name) || [];
        if (!cols.some((col) => col.name.toLowerCase() === link.label.toLowerCase())) {
          cols.push({ name: link.label, type: "key" });
        }
        refColumns.set(name, cols);
      }
    }
    const nodes: Node<ErNodeData>[] = [
      ...selected.map((name, index) => ({
        id: name,
        type: "erTable",
        position: { x: 24, y: index * 300 },
        data: {
          title: name,
          columns: columnsOf(tables.find((table) => table.table_name === name)),
          keys,
          reference: false,
          badge: "",
        },
        draggable: true,
      })),
      ...refNames.map((name, index) => ({
        id: name,
        type: "erTable",
        position: { x: 420, y: index * 220 },
        data: {
          title: name,
          columns: refColumns.get(name) || [],
          keys,
          reference: true,
          badge: referenceBadge,
        },
        draggable: true,
      })),
    ];
    const nodeIds = new Set(nodes.map((node) => node.id));
    const flowEdges: Edge[] = [];
    const pushEdge = (link: ErLink, reference: boolean, index: number) => {
      if (!link.from || !link.to || link.from === link.to) return;
      if (!nodeIds.has(link.from) || !nodeIds.has(link.to)) return;
      flowEdges.push({
        id: `${reference ? "ref" : "sel"}-${index}-${link.from}-${link.to}-${link.label}`,
        source: link.from,
        target: link.to,
        label: link.label,
        type: "smoothstep",
        style: reference
          ? { stroke: "#64748b", strokeDasharray: "5 4" }
          : { stroke: "#2563eb" },
        labelStyle: { fontSize: 11, fill: "#334155" },
        markerEnd: { type: MarkerType.ArrowClosed, color: reference ? "#64748b" : "#2563eb" },
      });
    };
    edges.forEach((link, index) => pushEdge(link, false, index));
    related.forEach((link, index) => pushEdge(link, true, index));
    return { nodes, edges: flowEdges };
  }, [tables, edges, related, keys, referenceBadge]);

  if (graph.nodes.length === 0) return null;

  return (
    <div className="h-[480px] overflow-hidden rounded-lg border theme-border">
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        minZoom={0.35}
        maxZoom={1.6}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
