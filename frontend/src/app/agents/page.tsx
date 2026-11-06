"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Plus, Bot, Trash2, Sparkles, PenLine, Loader2, RefreshCw,
  Search, Layers, Share2, Copy, MessageSquare,
} from "lucide-react";
import { agentsApi, modelsApi, skillsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { canDeleteAgent } from "@/lib/permissions";
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
  owner_id?: string | null;
  visibility?: "private" | "shared" | "org" | "platform";
  is_owner?: boolean;
  can_manage?: boolean;
  status: string; llm_provider: string | null; llm_model: string | null;
  temperature: number; tools_config: Array<{ tool_name: string }> | null;
  skills_config?: Array<{ skill_id: string }> | null;
  created_at?: string;
  metadata?: { from_deposit?: boolean; source_conversation_id?: string };
}

interface SkillOption { id: string; display_name: string; slug: string; status: string; }

interface ModelOption { provider: string; model_id: string; is_default?: boolean; }

const BUILTIN_TOOLS = ["web_search", "calculator", "http_request", "datetime", "desktop_list_demos", "desktop_replay", "desktop_capture"];

type AgentListScope = "usable" | "mine" | "shared" | "org" | "platform";

interface ShareTargetUser { id: string; display_name: string; employee_no?: string | null; }
interface ShareTargetDepartment { id: string; name: string; path: string; }
interface ShareGrant { grantee_type: "user" | "department"; grantee_id: string; permission: "use"; grantee_name?: string; }

interface WecomBot {
  bot_id: string;
  bot_id_masked: string;
  bot_name?: string;
  secret_set: boolean;
  enabled: boolean;
  connection: { state: string; raw?: string };
  binding: { id: string; name: string; enabled: boolean } | null;
}

interface WecomAgentState {
  agent_id: string;
  bound: boolean;
  bot_id: string;
  bot_id_masked: string;
  enabled: boolean;
  chat_ids: string[];
  reply_template: string;
  style?: Record<string, unknown>;
  bot_configured: boolean;
  bot_config_enabled: boolean;
  receiver_chat_ids: string[];
  connection: { state: string; raw?: string };
}

const WECOM_TEMPLATE_PRESETS: Record<string, string> = {
  standard: "{结论}\n\n{分析}\n{建议}\n{行数}",
  concise: "{结论}\n\n{行数}",
  detail: "{分析}\n{行数}",
};

const inferWecomPreset = (template: string): string => {
  const value = template.trim();
  if (!value || value === WECOM_TEMPLATE_PRESETS.standard) return "standard";
  if (value === WECOM_TEMPLATE_PRESETS.concise) return "concise";
  if (value === WECOM_TEMPLATE_PRESETS.detail) return "detail";
  return "custom";
};

