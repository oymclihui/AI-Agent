"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Plus, Bot, Trash2, Sparkles, PenLine, Loader2, RefreshCw,
  Search, Layers,
} from "lucide-react";
import { agentsApi, modelsApi, skillsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { canDeleteAgentsOrSkills } from "@/lib/permissions";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";
import {
  AGENT_CATEGORIES,
  FEATURED_SCENES,
  agentAvatarTone,
  agentCategory,
  agentPopularity,
  agentTags,
  isCustomAgent,
  type AgentCategoryId,
} from "@/lib/agentCatalog";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";

interface Agent {
  id: string; name: string; role: string; goal: string;
  status: string; llm_provider: string | null; llm_model: string | null;
  temperature: number; tools_config: Array<{ tool_name: string }> | null;
  skills_config?: Array<{ skill_id: string }> | null;
  created_at?: string;
  metadata?: { from_deposit?: boolean; source_conversation_id?: string };
}

interface SkillOption { id: string; display_name: string; slug: string; status: string; }

interface ModelOption { provider: string; model_id: string; is_default?: boolean; }

const BUILTIN_TOOLS = ["web_search", "calculator", "http_request", "datetime", "desktop_list_demos", "desktop_replay", "desktop_capture"];

export default function AgentsPage() {
  const router = useRouter();
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const canDelete = canDeleteAgentsOrSkills(user);
  const a = translations.agents;
  const c = translations.common;
  const chatT = translations.chat;

  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [category, setCategory] = useState<AgentCategoryId>("all");
  const [sortBy, setSortBy] = useState<"hot" | "new">("hot");
  const [myExpertsOnly, setMyExpertsOnly] = useState(false);
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
    if (!canDelete) {
      toast.error(a.deleteForbidden[lang]);
      return;
    }
    if (!confirm(a.deleteConfirm[lang])) return;
    try {
      await agentsApi.delete(id);
      toast.success(lang === "zh" ? "已删除" : "Deleted");
      load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) toast.error(a.deleteForbidden[lang]);
      else toast.error(lang === "zh" ? "删除失败" : "Delete failed");
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

  const filteredAgents = useMemo(() => {
    let list = [...agents];
    if (myExpertsOnly) {
      list = list.filter(isCustomAgent);
    }
    if (category !== "all") {
      list = list.filter((agent) => agentCategory(agent) === category);
    }
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (agent) =>
          agent.name.toLowerCase().includes(q) ||
          agent.role.toLowerCase().includes(q) ||
          agent.goal.toLowerCase().includes(q),
      );
    }
    if (sortBy === "hot") {
      list.sort((x, y) => agentPopularity(y) - agentPopularity(x));
    } else {
      list.sort((x, y) => {
        const ta = x.created_at ? new Date(x.created_at).getTime() : 0;
        const tb = y.created_at ? new Date(y.created_at).getTime() : 0;
        return tb - ta;
      });
    }
    return list;
  }, [agents, category, myExpertsOnly, searchQuery, sortBy]);

  const sceneAgents = (sceneId: AgentCategoryId) =>
    agents.filter((agent) => agentCategory(agent) === sceneId).slice(0, 4);

  const summonAgent = (agentId: string) => {
    router.push(`/chat?agent=${agentId}`);
  };

  const agentInitial = (name: string) => (name.trim()[0] || "A").toUpperCase();

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
    <div className="agents-hub">
      <div className="agents-hub-header">
        <div>
          <h1>{a.title[lang]}</h1>
          <p>{a.subtitle[lang]}</p>
        </div>
        <div className="agents-hub-actions">
          <button
            type="button"
            onClick={importAgencyLibrary}
            disabled={agencyLoading}
            className="agents-btn-secondary agents-btn-purple disabled:opacity-50"
          >
            {agencyLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {a.agencyImportAll[lang]}
          </button>
          <button type="button" onClick={seedTemplates} className="agents-btn-secondary">
            <RefreshCw className="h-4 w-4" /> {a.seedTemplates[lang]}
          </button>
          <button type="button" onClick={openCreate} className="agents-btn-primary">
            <Plus className="h-4 w-4" /> {a.newAgent[lang]}
          </button>
        </div>
      </div>

      <div className="agents-hub-toolbar">
        <div className="agents-hub-tabs">
          <span className="agents-hub-tab agents-hub-tab-active">{a.tabExpert[lang]}</span>
          <Link href="/skills" className="agents-hub-tab">{a.tabSkill[lang]}</Link>
          <Link href="/chat" className="agents-hub-tab">{a.tabConnector[lang]}</Link>
        </div>
        <div className="agents-hub-search">
          <Search className="h-4 w-4 shrink-0 theme-muted" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={a.searchPlaceholder[lang]}
          />
        </div>
        <button
          type="button"
          onClick={() => setMyExpertsOnly((v) => !v)}
          className={`agents-hub-my-btn${myExpertsOnly ? " agents-hub-my-btn-active" : ""}`}
        >
          {a.myExperts[lang]}
        </button>
      </div>

      {!loading && agents.length > 0 && (
        <section className="agents-featured">
          <h2 className="agents-featured-title">{a.featuredScenes[lang]}</h2>
          <CapsuleScrollRow
            scrollStep={268}
            scrollLeftLabel={chatT.scrollLeft[lang]}
            scrollRightLabel={chatT.scrollRight[lang]}
            innerClassName="agents-featured-scroll"
          >
            {FEATURED_SCENES.map((scene) => {
              const items = sceneAgents(scene.id);
              return (
                <button
                  key={scene.id}
                  type="button"
                  className={`agents-scene-card ${scene.tone}`}
                  onClick={() => setCategory(scene.id)}
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
          {AGENT_CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setCategory(cat.id)}
              className={`agents-filter-pill${category === cat.id ? " agents-filter-pill-active" : ""}`}
            >
              {lang === "zh" ? cat.label.zh : cat.label.en}
            </button>
          ))}
        </CapsuleScrollRow>
        <div className="agents-sort">
          <button
            type="button"
            onClick={() => setSortBy("hot")}
            className={`agents-sort-btn${sortBy === "hot" ? " agents-sort-btn-active" : ""}`}
          >
            {a.sortHot[lang]}
          </button>
          <button
            type="button"
            onClick={() => setSortBy("new")}
            className={`agents-sort-btn${sortBy === "new" ? " agents-sort-btn-active" : ""}`}
          >
            {a.sortNew[lang]}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="theme-muted text-sm">{c.loading[lang]}</div>
      ) : filteredAgents.length === 0 ? (
        <div className="agents-empty">
          <Bot className="mb-4 h-12 w-12 opacity-40" />
          <p>{agents.length === 0 ? a.noAgents[lang] : (lang === "zh" ? "没有匹配的专家" : "No matching experts")}</p>
        </div>
      ) : (
        <div className="agents-grid">
          {filteredAgents.map((agent) => {
            const tags = agentTags(agent);
            const fromChat = agent.metadata?.from_deposit || agent.metadata?.source_conversation_id;
            const isSenior = (agent.skills_config?.length ?? 0) >= 2;
            return (
              <article key={agent.id} className="agents-card">
                <div className="agents-card-top">
                  <div className={`agents-avatar ${agentAvatarTone(agent.id)}`} aria-hidden>
                    {agentInitial(agent.name)}
                  </div>
                  <div className="agents-card-head">
                    <div className="agents-card-title-row">
                      <h3 title={agent.name}>{agent.name}</h3>
                      {fromChat ? (
                        <span className="agents-badge agents-badge-chat">{a.fromChat[lang]}</span>
                      ) : isSenior ? (
                        <span className="agents-badge agents-badge-master">{a.badgeMaster[lang]}</span>
                      ) : (
                        <span className="agents-badge agents-badge-beta">{a.badgeBeta[lang]}</span>
                      )}
                    </div>
                    <p className="agents-card-role">{agent.role}</p>
                  </div>
                </div>
                <p className="agents-card-desc">{agent.goal}</p>
                <div className="agents-card-tags">
                  {tags.map((tag) => (
                    <span key={`${agent.id}-${tag}`} className="agents-tag">{tag}</span>
                  ))}
                  {(agent.skills_config ?? []).slice(0, 2).map((sk) => (
                    <span key={sk.skill_id} className="agents-tag">{skillName(sk.skill_id)}</span>
                  ))}
                </div>
                <div className="agents-card-footer">
                  <span className="agents-card-meta">
                    {agent.llm_provider}/{agent.llm_model}
                  </span>
                  <div className="agents-card-actions">
                    <button
                      type="button"
                      onClick={() => openSkillEdit(agent)}
                      className="agents-icon-btn"
                      title={a.editSkills[lang]}
                    >
                      <Layers className="h-3.5 w-3.5" />
                    </button>
                    {canDelete && (
                      <button
                        type="button"
                        onClick={() => deleteAgent(agent.id)}
                        className="agents-icon-btn agents-icon-btn-danger"
                        title={c.delete[lang]}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => summonAgent(agent.id)}
                      className="agents-summon-btn"
                    >
                      {a.summon[lang]}
                    </button>
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
            <h2 className="mb-4 text-lg font-semibold theme-text">{a.newAgent[lang]}</h2>

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
          <div className="theme-card w-full max-w-md p-6">
            <h2 className="mb-2 text-lg font-semibold theme-text">{a.editSkills[lang]}</h2>
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
