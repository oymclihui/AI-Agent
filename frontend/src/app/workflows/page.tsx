"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Workflow, Trash2, RefreshCw, GitBranch, Bot, Zap, Code2, Globe, User, Cpu, Sparkles, PenLine, Loader2 } from "lucide-react";
import { workflowsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

interface WorkflowItem {
  id: string; name: string; description: string | null;
  status: string; process_type: string; created_at: string;
  graph_definition?: { nodes?: Array<{ type: string }>; edges?: unknown[] } | null;
}

const NODE_TYPE_META: Record<string, { label: string; color: string; icon: typeof Bot }> = {
  agentNode:    { label: "Agent", color: "bg-blue-500/20 text-blue-400", icon: Bot },
  llmNode:      { label: "LLM", color: "bg-cyan-500/20 text-cyan-400", icon: Cpu },
  toolNode:     { label: "Tool", color: "bg-green-500/20 text-green-400", icon: Zap },
  conditionNode:{ label: "If", color: "bg-yellow-500/20 text-yellow-400", icon: GitBranch },
  humanNode:    { label: "Human", color: "bg-orange-500/20 text-orange-400", icon: User },
  httpNode:     { label: "HTTP", color: "bg-indigo-500/20 text-indigo-400", icon: Globe },
  codeNode:     { label: "Code", color: "bg-pink-500/20 text-pink-400", icon: Code2 },
};

function countNodeTypes(graph?: WorkflowItem["graph_definition"]) {
  const counts: Record<string, number> = {};
  for (const n of graph?.nodes ?? []) {
    counts[n.type] = (counts[n.type] ?? 0) + 1;
  }
  return counts;
}

export default function WorkflowsPage() {
  const { lang } = useLangStore();
  const w = translations.workflows;
  const c = translations.common;

  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [mode, setMode] = useState<"nl" | "manual">("nl");
  const [nlText, setNlText] = useState("");
  const [generating, setGenerating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", process_type: "sequential" });

  const load = async () => {
    try {
      const { data } = await workflowsApi.list();
      setWorkflows(data);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load workflows");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setMode("nl");
    setNlText("");
    setForm({ name: "", description: "", process_type: "sequential" });
    setShowCreate(true);
  };

  const generateFromNL = async () => {
    if (nlText.trim().length < 5) return;
    setGenerating(true);
    try {
      const { data } = await workflowsApi.generate({ description: nlText.trim() });
      toast.success(w.generated[lang]);
      setShowCreate(false);
      setNlText("");
      load();
      if (data?.id) {
        window.location.href = `/workflows/${data.id}/designer`;
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? w.generateFailed[lang]);
    } finally {
      setGenerating(false);
    }
  };

  const create = async () => {
    try {
      await workflowsApi.create(form);
      toast.success(lang === "zh" ? "工作流已创建" : "Workflow created");
      setShowCreate(false);
      load();
    } catch {
      toast.error(lang === "zh" ? "创建失败" : "Failed to create workflow");
    }
  };

  const deleteWorkflow = async (id: string) => {
    if (!confirm(w.deleteConfirm[lang])) return;
    try {
      await workflowsApi.delete(id);
      toast.success(lang === "zh" ? "已删除" : "Deleted");
      load();
    } catch {
      toast.error(lang === "zh" ? "删除失败" : "Delete failed");
    }
  };

  const seedTemplates = async () => {
    try {
      await workflowsApi.seedTemplates();
      toast.success(lang === "zh" ? "模板已加载" : "Templates loaded");
      load();
    } catch {
      toast.error(lang === "zh" ? "加载模板失败" : "Failed to load templates");
    }
  };

  const processColors: Record<string, string> = {
    sequential: "bg-blue-500/20 text-blue-400",
    hierarchical: "bg-purple-500/20 text-purple-400",
    parallel: "bg-green-500/20 text-green-400",
  };

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{w.title[lang]}</h1>
          <p className="text-slate-400">{w.subtitle[lang]}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={seedTemplates}
            className="flex items-center gap-2 rounded-lg border border-[#2d2d4e] px-4 py-2 text-sm text-slate-300 hover:bg-white/5 transition-colors"
          >
            <RefreshCw className="h-4 w-4" /> {w.seedTemplates[lang]}
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" /> {w.newWorkflow[lang]}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-slate-400">{c.loading[lang]}</div>
      ) : workflows.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#2d2d4e] py-16 text-center">
          <Workflow className="mb-4 h-12 w-12 text-slate-600" />
          <p className="text-slate-400">{w.noWorkflows[lang]}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {workflows.map((wf) => {
            const typeCounts = countNodeTypes(wf.graph_definition);
            const nodeCount = wf.graph_definition?.nodes?.length ?? 0;
            const edgeCount = wf.graph_definition?.edges?.length ?? 0;
            return (
              <div key={wf.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5">
                <div className="mb-3 flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500/20">
                      <Workflow className="h-4 w-4 text-purple-400" />
                    </div>
                    <h3 className="font-semibold text-white">{wf.name}</h3>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${processColors[wf.process_type] || "bg-slate-500/20 text-slate-400"}`}>
                    {wf.process_type}
                  </span>
                </div>
                {wf.description && (
                  <p className="mb-3 line-clamp-2 text-sm text-slate-400">{wf.description}</p>
                )}
                {nodeCount > 0 && (
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {Object.entries(typeCounts).map(([type, count]) => {
                      const meta = NODE_TYPE_META[type];
                      if (!meta) return null;
                      return (
                        <span key={type} className={`rounded px-2 py-0.5 text-[10px] font-medium ${meta.color}`}>
                          {meta.label}×{count}
                        </span>
                      );
                    })}
                    <span className="rounded bg-slate-700/40 px-2 py-0.5 text-[10px] text-slate-500">
                      {nodeCount} {w.nodes[lang]} · {edgeCount} {w.edges[lang]}
                    </span>
                  </div>
                )}
                <div className="flex gap-2">
                  <Link
                    href={`/workflows/${wf.id}/designer`}
                    className="flex items-center gap-1 rounded-lg bg-purple-600/20 px-3 py-1.5 text-xs text-purple-400 hover:bg-purple-600/30 transition-colors"
                  >
                    {w.openDesigner[lang]}
                  </Link>
                  <button
                    onClick={() => deleteWorkflow(wf.id)}
                    className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                  >
                    <Trash2 className="h-3 w-3" /> {c.delete[lang]}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">{w.newWorkflow[lang]}</h2>

            <div className="mb-4 flex rounded-lg border border-[#2d2d4e] p-0.5 text-sm">
              <button
                onClick={() => setMode("nl")}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md py-2 ${mode === "nl" ? "bg-blue-600 text-white" : "text-slate-400"}`}
              >
                <Sparkles className="h-3.5 w-3.5" /> {w.nlMode[lang]}
              </button>
              <button
                onClick={() => setMode("manual")}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md py-2 ${mode === "manual" ? "bg-blue-600 text-white" : "text-slate-400"}`}
              >
                <PenLine className="h-3.5 w-3.5" /> {w.manualMode[lang]}
              </button>
            </div>

            {mode === "nl" ? (
              <div className="space-y-3">
                <textarea
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-blue-500 focus:outline-none"
                  rows={6}
                  placeholder={w.nlPlaceholder[lang]}
                  value={nlText}
                  onChange={(e) => setNlText(e.target.value)}
                />
                <button
                  onClick={generateFromNL}
                  disabled={generating || nlText.trim().length < 5}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-purple-600 py-2.5 text-sm text-white hover:bg-purple-700 disabled:opacity-40"
                >
                  {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  {generating ? w.generating[lang] : w.generate[lang]}
                </button>
              </div>
            ) : (
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.name[lang]}</label>
                <input
                  type="text"
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.description[lang]}</label>
                <textarea
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  rows={2}
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{w.processType[lang]}</label>
                <select
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  value={form.process_type}
                  onChange={(e) => setForm((f) => ({ ...f, process_type: e.target.value }))}
                >
                  <option value="sequential">{w.sequential[lang]}</option>
                  <option value="hierarchical">{w.hierarchical[lang]}</option>
                  <option value="parallel">{w.parallel[lang]}</option>
                </select>
              </div>
            </div>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowCreate(false)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white">{c.cancel[lang]}</button>
              {mode === "manual" && (
                <button onClick={create} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">{c.create[lang]}</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
