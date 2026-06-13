"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Heart, Lightbulb, PenLine, Sparkles, X, Code2, FileCode, Eye, Plus, Trash2 } from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import {
  INSPIRATION_CATEGORIES,
  type InspirationCategory,
  type InspirationItem,
} from "@/lib/inspirationCatalog";
import {
  documentToJson,
  exportFullHtml,
  parseInspirationDocument,
  renderDocumentToHtml,
} from "@/lib/inspirationDocument";
import {
  listInspirationsMerged,
  readFavoriteIds,
  resetInspirationOverride,
  saveInspirationOverride,
  toggleFavorite,
  createCustomInspiration,
  deleteCustomInspiration,
} from "@/lib/inspirationStore";
import { launchInspiration } from "@/lib/launchInspiration";
import { InspirationPreviewFrame } from "@/components/inspiration/InspirationPreviewFrame";
import toast from "react-hot-toast";

type EditTab = "preview" | "json" | "html" | "prompt";

export default function InspirationPage() {
  const router = useRouter();
  const { lang } = useLangStore();
  const ins = translations.inspiration;
  const c = translations.common;

  const [items, setItems] = useState<InspirationItem[]>(() => listInspirationsMerged());
  const [favorites, setFavorites] = useState<Set<string>>(() => readFavoriteIds());
  const [category, setCategory] = useState<InspirationCategory>("all");
  const [editing, setEditing] = useState<InspirationItem | null>(null);
  const [editTab, setEditTab] = useState<EditTab>("preview");
  const [editJson, setEditJson] = useState("");
  const [editHtml, setEditHtml] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newSubtitle, setNewSubtitle] = useState("");
  const [newCategory, setNewCategory] = useState<InspirationCategory>("finance");
  const [newPrompt, setNewPrompt] = useState("");

  const filtered = useMemo(() => {
    let list = [...items];
    if (category !== "all") list = list.filter((i) => i.category === category);
    return list.sort((a, b) => {
      const fa = favorites.has(a.id) ? 1 : 0;
      const fb = favorites.has(b.id) ? 1 : 0;
      if (fb !== fa) return fb - fa;
      return (b.featured ? 1 : 0) - (a.featured ? 1 : 0);
    });
  }, [items, category, favorites]);

  const previewFromEdit = useMemo(() => {
    if (editTab === "html" || !editJson) return editHtml;
    const doc = parseInspirationDocument(editJson);
    return doc ? renderDocumentToHtml(doc) : editHtml;
  }, [editTab, editJson, editHtml]);

  const openEdit = (item: InspirationItem) => {
    setEditing(item);
    setEditTab("preview");
    const doc = item.document?.[lang];
    setEditJson(doc ? documentToJson(doc) : "");
    setEditHtml(item.previewHtml[lang]);
    setEditPrompt(item.prompt[lang]);
  };

  const persistEdit = () => {
    if (!editing) return null;
    const doc = editJson.trim() ? parseInspirationDocument(editJson) : editing.document?.[lang] ?? null;
    const html = doc ? renderDocumentToHtml(doc) : editHtml;
    saveInspirationOverride(editing.id, lang, {
      document: doc ?? undefined,
      previewHtml: html,
      prompt: editPrompt,
    });
    return listInspirationsMerged().find((i) => i.id === editing.id)!;
  };

  const saveEdit = () => {
    if (!editing) return;
    if (editJson.trim() && !parseInspirationDocument(editJson)) {
      toast.error(ins.jsonInvalid[lang]);
      return;
    }
    persistEdit();
    setItems(listInspirationsMerged());
    toast.success(ins.saved[lang]);
    setEditing(null);
  };

  const cloneFromEdit = () => {
    if (!editing) return;
    if (editJson.trim() && !parseInspirationDocument(editJson)) {
      toast.error(ins.jsonInvalid[lang]);
      return;
    }
    const merged = persistEdit()!;
    setItems(listInspirationsMerged());
    setEditing(null);
    launchInspiration(router, merged, lang);
  };

  const resetEdit = () => {
    if (!editing) return;
    if (editing.custom) {
      toast.error(lang === "zh" ? "自定义灵感无默认版本，请直接编辑保存" : "Custom items have no default to reset");
      return;
    }
    resetInspirationOverride(editing.id);
    setItems(listInspirationsMerged());
    const fresh = listInspirationsMerged().find((i) => i.id === editing.id)!;
    const doc = fresh.document?.[lang];
    setEditJson(doc ? documentToJson(doc) : "");
    setEditHtml(fresh.previewHtml[lang]);
    setEditPrompt(fresh.prompt[lang]);
    toast.success(ins.reset[lang]);
  };

  const onToggleFavorite = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    toggleFavorite(id);
    setFavorites(readFavoriteIds());
  };

  const exportHtml = () => {
    if (!editing) return;
    const doc = parseInspirationDocument(editJson) ?? editing.document?.[lang];
    const title = lang === "zh" ? editing.title.zh : editing.title.en;
    const html = doc
      ? exportFullHtml(doc, title)
      : `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>${title}</title></head><body>${editHtml}</body></html>`;
    navigator.clipboard.writeText(html).then(() => toast.success(ins.exportCopied[lang]));
  };

  const submitCreate = () => {
    if (!newTitle.trim() || !newPrompt.trim()) {
      toast.error(lang === "zh" ? "请填写标题和做同款描述" : "Title and prompt are required");
      return;
    }
    const item = createCustomInspiration({
      title: newTitle.trim(),
      subtitle: newSubtitle.trim() || newTitle.trim(),
      category: newCategory,
      prompt: newPrompt.trim(),
      tone: newCategory === "finance" ? "green" : "blue",
      scene: newCategory === "finance" ? "finance" : undefined,
      agentHint: newCategory === "finance" ? "finance" : undefined,
    });
    setItems(listInspirationsMerged());
    setCreating(false);
    setNewTitle("");
    setNewSubtitle("");
    setNewPrompt("");
    toast.success(ins.addCreated[lang]);
    openEdit(item);
  };

  const removeCustom = () => {
    if (!editing?.custom) return;
    if (!confirm(ins.deleteConfirm[lang])) return;
    deleteCustomInspiration(editing.id);
    setItems(listInspirationsMerged());
    setFavorites(readFavoriteIds());
    setEditing(null);
    toast.success(ins.deleted[lang]);
  };

  const renderCard = (item: InspirationItem, index: number) => {
    const title = lang === "zh" ? item.title.zh : item.title.en;
    const subtitle = lang === "zh" ? item.subtitle.zh : item.subtitle.en;
    const sizeClass = item.featured && index === 0
      ? " inspiration-card--hero"
      : item.featured && index < 3
        ? " inspiration-card--featured"
        : "";

    return (
    <article
      key={item.id}
      className={`inspiration-card inspiration-tone-${item.tone}${sizeClass}${favorites.has(item.id) ? " inspiration-card--fav" : ""}`}
    >
      <div className="inspiration-preview-wrap">
        <div className="inspiration-preview-badges">
          <span className={`inspiration-format-tag inspiration-format-${item.format}`}>
            {item.format === "html" ? "HTML" : "MD"}
          </span>
          {item.featured && <span className="inspiration-featured-tag">{ins.featured[lang]}</span>}
        </div>
        <InspirationPreviewFrame
          html={item.previewHtml[lang]}
          tone={item.tone}
          featured={item.featured && index < 3}
        />
      </div>
      <div className="inspiration-card-body">
        <div className="inspiration-card-title-row">
          <div className="min-w-0">
            <h3>{title}</h3>
            <p className="inspiration-card-sub">{subtitle}</p>
          </div>
          <button
            type="button"
            className={`inspiration-heart${favorites.has(item.id) ? " inspiration-heart-active" : ""}`}
            onClick={(e) => onToggleFavorite(item.id, e)}
            aria-label={ins.favorite[lang]}
          >
            <Heart className="h-4 w-4" fill={favorites.has(item.id) ? "currentColor" : "none"} />
          </button>
        </div>
        <div className="inspiration-card-meta">
          {item.custom && <span className="inspiration-badge inspiration-badge-mine">{ins.customBadge[lang]}</span>}
          {item.official && <span className="inspiration-badge inspiration-badge-official">{ins.official[lang]}</span>}
          {item.document?.[lang] && (
            <span className="inspiration-badge">{ins.jsonDriven[lang]}</span>
          )}
        </div>
        <div className="inspiration-card-actions">
          <button type="button" className="inspiration-btn-secondary" onClick={() => openEdit(item)}>
            <PenLine className="h-3.5 w-3.5" />
            {ins.edit[lang]}
          </button>
          <button
            type="button"
            className="inspiration-btn-primary"
            onClick={() => launchInspiration(router, item, lang)}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {ins.clone[lang]}
          </button>
        </div>
      </div>
    </article>
    );
  };

  const editTabs: { id: EditTab; label: string; icon: typeof Eye }[] = [
    { id: "preview", label: ins.tabPreview[lang], icon: Eye },
    { id: "json", label: ins.tabJson[lang], icon: Code2 },
    { id: "html", label: ins.tabHtml[lang], icon: FileCode },
    { id: "prompt", label: ins.promptLabel[lang], icon: Sparkles },
  ];

  return (
    <div className="inspiration-hub">
      <div className="inspiration-hub-bg" aria-hidden />
      <header className="inspiration-header">
        <div className="inspiration-header-icon">
          <Lightbulb className="h-6 w-6" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="inspiration-eyebrow">{lang === "zh" ? "模板画廊" : "Template gallery"}</p>
          <h1>{ins.title[lang]}</h1>
          <p>{ins.subtitle[lang]}</p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inspiration-btn-primary inspiration-header-cta shrink-0"
        >
          <Plus className="h-4 w-4" />
          {ins.addInspiration[lang]}
        </button>
      </header>

      <div className="inspiration-filter-bar">
        <div className="inspiration-filter-scroll">
          {INSPIRATION_CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setCategory(cat.id)}
              className={`inspiration-filter-pill${category === cat.id ? " inspiration-filter-pill-active" : ""}`}
            >
              {lang === "zh" ? cat.label.zh : cat.label.en}
            </button>
          ))}
        </div>
        <span className="inspiration-count">{filtered.length} {lang === "zh" ? "个模板" : "templates"}</span>
      </div>

      <section className="inspiration-section">
        <div className="inspiration-bento">{filtered.map((item, i) => renderCard(item, i))}</div>
        {filtered.length === 0 && (
          <div className="inspiration-empty">
            <Sparkles className="h-8 w-8 opacity-40" />
            <p>{lang === "zh" ? "该分类暂无模板" : "No templates in this category"}</p>
          </div>
        )}
      </section>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
          <div className="theme-card inspiration-edit-dialog max-h-[92vh] w-full max-w-3xl overflow-y-auto p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold theme-text">{ins.editTitle[lang]}</h2>
                <p className="text-xs theme-muted">{lang === "zh" ? editing.title.zh : editing.title.en}</p>
              </div>
              <button type="button" onClick={() => setEditing(null)} className="rounded-lg p-1 theme-muted hover:theme-text">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="agents-hub-tabs mb-4">
              {editTabs.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setEditTab(id)}
                  className={`agents-hub-tab flex items-center gap-1${editTab === id ? " agents-hub-tab-active" : ""}`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </div>

            {editTab === "preview" && (
              <>
                <div className="inspiration-edit-preview-wrap mb-4">
                  <InspirationPreviewFrame html={previewFromEdit} tone={editing.tone} featured />
                </div>
                <p className="text-[11px] theme-muted">{ins.jsonHint[lang]}</p>
              </>
            )}

            {editTab === "json" && (
              <>
                <label className="inspiration-edit-label">{ins.tabJson[lang]}</label>
                <textarea
                  className="inspiration-edit-textarea font-mono text-xs"
                  rows={16}
                  value={editJson}
                  onChange={(e) => setEditJson(e.target.value)}
                  spellCheck={false}
                  placeholder='{ "version": 1, "format": "html", "root": { ... } }'
                />
                <p className="mt-2 text-[11px] theme-muted">{ins.jsonSchemaHint[lang]}</p>
              </>
            )}

            {editTab === "html" && (
              <>
                <div className="mb-2 flex justify-end">
                  <button type="button" onClick={exportHtml} className="agents-btn-secondary text-xs">
                    {ins.exportHtml[lang]}
                  </button>
                </div>
                <label className="inspiration-edit-label">{ins.tabHtml[lang]}</label>
                <textarea
                  className="inspiration-edit-textarea font-mono text-xs"
                  rows={12}
                  value={editHtml}
                  onChange={(e) => setEditHtml(e.target.value)}
                  spellCheck={false}
                />
                <div
                  className="inspiration-preview inspiration-preview-edit mb-4 mt-2"
                  dangerouslySetInnerHTML={{ __html: editHtml }}
                />
              </>
            )}

            {editTab === "prompt" && (
              <>
                <label className="inspiration-edit-label">{ins.promptLabel[lang]}</label>
                <textarea
                  className="inspiration-edit-textarea"
                  rows={8}
                  value={editPrompt}
                  onChange={(e) => setEditPrompt(e.target.value)}
                />
                <p className="mb-4 text-[11px] theme-muted">{ins.editHint[lang]}</p>
              </>
            )}

            <div className="mt-4 flex flex-wrap justify-end gap-2">
              {editing.custom && (
                <button type="button" onClick={removeCustom} className="mr-auto flex items-center gap-1 text-sm text-red-400 hover:text-red-300">
                  <Trash2 className="h-4 w-4" />
                  {ins.deleteInspiration[lang]}
                </button>
              )}
              {!editing.custom && (
                <button type="button" onClick={resetEdit} className="agents-btn-secondary text-sm">
                  {ins.reset[lang]}
                </button>
              )}
              <button type="button" onClick={() => setEditing(null)} className="text-sm theme-muted px-3">
                {c.cancel[lang]}
              </button>
              <button type="button" onClick={saveEdit} className="agents-btn-primary text-sm">
                {c.save[lang]}
              </button>
              <button type="button" onClick={cloneFromEdit} className="inspiration-btn-primary px-4 py-2 text-sm">
                <Sparkles className="h-4 w-4 inline mr-1" />
                {ins.clone[lang]}
              </button>
            </div>
          </div>
        </div>
      )}

      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4">
          <div className="theme-card inspiration-edit-dialog max-h-[92vh] w-full max-w-lg overflow-y-auto p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
              <h2 className="text-lg font-semibold theme-text">{ins.addTitle[lang]}</h2>
              <button type="button" onClick={() => setCreating(false)} className="rounded-lg p-1 theme-muted hover:theme-text">
                <X className="h-5 w-5" />
              </button>
            </div>
            <label className="inspiration-edit-label">{ins.addTitleLabel[lang]}</label>
            <input
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-2 text-sm theme-text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder={lang === "zh" ? "例如：年度审计汇报" : "e.g. Annual audit report"}
            />
            <label className="inspiration-edit-label">{ins.addSubtitleLabel[lang]}</label>
            <input
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-2 text-sm theme-text"
              value={newSubtitle}
              onChange={(e) => setNewSubtitle(e.target.value)}
              placeholder={lang === "zh" ? "简短说明用途" : "Short description"}
            />
            <label className="inspiration-edit-label">{ins.addCategoryLabel[lang]}</label>
            <select
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-2 text-sm theme-text"
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value as InspirationCategory)}
            >
              {INSPIRATION_CATEGORIES.filter((c) => c.id !== "all").map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {lang === "zh" ? cat.label.zh : cat.label.en}
                </option>
              ))}
            </select>
            <label className="inspiration-edit-label">{ins.addPromptLabel[lang]}</label>
            <textarea
              className="inspiration-edit-textarea mb-4"
              rows={6}
              value={newPrompt}
              onChange={(e) => setNewPrompt(e.target.value)}
              placeholder={ins.addPromptPlaceholder[lang]}
            />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setCreating(false)} className="text-sm theme-muted px-3">
                {c.cancel[lang]}
              </button>
              <button type="button" onClick={submitCreate} className="inspiration-btn-primary px-4 py-2 text-sm">
                <Plus className="h-4 w-4 inline mr-1" />
                {ins.addInspiration[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
