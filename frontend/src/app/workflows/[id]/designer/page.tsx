"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  Connection,
  BackgroundVariant,
  Node,
  ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import { Save, Play, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { workflowsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { localizeCatalog, resolveCatalogNode, normalizeGraphCatalogId, type RawCatalogCategory, type RawCatalogNode } from "@/lib/catalogLocale";
import toast from "react-hot-toast";
import GenericWorkflowNode from "@/components/FlowDesigner/GenericWorkflowNode";
import NodePalette, { CatalogCategory, CatalogNode } from "@/components/FlowDesigner/NodePalette";
import NodeConfigPanel from "@/components/FlowDesigner/NodeConfigPanel";

const nodeTypes = { workflowNode: GenericWorkflowNode };

interface GraphNode {
  id: string;
  type: string;
  catalog_id?: string;
  label: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
}

interface PageProps {
  params: { id: string };
}

function catalogNodeFromDef(defn: CatalogNode, id: string, position: { x: number; y: number }): Node {
  const defaults: Record<string, unknown> = {};
  for (const p of defn.properties || []) {
    if (p.default !== undefined) defaults[p.name as string] = p.default;
  }
  return {
    id,
    type: "workflowNode",
    position,
    data: {
      label: defn.name,
      catalogId: defn.id,
      execType: defn.type,
      icon: defn.icon,
      color: defn.color,
      config: defaults,
    },
  };
}

function graphNodeToFlow(n: GraphNode, catalog: CatalogNode[]): Node {
  const normalizedId = normalizeGraphCatalogId(n.catalog_id, n.type);
  const cat = catalog.find((c) => c.id === normalizedId) || catalog.find((c) => c.type === n.type);
  return {
    id: n.id,
    type: "workflowNode",
    position: n.position,
    data: {
      label: n.label,
      catalogId: normalizedId || cat?.id || n.type,
      execType: cat?.type || n.type.replace(/Node$/, ""),
      icon: cat?.icon || "box",
      color: cat?.color || "#6366f1",
      config: n.config || {},
    },
  };
}

export default function WorkflowDesignerPage({ params }: PageProps) {
  const { lang } = useLangStore();
  const w = translations.workflows;
  const c = translations.common;
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [workflow, setWorkflow] = useState<{ name: string } | null>(null);
  const [executing, setExecuting] = useState(false);
  const [execInput, setExecInput] = useState("");
  const [catalogRaw, setCatalogRaw] = useState<RawCatalogNode[]>([]);
  const [categoriesRaw, setCategoriesRaw] = useState<RawCatalogCategory[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      let catRaw: RawCatalogNode[] = [];
      let catsRaw: RawCatalogCategory[] = [];
      try {
        const catData = await workflowsApi.loadNodeCatalog();
        catRaw = catData.nodes || [];
        catsRaw = catData.categories || [];
        if (!cancelled) {
          setCatalogRaw(catRaw);
          setCategoriesRaw(catsRaw);
        }
      } catch {
        if (!cancelled) toast.error(w.catalogFailed[lang]);
      }

      const localized = localizeCatalog({ nodes: catRaw, categories: catsRaw }, lang);

      try {
        const { data } = await workflowsApi.get(params.id);
        if (cancelled) return;
        setWorkflow(data);
        const graphDef = data.graph_definition;
        if (graphDef?.nodes?.length > 0) {
          setNodes(graphDef.nodes.map((n: GraphNode) => graphNodeToFlow(n, localized.nodes)));
          setEdges(graphDef.edges?.map((e: { id: string; source: string; target: string; label?: string; sourceHandle?: string }) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            sourceHandle: e.sourceHandle,
            label: e.label,
            style: { stroke: "#4a5568" },
          })) || []);
        } else {
          const startDef = localized.nodes.find((n) => n.id === "start") || {
            id: "start", type: "start", category: "control", name: lang === "zh" ? "开始" : "Start",
            description: "", icon: "play-circle", color: "#22c55e", properties: [],
          };
          const endDef = localized.nodes.find((n) => n.id === "end") || {
            id: "end", type: "end", category: "control", name: lang === "zh" ? "结束" : "End",
            description: "", icon: "stop-circle", color: "#ef4444", properties: [],
          };
          setNodes([
            catalogNodeFromDef(startDef as CatalogNode, "start", { x: 250, y: 50 }),
            catalogNodeFromDef(endDef as CatalogNode, "end", { x: 250, y: 450 }),
          ]);
        }
      } catch {
        if (!cancelled) toast.error(w.loadFailed[lang]);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [params.id, setNodes, setEdges, lang]);

  const catalog = useMemo(
    () => localizeCatalog({ nodes: catalogRaw, categories: categoriesRaw }, lang).nodes,
    [catalogRaw, categoriesRaw, lang],
  );
  const categories = useMemo(
    () => localizeCatalog({ nodes: catalogRaw, categories: categoriesRaw }, lang).categories,
    [catalogRaw, categoriesRaw, lang],
  );

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  );

  const selectedCatalogNode = useMemo(() => {
    if (!selectedNode) return null;
    return resolveCatalogNode(
      selectedNode.data.catalogId as string,
      selectedNode.data.execType as string,
      (selectedNode.data.label as string) || "",
      (selectedNode.data.icon as string) || "box",
      (selectedNode.data.color as string) || "#6366f1",
      catalog,
      catalogRaw,
      lang,
    );
  }, [selectedNode, catalog, catalogRaw, lang]);

  const onConnect = useCallback(
    (params: Connection) => {
      const label = params.sourceHandle || undefined;
      setEdges((eds) => addEdge({ ...params, label, style: { stroke: "#4a5568" } }, eds));
    },
    [setEdges],
  );

  const addNodeFromCatalog = useCallback((defn: CatalogNode, position?: { x: number; y: number }) => {
    const id = `${defn.id}_${Date.now()}`;
    const pos = position || { x: Math.random() * 400 + 120, y: Math.random() * 300 + 120 };
    setNodes((ns) => [...ns, catalogNodeFromDef(defn, id, pos)]);
  }, [setNodes]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/reactflow");
      if (!raw || !reactFlowInstance || !reactFlowWrapper.current) return;
      const defn: CatalogNode = JSON.parse(raw);
      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = reactFlowInstance.project({
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      });
      addNodeFromCatalog(defn, position);
    },
    [reactFlowInstance, addNodeFromCatalog],
  );

  const updateSelectedNode = useCallback((patch: Partial<{ label: string; config: Record<string, unknown> }>) => {
    if (!selectedNodeId) return;
    setNodes((ns) =>
      ns.map((n) =>
        n.id === selectedNodeId
          ? {
              ...n,
              data: {
                ...n.data,
                ...(patch.label !== undefined ? { label: patch.label } : {}),
                ...(patch.config !== undefined ? { config: patch.config } : {}),
              },
            }
          : n,
      ),
    );
  }, [selectedNodeId, setNodes]);

  const save = async () => {
    try {
      const graphDef = {
        nodes: nodes.map((n) => ({
          id: n.id,
          type: n.data.execType as string,
          catalog_id: n.data.catalogId as string,
          label: n.data.label as string,
          config: n.data.config || {},
          position: n.position,
        })),
        edges: edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          sourceHandle: e.sourceHandle,
        })),
      };
      await workflowsApi.update(params.id, { graph_definition: graphDef });
      toast.success(w.saved[lang]);
    } catch {
      toast.error(w.saveFailed[lang]);
    }
  };

  const execute = async () => {
    setExecuting(true);
    try {
      const { data } = await workflowsApi.execute(params.id, { input_data: { input: execInput } });
      toast.success(`${w.execDone[lang]}: ${String(data.output?.final_output || "").slice(0, 80)}...`);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || w.execFailed[lang]);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-[#0d0d1a]">
      <div className="flex items-center gap-4 border-b border-[#2d2d4e] bg-[#1a1a2e] px-4 py-3">
        <Link href="/workflows" className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <span className="text-white font-semibold">{workflow?.name || w.designerTitle[lang]}</span>
        <span className="text-xs text-slate-500">{catalog.length}{w.nodeCount[lang]}</span>
        <div className="ml-auto flex items-center gap-2">
          <input
            type="text"
            className="rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-1.5 text-sm text-white placeholder-slate-600 focus:border-blue-500 focus:outline-none w-64"
            placeholder={w.inputLabel[lang]}
            value={execInput}
            onChange={(e) => setExecInput(e.target.value)}
          />
          <button onClick={execute} disabled={executing} className="flex items-center gap-2 rounded-lg bg-green-600 px-3 py-1.5 text-sm text-white hover:bg-green-700 disabled:opacity-50 transition-colors">
            <Play className="h-4 w-4" /> {executing ? w.running[lang] : w.run[lang]}
          </button>
          <button onClick={save} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 transition-colors">
            <Save className="h-4 w-4" /> {c.save[lang]}
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-56 shrink-0 border-r border-[#2d2d4e] bg-[#1a1a2e]">
          <NodePalette categories={categories} nodes={catalog} onAddNode={addNodeFromCatalog} />
        </div>

        <div className="flex-1" ref={reactFlowWrapper}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onInit={setReactFlowInstance}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onSelectionChange={({ nodes: sel }) => {
              if (sel.length === 1) setSelectedNodeId(sel[0].id);
              else if (sel.length === 0) setSelectedNodeId(null);
            }}
            onPaneClick={() => setSelectedNodeId(null)}
            nodeTypes={nodeTypes}
            fitView
            deleteKeyCode={["Backspace", "Delete"]}
          >
            <Background variant={BackgroundVariant.Dots} color="#2d2d4e" gap={20} />
            <Controls />
            <MiniMap nodeColor="#3b82f6" maskColor="#0d0d1a88" style={{ background: "#1a1a2e" }} />
          </ReactFlow>
        </div>

        <div className="flex h-full min-h-0 w-80 shrink-0 flex-col border-l border-[#2d2d4e] bg-[#1a1a2e]">
          <NodeConfigPanel
            nodeId={selectedNodeId}
            catalogNode={selectedCatalogNode}
            label={(selectedNode?.data.label as string) || ""}
            config={(selectedNode?.data.config as Record<string, unknown>) || {}}
            onLabelChange={(label) => updateSelectedNode({ label })}
            onConfigChange={(config) => updateSelectedNode({ config })}
            workflowContext={{ workflowId: params.id, nodeCount: nodes.length }}
          />
        </div>
      </div>
    </div>
  );
}
