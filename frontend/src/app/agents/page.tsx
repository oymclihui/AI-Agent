"use client";

import { useEffect, useState } from "react";
import {
  Plus, Bot, Trash2, Sparkles, PenLine, Loader2, RefreshCw,
  Search, Code2, Megaphone, BarChart2, ShieldCheck, Layers, Globe, Server,
} from "lucide-react";
import { agentsApi, modelsApi, skillsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

interface Agent {
  id: string; name: string; role: string; goal: string;
  status: string; llm_provider: string | null; llm_model: string | null;
  temperature: number; tools_config: Array<{ tool_name: string }> | null;
  skills_config?: Array<{ skill_id: string }> | null;
}

interface SkillOption { id: string; display_name: string; slug: string; status: string; }

interface ModelOption { provider: string; model_id: string; is_default?: boolean; }

const BUILTIN_TOOLS = ["web_search", "calculator", "http_request", "datetime"];

const ROLE_ICONS: Record<string, typeof Bot> = {
  research: Search, code: Code2, marketing: Megaphone, data: BarChart2,
  security: ShieldCheck, product: Layers, translate: Globe, devops: Server,
};

function pickIcon(role: string) {
  const r = role.toLowerCase();
  if (r.includes("research") || r.includes("analyst")) return ROLE_ICONS.research;
  if (r.includes("engineer") || r.includes("code") || r.includes("developer")) return ROLE_ICONS.code;
  if (r.includes("content") || r.includes("marketing") || r.includes("copy")) return ROLE_ICONS.marketing;
  if (r.includes("data")) return ROLE_ICONS.data;
  if (r.includes("security") || r.includes("cyber")) return ROLE_ICONS.security;
  if (r.includes("product")) return ROLE_ICONS.product;
  if (r.includes("translat") || r.includes("local")) return ROLE_ICONS.translate;
  if (r.includes("devops") || r.includes("sre")) return ROLE_ICONS.devops;
  return Bot;
}

export default function AgentsPage() {
  const { lang } = useLangStore();
  const a = translations.agents;
  const c = translations.common;

  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showSkillEdit, setShowSkillEdit] = useState<string | null>(null);
  const [skillEditIds, setSkillEditIds] = useState<string[]>([]);
  const [savingSkills, setSavingSkills] = useState(false);
  const [mode, setMode] = useState<"nl" | "manual">("nl");
  const [nlText, setNlText] = useState("");
  const [generating, setGenerating] = useState(false);
  const [agencyLoading, setAgencyLoading] = useState(false);
  const [form, setForm] = useState({
    name: "", role: "", goal: "", backstory: "",
    llm_provider: "ollama", llm_model: "qwen3.6:35b",
    temperature: 0.7, max_iterations: 10,
    tools_config: [] as string[],
    skills_config: [] as string[],
  });

  const load = async () => {
    try {
      const { data } = await agentsApi.list(lang);
      setAgents(data);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load agents");
    } finally {
      setLoading(false);
    }
  };

  const loadModels = async () => {
    try {
      const { data } = await modelsApi.listConfigs();
      setModels(data);
      const def = data.find((m: ModelOption) => m.is_default) ?? data[0];
      if (def) setForm((f) => ({ ...f, llm_provider: def.provider, llm_model: def.model_id }));
    } catch { /* keep defaults */ }
  };

  const loadSkills = async () => {
    try {
      const { data } = await skillsApi.list(lang);
      setSkills(data.filter((s: SkillOption) => s.status === "active"));
    } catch { /* optional */ }
  };

  useEffect(() => { load(); loadModels(); }, [lang]);
  useEffect(() => { loadSkills(); }, [lang]);

  const openCreate = () => {
    setMode("nl");
    setNlText("");
    setShowCreate(true);
  };

  const generateFromNL = async () => {
    if (nlText.trim().length < 5) return;
    setGenerating(true);
    try {
      await agentsApi.generate(nlText.trim());
      toast.success(lang === "zh" ? "智能体已生成" : "Agent generated");
      setShowCreate(false);
      setNlText("");
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? (lang === "zh" ? "生成失败" : "Generation failed"));
    } finally {
      setGenerating(false);
    }
  };

  const create = async () => {
    try {
      await agentsApi.create({
        ...form,
        tools_config: form.tools_config.map((t) => ({ tool_name: t })),
        skills_config: form.skills_config.map((skill_id) => ({ skill_id, always_load: true, priority: 0 })),
      });
      toast.success(lang === "zh" ? "创建成功" : "Agent created");
      setShowCreate(false);
      load();
    } catch {
      toast.error(lang === "zh" ? "创建失败" : "Failed to create agent");
    }
  };

  const deleteAgent = async (id: string) => {
    if (!confirm(a.deleteConfirm[lang])) return;
    try {
      await agentsApi.delete(id);
      toast.success(lang === "zh" ? "已删除" : "Deleted");
      load();
    } catch {
      toast.error(lang === "zh" ? "删除失败" : "Delete failed");
    }
  };

  const openSkillEdit = (agent: Agent) => {
    setShowSkillEdit(agent.id);
    setSkillEditIds((agent.skills_config ?? []).map((s) => s.skill_id));
  };

  const saveSkillEdit = async () => {
    if (!showSkillEdit) return;
    setSavingSkills(true);
    try {
      await agentsApi.update(showSkillEdit, {
        skills_config: skillEditIds.map((skill_id) => ({ skill_id, always_load: true, priority: 0 })),
      });
      toast.success(lang === "zh" ? "技能已更新" : "Skills updated");
      setShowSkillEdit(null);
      load();
    } catch {
      toast.error(lang === "zh" ? "更新失败" : "Update failed");
    } finally {
      setSavingSkills(false);
    }
  };

  const skillName = (id: string) => skills.find((s) => s.id === id)?.display_name ?? id.slice(0, 8);

  const seedTemplates = async () => {
    try {
      await agentsApi.seedTemplates();
      toast.success(lang === "zh" ? "模板已加载" : "Templates loaded");
      load();
    } catch {
      toast.error(lang === "zh" ? "加载模板失败" : "Failed to load templates");
    }
  };

  const importAgencyLibrary = async () => {
    setAgencyLoading(true);
    try {
      await agentsApi.librarySync();
      const { data } = await agentsApi.libraryImport({ import_all: true, import_skills: true, overwrite: true });
      await agentsApi.libraryI18nBackfill();
      const count = (data.imported_agents as string[] | undefined)?.length ?? 0;
      const skills = (data.imported_skills as string[] | undefined)?.length ?? 0;
      toast.success(
        lang === "zh"
          ? `已导入 ${count} 个 Agency 角色${skills ? `、${skills} 个 SOP 技能` : ""}`
          : `Imported ${count} Agency roles${skills ? ` and ${skills} SOP skills` : ""}`,
      );
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? a.agencyImportFail[lang]);
    } finally {
      setAgencyLoading(false);
    }
  };

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{a.title[lang]}</h1>
          <p className="text-slate-400">{a.subtitle[lang]}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={importAgencyLibrary}
            disabled={agencyLoading}
            className="flex items-center gap-2 rounded-lg border border-purple-500/40 px-4 py-2 text-sm text-purple-300 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
          >
            {agencyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {a.agencyImportAll[lang]}
          </button>
          <button
            onClick={seedTemplates}
            className="flex items-center gap-2 rounded-lg border border-[#2d2d4e] px-4 py-2 text-sm text-slate-300 hover:bg-white/5 transition-colors"
          >
            <RefreshCw className="h-4 w-4" /> {a.seedTemplates[lang]}
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" /> {a.newAgent[lang]}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-slate-400">{c.loading[lang]}</div>
      ) : agents.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#2d2d4e] py-16 text-center">
          <Bot className="mb-4 h-12 w-12 text-slate-600" />
          <p className="text-slate-400">{a.noAgents[lang]}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => {
            const Icon = pickIcon(agent.role);
            return (
              <div key={agent.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5">
                <div className="mb-3 flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/20">
                      <Icon className="h-4 w-4 text-blue-400" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-white">{agent.name}</h3>
                      <p className="text-xs text-blue-400">{agent.role}</p>
                    </div>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${agent.status === "active" ? "bg-green-500/20 text-green-400" : "bg-slate-500/20 text-slate-400"}`}>
                    {agent.status === "active" ? c.active[lang] : c.inactive[lang]}
                  </span>
                </div>
                <p className="mb-4 line-clamp-2 text-sm text-slate-400">{agent.goal}</p>
                <div className="mb-4 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span className="rounded bg-slate-700/50 px-2 py-0.5">{agent.llm_provider}/{agent.llm_model}</span>
                  {(agent.tools_config ?? []).map((t) => (
                    <span key={t.tool_name} className="rounded bg-purple-500/10 px-2 py-0.5 text-purple-400">{t.tool_name}</span>
                  ))}
                  {(agent.skills_config ?? []).map((sk) => (
                    <span key={sk.skill_id} className="rounded bg-teal-500/10 px-2 py-0.5 text-teal-400">{skillName(sk.skill_id)}</span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => openSkillEdit(agent)}
                    className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-teal-400 hover:bg-teal-500/10 transition-colors"
                  >
                    {a.editSkills[lang]}
                  </button>
                  <button
                    onClick={() => deleteAgent(agent.id)}
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
            <h2 className="mb-4 text-lg font-semibold text-white">{a.newAgent[lang]}</h2>

            <div className="mb-4 flex rounded-lg border border-[#2d2d4e] p-0.5 text-sm">
              <button
                onClick={() => setMode("nl")}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md py-2 ${mode === "nl" ? "bg-blue-600 text-white" : "text-slate-400"}`}
              >
                <Sparkles className="h-3.5 w-3.5" /> {a.nlMode[lang]}
              </button>
              <button
                onClick={() => setMode("manual")}
                className={`flex flex-1 items-center justify-center gap-1 rounded-md py-2 ${mode === "manual" ? "bg-blue-600 text-white" : "text-slate-400"}`}
              >
                <PenLine className="h-3.5 w-3.5" /> {a.manualMode[lang]}
              </button>
            </div>

            {mode === "nl" ? (
              <div className="space-y-3">
                <textarea
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-blue-500 focus:outline-none"
                  rows={5}
                  placeholder={a.nlPlaceholder[lang]}
                  value={nlText}
                  onChange={(e) => setNlText(e.target.value)}
                />
                <button
                  onClick={generateFromNL}
                  disabled={generating || nlText.trim().length < 5}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2.5 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
                >
                  {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  {generating ? a.generating[lang] : a.generate[lang]}
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {[
                  { key: "name", label: c.name[lang], placeholder: a.namePlaceholder[lang] },
                  { key: "role", label: a.role[lang], placeholder: a.rolePlaceholder[lang] },
                  { key: "goal", label: a.goal[lang], placeholder: a.goalPlaceholder[lang], textarea: true },
                  { key: "backstory", label: a.backstory[lang], placeholder: "", textarea: true },
                ].map(({ key, label, placeholder, textarea }) => (
                  <div key={key}>
                    <label className="mb-1 block text-xs text-slate-400">{label}</label>
                    {textarea ? (
                      <textarea
                        className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        rows={2}
                        placeholder={placeholder}
                        value={form[key as "name" | "role" | "goal" | "backstory"]}
                        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                      />
                    ) : (
                      <input
                        type="text"
                        className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        placeholder={placeholder}
                        value={form[key as "name" | "role" | "goal" | "backstory"]}
                        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                      />
                    )}
                  </div>
                ))}
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.selectModel[lang]}</label>
                  <select
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    value={`${form.llm_provider}::${form.llm_model}`}
                    onChange={(e) => {
                      const [provider, model_id] = e.target.value.split("::");
                      setForm((f) => ({ ...f, llm_provider: provider, llm_model: model_id }));
                    }}
                  >
                    {models.map((m) => (
                      <option key={m.model_id} value={`${m.provider}::${m.model_id}`}>
                        {m.provider}/{m.model_id}{m.is_default ? " ★" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.tools[lang]}</label>
                  <div className="flex flex-wrap gap-2">
                    {BUILTIN_TOOLS.map((tool) => (
                      <label key={tool} className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[#2d2d4e] px-2 py-1 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={form.tools_config.includes(tool)}
                          onChange={(e) => setForm((f) => ({
                            ...f,
                            tools_config: e.target.checked
                              ? [...f.tools_config, tool]
                              : f.tools_config.filter((t) => t !== tool),
                          }))}
                        />
                        {tool}
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.skills[lang]}</label>
                  <p className="mb-2 text-[11px] text-slate-600">{a.skillsHint[lang]}</p>
                  {skills.length === 0 ? (
                    <p className="text-xs text-slate-500">{lang === "zh" ? "请先在「技能」页创建并发布技能" : "Create and publish skills first"}</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {skills.map((skill) => (
                        <label key={skill.id} className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[#2d2d4e] px-2 py-1 text-xs text-slate-300">
                          <input
                            type="checkbox"
                            checked={form.skills_config.includes(skill.id)}
                            onChange={(e) => setForm((f) => ({
                              ...f,
                              skills_config: e.target.checked
                                ? [...f.skills_config, skill.id]
                                : f.skills_config.filter((id) => id !== skill.id),
                            }))}
                          />
                          {skill.display_name}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={create}
                  className="w-full rounded-lg bg-blue-600 py-2.5 text-sm text-white hover:bg-blue-700"
                >
                  {c.create[lang]}
                </button>
              </div>
            )}

            <button
              onClick={() => setShowCreate(false)}
              className="mt-4 w-full rounded-lg py-2 text-sm text-slate-400 hover:text-white"
            >
              {c.cancel[lang]}
            </button>
          </div>
        </div>
      )}

      {showSkillEdit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-2 text-lg font-semibold text-white">{a.editSkills[lang]}</h2>
            <p className="mb-4 text-xs text-slate-500">{a.skillsHint[lang]}</p>
            <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto">
              {skills.map((skill) => (
                <label key={skill.id} className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-[#2d2d4e] px-2 py-1 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={skillEditIds.includes(skill.id)}
                    onChange={(e) => setSkillEditIds((ids) =>
                      e.target.checked ? [...ids, skill.id] : ids.filter((id) => id !== skill.id)
                    )}
                  />
                  {skill.display_name}
                </label>
              ))}
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowSkillEdit(null)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white">{c.cancel[lang]}</button>
              <button onClick={saveSkillEdit} disabled={savingSkills} className="rounded-lg bg-teal-600 px-4 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-40">{c.save[lang]}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
