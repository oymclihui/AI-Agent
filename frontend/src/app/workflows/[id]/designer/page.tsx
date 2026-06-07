"use client";

import { useCallback, useEffect, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  Connection,
  BackgroundVariant,
  Panel,
} from "reactflow";
import "reactflow/dist/style.css";
import { Save, Play, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { workflowsApi } from "@/lib/api";
import toast from "react-hot-toast";
import AgentNode from "@/components/FlowDesigner/AgentNode";
import StartEndNode from "@/components/FlowDesigner/StartEndNode";
import ConditionNode from "@/components/FlowDesigner/ConditionNode";

const nodeTypes = {
  agentNode: AgentNode,
  startNode: StartEndNode,
  endNode: StartEndNode,
  conditionNode: ConditionNode,
};

const defaultNodes = [
  { id: "start", type: "startNode", position: { x: 250, y: 50 }, data: { label: "Start", type: "start" } },
  { id: "end", type: "endNode", position: { x: 250, y: 400 }, data: { label: "End", type: "end" } },
];

interface PageProps {
  params: { id: string };
}

export default function WorkflowDesignerPage({ params }: PageProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(defaultNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [workflow, setWorkflow] = useState<{ name: string } | null>(null);
  const [executing, setExecuting] = useState(false);
  const [execInput, setExecInput] = useState("");

  useEffect(() => {
    workflowsApi.get(params.id).then(({ data }) => {
      setWorkflow(data);
      const graphDef = data.graph_definition;
      if (graphDef?.nodes?.length > 0) {
        setNodes(graphDef.nodes.map((n: { id: string; type: string; position: { x: number; y: number }; config: Record<string, unknown>; label: string }) => ({
          id: n.id,
          type: n.type === "start" ? "startNode" : n.type === "end" ? "endNode" : n.type === "condition" ? "conditionNode" : "agentNode",
          position: n.position,
          data: { label: n.label, type: n.type, config: n.config },
        })));
        setEdges(graphDef.edges?.map((e: { id: string; source: string; target: string; label?: string }) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          style: { stroke: "#4a5568" },
        })) || []);
      }
    }).catch(() => toast.error("Failed to load workflow"));
  }, [params.id]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge({ ...params, style: { stroke: "#4a5568" } }, eds)),
    [setEdges]
  );

  const addAgentNode = () => {
    const id = `agent_${Date.now()}`;
    setNodes((ns) => [...ns, {
      id,
      type: "agentNode",
      position: { x: Math.random() * 300 + 100, y: Math.random() * 200 + 150 },
      data: { label: "Agent Node", type: "agent", config: {} },
    }]);
  };

  const addConditionNode = () => {
    const id = `cond_${Date.now()}`;
    setNodes((ns) => [...ns, {
      id,
      type: "conditionNode",
      position: { x: Math.random() * 300 + 100, y: Math.random() * 200 + 150 },
      data: { label: "Condition", type: "condition", config: {} },
    }]);
  };

  const save = async () => {
    try {
      const graphDef = {
        nodes: nodes.map((n) => ({
          id: n.id,
          type: n.data.type,
          label: n.data.label,
          config: n.data.config || {},
          position: n.position,
        })),
        edges: edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
        })),
      };
      await workflowsApi.update(params.id, { graph_definition: graphDef });
      toast.success("Workflow saved");
    } catch {
      toast.error("Failed to save workflow");
    }
  };

  const execute = async () => {
    setExecuting(true);
    try {
      const { data } = await workflowsApi.execute(params.id, { input_data: { input: execInput } });
      toast.success(`Completed: ${data.output?.final_output?.slice(0, 60)}...`);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Execution failed");
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-[#0d0d1a]">
      {/* Header */}
      <div className="flex items-center gap-4 border-b border-[#2d2d4e] bg-[#1a1a2e] px-4 py-3">
        <Link href="/workflows" className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <span className="text-white font-semibold">{workflow?.name || "Workflow Designer"}</span>
        <div className="ml-auto flex items-center gap-2">
          <input
            type="text"
            className="rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-1.5 text-sm text-white placeholder-slate-600 focus:border-blue-500 focus:outline-none w-64"
            placeholder="Input for execution..."
            value={execInput}
            onChange={(e) => setExecInput(e.target.value)}
          />
          <button onClick={execute} disabled={executing} className="flex items-center gap-2 rounded-lg bg-green-600 px-3 py-1.5 text-sm text-white hover:bg-green-700 disabled:opacity-50 transition-colors">
            <Play className="h-4 w-4" /> {executing ? "Running..." : "Run"}
          </button>
          <button onClick={save} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 transition-colors">
            <Save className="h-4 w-4" /> Save
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Toolbar */}
        <div className="w-48 border-r border-[#2d2d4e] bg-[#1a1a2e] p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Add Nodes</p>
          <div className="space-y-2">
            <button onClick={addAgentNode} className="w-full rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-left text-sm text-blue-400 hover:bg-blue-500/20 transition-colors">
              + Agent Node
            </button>
            <button onClick={addConditionNode} className="w-full rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-left text-sm text-yellow-400 hover:bg-yellow-500/20 transition-colors">
              + Condition
            </button>
          </div>
          <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-slate-500">Tips</p>
          <p className="text-xs text-slate-500">Drag nodes to reposition. Connect nodes by dragging from handles.</p>
        </div>

        {/* Flow Canvas */}
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background variant={BackgroundVariant.Dots} color="#2d2d4e" gap={20} />
            <Controls />
            <MiniMap nodeColor="#3b82f6" maskColor="#0d0d1a88" style={{ background: "#1a1a2e" }} />
          </ReactFlow>
        </div>
      </div>
    </div>
  );
}
