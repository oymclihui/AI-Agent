"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Plus, Workflow, Trash2, RefreshCw, GitBranch, Bot, Zap, Code2, Globe, User, Cpu,
  Sparkles, PenLine, Loader2, Search,
} from "lucide-react";
import { workflowsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { agentAvatarTone } from "@/lib/agentCatalog";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";
import toast from "react-hot-toast";

interface WorkflowItem {
  id: string; name: string; description: string | null;
  status: string; process_type: string; created_at: string;
  graph_definition?: { nodes?: Array<{ type: string }>; edges?: unknown[] } | null;
}

type ProcessFilter = "all" | "sequential" | "hierarchical" | "parallel";

const NODE_TYPE_META: Record<string, { label: string; color: string; icon: typeof Bot }> = {
  agentNode:    { label: "Agent", color: "bg-blue-500/20 text-blue-400", icon: Bot },
  llmNode:      { label: "LLM", color: "bg-cyan-500/20 text-cyan-400", icon: Cpu },
  toolNode:     { label: "Tool", color: "bg-green-500/20 text-green-400", icon: Zap },
  conditionNode:{ label: "If", color: "bg-yellow-500/20 text-yellow-400", icon: GitBranch },
  humanNode:    { label: "Human", color: "bg-orange-500/20 text-orange-400", icon: User },
  httpNode:     { label: "HTTP", color: "bg-indigo-500/20 text-indigo-400", icon: Globe },
  codeNode:     { label: "Code", color: "bg-pink-500/20 text-pink-400", icon: Code2 },
};

const PROCESS_SCENES: Array<{
  id: ProcessFilter;
  title: { zh: string; en: string };
  subtitle: { zh: string; en: string };
  tone: string;
}> = [
  {
    id: "sequential",
    title: { zh: "顺序执行", en: "Sequential" },
    subtitle: { zh: "智能体依次接力完成", en: "Agents run one after another" },
    tone: "agents-scene-tech",
  },
  {
    id: "hierarchical",
    title: { zh: "层级编排", en: "Hierarchical" },
    subtitle: { zh: "管理者分配子任务", en: "Manager delegates to workers" },
    tone: "agents-scene-finance",
  },
  {
    id: "parallel",
    title: { zh: "并行执行", en: "Parallel" },
    subtitle: { zh: "多路同时运行汇总", en: "All branches run at once" },
    tone: "agents-scene-data",
  },
];

const PROCESS_FILTERS: ProcessFilter[] = ["all", "sequential", "hierarchical", "parallel"];

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
  const chatT = translations.chat;

  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [processFilter, setProcessFilter] = useState<ProcessFilter>("all");
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

  const processLabel = (type: string) => {
    if (type === "sequential") return w.sequential[lang].split("—")[0].trim();
    if (type === "hierarchical") return w.hierarchical[lang].split("—")[0].trim();
    if (type === "parallel") return w.parallel[lang].split("—")[0].trim();
    return type;
  };

  const filteredWorkflows = useMemo(() => {
    let list = [...workflows];
    if (processFilter !== "all") list = list.filter((wf) => wf.process_type === processFilter);
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (wf) =>
          wf.name.toLowerCase().includes(q) ||
          (wf.description ?? "").toLowerCase().includes(q) ||
          wf.process_type.toLowerCase().includes(q),
      );
    }
    return list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }, [workflows, processFilter, searchQuery]);

  const sceneWorkflows = (type: ProcessFilter) =>
    type === "all" ? workflows.slice(0, 4) : workflows.filter((wf) => wf.process_type === type).slice(0, 4);

  const wfInitial = (name: string) => (name.trim()[0] || "W").toUpperCase();

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

  return (
    <div className="agents-hub">
      <div className="agents-hub-header">
        <div>
          <h1>{w.title[lang]}</h1>
          <p>{w.subtitle[lang]}</p>
        </div>
        <div className="agents-hub-actions">
          <button type="button" onClick={seedTemplates} className="agents-btn-secondary">
            <RefreshCw className="h-4 w-4" /> {w.seedTemplates[lang]}
          </button>
          <button type="button" onClick={openCreate} className="agents-btn-primary">
            <Plus className="h-4 w-4" /> {w.newWorkflow[lang]}
          </button>
        </div>
      </div>

      <div className="agents-hub-toolbar">
        <div className="agents-hub-search">
          <Search className="h-4 w-4 shrink-0 theme-muted" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={w.searchPlaceholder[lang]}
          />
        </div>
      </div>

      {!loading && workflows.length > 0 && (
        <section className="agents-featured">
          <h2 className="agents-featured-title">{w.featuredTitle[lang]}</h2>
          <CapsuleScrollRow
            scrollStep={268}
            scrollLeftLabel={chatT.scrollLeft[lang]}
            scrollRightLabel={chatT.scrollRight[lang]}
            innerClassName="agents-featured-scroll"
          >
            {PROCESS_SCENES.map((scene) => {
              const items = sceneWorkflows(scene.id);
              return (
                <button
                  key={scene.id}
                  type="button"
                  className={`agents-scene-card ${scene.tone}`}
                  onClick={() => setProcessFilter(scene.id)}
                >
                  <div>
                    <h3>{lang === "zh" ? scene.title.zh : scene.title.en}</h3>
                    <p>{lang === "zh" ? scene.subtitle.zh : scene.subtitle.en}</p>
                  </div>
                  <ul className="agents-scene-list">
                    {items.length > 0 ? (
                      items.map((item) => <li key={item.id}>{item.name}</li>)
                    ) : (
                      <li>{lang === "zh" ? "暂无，点击筛选" : "None yet — click to filter"}</li>
                    )}
                  </ul>
                </button>
              );
            })}
          </CapsuleScrollRow>
        </section>
      )}

      <div className="agents-filter-row">
        <CapsuleScrollRow
          centerWhenFit
          className="flex-1 min-w-0"
          scrollLeftLabel={chatT.scrollLeft[lang]}
          scrollRightLabel={chatT.scrollRight[lang]}
          innerClassName="agents-filter-scroll"
        >
          {PROCESS_FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setProcessFilter(id)}
              className={`agents-filter-pill${processFilter === id ? " agents-filter-pill-active" : ""}`}
            >
              {id === "all" ? w.filterAll[lang] : processLabel(id)}
            </button>
          ))}
        </CapsuleScrollRow>
      </div>

      {loading ? (
        <div className="theme-muted text-sm">{c.loading[lang]}</div>
      ) : filteredWorkflows.length === 0 ? (
        <div className="agents-empty">
          <Workflow className="mb-4 h-12 w-12 opacity-40" />
          <p>{workflows.length === 0 ? w.noWorkflows[lang] : (lang === "zh" ? "没有匹配的工作流" : "No matching workflows")}</p>
        </div>
      ) : (
        <div className="agents-grid">
          {filteredWorkflows.map((wf) => {
            const typeCounts = countNodeTypes(wf.graph_definition);
            const nodeCount = wf.graph_definition?.nodes?.length ?? 0;
            const edgeCount = wf.graph_definition?.edges?.length ?? 0;
            return (
              <article key={wf.id} className="agents-card">
                <div className="agents-card-top">
                  <div className={`agents-avatar ${agentAvatarTone(wf.id)}`} aria-hidden>
                    {wfInitial(wf.name)}
                  </div>
                  <div className="agents-card-head">
                    <div className="agents-card-title-row">
                      <h3 title={wf.name}>{wf.name}</h3>
                      <span className="agents-badge agents-badge-beta">{processLabel(wf.process_type)}</span>
                    </div>
                    <p className="agents-card-role">{wf.status}</p>
                  </div>
                </div>
                {wf.description && (
                  <p className="agents-card-desc">{wf.description}</p>
                )}
                {nodeCount > 0 && (
                  <div className="agents-card-tags">
                    {Object.entries(typeCounts).map(([type, count]) => {
                      const meta = NODE_TYPE_META[type];
                      if (!meta) return null;
                      return (
                        <span key={type} className="agents-tag">{meta.label}×{count}</span>
                      );
                    })}
                    <span className="agents-tag">{nodeCount} {w.nodes[lang]} · {edgeCount} {w.edges[lang]}</span>
                  </div>
                )}
                <div className="agents-card-footer">
                  <span className="agents-card-meta">{new Date(wf.created_at).toLocaleDateString()}</span>
                  <div className="agents-card-actions">
                    <button
                      type="button"
                      onClick={() => deleteWorkflow(wf.id)}
                      className="agents-icon-btn agents-icon-btn-danger"
                      title={c.delete[lang]}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    <Link href={`/workflows/${wf.id}/designer`} className="agents-summon-btn">
                      {w.openDesigner[lang]}
                    </Link>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-4 text-lg font-semibold theme-text">{w.newWorkflow[lang]}</h2>

            <div className="mb-4 flex rounded-lg border border-[var(--border)] p-0.5 text-sm">
              <button
                type="button"
                onClick={() => setMode("nl")}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md py-2 ${mode === "nl" ? "bg-[var(--primary)] text-white" : "theme-muted"}`}
              >
                <Sparkles className="h-3.5 w-3.5" /> {w.nlMode[lang]}
              </button>
              <button
                type="button"
                onClick={() => setMode("manual")}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md py-2 ${mode === "manual" ? "bg-[var(--primary)] text-white" : "theme-muted"}`}
              >
                <PenLine className="h-3.5 w-3.5" /> {w.manualMode[lang]}
              </button>
            </div>

            {mode === "nl" ? (
              <div className="space-y-3">
                <textarea
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text placeholder:theme-muted focus:border-[var(--primary)] focus:outline-none"
                  rows={6}
                  placeholder={w.nlPlaceholder[lang]}
                  value={nlText}
                  onChange={(e) => setNlText(e.target.value)}
                />
                <button
                  type="button"
                  onClick={generateFromNL}
                  disabled={generating || nlText.trim().length < 5}
                  className="agents-btn-primary flex w-full justify-center disabled:opacity-40"
                >
                  {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  {generating ? w.generating[lang] : w.generate[lang]}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs theme-muted">{c.name[lang]}</label>
                  <input
                    type="text"
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text focus:border-[var(--primary)] focus:outline-none"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs theme-muted">{c.description[lang]}</label>
                  <textarea
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text focus:border-[var(--primary)] focus:outline-none"
                    rows={2}
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs theme-muted">{w.processType[lang]}</label>
                  <select
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text focus:border-[var(--primary)] focus:outline-none"
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
              <button type="button" onClick={() => setShowCreate(false)} className="text-sm theme-muted hover:theme-text">{c.cancel[lang]}</button>
              {mode === "manual" && (
                <button type="button" onClick={create} className="agents-btn-primary">{c.create[lang]}</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