export default function AgentsPage() {
  const router = useRouter();
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
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
  const [listScope, setListScope] = useState<AgentListScope>("usable");
  const [showShare, setShowShare] = useState<string | null>(null);
  const [shareVisibility, setShareVisibility] = useState<"private" | "shared" | "org">("private");
  const [shareUserIds, setShareUserIds] = useState<string[]>([]);
  const [shareDeptIds, setShareDeptIds] = useState<string[]>([]);
  const [shareUsers, setShareUsers] = useState<ShareTargetUser[]>([]);
  const [shareDepts, setShareDepts] = useState<ShareTargetDepartment[]>([]);
  const [shareSearch, setShareSearch] = useState("");
  const [savingShare, setSavingShare] = useState(false);
  const [showNameEdit, setShowNameEdit] = useState<string | null>(null);
  const [nameEditValue, setNameEditValue] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [showWecom, setShowWecom] = useState<string | null>(null);
  const [wecomState, setWecomState] = useState<WecomAgentState | null>(null);
  const [wecomBots, setWecomBots] = useState<WecomBot[]>([]);
  const [wecomConfigured, setWecomConfigured] = useState(false);
  const [wecomEnabled, setWecomEnabled] = useState(false);
  const [wecomLoading, setWecomLoading] = useState(false);
  const [wecomSaving, setWecomSaving] = useState(false);
  const [wecomTesting, setWecomTesting] = useState(false);
  const [wecomTemplate, setWecomTemplate] = useState("");
  const [wecomStyle, setWecomStyle] = useState<Record<string, unknown>>({});
  const [wecomPreset, setWecomPreset] = useState("standard");
  const [wecomConflict, setWecomConflict] = useState<{ name: string } | null>(null);
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
      const { data } = await agentsApi.list(lang, listScope);
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

  const loadWecomBots = async () => {
    try {
      const { data } = await agentsApi.wecomBots();
      setWecomBots(data?.bots ?? []);
      setWecomConfigured(!!data?.configured);
    } catch { /* optional */ }
  };

  useEffect(() => { setLoading(true); load(); loadModels(); }, [lang, listScope]);
  useEffect(() => { loadSkills(); }, [lang]);
  useEffect(() => { void loadWecomBots(); }, []);

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

  const deleteAgent = async (agent: Agent) => {
    if (!canDeleteAgent(user, agent)) {
      toast.error(a.deleteForbidden[lang]);
      return;
    }
    if (!confirm(a.deleteConfirm[lang])) return;
    try {
      await agentsApi.delete(agent.id);
      toast.success(lang === "zh" ? "已删除" : "Deleted");
      load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) toast.error(a.deleteForbidden[lang]);
      else toast.error(lang === "zh" ? "删除失败" : "Delete failed");
    }
  };

  const copyAgent = async (agentId: string) => {
    try {
      await agentsApi.copy(agentId);
      toast.success(a.copyOk[lang]);
      setListScope("mine");
      load();
    } catch {
      toast.error(lang === "zh" ? "复制失败" : "Copy failed");
    }
  };

  const openShare = async (agentId: string) => {
    setShowShare(agentId);
    try {
      const [{ data: sharing }, { data: targets }] = await Promise.all([
        agentsApi.getSharing(agentId),
        agentsApi.shareTargets(""),
      ]);
      setShareVisibility(sharing.visibility === "org" ? "org" : sharing.visibility === "shared" ? "shared" : "private");
      setShareUserIds(
        (sharing.grants as ShareGrant[]).filter((g) => g.grantee_type === "user").map((g) => g.grantee_id),
      );
      setShareDeptIds(
        (sharing.grants as ShareGrant[]).filter((g) => g.grantee_type === "department").map((g) => g.grantee_id),
      );
      setShareDepts(targets.departments ?? []);
      setShareUsers(targets.users ?? []);
    } catch {
      toast.error(lang === "zh" ? "加载共享设置失败" : "Failed to load sharing");
      setShowShare(null);
    }
  };

  useEffect(() => {
    if (!showShare) return;
    const t = setTimeout(() => {
      agentsApi.shareTargets(shareSearch).then(({ data }) => {
        setShareUsers(data.users ?? []);
        if (!shareSearch.trim()) setShareDepts(data.departments ?? []);
      }).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [showShare, shareSearch]);

  const saveShare = async () => {
    if (!showShare) return;
    setSavingShare(true);
    try {
      const grants = [
        ...shareUserIds.map((id) => ({ grantee_type: "user" as const, grantee_id: id, permission: "use" as const })),
        ...shareDeptIds.map((id) => ({ grantee_type: "department" as const, grantee_id: id, permission: "use" as const })),
      ];
      await agentsApi.updateSharing(showShare, {
        visibility: shareVisibility,
        grants: shareVisibility === "shared" ? grants : [],
      });
      toast.success(lang === "zh" ? "共享已保存" : "Sharing saved");
      setShowShare(null);
      load();
    } catch {
      toast.error(lang === "zh" ? "保存失败" : "Save failed");
    } finally {
      setSavingShare(false);
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

  const canEditAgent = (agent: Agent) => !!agent.is_owner || !!agent.can_manage;

  const visibilityLabel = (v?: Agent["visibility"]) => {
    if (v === "platform") return a.badgeOrg[lang];
    if (v === "org") return a.badgeOrg[lang];
    if (v === "shared") return a.badgeShared[lang];
    return a.badgePrivate[lang];
  };

  const scopeTabs: { id: AgentListScope; label: string }[] = [
    { id: "usable", label: a.scopeUsable[lang] },
    { id: "mine", label: a.scopeMine[lang] },
    { id: "shared", label: a.scopeShared[lang] },
    { id: "org", label: a.scopeOrg[lang] },
    { id: "platform", label: a.scopePlatform[lang] },
  ];

  const openNameEdit = (agent: Agent) => {
    setShowNameEdit(agent.id);
    setNameEditValue(agent.name);
  };

  const saveNameEdit = async () => {
    if (!showNameEdit) return;
    const trimmed = nameEditValue.trim();
    if (!trimmed) {
      toast.error(lang === "zh" ? "名称不能为空" : "Name is required");
      return;
    }
    setSavingName(true);
    try {
      await agentsApi.update(showNameEdit, { name: trimmed });
      toast.success(lang === "zh" ? "名称已更新" : "Name updated");
      setShowNameEdit(null);
      load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) toast.error(a.editForbidden[lang]);
      else toast.error(lang === "zh" ? "更新失败" : "Update failed");
    } finally {
      setSavingName(false);
    }
  };

  const skillName = (id: string) => skills.find((s) => s.id === id)?.display_name ?? id.slice(0, 8);

  const wecomBoundAgentId = (agentId: string) =>
    wecomBots.find((b) => b.binding?.id === agentId && b.binding?.enabled)?.binding?.id ?? "";

  const openWecom = async (agentId: string) => {
    setShowWecom(agentId);
    setWecomState(null);
    setWecomConflict(null);
    setWecomLoading(true);
    try {
      const [{ data: state }] = await Promise.all([agentsApi.getWecom(agentId), loadWecomBots()]);
      setWecomState(state);
      setWecomEnabled(!!state.enabled);
      const template = (state as WecomAgentState | null)?.reply_template ?? "";
      setWecomTemplate(template);
      setWecomPreset(inferWecomPreset(template));
      setWecomStyle(((state as WecomAgentState | null)?.style as Record<string, unknown>) ?? {});
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      toast.error(
        status === 403
          ? (lang === "zh" ? "仅智能体所有者或管理员可配置企业微信" : "Only the owner or an admin can configure WeCom")
          : (lang === "zh" ? "加载企业微信配置失败" : "Failed to load WeCom config"),
      );
      setShowWecom(null);
    } finally {
      setWecomLoading(false);
    }
  };

  // 样式覆盖：留空（继承）时删除该键，只把用户明确选择的项提交给后端
  const setOverride = (key: string, value: unknown) => {
    setWecomStyle((prev) => {
      const next = { ...prev };
      if (value === "" || value === undefined || value === null || value === "inherit") {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  };

  const saveWecom = async (force = false) => {
    if (!showWecom) return;
    const botId = wecomState?.bot_id || wecomBots[0]?.bot_id || "";
    if (!botId) {
      toast.error(a.wecomNone[lang]);
      return;
    }
    setWecomSaving(true);
    setWecomConflict(null);
    try {
      await agentsApi.saveWecom(showWecom, {
        bot_id: botId,
        enabled: wecomEnabled,
        chat_ids: wecomState?.chat_ids ?? [],
        reply_template: wecomTemplate.trim(),
        style: wecomStyle,
        force,
      });
      toast.success(
        wecomEnabled
          ? (lang === "zh" ? "已关联并启用" : "Linked and enabled")
          : (lang === "zh" ? "已保存（当前未启用）" : "Saved (disabled)"),
      );
      setShowWecom(null);
      void load();
      void loadWecomBots();
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
      const detail = resp?.data?.detail;
      if (resp?.status === 409 && detail && typeof detail === "object") {
        const payload = detail as { detail?: string; conflict_agent?: { name?: string } };
        setWecomConflict({ name: payload.conflict_agent?.name ?? "" });
        toast.error(payload.detail ?? a.wecomConflict[lang]);
      } else {
        toast.error(typeof detail === "string" ? detail : (lang === "zh" ? "保存失败" : "Save failed"));
      }
    } finally {
      setWecomSaving(false);
    }
  };

  const testWecom = async () => {
    if (!showWecom) return;
    setWecomTesting(true);
    try {
      const { data } = await agentsApi.testWecom(showWecom);
      if (data?.ok) {
        toast.success(a.wecomTestOk[lang]);
      } else {
        const errors = (data?.errors as Array<{ error?: string }> | undefined) ?? [];
        toast.error(errors[0]?.error || data?.error || (lang === "zh" ? "测试消息发送失败" : "Test message failed"));
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : (lang === "zh" ? "测试失败" : "Test failed"));
    } finally {
      setWecomTesting(false);
    }
  };

  const unbindWecom = async () => {
    if (!showWecom) return;
    if (!confirm(a.wecomUnbindConfirm[lang])) return;
    try {
      await agentsApi.deleteWecom(showWecom);
      toast.success(lang === "zh" ? "已解除关联" : "Unlinked");
      setShowWecom(null);
      void load();
      void loadWecomBots();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : (lang === "zh" ? "解除失败" : "Unlink failed"));
    }
  };
  const wecomStatusLabel = () => {
    const state = wecomState?.connection?.state;
    if (!wecomState?.bot_config_enabled) return a.wecomDisabled[lang];
    if (state === "online") return a.wecomOnline[lang];
    if (state === "disabled") return a.wecomDisabled[lang];
    return a.wecomOffline[lang];
  };


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

      <div className="agents-filter-row mb-3">
        <CapsuleScrollRow
          centerWhenFit
          className="flex-1 min-w-0"
          scrollLeftLabel={chatT.scrollLeft[lang]}
          scrollRightLabel={chatT.scrollRight[lang]}
          innerClassName="agents-filter-scroll"
        >
          {scopeTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setListScope(tab.id)}
              className={`agents-filter-pill${listScope === tab.id ? " agents-filter-pill-active" : ""}`}
            >
              {tab.label}
            </button>
          ))}
        </CapsuleScrollRow>
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
                        <span className="agents-badge agents-badge-beta">{visibilityLabel(agent.visibility)}</span>
                      )}
                      {wecomBoundAgentId(agent.id) && (
                        <span className="agents-badge agents-badge-chat">{a.wecom[lang]}</span>
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
                    {agent.is_owner && (
                      <button
                        type="button"
                        onClick={() => openShare(agent.id)}
                        className="agents-icon-btn"
                        title={a.share[lang]}
                      >
                        <Share2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {(canEditAgent(agent) || !!user?.is_admin) && (
                      <button
                        type="button"
                        onClick={() => void openWecom(agent.id)}
                        className="agents-icon-btn"
                        title={a.wecom[lang]}
                      >
                        <MessageSquare className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {canEditAgent(agent) && (
                      <button
                        type="button"
                        onClick={() => openNameEdit(agent)}
                        className="agents-icon-btn"
                        title={a.editName[lang]}
                      >
                        <PenLine className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => openSkillEdit(agent)}
                      className="agents-icon-btn"
                      title={a.editSkills[lang]}
                      disabled={!canEditAgent(agent)}
                    >
                      <Layers className="h-3.5 w-3.5" />
                    </button>
                    {!agent.is_owner && agent.visibility !== "platform" && (
                      <button
                        type="button"
                        onClick={() => copyAgent(agent.id)}
                        className="agents-icon-btn"
                        title={a.copyAgent[lang]}
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {canDeleteAgent(user, agent) && (
                      <button
                        type="button"
                        onClick={() => deleteAgent(agent)}
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

      {showShare && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-2 text-lg font-semibold theme-text">{a.shareTitle[lang]}</h2>
            <p className="mb-4 text-xs text-slate-500">{a.shareHint[lang]}</p>
            <div className="mb-4 flex flex-col gap-2 text-sm">
              {([
                ["private", a.visibilityPrivate[lang]],
                ["shared", a.visibilityShared[lang]],
                ["org", a.visibilityOrg[lang]],
              ] as const).map(([val, label]) => (
                <label key={val} className="flex cursor-pointer items-center gap-2 rounded-lg border border-[#2d2d4e] px-3 py-2">
                  <input
                    type="radio"
                    name="visibility"
                    checked={shareVisibility === val}
                    onChange={() => setShareVisibility(val)}
                  />
                  {label}
                </label>
              ))}
            </div>
            {shareVisibility === "shared" && (
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.shareSearch[lang]}</label>
                  <input
                    type="search"
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                    value={shareSearch}
                    onChange={(e) => setShareSearch(e.target.value)}
                    placeholder={a.shareSearch[lang]}
                  />
                </div>
                <div>
                  <p className="mb-2 text-xs text-slate-400">{a.shareUsers[lang]}</p>
                  <div className="max-h-32 space-y-1 overflow-y-auto">
                    {shareUsers.map((u) => (
                      <label key={u.id} className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={shareUserIds.includes(u.id)}
                          onChange={(e) => setShareUserIds((ids) =>
                            e.target.checked ? [...ids, u.id] : ids.filter((x) => x !== u.id)
                          )}
                        />
                        {u.display_name}{u.employee_no ? ` (${u.employee_no})` : ""}
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="mb-2 text-xs text-slate-400">{a.shareDepts[lang]}</p>
                  <div className="max-h-32 space-y-1 overflow-y-auto">
                    {shareDepts.map((d) => (
                      <label key={d.id} className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={shareDeptIds.includes(d.id)}
                          onChange={(e) => setShareDeptIds((ids) =>
                            e.target.checked ? [...ids, d.id] : ids.filter((x) => x !== d.id)
                          )}
                        />
                        {d.name}
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowShare(null)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white">{c.cancel[lang]}</button>
              <button onClick={saveShare} disabled={savingShare} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40">{c.save[lang]}</button>
            </div>
          </div>
        </div>
      )}

      {showNameEdit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card w-full max-w-md p-6">
            <h2 className="mb-2 text-lg font-semibold theme-text">{a.editName[lang]}</h2>
            <p className="mb-4 text-xs text-slate-500">{a.editNameHint[lang]}</p>
            <label className="mb-1 block text-xs text-slate-400">{c.name[lang]}</label>
            <input
              type="text"
              className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              value={nameEditValue}
              maxLength={255}
              onChange={(e) => setNameEditValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void saveNameEdit();
              }}
              autoFocus
            />
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setShowNameEdit(null)}
                className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white"
              >
                {c.cancel[lang]}
              </button>
              <button
                onClick={saveNameEdit}
                disabled={savingName || !nameEditValue.trim()}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
              >
                {c.save[lang]}
              </button>
            </div>
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
      {showWecom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-2 text-lg font-semibold theme-text">{a.wecomTitle[lang]}</h2>
            <p className="mb-4 text-xs text-slate-500">{a.wecomHint[lang]}</p>

            {wecomLoading ? (
              <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" /> {c.loading[lang]}
              </div>
            ) : !wecomConfigured ? (
              <div className="space-y-4">
                <p className="rounded-lg border border-[#2d2d4e] px-3 py-3 text-sm text-slate-300">{a.wecomNone[lang]}</p>
                <Link
                  href="/settings/integrations"
                  onClick={() => setShowWecom(null)}
                  className="block w-full rounded-lg bg-blue-600 py-2.5 text-center text-sm text-white hover:bg-blue-700"
                >
                  {a.wecomGoConfig[lang]}
                </Link>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.wecomBot[lang]}</label>
                  <div className="flex items-center justify-between rounded-lg border border-[#2d2d4e] px-3 py-2 text-sm text-white">
                    <span>
                      {wecomState?.bot_id_masked || wecomBots[0]?.bot_id_masked || ""}
                      {wecomState?.bot_config_enabled ? "" : ` · ${a.wecomDisabled[lang]}`}
                    </span>
                    <span className={`text-xs ${wecomState?.connection?.state === "online" ? "text-emerald-400" : "text-amber-400"}`}>
                      {wecomStatusLabel()}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {lang === "zh" ? "Bot 来自「设置 → 集成 → 企业微信」。" : "The bot comes from Settings → Integrations → WeCom."}
                  </p>
                </div>

                <div>
                  <label className="flex cursor-pointer items-center justify-between rounded-lg border border-[#2d2d4e] px-3 py-2">
                    <span className="text-sm text-slate-200">{a.wecomEnable[lang]}</span>
                    <input
                      type="checkbox"
                      checked={wecomEnabled}
                      onChange={(e) => { setWecomEnabled(e.target.checked); setWecomConflict(null); }}
                    />
                  </label>
                  <p className="mt-1 text-[11px] text-slate-500">{a.wecomEnableHint[lang]}</p>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.wecomScope[lang]}</label>
                  <div className="rounded-lg border border-[#2d2d4e] px-3 py-2 text-sm text-slate-300">{a.wecomScopeAll[lang]}</div>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-slate-400">{a.wecomTemplate[lang]}</label>
                  <select
                    value={wecomPreset}
                    onChange={(e) => {
                      const preset = e.target.value;
                      setWecomPreset(preset);
                      if (preset !== "custom") setWecomTemplate(WECOM_TEMPLATE_PRESETS[preset] ?? "");
                    }}
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                  >
                    <option value="standard">{a.wecomTemplateStandard[lang]}</option>
                    <option value="concise">{a.wecomTemplateConcise[lang]}</option>
                    <option value="detail">{a.wecomTemplateDetail[lang]}</option>
                    <option value="custom">{a.wecomTemplateCustom[lang]}</option>
                  </select>
                  <textarea
                    value={wecomTemplate}
                    onChange={(e) => {
                      setWecomTemplate(e.target.value);
                      setWecomPreset(inferWecomPreset(e.target.value));
                    }}
                    rows={6}
                    maxLength={2000}
                    spellCheck={false}
                    placeholder={WECOM_TEMPLATE_PRESETS.standard}
                    className="mt-2 w-full rounded-lg border border-[#2d2d4e] bg-transparent px-3 py-2 font-mono text-xs leading-5 text-slate-200"
                  />
                  <p className="mt-1 text-[11px] text-slate-500">{a.wecomTemplateHint[lang]}</p>
                  <p className="mt-1 font-mono text-[11px] text-slate-500">{a.wecomTemplatePlaceholders[lang]}</p>
                </div>

                <details className="rounded-lg border border-[#2d2d4e] bg-[#16162a]/60 px-3 py-2">
                  <summary className="cursor-pointer select-none text-xs text-slate-300">
                    {lang === "zh" ? "样式覆盖（不选则继承全局）" : "Style override (inherit global)"}
                  </summary>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "主题色" : "Theme"}
                      <select
                        value={(wecomStyle.theme as string) ?? ""}
                        onChange={(e) => setOverride("theme", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="blue">{lang === "zh" ? "商务蓝" : "Business blue"}</option>
                        <option value="green">{lang === "zh" ? "青绿" : "Green"}</option>
                        <option value="purple">{lang === "zh" ? "紫罗兰" : "Purple"}</option>
                        <option value="orange">{lang === "zh" ? "暖橙" : "Orange"}</option>
                        <option value="dark">{lang === "zh" ? "石墨黑" : "Dark"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "字号" : "Font size"}
                      <select
                        value={(wecomStyle.font_size as string) ?? ""}
                        onChange={(e) => setOverride("font_size", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="small">{lang === "zh" ? "小" : "Small"}</option>
                        <option value="medium">{lang === "zh" ? "中" : "Medium"}</option>
                        <option value="large">{lang === "zh" ? "大" : "Large"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "表格最大行数" : "Table max rows"}
                      <input
                        type="number" min={1} max={500}
                        value={wecomStyle.table_max_rows === undefined ? "" : String(wecomStyle.table_max_rows)}
                        onChange={(e) => setOverride("table_max_rows", e.target.value === "" ? "" : Number(e.target.value))}
                        placeholder={lang === "zh" ? "继承全局" : "Inherit"}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      />
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "图表类型" : "Chart type"}
                      <select
                        value={(wecomStyle.chart_type as string) ?? ""}
                        onChange={(e) => setOverride("chart_type", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="auto">{lang === "zh" ? "自动" : "Auto"}</option>
                        <option value="bar">{lang === "zh" ? "柱状" : "Bar"}</option>
                        <option value="barh">{lang === "zh" ? "条形" : "Horizontal"}</option>
                        <option value="line">{lang === "zh" ? "折线" : "Line"}</option>
                        <option value="area">{lang === "zh" ? "面积" : "Area"}</option>
                        <option value="pie">{lang === "zh" ? "饼图" : "Pie"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "数字千分位" : "Thousands separator"}
                      <select
                        value={wecomStyle.show_thousands === undefined ? "" : wecomStyle.show_thousands ? "on" : "off"}
                        onChange={(e) =>
                          setOverride("show_thousands", e.target.value === "" ? "" : e.target.value === "on")
                        }
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="on">{lang === "zh" ? "开" : "On"}</option>
                        <option value="off">{lang === "zh" ? "关" : "Off"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "语音播报" : "Voice reply"}
                      <select
                        value={wecomStyle.voice_reply === undefined ? "" : wecomStyle.voice_reply ? "on" : "off"}
                        onChange={(e) =>
                          setOverride("voice_reply", e.target.value === "" ? "" : e.target.value === "on")
                        }
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="on">{lang === "zh" ? "开" : "On"}</option>
                        <option value="off">{lang === "zh" ? "关" : "Off"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "语音音色" : "Voice"}
                      <select
                        value={(wecomStyle.voice_name as string) ?? ""}
                        onChange={(e) => setOverride("voice_name", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="zh-CN-XiaoxiaoNeural">{lang === "zh" ? "晓晓（女声·默认）" : "Xiaoxiao (F)"}</option>
                        <option value="zh-CN-XiaoyiNeural">{lang === "zh" ? "晓伊（女声）" : "Xiaoyi (F)"}</option>
                        <option value="zh-CN-YunxiNeural">{lang === "zh" ? "云希（男声）" : "Yunxi (M)"}</option>
                        <option value="zh-CN-YunyangNeural">{lang === "zh" ? "云扬（男声）" : "Yunyang (M)"}</option>
                        <option value="zh-CN-YunjianNeural">{lang === "zh" ? "云健（男声）" : "Yunjian (M)"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "语音最大字数" : "Voice max chars"}
                      <input
                        type="number" min={40} max={400}
                        value={wecomStyle.voice_max_chars === undefined ? "" : String(wecomStyle.voice_max_chars)}
                        onChange={(e) => setOverride("voice_max_chars", e.target.value === "" ? "" : Number(e.target.value))}
                        placeholder={lang === "zh" ? "继承全局（默认 260）" : "Inherit (default 260)"}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      />
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "语速" : "Rate"}
                      <select
                        value={(wecomStyle.voice_rate as string) ?? ""}
                        onChange={(e) => setOverride("voice_rate", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="-30%">{lang === "zh" ? "慢 30%" : "-30%"}</option>
                        <option value="-10%">{lang === "zh" ? "慢 10%" : "-10%"}</option>
                        <option value="+0%">{lang === "zh" ? "正常" : "+0%"}</option>
                        <option value="+10%">{lang === "zh" ? "快 10%" : "+10%"}</option>
                        <option value="+30%">{lang === "zh" ? "快 30%" : "+30%"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "音量" : "Volume"}
                      <select
                        value={(wecomStyle.voice_volume as string) ?? ""}
                        onChange={(e) => setOverride("voice_volume", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="-30%">{lang === "zh" ? "低 30%" : "-30%"}</option>
                        <option value="-10%">{lang === "zh" ? "低 10%" : "-10%"}</option>
                        <option value="+0%">{lang === "zh" ? "正常" : "+0%"}</option>
                        <option value="+10%">{lang === "zh" ? "高 10%" : "+10%"}</option>
                        <option value="+30%">{lang === "zh" ? "高 30%" : "+30%"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "音调" : "Pitch"}
                      <select
                        value={(wecomStyle.voice_pitch as string) ?? ""}
                        onChange={(e) => setOverride("voice_pitch", e.target.value)}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      >
                        <option value="">{lang === "zh" ? "继承全局" : "Inherit"}</option>
                        <option value="-10Hz">{lang === "zh" ? "低 10Hz" : "-10Hz"}</option>
                        <option value="-5Hz">{lang === "zh" ? "低 5Hz" : "-5Hz"}</option>
                        <option value="+0Hz">{lang === "zh" ? "正常" : "+0Hz"}</option>
                        <option value="+5Hz">{lang === "zh" ? "高 5Hz" : "+5Hz"}</option>
                        <option value="+10Hz">{lang === "zh" ? "高 10Hz" : "+10Hz"}</option>
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "静音开始（整点）" : "Quiet from"}
                      <input
                        type="number" min={-1} max={23}
                        value={wecomStyle.voice_quiet_from === undefined ? "" : String(wecomStyle.voice_quiet_from)}
                        onChange={(e) => setOverride("voice_quiet_from", e.target.value === "" ? "" : Math.max(-1, Math.min(23, Number(e.target.value)) || 0))}
                        placeholder={lang === "zh" ? "继承全局（-1 不启用）" : "Inherit (-1 off)"}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      />
                    </label>
                    <label className="text-[11px] text-slate-400">
                      {lang === "zh" ? "静音结束（整点，可跨夜）" : "Quiet to"}
                      <input
                        type="number" min={-1} max={23}
                        value={wecomStyle.voice_quiet_to === undefined ? "" : String(wecomStyle.voice_quiet_to)}
                        onChange={(e) => setOverride("voice_quiet_to", e.target.value === "" ? "" : Math.max(-1, Math.min(23, Number(e.target.value)) || 0))}
                        placeholder={lang === "zh" ? "继承全局" : "Inherit"}
                        className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#16162a] px-3 py-2 text-sm text-white"
                      />
                    </label>
                  </div>
                </details>

                {wecomConflict && (
                  <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                    {a.wecomConflict[lang]}
                    {wecomConflict.name ? `（${wecomConflict.name}）` : ""}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {wecomState?.bound && (
                    <button
                      type="button"
                      onClick={() => void unbindWecom()}
                      className="rounded-lg border border-red-500/40 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10"
                    >
                      {a.wecomUnbind[lang]}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void testWecom()}
                    disabled={wecomTesting || !wecomState?.bound}
                    className="rounded-lg border border-[#2d2d4e] px-3 py-1.5 text-xs text-slate-200 hover:border-blue-500 disabled:opacity-40"
                  >
                    {wecomTesting ? <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> : null}
                    {a.wecomTest[lang]}
                  </button>
                </div>
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setShowWecom(null)}
                className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white"
              >
                {c.cancel[lang]}
              </button>
              {wecomConfigured && (
                <button
                  onClick={() => void saveWecom(!!wecomConflict)}
                  disabled={wecomSaving || wecomLoading}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
                >
                  {wecomConflict ? (lang === "zh" ? "确认改绑并保存" : "Rebind and save") : c.save[lang]}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
