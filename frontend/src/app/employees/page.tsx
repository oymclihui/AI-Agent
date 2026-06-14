"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Plus, Briefcase, Trash2, ChevronRight, Loader2, LayoutTemplate, Search, X, Clock,
  Network, LayoutGrid,
} from "lucide-react";
import { agentsApi, employeesApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { useAuthStore } from "@/lib/authStore";
import EmployeeOrgChart, { type OrgTreeData } from "@/components/EmployeeOrgChart";
import {
  EMPLOYEE_CATEGORIES,
  categoryLabel,
  employeeAvatarTone,
  normalizeTemplateCategory,
  type EmployeeTemplateCategoryId,
} from "@/lib/employeeCatalog";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";
import toast from "react-hot-toast";

interface Employee {
  id: string;
  name: string;
  title: string | null;
  description: string | null;
  status: string;
  agent_id: string;
  timezone: string;
  task_count: number;
  metadata?: Record<string, unknown>;
}

interface AgentOption { id: string; name: string; role: string; }

interface EmployeeTemplate {
  template_id: string;
  name_zh: string;
  name_en: string;
  description_zh: string;
  description_en: string;
  category: string;
  status?: string;
  employee_name: string;
  employee_title: string | null;
  task_count: number;
  tasks_preview: string[];
}

const FEATURED_EMPLOYEE_SCENES = [
  {
    id: "marketing" as EmployeeTemplateCategoryId,
    title: { zh: "内容营销", en: "Marketing" },
    subtitle: { zh: "每日选题 · 文案 · 社媒运营", en: "Daily topics · copy · social" },
    tone: "agents-scene-content",
  },
  {
    id: "analytics" as EmployeeTemplateCategoryId,
    title: { zh: "数据分析", en: "Analytics" },
    subtitle: { zh: "周报 · 指标 · 可视化", en: "Weekly reports · metrics · viz" },
    tone: "agents-scene-data",
  },
  {
    id: "engineering" as EmployeeTemplateCategoryId,
    title: { zh: "技术工程", en: "Engineering" },
    subtitle: { zh: "代码审查 · 架构 · 质量", en: "Code review · architecture" },
    tone: "agents-scene-tech",
  },
  {
    id: "finance" as EmployeeTemplateCategoryId,
    title: { zh: "金融投研", en: "Finance" },
    subtitle: { zh: "研报 · 估值 · 市场洞察", en: "Research · valuation" },
    tone: "agents-scene-finance",
  },
];

export default function EmployeesPage() {
  const router = useRouter();
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const e = translations.employees;
  const s = translations.skills;
  const c = translations.common;
  const chatT = translations.chat;

  const [items, setItems] = useState<Employee[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [templates, setTemplates] = useState<EmployeeTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [importingId, setImportingId] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<EmployeeTemplate | null>(null);
  const [importName, setImportName] = useState("");
  const [templateSearch, setTemplateSearch] = useState("");
  const [templateCategory, setTemplateCategory] = useState<EmployeeTemplateCategoryId>("all");
  const [saving, setSaving] = useState(false);
  const [viewMode, setViewMode] = useState<"org" | "cards">("org");
  const [orgTree, setOrgTree] = useState<OrgTreeData | null>(null);
  const [orgLoading, setOrgLoading] = useState(false);
  const [syncingOrg, setSyncingOrg] = useState(false);
  const [form, setForm] = useState({
    name: "", title: "", description: "", agent_id: "", timezone: "Asia/Shanghai",
  });

  const load = async () => {
    try {
      const { data } = await employeesApi.list();
      setItems(data);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  const loadOrgTree = async () => {
    setOrgLoading(true);
    try {
      const { data } = await employeesApi.orgTree(true);
      setOrgTree(data as OrgTreeData);
    } catch {
      toast.error(lang === "zh" ? "组织架构加载失败" : "Failed to load org chart");
    } finally {
      setOrgLoading(false);
    }
  };

  const syncOrg = async () => {
    setSyncingOrg(true);
    try {
      await employeesApi.syncOrgTree();
      toast.success(e.syncOrgOk[lang]);
      await loadOrgTree();
    } catch {
      toast.error(e.syncOrgFail[lang]);
    } finally {
      setSyncingOrg(false);
    }
  };

  useEffect(() => {
    load();
    agentsApi.list(lang).then(({ data }) => {
      setAgents(data);
      if (data[0]) setForm((f) => ({ ...f, agent_id: data[0].id }));
    }).catch(() => {});
  }, [lang]);

  useEffect(() => {
    if (viewMode === "org" && !loading && items.length > 0) {
      void loadOrgTree();
    }
  }, [viewMode, loading, items.length]);

  const openTemplates = async () => {
    setShowTemplates(true);
    setSelectedTemplate(null);
    setImportName("");
    setTemplateSearch("");
    setTemplateCategory("all");
    setTemplatesLoading(true);
    try {
      const { data } = await employeesApi.listTemplates();
      setTemplates(data);
    } catch {
      toast.error(e.templateImportFail[lang]);
    } finally {
      setTemplatesLoading(false);
    }
  };

  const selectTemplate = (tpl: EmployeeTemplate) => {
    setSelectedTemplate(tpl);
    setImportName(tpl.employee_name);
  };

  const importTemplate = async () => {
    if (!selectedTemplate) return;
    setImportingId(selectedTemplate.template_id);
    try {
      const { data } = await employeesApi.importTemplate({
        template_id: selectedTemplate.template_id,
        employee_name: importName.trim() || undefined,
      });
      toast.success(e.templateImportOk[lang]);
      setShowTemplates(false);
      load();
      if (viewMode === "org") void loadOrgTree();
      router.push(`/employees/${data.employee.id}`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : e.templateImportFail[lang];
      toast.error(msg);
      if (typeof detail === "string" && detail.includes("Agent not found")) {
        toast.error(e.agentMissingHint[lang], { duration: 5000 });
      }
    } finally {
      setImportingId(null);
    }
  };

  const create = async () => {
    if (!form.name.trim() || !form.agent_id) return;
    setSaving(true);
    try {
      await employeesApi.create(form);
      toast.success(c.create[lang] + " OK");
      setShowCreate(false);
      setForm({ name: "", title: "", description: "", agent_id: agents[0]?.id ?? "", timezone: "Asia/Shanghai" });
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : (lang === "zh" ? "创建失败" : "Create failed");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm(e.deleteConfirm[lang])) return;
    try {
      await employeesApi.delete(id);
      load();
    } catch {
      toast.error(c.delete[lang] + " failed");
    }
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);
  const tplName = (tpl: EmployeeTemplate) => (lang === "zh" ? tpl.name_zh : tpl.name_en) || tpl.template_id;
  const tplDesc = (tpl: EmployeeTemplate) => (lang === "zh" ? tpl.description_zh : tpl.description_en);
  const initial = (name: string) => (name.trim()[0] || "E").toUpperCase();

  const filteredTemplates = useMemo(() => {
    let list = [...templates];
    if (templateCategory !== "all") {
      list = list.filter((tpl) => normalizeTemplateCategory(tpl.category) === templateCategory);
    }
    const q = templateSearch.trim().toLowerCase();
    if (q) {
      list = list.filter((tpl) => {
        const hay = [
          tplName(tpl),
          tplDesc(tpl),
          tpl.employee_title ?? "",
          tpl.category,
          ...tpl.tasks_preview,
        ].join(" ").toLowerCase();
        return hay.includes(q);
      });
    }
    return list;
  }, [templates, templateCategory, templateSearch, lang]);

  const sceneTemplates = (catId: EmployeeTemplateCategoryId) =>
    templates.filter((tpl) => normalizeTemplateCategory(tpl.category) === catId).slice(0, 3);

  const sortedItems = useMemo(() => [...items].sort((a, b) => a.name.localeCompare(b.name)), [items]);

  return (
    <div className="agents-hub">
      <div className="agents-hub-header">
        <div>
          <h1>{e.title[lang]}</h1>
          <p>{e.subtitle[lang]}</p>
        </div>
        <div className="agents-hub-actions">
          <button type="button" onClick={openTemplates} className="agents-btn-secondary">
            <LayoutTemplate className="h-4 w-4" /> {e.fromTemplate[lang]}
          </button>
          <button type="button" onClick={() => setShowCreate(true)} className="agents-btn-primary">
            <Plus className="h-4 w-4" /> {e.newEmployee[lang]}
          </button>
        </div>
      </div>

      {!loading && items.length > 0 && (
        <div className="employees-view-toggle">
          <button
            type="button"
            onClick={() => setViewMode("org")}
            className={`employees-view-btn${viewMode === "org" ? " employees-view-btn-active" : ""}`}
          >
            <Network className="h-4 w-4" /> {e.viewOrg[lang]}
          </button>
          <button
            type="button"
            onClick={() => setViewMode("cards")}
            className={`employees-view-btn${viewMode === "cards" ? " employees-view-btn-active" : ""}`}
          >
            <LayoutGrid className="h-4 w-4" /> {e.viewCards[lang]}
          </button>
          {viewMode === "org" && (
            <button
              type="button"
              disabled={syncingOrg || orgLoading}
              onClick={() => void syncOrg()}
              className="employees-view-btn ml-auto"
            >
              {syncingOrg ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
              {e.syncOrg[lang]}
            </button>
          )}
        </div>
      )}

      {loading ? (
        <div className="theme-muted text-sm">{c.loading[lang]}</div>
      ) : items.length === 0 ? (
        <div className="agents-empty">
          <Briefcase className="mb-4 h-12 w-12 opacity-40" />
          <p className="mb-4">{e.noEmployees[lang]}</p>
          <button type="button" onClick={openTemplates} className="agents-btn-secondary">
            <LayoutTemplate className="h-4 w-4" /> {e.fromTemplate[lang]}
          </button>
        </div>
      ) : viewMode === "org" ? (
        orgLoading || !orgTree ? (
          <div className="theme-muted flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> {c.loading[lang]}
          </div>
        ) : (
          <EmployeeOrgChart
            tree={orgTree}
            lang={lang}
            activeLabel={c.active[lang]}
            pausedLabel={e.paused[lang]}
            taskCountLabel={e.taskCount[lang]}
            openDetailLabel={e.openDetail[lang]}
          />
        )
      ) : (
        <div className="agents-grid">
          {sortedItems.map((emp) => (
            <article key={emp.id} className="agents-card">
              <div className="agents-card-top">
                <div className={`agents-avatar ${employeeAvatarTone(emp.id)}`} aria-hidden>
                  {initial(emp.name)}
                </div>
                <div className="agents-card-head">
                  <div className="agents-card-title-row">
                    <h3 title={emp.name}>{emp.name}</h3>
                    <span className={`agents-badge ${
                      emp.status === "active" ? "agents-badge-chat" : "agents-badge-beta"
                    }`}>
                      {emp.status === "active" ? c.active[lang] : e.paused[lang]}
                    </span>
                  </div>
                  {emp.title && <p className="agents-card-role">{emp.title}</p>}
                </div>
              </div>
              <p className="agents-card-desc">{emp.description || "—"}</p>
              <div className="agents-card-tags">
                <span className="agents-tag">{agentName(emp.agent_id)}</span>
                <span className="agents-tag">
                  <Clock className="mr-0.5 inline h-3 w-3 opacity-70" />
                  {e.taskCount[lang]}: {emp.task_count}
                </span>
              </div>
              <div className="agents-card-footer">
                <span className="agents-card-meta">{emp.timezone}</span>
                <div className="agents-card-actions">
                  <button
                    type="button"
                    onClick={() => remove(emp.id)}
                    className="agents-icon-btn agents-icon-btn-danger"
                    title={c.delete[lang]}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  <Link href={`/employees/${emp.id}`} className="agents-summon-btn inline-flex items-center">
                    {e.openDetail[lang]} <ChevronRight className="ml-0.5 inline h-3 w-3" />
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {showTemplates && (
        <div className="employees-template-overlay">
          <div className="employees-template-dialog">
            <div className="employees-template-header">
              <div>
                <h2>{e.templateTitle[lang]}</h2>
                <p>{e.templateSelectHint[lang]}</p>
              </div>
              <button
                type="button"
                onClick={() => setShowTemplates(false)}
                className="employees-template-close"
                aria-label={c.cancel[lang]}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {!templatesLoading && templates.length > 0 && (
              <section className="agents-featured">
                <h2 className="agents-featured-title">{e.templateFeatured[lang]}</h2>
                <CapsuleScrollRow
                  scrollStep={268}
                  scrollLeftLabel={chatT.scrollLeft[lang]}
                  scrollRightLabel={chatT.scrollRight[lang]}
                  innerClassName="agents-featured-scroll"
                >
                  {FEATURED_EMPLOYEE_SCENES.map((scene) => {
                    const picks = sceneTemplates(scene.id);
                    return (
                      <button
                        key={scene.id}
                        type="button"
                        className={`agents-scene-card ${scene.tone}`}
                        onClick={() => setTemplateCategory(scene.id)}
                      >
                        <div>
                          <h3>{lang === "zh" ? scene.title.zh : scene.title.en}</h3>
                          <p>{lang === "zh" ? scene.subtitle.zh : scene.subtitle.en}</p>
                        </div>
                        <ul className="agents-scene-list">
                          {picks.length > 0 ? (
                            picks.map((item) => <li key={item.template_id}>{tplName(item)}</li>)
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

            <div className="agents-hub-toolbar employees-template-toolbar">
              <div className="agents-hub-search employees-template-search">
                <Search className="h-4 w-4 shrink-0 theme-muted" />
                <input
                  type="search"
                  value={templateSearch}
                  onChange={(ev) => setTemplateSearch(ev.target.value)}
                  placeholder={e.templateSearch[lang]}
                />
              </div>
            </div>

            <div className="agents-filter-row employees-template-filters">
              <CapsuleScrollRow
                centerWhenFit
                className="flex-1 min-w-0"
                scrollLeftLabel={chatT.scrollLeft[lang]}
                scrollRightLabel={chatT.scrollRight[lang]}
                innerClassName="agents-filter-scroll"
              >
                {EMPLOYEE_CATEGORIES.map((cat) => (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => setTemplateCategory(cat.id)}
                    className={`agents-filter-pill${
                      templateCategory === cat.id ? " agents-filter-pill-active" : ""
                    }`}
                  >
                    {lang === "zh" ? cat.label.zh : cat.label.en}
                  </button>
                ))}
              </CapsuleScrollRow>
            </div>

            <div className="employees-template-body">
              <div className="employees-template-grid-wrap">
                {templatesLoading ? (
                  <div className="employees-template-loading">
                    <Loader2 className="h-6 w-6 animate-spin" />
                    <span>{c.loading[lang]}</span>
                  </div>
                ) : filteredTemplates.length === 0 ? (
                  <div className="agents-empty">
                    <LayoutTemplate className="mb-3 h-10 w-10 opacity-40" />
                    <p>{c.noData[lang]}</p>
                  </div>
                ) : (
                  <div className="agents-grid employees-template-grid">
                    {filteredTemplates.map((tpl) => {
                      const selected = selectedTemplate?.template_id === tpl.template_id;
                      return (
                        <button
                          key={tpl.template_id}
                          type="button"
                          onClick={() => selectTemplate(tpl)}
                          className={`agents-card employees-template-card${selected ? " employees-template-card-selected" : ""}`}
                        >
                          <div className="agents-card-top">
                            <div className={`agents-avatar ${employeeAvatarTone(tpl.template_id)}`} aria-hidden>
                              {initial(tpl.employee_name || tplName(tpl))}
                            </div>
                            <div className="agents-card-head">
                              <div className="agents-card-title-row">
                                <h3 title={tplName(tpl)}>{tplName(tpl)}</h3>
                                {user?.is_admin && tpl.status && (
                                  <span className={`agents-badge ${
                                    tpl.status === "active" ? "agents-badge-chat" : "agents-badge-master"
                                  }`}>
                                    {tpl.status === "active" ? s.statusActive[lang] : s.statusDraft[lang]}
                                  </span>
                                )}
                              </div>
                              {tpl.employee_title && (
                                <p className="agents-card-role">{tpl.employee_title}</p>
                              )}
                            </div>
                          </div>
                          <p className="agents-card-desc">{tplDesc(tpl)}</p>
                          <div className="agents-card-tags">
                            <span className="agents-tag">{categoryLabel(tpl.category, lang)}</span>
                            <span className="agents-tag">{e.templateTasks[lang]}: {tpl.task_count}</span>
                            {tpl.tasks_preview.slice(0, 2).map((task) => (
                              <span key={task} className="agents-tag">{task}</span>
                            ))}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <aside className="employees-template-preview">
                {selectedTemplate ? (
                  <>
                    <div className="employees-template-preview-head">
                      <div className={`agents-avatar ${employeeAvatarTone(selectedTemplate.template_id)}`}>
                        {initial(importName || selectedTemplate.employee_name)}
                      </div>
                      <div>
                        <h3>{tplName(selectedTemplate)}</h3>
                        <p>{selectedTemplate.employee_title}</p>
                      </div>
                    </div>
                    <p className="employees-template-preview-desc">{tplDesc(selectedTemplate)}</p>
                    <label className="employees-template-label">{e.customName[lang]}</label>
                    <input
                      className="employees-template-input"
                      value={importName}
                      onChange={(ev) => setImportName(ev.target.value)}
                      placeholder={selectedTemplate.employee_name}
                    />
                    <p className="employees-template-label">{e.templateTasks[lang]}</p>
                    <ul className="employees-template-task-list">
                      {selectedTemplate.tasks_preview.map((task) => (
                        <li key={task}>{task}</li>
                      ))}
                    </ul>
                    <button
                      type="button"
                      onClick={importTemplate}
                      disabled={importingId === selectedTemplate.template_id}
                      className="agents-btn-primary employees-template-import"
                    >
                      {importingId === selectedTemplate.template_id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <LayoutTemplate className="h-4 w-4" />
                      )}
                      {e.templateImport[lang]}
                    </button>
                  </>
                ) : (
                  <div className="employees-template-preview-empty">
                    <LayoutTemplate className="mb-3 h-10 w-10 opacity-30" />
                    <p>{e.templatePickHint[lang]}</p>
                  </div>
                )}
              </aside>
            </div>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card w-full max-w-md p-6">
            <h2 className="mb-4 text-lg font-semibold theme-text">{e.newEmployee[lang]}</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs theme-muted">{c.name[lang]}</label>
                <input
                  className="theme-input w-full rounded-lg px-3 py-2 text-sm"
                  value={form.name}
                  onChange={(ev) => setForm((f) => ({ ...f, name: ev.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs theme-muted">{e.titleField[lang]}</label>
                <input
                  className="theme-input w-full rounded-lg px-3 py-2 text-sm"
                  value={form.title}
                  onChange={(ev) => setForm((f) => ({ ...f, title: ev.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs theme-muted">{c.description[lang]}</label>
                <textarea
                  className="theme-input w-full rounded-lg px-3 py-2 text-sm"
                  rows={2}
                  value={form.description}
                  onChange={(ev) => setForm((f) => ({ ...f, description: ev.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs theme-muted">{e.bindAgent[lang]}</label>
                <select
                  className="theme-input w-full rounded-lg px-3 py-2 text-sm"
                  value={form.agent_id}
                  onChange={(ev) => setForm((f) => ({ ...f, agent_id: ev.target.value }))}
                >
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({a.role})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" onClick={() => setShowCreate(false)} className="text-sm theme-muted">
                {c.cancel[lang]}
              </button>
              <button
                type="button"
                onClick={create}
                disabled={saving || !form.name.trim()}
                className="agents-btn-primary disabled:opacity-40"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {c.create[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
