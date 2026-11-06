"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Plus, BookOpen, Trash2, RefreshCw, Pencil, Loader2, CloudDownload, Search,
} from "lucide-react";
import { dataSourcesApi, skillsApi, toolsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { canDeleteAgentsOrSkills } from "@/lib/permissions";
import { translations } from "@/lib/i18n";
import { agentAvatarTone } from "@/lib/agentCatalog";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";
import toast from "react-hot-toast";

interface Skill {
  id: string;
  slug: string;
  display_name: string;
  description: string;
  instructions_md: string;
  status: "draft" | "active" | "archived";
  auto_invoke: boolean;
  version: number;
  tags: string[];
  metadata?: { category?: string };
}

const EMPTY_FORM = {
  slug: "",
  display_name: "",
  description: "",
  instructions_md: "",
  status: "draft" as Skill["status"],
  auto_invoke: false,
  tags: "",
};

interface LibrarySource {
  id: string;
  name: string;
  name_zh: string;
}

interface LibraryTemplate {
  source: string;
  slug: string;
  display_name: string;
  description: string;
  category: string;
  tags: string[];
}

type StatusFilter = "all" | Skill["status"];

const SKILL_SCENES: Array<{
  id: StatusFilter;
  title: { zh: string; en: string };
  subtitle: { zh: string; en: string };
  tone: string;
}> = [
  {
    id: "active",
    title: { zh: "已发布技能", en: "Active Skills" },
    subtitle: { zh: "可直接绑定到智能体", en: "Ready to bind to agents" },
    tone: "agents-scene-data",
  },
  {
    id: "draft",
    title: { zh: "草稿技能", en: "Draft Skills" },
    subtitle: { zh: "编辑完善后发布", en: "Edit and publish when ready" },
    tone: "agents-scene-content",
  },
  {
    id: "archived",
    title: { zh: "已归档", en: "Archived" },
    subtitle: { zh: "历史技能留存", en: "Historical skills" },
    tone: "agents-scene-tech",
  },
];

const STATUS_FILTERS: StatusFilter[] = ["all", "active", "draft", "archived"];

type EditorTab = "method" | "steps" | "style" | "memory";
interface OperatorProp { type?: string; description?: string }
interface OperatorInfo {
  name: string;
  display_name?: string;
  description: string;
  parameters_schema?: { properties?: Record<string, OperatorProp> };
}
interface StepDraft {
  key: string;
  kind: "tool" | "prompt";
  tool: string;
  params: Record<string, string>;
  prompt: string;
}
interface AnalysisDraft {
  enabled: boolean;
  keywords: string;
  persona: string;
  formatMode: string;
  grounding: string;
  steps: StepDraft[];
}
interface MemoryItem { id: string; question: string; source?: string; use_count?: number }
interface SourceOption { id: string; name: string }

const EMPTY_ANALYSIS: AnalysisDraft = {
  enabled: false, keywords: "", persona: "", formatMode: "analysis_v2", grounding: "", steps: [],
};

function stepKey() {
  return Math.random().toString(36).slice(2, 10);
}

function analysisFromMeta(meta: Record<string, unknown> | null | undefined): AnalysisDraft {
  const raw = meta || {};
  const trigger = (raw.trigger || {}) as { keywords?: string[] };
  const style = (raw.answer_style || {}) as { persona?: string; format_mode?: string; grounding_extra?: string };
  const steps = Array.isArray(raw.steps) ? raw.steps : [];
  return {
    enabled: raw.category === "analysis",
    keywords: (trigger.keywords || []).join(", "),
    persona: style.persona || "",
    formatMode: style.format_mode || "analysis_v2",
    grounding: style.grounding_extra || "",
    steps: steps.filter((item) => item && typeof item === "object").map((step) => {
      const row = step as { tool?: string; prompt?: string; params?: Record<string, unknown> };
      if (row.prompt && !row.tool) {
        return { key: stepKey(), kind: "prompt" as const, tool: "", params: {}, prompt: String(row.prompt) };
      }
      const params: Record<string, string> = {};
      Object.entries(row.params || {}).forEach(([key, value]) => {
        params[key] = Array.isArray(value) ? value.join(", ") : String(value ?? "");
      });
      return { key: stepKey(), kind: "tool" as const, tool: row.tool || "metric_query", params, prompt: "" };
    }),
  };
}

function composeMetadata(base: Record<string, unknown>, draft: AnalysisDraft, operators: OperatorInfo[]) {
  const steps = draft.steps.map((step) => {
    if (step.kind === "prompt") {
      const prompt = step.prompt.trim();
      return prompt ? { prompt } : null;
    }
    const props = operators.find((op) => op.name === step.tool)?.parameters_schema?.properties || {};
    const params: Record<string, unknown> = {};
    Object.entries(step.params).forEach(([key, raw]) => {
      const text = raw.trim();
      if (!text) return;
      const kind = props[key]?.type;
      if (kind === "array") params[key] = text.split(/[,，]/).map((part) => part.trim()).filter(Boolean);
      else if (kind === "integer") params[key] = Number.parseInt(text, 10);
      else if (kind === "number") params[key] = Number(text);
      else params[key] = text;
    });
    return step.tool ? { tool: step.tool, params } : null;
  }).filter(Boolean);
  return {
    ...base,
    category: "analysis",
    trigger: {
      ...((typeof base.trigger === "object" && base.trigger) ? base.trigger as object : {}),
      keywords: draft.keywords.split(/[,，]/).map((part) => part.trim()).filter(Boolean),
    },
    answer_style: {
      persona: draft.persona,
      format_mode: draft.formatMode || "analysis_v2",
      grounding_extra: draft.grounding,
    },
    steps,
  };
}

function SkillBoard() {
  const { lang } = useLangStore();
  const [rows, setRows] = useState<Array<{ skill_id: string; display_name: string; asks: number; success_rate: number; scope: string }>>([]);
  useEffect(() => {
    skillsApi.leaderboard().then(({ data }) => setRows(data.items || [])).catch(() => setRows([]));
  }, []);
  if (!rows.length) return null;
  return (
    <section className="mb-4 rounded-xl border theme-border theme-surface p-4">
      <h2 className="mb-2 text-sm font-medium">{lang === "zh" ? "技能评测榜（近 30 天问数）" : "Skill board, last 30 days"}</h2>
      <div className="space-y-1 text-xs">
        {rows.map((row) => (
          <div key={row.skill_id} className="flex justify-between gap-3">
            <span>{row.display_name}{row.scope === "org" ? (lang === "zh" ? " · 组织共享" : " · org") : ""}</span>
            <span className="theme-muted">{row.asks} · {Math.round(row.success_rate * 100)}%</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function SkillsPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const canDelete = canDeleteAgentsOrSkills(user);
  const s = translations.skills;
  const c = translations.common;
  const chatT = translations.chat;

  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showLibrary, setShowLibrary] = useState(false);
  const [libSources, setLibSources] = useState<LibrarySource[]>([]);
  const [libTemplates, setLibTemplates] = useState<LibraryTemplate[]>([]);
  const [libCategories, setLibCategories] = useState<string[]>([]);
  const [libSource, setLibSource] = useState("");
  const [libCategory, setLibCategory] = useState("");
  const [libQuery, setLibQuery] = useState("");
  const [libSelected, setLibSelected] = useState<Set<string>>(new Set());
  const [libLoading, setLibLoading] = useState(false);
  const [libImporting, setLibImporting] = useState(false);
  const [libSyncing, setLibSyncing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [analysis, setAnalysis] = useState<AnalysisDraft>(EMPTY_ANALYSIS);
  const [metaBase, setMetaBase] = useState<Record<string, unknown>>({});
  const [editorTab, setEditorTab] = useState<EditorTab>("method");
  const [operators, setOperators] = useState<OperatorInfo[]>([]);
  const [sources, setSources] = useState<SourceOption[]>([]);
  const [trialSource, setTrialSource] = useState("");
  const [trialQuestions, setTrialQuestions] = useState("");
  const [trialResult, setTrialResult] = useState("");
  const [examples, setExamples] = useState<MemoryItem[]>([]);
  const [trialing, setTrialing] = useState(false);

  const load = async () => {
    try {
      const { data } = await skillsApi.list(lang);
      setSkills(data);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [lang]);

  useEffect(() => {
    if (showLibrary) loadLibrary(libSource, libCategory, libQuery);
  }, [lang]);

  useEffect(() => {
    if (!showModal || !analysis.enabled) return;
    if (operators.length === 0) {
      toolsApi.analysis().then(({ data }) => setOperators(Array.isArray(data) ? data : [])).catch(() => {});
    }
    if (sources.length === 0) {
      dataSourcesApi.list().then((res) => {
        const rows = (res.data?.items || res.data || []) as SourceOption[];
        setSources(Array.isArray(rows) ? rows : []);
        setTrialSource((current) => current || rows[0]?.id || "");
      }).catch(() => {});
    }
  }, [showModal, analysis.enabled, operators.length, sources.length]);

  const resetAnalysis = () => {
    setAnalysis(EMPTY_ANALYSIS);
    setMetaBase({});
    setEditorTab("method");
    setTrialResult("");
    setExamples([]);
  };

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    resetAnalysis();
    setShowModal(true);
  };

  const openEdit = async (skill: Skill) => {
    setEditingId(skill.id);
    try {
      const { data } = await skillsApi.get(skill.id, { raw: true });
      const meta = (data.metadata || {}) as Record<string, unknown>;
      setMetaBase(meta);
      setAnalysis(analysisFromMeta(meta));
      setForm({
        slug: data.slug,
        display_name: data.display_name,
        description: data.description,
        instructions_md: data.instructions_md,
        status: data.status,
        auto_invoke: data.auto_invoke,
        tags: (data.tags ?? []).join(", "),
      });
    } catch {
      resetAnalysis();
      setForm({
        slug: skill.slug,
        display_name: skill.display_name,
        description: skill.description,
        instructions_md: skill.instructions_md,
        status: skill.status,
        auto_invoke: skill.auto_invoke,
        tags: (skill.tags ?? []).join(", "),
      });
    }
    setShowModal(true);
  };

  const save = async () => {
    if (!form.display_name.trim() || !form.description.trim()) return;
    setSaving(true);
    const payload: Record<string, unknown> = {
      slug: form.slug.trim() || undefined,
      display_name: form.display_name.trim(),
      description: form.description.trim(),
      instructions_md: form.instructions_md,
      status: form.status,
      auto_invoke: form.auto_invoke,
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
    };
    if (analysis.enabled) {
      payload.metadata = composeMetadata(metaBase, analysis, operators);
      payload.tools_required = analysis.steps.filter((step) => step.kind === "tool" && step.tool).map((step) => step.tool);
    } else if (metaBase.category === "analysis") {
      const next = { ...metaBase };
      delete next.category;
      payload.metadata = next;
    }
    try {
      if (editingId) {
        await skillsApi.update(editingId, payload);
        toast.success(s.saved[lang]);
      } else {
        await skillsApi.create(payload);
        toast.success(s.created[lang]);
      }
      setShowModal(false);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? s.saveFailed[lang]);
    } finally {
      setSaving(false);
    }
  };

  const loadExamples = async (skillId: string) => {
    try {
      const { data } = await skillsApi.examples(skillId);
      setExamples((data.items || []) as MemoryItem[]);
    } catch {
      setExamples([]);
    }
  };

  const runTrial = async (kind: "dry" | "regress" | "ab") => {
    if (!editingId) {
      toast.error(lang === "zh" ? "请先保存技能，再试运行" : "Save the skill before a trial");
      return;
    }
    if (!trialSource) {
      toast.error(lang === "zh" ? "请选择数据源" : "Choose a data source");
      return;
    }
    const questions = trialQuestions.split("\n").map((line) => line.trim()).filter(Boolean);
    if (kind === "dry" && questions.length === 0) {
      toast.error(lang === "zh" ? "请填写至少一条样例问题" : "Add at least one sample question");
      return;
    }
    setTrialing(true);
    try {
      if (kind === "dry") {
        const { data } = await skillsApi.dryRun(editingId, {
          data_source_id: trialSource,
          questions,
          include_answer: false,
          metadata: composeMetadata(metaBase, analysis, operators),
        });
        const lines = ((data.items || []) as { ok?: boolean; question?: string; error?: string; facts?: unknown[] }[])
          .map((item) => `${item.ok ? "OK" : "FAIL"} ${item.question || ""} ${item.error || ""} facts:${(item.facts || []).length}`);
        setTrialResult(lines.join("\n") || (lang === "zh" ? "无结果" : "No result"));
      } else if (kind === "regress") {
        const { data } = await skillsApi.regress(editingId, { data_source_id: trialSource });
        setTrialResult(data.warning || (lang === "zh"
          ? `回归 ${data.passed}/${data.total} 通过`
          : `Regression ${data.passed}/${data.total} passed`));
      } else {
        const { data } = await skillsApi.compareVersions(editingId, { data_source_id: trialSource });
        if (!data.ready) setTrialResult(data.reason || "");
        else setTrialResult(`${data.note || ""} ${data.decision || ""}`);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || (lang === "zh" ? "试运行失败" : "Trial failed"));
    } finally {
      setTrialing(false);
    }
  };

  const deleteSkill = async (id: string) => {
    if (!canDelete) {
      toast.error(s.deleteForbidden[lang]);
      return;
    }
    if (!confirm(s.deleteConfirm[lang])) return;
    try {
      await skillsApi.delete(id);
      toast.success(lang === "zh" ? "已删除" : "Deleted");
      load();
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) toast.error(s.deleteForbidden[lang]);
      else toast.error(lang === "zh" ? "删除失败" : "Delete failed");
    }
  };

  const seedTemplates = async () => {
    try {
      await skillsApi.seedTemplates();
      toast.success(lang === "zh" ? "模板已加载" : "Templates loaded");
      load();
    } catch {
      toast.error(lang === "zh" ? "加载模板失败" : "Failed to load templates");
    }
  };

  const libKey = (t: LibraryTemplate) => `${t.source}:${t.slug}`;

  const loadLibrary = async (source = libSource, category = libCategory, q = libQuery) => {
    setLibLoading(true);
    try {
      const params: { source?: string; category?: string; q?: string; lang?: string } = { lang };
      if (source) params.source = source;
      if (category) params.category = category;
      if (q.trim()) params.q = q.trim();
      const { data } = await skillsApi.libraryCatalog(params);
      setLibTemplates(data);
    } catch {
      toast.error(lang === "zh" ? "加载技能库失败" : "Failed to load library");
    } finally {
      setLibLoading(false);
    }
  };

  const openLibrary = async () => {
    setShowLibrary(true);
    setLibSelected(new Set());
    setLibQuery("");
    setLibSource("");
    setLibCategory("");
    try {
      const [{ data: sources }, { data: cats }] = await Promise.all([
        skillsApi.librarySources(),
        skillsApi.libraryCategories(),
      ]);
      setLibSources(sources);
      setLibCategories(cats);
      await loadLibrary("", "", "");
    } catch {
      toast.error(lang === "zh" ? "加载技能库失败" : "Failed to load library");
    }
  };

  const onLibSourceChange = async (source: string) => {
    setLibSource(source);
    setLibCategory("");
    setLibSelected(new Set());
    try {
      const { data: cats } = await skillsApi.libraryCategories(source || undefined);
      setLibCategories(cats);
    } catch { /* keep */ }
    await loadLibrary(source, "", libQuery);
  };

  const syncLibrary = async () => {
    setLibSyncing(true);
    try {
      const syncSource = libSource || "all";
      await skillsApi.librarySync(syncSource);
      toast.success(s.librarySyncOk[lang]);
      const { data: sources } = await skillsApi.librarySources();
      setLibSources(sources);
      const { data: cats } = await skillsApi.libraryCategories(libSource || undefined);
      setLibCategories(cats);
      await loadLibrary();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? (lang === "zh" ? "同步失败" : "Sync failed"));
    } finally {
      setLibSyncing(false);
    }
  };

  const importLibrary = async (items: LibraryTemplate[]) => {
    if (!items.length) {
      toast.error(s.librarySelect[lang]);
      return;
    }
    setLibImporting(true);
    try {
      const { data } = await skillsApi.libraryImport({
        items: items.map((t) => ({ source: t.source, slug: t.slug })),
      });
      const n = (data.imported as string[])?.length ?? 0;
      const skipped = (data.skipped as string[])?.length ?? 0;
      toast.success(`${s.libraryImported[lang]}: ${n}${skipped ? ` (${skipped} skipped)` : ""}`);
      setLibSelected(new Set());
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? (lang === "zh" ? "导入失败" : "Import failed"));
    } finally {
      setLibImporting(false);
    }
  };

  const localSlugs = new Set(skills.map((sk) => sk.slug));

  const statusLabel = (status: Skill["status"]) => {
    if (status === "active") return s.statusActive[lang];
    if (status === "archived") return s.statusArchived[lang];
    return s.statusDraft[lang];
  };

  const statusClass = (status: Skill["status"]) => {
    if (status === "active") return "agents-badge agents-badge-chat";
    if (status === "archived") return "agents-badge";
    return "agents-badge agents-badge-master";
  };

  const filteredSkills = useMemo(() => {
    let list = [...skills];
    if (statusFilter !== "all") list = list.filter((sk) => sk.status === statusFilter);
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (sk) =>
          sk.display_name.toLowerCase().includes(q) ||
          sk.slug.toLowerCase().includes(q) ||
          sk.description.toLowerCase().includes(q) ||
          (sk.tags ?? []).some((t) => t.toLowerCase().includes(q)),
      );
    }
    return list.sort((a, b) => {
      const order = { active: 0, draft: 1, archived: 2 };
      return order[a.status] - order[b.status] || a.display_name.localeCompare(b.display_name);
    });
  }, [skills, statusFilter, searchQuery]);

  const sceneSkills = (status: StatusFilter) =>
    status === "all" ? skills.slice(0, 4) : skills.filter((sk) => sk.status === status).slice(0, 4);

  const skillInitial = (name: string) => (name.trim()[0] || "S").toUpperCase();

  const statusFilterLabel = (id: StatusFilter) => {
    if (id === "all") return s.filterAll[lang];
    return statusLabel(id);
  };

  return (
    <div className="agents-hub">
      <SkillBoard />
      <div className="agents-hub-header">
        <div>
          <h1>{s.title[lang]}</h1>
          <p>{s.subtitle[lang]}</p>
        </div>
        <div className="agents-hub-actions">
          <button type="button" onClick={openLibrary} className="agents-btn-secondary agents-btn-teal">
            <CloudDownload className="h-4 w-4" /> {s.library[lang]}
          </button>
          <button type="button" onClick={seedTemplates} className="agents-btn-secondary">
            <RefreshCw className="h-4 w-4" /> {s.seedTemplates[lang]}
          </button>
          <button type="button" onClick={openCreate} className="agents-btn-primary">
            <Plus className="h-4 w-4" /> {s.newSkill[lang]}
          </button>
        </div>
      </div>

      <div className="agents-hub-toolbar">
        <div className="agents-hub-tabs">
          <Link href="/agents" className="agents-hub-tab">{translations.agents.tabExpert[lang]}</Link>
          <span className="agents-hub-tab agents-hub-tab-active">{translations.agents.tabSkill[lang]}</span>
          <Link href="/chat" className="agents-hub-tab">{translations.agents.tabConnector[lang]}</Link>
        </div>
        <div className="agents-hub-search">
          <Search className="h-4 w-4 shrink-0 theme-muted" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={s.searchPlaceholder[lang]}
          />
        </div>
      </div>

      {!loading && skills.length > 0 && (
        <section className="agents-featured">
          <h2 className="agents-featured-title">{s.featuredTitle[lang]}</h2>
          <CapsuleScrollRow
            scrollStep={268}
            scrollLeftLabel={chatT.scrollLeft[lang]}
            scrollRightLabel={chatT.scrollRight[lang]}
            innerClassName="agents-featured-scroll"
          >
            {SKILL_SCENES.map((scene) => {
              const items = sceneSkills(scene.id);
              return (
                <button
                  key={scene.id}
                  type="button"
                  className={`agents-scene-card ${scene.tone}`}
                  onClick={() => setStatusFilter(scene.id)}
                >
                  <div>
                    <h3>{lang === "zh" ? scene.title.zh : scene.title.en}</h3>
                    <p>{lang === "zh" ? scene.subtitle.zh : scene.subtitle.en}</p>
                  </div>
                  <ul className="agents-scene-list">
                    {items.length > 0 ? (
                      items.map((item) => <li key={item.id}>{item.display_name}</li>)
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
          {STATUS_FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setStatusFilter(id)}
              className={`agents-filter-pill${statusFilter === id ? " agents-filter-pill-active" : ""}`}
            >
              {statusFilterLabel(id)}
            </button>
          ))}
        </CapsuleScrollRow>
      </div>

      {loading ? (
        <div className="theme-muted text-sm">{c.loading[lang]}</div>
      ) : filteredSkills.length === 0 ? (
        <div className="agents-empty">
          <BookOpen className="mb-4 h-12 w-12 opacity-40" />
          <p>{skills.length === 0 ? s.noSkills[lang] : (lang === "zh" ? "没有匹配的技能" : "No matching skills")}</p>
        </div>
      ) : (
        <div className="agents-grid">
          {filteredSkills.map((skill) => (
            <article key={skill.id} className="agents-card">
              <div className="agents-card-top">
                <div className={`agents-avatar ${agentAvatarTone(skill.id)}`} aria-hidden>
                  {skillInitial(skill.display_name)}
                </div>
                <div className="agents-card-head">
                  <div className="agents-card-title-row">
                    <h3 title={skill.display_name}>{skill.display_name}</h3>
                    <span className={statusClass(skill.status)}>{statusLabel(skill.status)}</span>
                  </div>
                  <p className="agents-card-role font-mono">{skill.slug}</p>
                </div>
              </div>
              <p className="agents-card-desc">{skill.description}</p>
              <div className="agents-card-tags">
                <span className="agents-tag">{s.version[lang]} v{skill.version}</span>
                {skill.metadata?.category === "analysis" && (
                  <span className="agents-tag">{lang === "zh" ? "分析技能" : "Analysis"}</span>
                )}
                {(skill.tags ?? []).map((tag) => (
                  <span key={tag} className="agents-tag">{tag}</span>
                ))}
              </div>
              <div className="agents-card-footer">
                <span className="agents-card-meta">{skill.auto_invoke ? (lang === "zh" ? "自动发现" : "Auto-invoke") : (lang === "zh" ? "手动绑定" : "Manual bind")}</span>
                <div className="agents-card-actions">
                  <button type="button" onClick={() => openEdit(skill)} className="agents-icon-btn" title={s.editSkill[lang]}>
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  {canDelete && (
                    <button type="button" onClick={() => deleteSkill(skill.id)} className="agents-icon-btn agents-icon-btn-danger" title={c.delete[lang]}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {showLibrary && (
        <div className="employees-template-overlay">
          <div className="employees-template-dialog">
            <div className="employees-template-header">
              <div>
                <h2>{s.libraryTitle[lang]}</h2>
                <p>{s.librarySubtitle[lang]}</p>
              </div>
              <button type="button" onClick={() => setShowLibrary(false)} className="agents-icon-btn">
                <span className="sr-only">{c.cancel[lang]}</span>×
              </button>
            </div>
            <div className="employees-template-toolbar px-6 pb-3">
              <div className="flex flex-wrap gap-2">
                <select
                  className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                  value={libSource}
                  onChange={(e) => onLibSourceChange(e.target.value)}
                >
                  <option value="">{s.allSources[lang]}</option>
                  {libSources.map((src) => (
                    <option key={src.id} value={src.id}>
                      {lang === "zh" ? src.name_zh : src.name}
                    </option>
                  ))}
                </select>
                <select
                  className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                  value={libCategory}
                  onChange={(e) => { setLibCategory(e.target.value); loadLibrary(libSource, e.target.value, libQuery); }}
                >
                  <option value="">{s.allCategories[lang]}</option>
                  {libCategories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
                <div className="agents-hub-search min-w-[200px] flex-1 max-w-none">
                  <Search className="h-4 w-4 shrink-0 theme-muted" />
                  <input
                    type="text"
                    placeholder={s.librarySearch[lang]}
                    value={libQuery}
                    onChange={(e) => setLibQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && loadLibrary(libSource, libCategory, libQuery)}
                  />
                </div>
                <button type="button" onClick={() => loadLibrary(libSource, libCategory, libQuery)} className="agents-btn-secondary">
                  {lang === "zh" ? "搜索" : "Search"}
                </button>
                <button type="button" onClick={syncLibrary} disabled={libSyncing} className="agents-btn-secondary disabled:opacity-40">
                  {libSyncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  {s.librarySync[lang]}
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4">
              {libLoading ? (
                <div className="py-12 text-center theme-muted">{c.loading[lang]}</div>
              ) : libTemplates.length === 0 ? (
                <div className="py-12 text-center theme-muted">{c.noData[lang]}</div>
              ) : (
                <div className="space-y-2">
                  {libTemplates.slice(0, 120).map((tpl) => {
                    const key = libKey(tpl);
                    const imported = localSlugs.has(tpl.slug);
                    const checked = libSelected.has(key);
                    return (
                      <label
                        key={key}
                        className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors ${
                          checked ? "border-teal-500/50 bg-teal-500/5" : "border-[var(--border)] hover:bg-[var(--hover)]"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={checked}
                          disabled={imported}
                          onChange={(e) => {
                            setLibSelected((prev) => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(key);
                              else next.delete(key);
                              return next;
                            });
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium theme-text">{tpl.display_name}</span>
                            <span className="font-mono text-[10px] theme-muted">{tpl.slug}</span>
                            <span className="agents-tag">{tpl.category}</span>
                            <span className="agents-tag">{tpl.source}</span>
                            {imported && (
                              <span className="agents-badge agents-badge-chat">{lang === "zh" ? "已导入" : "Imported"}</span>
                            )}
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs theme-muted">{tpl.description}</p>
                        </div>
                      </label>
                    );
                  })}
                  {libTemplates.length > 120 && (
                    <p className="py-2 text-center text-xs theme-muted">
                      {lang === "zh"
                        ? `显示前 120 / ${libTemplates.length} 条，请用搜索或分类缩小范围`
                        : `Showing 120 / ${libTemplates.length}. Use search or category to narrow.`}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-6 py-4">
              <span className="text-xs theme-muted">
                {libSelected.size} {lang === "zh" ? "已选" : "selected"} · {libTemplates.length} {lang === "zh" ? "条结果" : "results"}
              </span>
              <div className="flex gap-2">
                <button type="button" onClick={() => setShowLibrary(false)} className="agents-btn-secondary">{c.cancel[lang]}</button>
                <button
                  type="button"
                  onClick={() => importLibrary(libTemplates.slice(0, 120).filter((t) => !localSlugs.has(t.slug)))}
                  disabled={libImporting || libTemplates.length === 0}
                  className="agents-btn-secondary disabled:opacity-40"
                >
                  {s.libraryImportAll[lang]}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const items = libTemplates.filter((t) => libSelected.has(libKey(t)));
                    importLibrary(items);
                  }}
                  disabled={libImporting || libSelected.size === 0}
                  className="agents-btn-primary disabled:opacity-40"
                >
                  {libImporting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {s.libraryImport[lang]}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-2xl overflow-y-auto p-6">
            <h2 className="mb-4 text-lg font-semibold theme-text">
              {editingId ? s.editSkill[lang] : s.newSkill[lang]}
            </h2>
            <div className="space-y-3">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{c.name[lang]}</label>
                  <input
                    type="text"
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    value={form.display_name}
                    onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{s.slug[lang]}</label>
                  <input
                    type="text"
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    placeholder={s.slugHint[lang]}
                    value={form.slug}
                    onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.description[lang]}</label>
                <textarea
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  rows={3}
                  placeholder={s.descriptionHint[lang]}
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={analysis.enabled}
                  onChange={(e) => setAnalysis((prev) => ({ ...prev, enabled: e.target.checked }))}
                />
                {lang === "zh" ? "分析技能（方法论、步骤、结论规范、记忆库）" : "Analysis skill"}
              </label>
              {analysis.enabled && (
                <div className="flex flex-wrap gap-2">
                  {([
                    ["method", lang === "zh" ? "方法论" : "Method"],
                    ["steps", lang === "zh" ? "步骤编排" : "Steps"],
                    ["style", lang === "zh" ? "结论规范" : "Answer style"],
                    ["memory", lang === "zh" ? "记忆库" : "Memory"],
                  ] as [EditorTab, string][]).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => {
                        setEditorTab(id);
                        if (id === "memory" && editingId) void loadExamples(editingId);
                      }}
                      className={`rounded-full px-3 py-1 text-xs ${editorTab === id ? "bg-blue-600 text-white" : "bg-[#1a1a2e] text-slate-300"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {(!analysis.enabled || editorTab === "method") && (
              <div>
                <label className="mb-1 block text-xs text-slate-400">{s.instructions[lang]}</label>
                <textarea
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 font-mono text-sm text-white focus:border-blue-500 focus:outline-none"
                  rows={analysis.enabled ? 8 : 12}
                  placeholder={s.instructionsHint[lang]}
                  value={form.instructions_md}
                  onChange={(e) => setForm((f) => ({ ...f, instructions_md: e.target.value }))}
                />
              </div>
              )}
              {analysis.enabled && editorTab === "steps" && (
                <div className="space-y-3">
                  {analysis.steps.map((step, index) => {
                    const props = operators.find((op) => op.name === step.tool)?.parameters_schema?.properties || {};
                    return (
                      <div key={step.key} className="rounded-lg border border-[#2d2d4e] p-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <span className="text-xs text-slate-400">{index + 1}</span>
                          <button
                            type="button"
                            className="text-xs text-red-400"
                            onClick={() => setAnalysis((prev) => ({ ...prev, steps: prev.steps.filter((item) => item.key !== step.key) }))}
                          >
                            {lang === "zh" ? "删除" : "Remove"}
                          </button>
                        </div>
                        {step.kind === "prompt" ? (
                          <textarea
                            className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                            rows={2}
                            value={step.prompt}
                            placeholder={lang === "zh" ? "这一步要模型解释什么" : "What the model should explain"}
                            onChange={(e) => setAnalysis((prev) => ({
                              ...prev,
                              steps: prev.steps.map((item) => item.key === step.key ? { ...item, prompt: e.target.value } : item),
                            }))}
                          />
                        ) : (
                          <div className="space-y-2">
                            <select
                              className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                              value={step.tool}
                              onChange={(e) => setAnalysis((prev) => ({
                                ...prev,
                                steps: prev.steps.map((item) => item.key === step.key ? { ...item, tool: e.target.value, params: {} } : item),
                              }))}
                            >
                              {(operators.length ? operators : [{ name: step.tool || "metric_query", description: "" }]).map((op) => (
                                <option key={op.name} value={op.name}>{op.display_name || op.name}</option>
                              ))}
                            </select>
                            {Object.entries(props).map(([key, spec]) => (
                              <label key={key} className="block text-xs text-slate-400">
                                {key}
                                <input
                                  className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                                  value={step.params[key] || ""}
                                  placeholder={spec.description || ""}
                                  onChange={(e) => setAnalysis((prev) => ({
                                    ...prev,
                                    steps: prev.steps.map((item) => item.key === step.key
                                      ? { ...item, params: { ...item.params, [key]: e.target.value } }
                                      : item),
                                  }))}
                                />
                              </label>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded-lg bg-[#1a1a2e] px-3 py-1 text-xs text-slate-200"
                      onClick={() => setAnalysis((prev) => ({
                        ...prev,
                        steps: [...prev.steps, { key: stepKey(), kind: "tool", tool: operators[0]?.name || "metric_query", params: {}, prompt: "" }],
                      }))}
                    >
                      {lang === "zh" ? "加算子" : "Add operator"}
                    </button>
                    <button
                      type="button"
                      className="rounded-lg bg-[#1a1a2e] px-3 py-1 text-xs text-slate-200"
                      onClick={() => setAnalysis((prev) => ({
                        ...prev,
                        steps: [...prev.steps, { key: stepKey(), kind: "prompt", tool: "", params: {}, prompt: "" }],
                      }))}
                    >
                      {lang === "zh" ? "加结论提示" : "Add prompt"}
                    </button>
                  </div>
                  <div className="rounded-lg border border-[#2d2d4e] p-3">
                    <p className="mb-2 text-xs text-slate-400">{lang === "zh" ? "试运行（先保存再跑当前步骤）" : "Dry run the saved skill with these steps"}</p>
                    <select
                      className="mb-2 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      value={trialSource}
                      onChange={(e) => setTrialSource(e.target.value)}
                    >
                      <option value="">{lang === "zh" ? "选择数据源" : "Data source"}</option>
                      {sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
                    </select>
                    <textarea
                      className="mb-2 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      rows={3}
                      placeholder={lang === "zh" ? "每行一个样例问题" : "One sample question per line"}
                      value={trialQuestions}
                      onChange={(e) => setTrialQuestions(e.target.value)}
                    />
                    <div className="flex gap-2">
                      <button type="button" disabled={trialing} onClick={() => runTrial("dry")} className="rounded-lg bg-blue-600 px-3 py-1 text-xs text-white disabled:opacity-40">
                        {lang === "zh" ? "试运行" : "Dry run"}
                      </button>
                      <button type="button" disabled={trialing} onClick={() => runTrial("regress")} className="rounded-lg bg-[#1a1a2e] px-3 py-1 text-xs text-slate-200 disabled:opacity-40">
                        {lang === "zh" ? "金标回归" : "Regression"}
                      </button>
                      <button type="button" disabled={trialing} onClick={() => runTrial("ab")} className="rounded-lg bg-[#1a1a2e] px-3 py-1 text-xs text-slate-200 disabled:opacity-40">
                        {lang === "zh" ? "对比上一版" : "Compare"}
                      </button>
                      <button type="button" disabled={trialing} onClick={async () => {
                        if (!editingId) return;
                        try { await skillsApi.submitReview(editingId); toast.success(lang === "zh" ? "已提交审批" : "Submitted"); }
                        catch { toast.error(lang === "zh" ? "提交失败" : "Submit failed"); }
                      }} className="rounded-lg bg-[#1a1a2e] px-3 py-1 text-xs text-slate-200">
                        {lang === "zh" ? "提交审批" : "Submit"}
                      </button>
                    </div>
                    {trialResult && <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-300">{trialResult}</pre>}
                  </div>
                </div>
              )}
              {analysis.enabled && editorTab === "style" && (
                <div className="space-y-2">
                  <label className="block text-xs text-slate-400">
                    {lang === "zh" ? "触发词，逗号分隔" : "Trigger keywords"}
                    <input
                      className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      value={analysis.keywords}
                      onChange={(e) => setAnalysis((prev) => ({ ...prev, keywords: e.target.value }))}
                    />
                  </label>
                  <label className="block text-xs text-slate-400">
                    {lang === "zh" ? "结论人设" : "Persona"}
                    <textarea
                      className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      rows={3}
                      value={analysis.persona}
                      onChange={(e) => setAnalysis((prev) => ({ ...prev, persona: e.target.value }))}
                    />
                  </label>
                  <label className="block text-xs text-slate-400">
                    {lang === "zh" ? "排版" : "Format"}
                    <input
                      className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      value={analysis.formatMode}
                      onChange={(e) => setAnalysis((prev) => ({ ...prev, formatMode: e.target.value }))}
                    />
                  </label>
                  <label className="block text-xs text-slate-400">
                    {lang === "zh" ? "口径约束" : "Grounding"}
                    <textarea
                      className="mt-1 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      rows={3}
                      value={analysis.grounding}
                      onChange={(e) => setAnalysis((prev) => ({ ...prev, grounding: e.target.value }))}
                    />
                  </label>
                </div>
              )}
              {analysis.enabled && editorTab === "memory" && (
                <div className="space-y-2">
                  {!editingId && <p className="text-xs text-slate-400">{lang === "zh" ? "保存后才能管理记忆。" : "Save the skill to manage memory."}</p>}
                  {examples.length === 0 && editingId && <p className="text-xs text-slate-400">{lang === "zh" ? "还没有沉淀示例。" : "No examples yet."}</p>}
                  {examples.map((item) => (
                    <div key={item.id} className="flex items-start justify-between gap-2 rounded-lg border border-[#2d2d4e] p-2">
                      <div>
                        <p className="text-sm text-white">{item.question}</p>
                        <p className="text-[11px] text-slate-400">{item.source || ""} · {item.use_count || 0}</p>
                      </div>
                      <button
                        type="button"
                        className="text-xs text-red-400"
                        onClick={async () => {
                          if (!editingId) return;
                          await skillsApi.deleteExample(editingId, item.id);
                          void loadExamples(editingId);
                        }}
                      >
                        {lang === "zh" ? "删除" : "Delete"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{c.status[lang]}</label>
                  <select
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    value={form.status}
                    onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as Skill["status"] }))}
                  >
                    <option value="draft">{s.statusDraft[lang]}</option>
                    <option value="active">{s.statusActive[lang]}</option>
                    <option value="archived">{s.statusArchived[lang]}</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{s.tags[lang]}</label>
                  <input
                    type="text"
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    placeholder={s.tagsHint[lang]}
                    value={form.tags}
                    onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
                  />
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" onClick={() => setShowModal(false)} className="rounded-lg px-4 py-2 text-sm theme-muted hover:theme-text">
                {c.cancel[lang]}
              </button>
              <button
                type="button"
                onClick={save}
                disabled={saving || !form.display_name.trim() || !form.description.trim()}
                className="agents-btn-primary disabled:opacity-40"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {c.save[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
