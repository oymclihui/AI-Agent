import { Handle, Position, NodeProps } from "reactflow";
import type { LucideIcon } from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import {
  Bot, Globe, Code, GitBranch, PlayCircle, StopCircle, Wrench, Brain,
  Box, Webhook, Clock, Mail, MessageCircle, Split, Merge, Edit, Filter,
  Timer, Minus, AlertCircle, Reply, Workflow, UserCheck, Sparkles, Tags,
  FileText, Braces, ArrowUpDown, List, Sigma, CopyMinus, FileDown, FileUp,
  MessageSquare, Gamepad2, Send, Table, BookOpen, Grid, Github, Gitlab,
  Ticket, CheckSquare, Building, Cloud, CreditCard, ShoppingBag, Database,
  Search, HardDrive, Users, Video, Twitter, Linkedin, Radio, StickyNote,
  Play, Layers,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  bot: Bot, globe: Globe, code: Code, "git-branch": GitBranch,
  "play-circle": PlayCircle, "stop-circle": StopCircle, wrench: Wrench,
  brain: Brain, box: Box, webhook: Webhook, clock: Clock, mail: Mail,
  "message-circle": MessageCircle, split: Split, merge: Merge, edit: Edit,
  filter: Filter, timer: Timer, minus: Minus, "alert-circle": AlertCircle,
  reply: Reply, workflow: Workflow, "user-check": UserCheck, sparkles: Sparkles,
  tags: Tags, "file-text": FileText, braces: Braces, "arrow-up-down": ArrowUpDown,
  list: List, sigma: Sigma, "copy-minus": CopyMinus, "file-down": FileDown,
  "file-up": FileUp, "message-square": MessageSquare, "gamepad-2": Gamepad2,
  send: Send, table: Table, "book-open": BookOpen, grid: Grid, github: Github,
  gitlab: Gitlab, ticket: Ticket, "check-square": CheckSquare, building: Building,
  cloud: Cloud, "credit-card": CreditCard, "shopping-bag": ShoppingBag,
  database: Database, search: Search, "hard-drive": HardDrive, users: Users,
  video: Video, twitter: Twitter, linkedin: Linkedin, radio: Radio,
  "sticky-note": StickyNote, play: Play, layers: Layers,
};

export default function GenericWorkflowNode({ data, selected }: NodeProps) {
  const { lang } = useLangStore();
  const d = translations.designer;
  const Icon = ICONS[data.icon as string] || Box;
  const color = (data.color as string) || "#6366f1";
  const isCondition = data.execType === "condition" || data.execType === "switch";
  const isStart = data.execType === "start";
  const isEnd = data.execType === "end";
  const isNote = data.execType === "note";

  return (
    <div
      className={`flow-node-card min-w-[170px] rounded-xl border bg-[#1a1a2e] px-3 py-2.5 shadow-lg transition-all ${
        selected ? "ring-2 ring-offset-1 ring-offset-[#0d0d1a]" : ""
      } ${isNote ? "border-dashed opacity-80" : ""}`}
      style={{ borderColor: selected ? color : `${color}66` }}
    >
      {!isStart && (
        <Handle type="target" position={Position.Top} style={{ background: color, border: "2px solid #1a1a2e" }} />
      )}

      <div className="flex items-start gap-2">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg" style={{ background: `${color}22` }}>
          <Icon className="h-3.5 w-3.5" style={{ color }} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-white">{data.label}</p>
          <p className="truncate text-[10px] text-slate-500">{data.catalogId || data.execType}</p>
          {data.config && Object.keys(data.config).length > 0 && (
            <p className="mt-0.5 text-[10px] text-slate-600">
              {Object.keys(data.config).length}{d.configItems[lang]}
            </p>
          )}
        </div>
      </div>

      {isCondition ? (
        <>
          <div className="mt-1 flex justify-between px-1 text-[9px] text-slate-500">
            <span>{d.branchTrue[lang]}</span><span>{d.branchFalse[lang]}</span>
          </div>
          <Handle type="source" position={Position.Bottom} id="true" style={{ left: "28%", background: "#22c55e", border: "2px solid #1a1a2e" }} />
          <Handle type="source" position={Position.Bottom} id="false" style={{ left: "72%", background: "#ef4444", border: "2px solid #1a1a2e" }} />
          <Handle type="source" position={Position.Bottom} id="success" style={{ left: "28%", background: "#22c55e", border: "2px solid #1a1a2e" }} />
          <Handle type="source" position={Position.Bottom} id="error" style={{ left: "72%", background: "#ef4444", border: "2px solid #1a1a2e" }} />
        </>
      ) : !isEnd ? (
        <Handle type="source" position={Position.Bottom} style={{ background: color, border: "2px solid #1a1a2e" }} />
      ) : null}
    </div>
  );
}
