"use client";

import { useEffect, useState } from "react";
import {
  Plus, BookOpen, Trash2, RefreshCw, Pencil, Loader2, CloudDownload, Search,
} from "lucide-react";
import { skillsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
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

export default function SkillsPage() {
  const { lang } = useLangStore();
  const s = translations.skills;
  const c = translations.common;

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

  const load = async () => {
    try {
      const { data } = await skillsApi.list();
      setSkills(data);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowModal(true);
  };

  const openEdit = (skill: Skill) => {
    setEditingId(skill.id);
    setForm({
      slug: skill.slug,
      display_name: skill.display_name,
      description: skill.description,
      instructions_md: skill.instructions_md,
      status: skill.status,
      auto_invoke: skill.auto_invoke,
      tags: (skill.tags ?? []).join(", "),
    });
    setShowModal(true);
  };

  const save = async () => {
    if (!form.display_name.trim() || !form.description.trim()) return;
    setSaving(true);
    const payload = {
      slug: form.slug.trim() || undefined,
      display_name: form.display_name.trim(),
      description: form.description.trim(),
      instructions_md: form.instructions_md,
      status: form.status,
      auto_invoke: form.auto_invoke,
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
    };
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

  const deleteSkill = async (id: string) => {
    if (!confirm(s.deleteConfirm[lang])) return;
    try {
      await skillsApi.delete(id);
      toast.success(lang === "zh" ? "已删除" : "Deleted");
      load();
    } catch {
      toast.error(lang === "zh" ? "删除失败" : "Delete failed");
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
      const params: { source?: string; category?: string; q?: string } = {};
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
      await skillsApi.librarySync("skills-hub");
      toast.success(s.librarySyncOk[lang]);
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
    if (status === "active") return "bg-green-500/20 text-green-400";
    if (status === "archived") return "bg-slate-500/20 text-slate-400";
    return "bg-yellow-500/20 text-yellow-400";
  };

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{s.title[lang]}</h1>
          <p className="text-slate-400">{s.subtitle[lang]}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={openLibrary}
            className="flex items-center gap-2 rounded-lg border border-teal-500/40 px-4 py-2 text-sm text-teal-300 hover:bg-teal-500/10 transition-colors"
          >
            <CloudDownload className="h-4 w-4" /> {s.library[lang]}
          </button>
          <button
            onClick={seedTemplates}
            className="flex items-center gap-2 rounded-lg border border-[#2d2d4e] px-4 py-2 text-sm text-slate-300 hover:bg-white/5 transition-colors"
          >
            <RefreshCw className="h-4 w-4" /> {s.seedTemplates[lang]}
          </button>
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" /> {s.newSkill[lang]}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-slate-400">{c.loading[lang]}</div>
      ) : skills.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#2d2d4e] py-16 text-center">
          <BookOpen className="mb-4 h-12 w-12 text-slate-600" />
          <p className="text-slate-400">{s.noSkills[lang]}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {skills.map((skill) => (
            <div key={skill.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-white">{skill.display_name}</h3>
                  <p className="text-xs text-slate-500 font-mono">{skill.slug}</p>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${statusClass(skill.status)}`}>
                  {statusLabel(skill.status)}
                </span>
              </div>
              <p className="mb-4 line-clamp-3 text-sm text-slate-400">{skill.description}</p>
              <div className="mb-4 flex flex-wrap gap-2 text-xs">
                <span className="rounded bg-slate-700/50 px-2 py-0.5 text-slate-400">
                  {s.version[lang]} v{skill.version}
                </span>
                {(skill.tags ?? []).map((tag) => (
                  <span key={tag} className="rounded bg-teal-500/10 px-2 py-0.5 text-teal-400">{tag}</span>
                ))}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => openEdit(skill)}
                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-blue-400 hover:bg-blue-500/10 transition-colors"
                >
                  <Pencil className="h-3 w-3" /> {s.editSkill[lang]}
                </button>
                <button
                  onClick={() => deleteSkill(skill.id)}
                  className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                >
                  <Trash2 className="h-3 w-3" /> {c.delete[lang]}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showLibrary && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="flex max-h-[92vh] w-full max-w-4xl flex-col rounded-xl border border-[#2d2d4e] bg-[#1a1a2e]">
            <div className="border-b border-[#2d2d4e] p-5">
              <h2 className="text-lg font-semibold text-white">{s.libraryTitle[lang]}</h2>
              <p className="mt-1 text-sm text-slate-400">{s.librarySubtitle[lang]}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <select
                  className="rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
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
                  className="rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={libCategory}
                  onChange={(e) => { setLibCategory(e.target.value); loadLibrary(libSource, e.target.value, libQuery); }}
                >
                  <option value="">{s.allCategories[lang]}</option>
                  {libCategories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
                <div className="relative min-w-[200px] flex-1">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="text"
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] py-2 pl-9 pr-3 text-sm text-white"
                    placeholder={s.librarySearch[lang]}
                    value={libQuery}
                    onChange={(e) => setLibQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && loadLibrary(libSource, libCategory, libQuery)}
                  />
                </div>
                <button
                  onClick={() => loadLibrary(libSource, libCategory, libQuery)}
                  className="rounded-lg border border-[#2d2d4e] px-3 py-2 text-sm text-slate-300 hover:bg-white/5"
                >
                  {lang === "zh" ? "搜索" : "Search"}
                </button>
                <button
                  onClick={syncLibrary}
                  disabled={libSyncing}
                  className="flex items-center gap-1 rounded-lg border border-[#2d2d4e] px-3 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-40"
                >
                  {libSyncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  {s.librarySync[lang]}
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {libLoading ? (
                <div className="py-12 text-center text-slate-400">{c.loading[lang]}</div>
              ) : libTemplates.length === 0 ? (
                <div className="py-12 text-center text-slate-500">{c.noData[lang]}</div>
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
                          checked ? "border-teal-500/50 bg-teal-500/5" : "border-[#2d2d4e] hover:bg-white/[0.02]"
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
                            <span className="font-medium text-white">{tpl.display_name}</span>
                            <span className="font-mono text-[10px] text-slate-500">{tpl.slug}</span>
                            <span className="rounded bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-400">{tpl.category}</span>
                            <span className="rounded bg-purple-500/10 px-1.5 py-0.5 text-[10px] text-purple-400">{tpl.source}</span>
                            {imported && (
                              <span className="rounded bg-green-500/10 px-1.5 py-0.5 text-[10px] text-green-400">
                                {lang === "zh" ? "已导入" : "Imported"}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs text-slate-400">{tpl.description}</p>
                        </div>
                      </label>
                    );
                  })}
                  {libTemplates.length > 120 && (
                    <p className="py-2 text-center text-xs text-slate-500">
                      {lang === "zh"
                        ? `显示前 120 / ${libTemplates.length} 条，请用搜索或分类缩小范围`
                        : `Showing 120 / ${libTemplates.length}. Use search or category to narrow.`}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-[#2d2d4e] p-4">
              <span className="text-xs text-slate-500">
                {libSelected.size} {lang === "zh" ? "已选" : "selected"} · {libTemplates.length} {lang === "zh" ? "条结果" : "results"}
              </span>
              <div className="flex gap-2">
                <button onClick={() => setShowLibrary(false)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white">
                  {c.cancel[lang]}
                </button>
                <button
                  onClick={() => importLibrary(libTemplates.slice(0, 120).filter((t) => !localSlugs.has(t.slug)))}
                  disabled={libImporting || libTemplates.length === 0}
                  className="rounded-lg border border-[#2d2d4e] px-4 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-40"
                >
                  {s.libraryImportAll[lang]}
                </button>
                <button
                  onClick={() => {
                    const items = libTemplates.filter((t) => libSelected.has(libKey(t)));
                    importLibrary(items);
                  }}
                  disabled={libImporting || libSelected.size === 0}
                  className="flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm text-white hover:bg-teal-700 disabled:opacity-40"
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
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">
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
              <div>
                <label className="mb-1 block text-xs text-slate-400">{s.instructions[lang]}</label>
                <textarea
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 font-mono text-sm text-white focus:border-blue-500 focus:outline-none"
                  rows={12}
                  placeholder={s.instructionsHint[lang]}
                  value={form.instructions_md}
                  onChange={(e) => setForm((f) => ({ ...f, instructions_md: e.target.value }))}
                />
              </div>
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
              <button
                onClick={() => setShowModal(false)}
                className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white"
              >
                {c.cancel[lang]}
              </button>
              <button
                onClick={save}
                disabled={saving || !form.display_name.trim() || !form.description.trim()}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
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
