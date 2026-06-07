import { Handle, Position, NodeProps } from "reactflow";

export default function StartEndNode({ data, selected }: NodeProps) {
  const isStart = data.type === "start";
  return (
    <div
      className={`rounded-full border px-5 py-2 text-sm font-semibold shadow-lg transition-colors ${
        isStart
          ? selected ? "border-green-400 bg-green-500/20 text-green-300" : "border-green-500/50 bg-green-500/10 text-green-400"
          : selected ? "border-red-400 bg-red-500/20 text-red-300" : "border-red-500/50 bg-red-500/10 text-red-400"
      }`}
    >
      {isStart ? null : (
        <Handle type="target" position={Position.Top} style={{ background: "#ef4444", border: "2px solid #1a1a2e" }} />
      )}
      {data.label}
      {isStart ? (
        <Handle type="source" position={Position.Bottom} style={{ background: "#22c55e", border: "2px solid #1a1a2e" }} />
      ) : null}
    </div>
  );
}
