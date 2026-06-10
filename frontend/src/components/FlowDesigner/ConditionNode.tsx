import { Handle, Position, NodeProps } from "reactflow";
import { GitBranch } from "lucide-react";

export default function ConditionNode({ data, selected }: NodeProps) {
  return (
    <div
      className={`flow-node-card min-w-[140px] rotate-0 rounded-xl border bg-[#1a1a2e] px-4 py-3 shadow-lg transition-colors ${
        selected ? "border-yellow-400" : "border-yellow-500/40"
      }`}
    >
      <Handle type="target" position={Position.Top} style={{ background: "#eab308", border: "2px solid #1a1a2e" }} />
      <div className="flex items-center gap-2">
        <GitBranch className="h-3.5 w-3.5 text-yellow-400" />
        <p className="text-xs font-semibold text-yellow-400">{data.label}</p>
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>success</span>
        <span>error</span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        id="success"
        style={{ left: "30%", background: "#22c55e", border: "2px solid #1a1a2e" }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="error"
        style={{ left: "70%", background: "#ef4444", border: "2px solid #1a1a2e" }}
      />
    </div>
  );
}
