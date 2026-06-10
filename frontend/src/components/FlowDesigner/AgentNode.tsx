import { Handle, Position, NodeProps } from "reactflow";
import { Bot } from "lucide-react";

export default function AgentNode({ data, selected }: NodeProps) {
  return (
    <div
      className={`flow-node-card min-w-[160px] rounded-xl border bg-[#1a1a2e] px-4 py-3 shadow-lg transition-colors ${
        selected ? "border-blue-500" : "border-[#2d2d4e]"
      }`}
    >
      <Handle type="target" position={Position.Top} style={{ background: "#3b82f6", border: "2px solid #1a1a2e" }} />
      <div className="flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded bg-blue-500/20">
          <Bot className="h-3.5 w-3.5 text-blue-400" />
        </div>
        <div>
          <p className="text-xs font-semibold text-white">{data.label}</p>
          {data.config?.agent_id && (
            <p className="text-[10px] text-slate-500">id: {data.config.agent_id.slice(0, 8)}...</p>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: "#3b82f6", border: "2px solid #1a1a2e" }} />
    </div>
  );
}
