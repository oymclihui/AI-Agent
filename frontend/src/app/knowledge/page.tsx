"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Database, Upload, Trash2, Search, FileText, Loader2, X, Eye, FolderOpen, HardDrive, Shield } from "lucide-react";
import MarkdownView from "@/components/MarkdownView";
import { knowledgeApi, modelsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

interface KB {
  id: string;
  name: string;
  description: string | null;
  status: string;
  source_type: string;
  document_count: number;
  embedding_model: string;
  visibility?: string;
  can_manage?: boolean;
  grant_count?: number;
}
interface KbGrant {
  grantee_type: string;
  grantee_id: string;
  label: string;
}
interface Doc {
  id: string;
  filename: string;
  file_type: string;
  status: string;
  chunk_count: number;
  file_size: number | null;
  stage?: string;
  stages?: Record<string, string>;
  stage_error?: string;
}
interface DocContent {
  id: string;
  filename: string;
  file_type: string;
  content: string;
  source: string;
  chunk_count: number;
}
interface ModelOpt { model: string; type: string; }

const FALLBACK_EMBEDDINGS = ["nomic-embed-text", "nomic-embed-text-v2-moe", "qwen3-embedding:0.6b", "bge-m3"];

type ListFilter = "all" | "local";

function isMarkdown(fileType: string, filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || fileType.toLowerCase();
  return ext === "md" || ext === "markdown";
}

export default function KnowledgePage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const k = translations.knowledge;
  const c = translations.common;

  const [kbs, setKbs] = useState<KB[]>([]);
  const [activeKb, setActiveKb] = useState<string | null>(null);
  const [activeKbMeta, setActiveKbMeta] = useState<KB | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [activeDoc, setActiveDoc] = useState<Doc | null>(null);
  const [docContent, setDocContent] = useState<DocContent | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [docsLoading, setDocsLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [embedOptions, setEmbedOptions] = useState<string[]>(FALLBACK_EMBEDDINGS);
  const [listFilter, setListFilter] = useState<ListFilter>("all");
  const [kbFilterSearch, setKbFilterSearch] = useState("");
  const [form, setForm] = useState({ name: "", description: "", embedding_model: "nomic-embed-text", chunk_size: 1000, chunk_overlap: 200 });
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{ content: string; score: number; document_name: string }[]>([]);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [faqOpen, setFaqOpen] = useState(false);
  const [faqRows, setFaqRows] = useState<{ id: string; standard_question: string; answer: string }[]>([]);
  const [faqQuestion, setFaqQuestion] = useState("");
  const [faqSimilar, setFaqSimilar] = useState("");
  const [faqNegative, setFaqNegative] = useState("");
  const [faqAnswer, setFaqAnswer] = useState("");
  const [wecomOpen, setWecomOpen] = useState(false);
  const [wecomEnabled, setWecomEnabled] = useState(false);
  const [wecomCorp, setWecomCorp] = useState("");
  const [wecomSecret, setWecomSecret] = useState("");
  const [wecomDocsText, setWecomDocsText] = useState("");
  const [wecomStatus, setWecomStatus] = useState("");
  const [shareVisibility, setShareVisibility] = useState<"private" | "public">("private");
  const [shareGrants, setShareGrants] = useState<KbGrant[]>([]);
  const [shareUsers, setShareUsers] = useState<{ id: string; display_name: string; employee_no?: string | null }[]>([]);
  const [shareDepts, setShareDepts] = useState<{ id: string; name: string }[]>([]);
  const [shareQuery, setShareQuery] = useState("");
  const [shareDeptId, setShareDeptId] = useState("");
  const [shareSaving, setShareSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const accessText = (kb: KB) => {
    if (kb.visibility === "public") return lang === "zh" ? "公开" : "Public";
    if ((kb.grant_count || 0) > 0) return lang === "zh" ? "已共享" : "Shared";
    return lang === "zh" ? "私有" : "Private";
  };

  const load = async () => {
    try {
      const { data } = await knowledgeApi.list();
      setKbs(data);
    } finally {
      setLoading(false);
    }
  };

  const loadEmbeddings = async () => {
    try {
      const { data } = await modelsApi.listAvailable();
      const embeds = (data as ModelOpt[])
        .map((m) => m.model)
        .filter((m) => m.toLowerCase().includes("embed"));
      if (embeds.length) {
        setEmbedOptions(embeds);
        setForm((f) => ({ ...f, embedding_model: embeds.find((e) => e.includes("nomic")) || embeds[0] }));
      }
    } catch { /* keep fallback list */ }
  };

  useEffect(() => { load(); loadEmbeddings(); }, []);

  useEffect(() => {
    const f = new URLSearchParams(window.location.search).get("filter");
    if (f === "local" || f === "all") setListFilter(f as ListFilter);
  }, []);

  const openCreateModal = () => {
    setShowCreate(true);
  };

  const closeViewer = () => {
    setActiveDoc(null);
    setDocContent(null);
  };

  const openKb = async (kb: KB) => {
    setActiveKb(kb.id);
    setActiveKbMeta(kb);
    closeViewer();
    setDocsLoading(true);
    setSearchResults([]);
    setSearched(false);
    setQuery("");
    try {
      const { data } = await knowledgeApi.listDocuments(kb.id);
      setDocs(data);
    } catch {
      toast.error(lang === "zh" ? "加载文档失败" : "Failed to load documents");
    } finally {
      setDocsLoading(false);
    }
  };

  const openDoc = async (doc: Doc) => {
    if (!activeKb) return;
    setActiveDoc(doc);
    setDocContent(null);
    setContentLoading(true);
    try {
      const { data } = await knowledgeApi.getDocumentContent(activeKb, doc.id);
      setDocContent(data);
    } catch {
      toast.error(k.contentFailed[lang]);
      setActiveDoc(null);
    } finally {
      setContentLoading(false);
    }
  };

  const openShare = async (kb: KB) => {
    setShareOpen(true);
    setShareQuery("");
    setShareUsers([]);
    setShareDeptId("");
    try {
      const [{ data: access }, { data: targets }] = await Promise.all([
        knowledgeApi.access(kb.id),
        knowledgeApi.shareTargets(""),
      ]);
      const row = access as { visibility?: string; grants?: KbGrant[] };
      const targetRow = targets as { departments?: { id: string; name: string }[] };
      setShareVisibility(row.visibility === "public" ? "public" : "private");
      setShareGrants(row.grants || []);
      setShareDepts(targetRow.departments || []);
    } catch {
      toast.error(lang === "zh" ? "权限加载失败" : "Failed to load access");
      setShareOpen(false);
    }
  };

  const findPeople = async () => {
    if (!shareQuery.trim()) return;
    const { data } = await knowledgeApi.shareTargets(shareQuery.trim());
    setShareUsers((data as { users?: { id: string; display_name: string; employee_no?: string | null }[] }).users || []);
  };

  const addGrant = (grant: KbGrant) => {
    setShareGrants((items) => (
      items.some((item) => item.grantee_type === grant.grantee_type && item.grantee_id === grant.grantee_id)
        ? items
        : [...items, grant]
    ));
  };

  const saveShare = async () => {
    if (!activeKb) return;
    setShareSaving(true);
    try {
      await knowledgeApi.saveAccess(activeKb, {
        visibility: shareVisibility,
        grants: shareGrants.map((item) => ({ grantee_type: item.grantee_type, grantee_id: item.grantee_id })),
      });
      toast.success(lang === "zh" ? "权限已保存" : "Access saved");
      setShareOpen(false);
      await load();
      setActiveKbMeta((meta) => meta ? {
        ...meta,
        visibility: shareVisibility,
        grant_count: shareGrants.length,
      } : meta);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || (lang === "zh" ? "保存失败" : "Save failed"));
    } finally {
      setShareSaving(false);
    }
  };

  const retryDoc = async (docId: string) => {
    if (!activeKb) return;
    try {
      await knowledgeApi.retryDocument(activeKb, docId);
      toast.success(lang === "zh" ? "已重新解析" : "Reindexed");
      const { data } = await knowledgeApi.listDocuments(activeKb);
      setDocs(data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || (lang === "zh" ? "重建失败" : "Retry failed"));
    }
  };

  const openFaq = async () => {
    if (!activeKb) return;
    setFaqOpen(true);
    const { data } = await knowledgeApi.listFaq(activeKb);
    setFaqRows(data || []);
  };

  const saveFaq = async () => {
    if (!activeKb || !faqQuestion.trim() || !faqAnswer.trim()) return;
    await knowledgeApi.createFaq(activeKb, {
      standard_question: faqQuestion.trim(),
      similar_questions: faqSimilar.split(/\n+/).map((item) => item.trim()).filter(Boolean),
      negative_questions: faqNegative.split(/\n+/).map((item) => item.trim()).filter(Boolean),
      answer: faqAnswer.trim(),
      enabled: true,
    });
    setFaqQuestion("");
    setFaqSimilar("");
    setFaqNegative("");
    setFaqAnswer("");
    const { data } = await knowledgeApi.listFaq(activeKb);
    setFaqRows(data || []);
  };

  const openWecom = async () => {
    if (!activeKb) return;
    setWecomOpen(true);
    const { data } = await knowledgeApi.wecomDocs(activeKb);
    setWecomEnabled(Boolean(data.enabled));
    setWecomCorp(data.corp_id || "");
    setWecomSecret("");
    setWecomDocsText((data.doc_ids || []).join("\n"));
    setWecomStatus(data.last_error || data.last_status || "");
  };

  const saveWecom = async (syncNow: boolean) => {
    if (!activeKb) return;
    const docIds = wecomDocsText.split(/\n+/).map((item) => item.trim()).filter(Boolean);
    await knowledgeApi.saveWecomDocs(activeKb, {
      enabled: wecomEnabled,
      corp_id: wecomCorp.trim(),
      secret: wecomSecret,
      doc_ids: docIds,
    });
    if (syncNow) {
      const { data } = await knowledgeApi.syncWecomDocs(activeKb);
      setWecomStatus(data.last_error || data.last_status || "");
      const docs = await knowledgeApi.listDocuments(activeKb);
      setDocs(docs.data);
    }
    toast.success(lang === "zh" ? "企微文档已保存" : "Saved");
  };

  const create = async () => {
    if (!form.name.trim()) { toast.error(k.nameRequired[lang]); return; }
    setCreating(true);
    try {
      await knowledgeApi.create({
        name: form.name,
        description: form.description || undefined,
        embedding_model: form.embedding_model,
        chunk_size: form.chunk_size,
        chunk_overlap: form.chunk_overlap,
      });
      toast.success(k.created[lang]);
      setShowCreate(false);
      setForm((f) => ({ ...f, name: "", description: "" }));
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${k.createFailed[lang]}: ${detail}` : k.createFailed[lang]);
    } finally {
      setCreating(false);
    }
  };

  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!activeKb || !e.target.files?.length) return;
    const file = e.target.files[0];
    const toastId = toast.loading(`${k.uploading[lang]} ${file.name}...`);
    try {
      await knowledgeApi.uploadDocument(activeKb, file);
      toast.success(k.uploaded[lang], { id: toastId });
      const { data } = await knowledgeApi.listDocuments(activeKb);
      setDocs(data);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${k.uploadFailed[lang]}: ${detail}` : k.uploadFailed[lang], { id: toastId });
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const search = async () => {
    if (!activeKb || !query.trim() || searching) return;
    setSearching(true);
    setSearched(true);
    try {
      const { data } = await knowledgeApi.search(activeKb, { query, top_k: 5 });
      setSearchResults(data);
    } catch {
      toast.error(k.searchFailed[lang]);
    } finally {
      setSearching(false);
    }
  };

  const deleteDoc = async (docId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    e?.preventDefault();
    if (!activeKb || deletingDocId === docId || !confirm(k.deleteDocConfirm[lang])) return;
    setDeletingDocId(docId);
    try {
      await knowledgeApi.deleteDocument(activeKb, docId);
      setDocs((d) => d.filter((doc) => doc.id !== docId));
      if (activeDoc?.id === docId) closeViewer();
      toast.success(k.docDeleted[lang]);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number; data?: { detail?: string } } })?.response?.status;
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (status === 404) {
        setDocs((d) => d.filter((doc) => doc.id !== docId));
        if (activeDoc?.id === docId) closeViewer();
        toast.success(k.docDeleted[lang]);
      } else {
        toast.error(typeof detail === "string" ? detail : k.deleteFailed[lang]);
      }
    } finally {
      setDeletingDocId(null);
      void load();
    }
  };

  const markdownMode = docContent
    ? isMarkdown(docContent.file_type, docContent.filename)
    : false;

  const filteredKbs = useMemo(() => {
    let list = kbs;
    if (listFilter === "local") {
      list = list.filter((kb) => (kb.source_type || "local") === "local");
    }
    const q = kbFilterSearch.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (kb) =>
          kb.name.toLowerCase().includes(q) ||
          (kb.description || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [kbs, listFilter, kbFilterSearch]);

  const renderKbItem = (kb: KB) => (
    <button
      key={kb.id}
      type="button"
      onClick={() => openKb(kb)}
      className={`knowledge-kb-item${activeKb === kb.id ? " knowledge-kb-item-active" : ""}`}
    >
      <div className="knowledge-kb-icon knowledge-kb-icon-local">
        <FolderOpen className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="line-clamp-1 text-xs font-medium theme-text">{kb.name}</p>
          <span className="knowledge-kb-badge knowledge-kb-badge-local">
            {accessText(kb)}
          </span>
        </div>
        <p className="text-[10px] theme-muted">
          {`${kb.document_count} ${k.documents[lang]}`}
        </p>
      </div>
    </button>
  );

  return (
    <div className="knowledge-hub flex h-[calc(100vh-0px)] min-h-0">
      {/* Sidebar */}
      <div className="knowledge-sidebar">
        <div className="knowledge-sidebar-head">
          <div>
            <h1>{k.title[lang]}</h1>
            <p>{k.subtitle[lang]}</p>
          </div>
          <button type="button" onClick={() => openCreateModal()} className="knowledge-icon-btn" title={k.newKB[lang]}>
            <Plus className="h-4 w-4" />
          </button>
        </div>

        <div className="knowledge-filter-tabs">
          {(["all", "local"] as ListFilter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setListFilter(f)}
              className={`knowledge-filter-tab${listFilter === f ? " knowledge-filter-tab-active" : ""}`}
            >
              {f === "all" ? k.tabAll[lang] : k.tabLocal[lang]}
            </button>
          ))}
        </div>

        <div className="knowledge-sidebar-search">
          <Search className="h-3.5 w-3.5 shrink-0 theme-muted" />
          <input
            type="search"
            value={kbFilterSearch}
            onChange={(e) => setKbFilterSearch(e.target.value)}
            placeholder={k.searchKbPlaceholder[lang]}
          />
        </div>

        <div className="knowledge-sidebar-list">
          {loading ? (
            <p className="px-2 text-xs theme-muted">{c.loading[lang]}</p>
          ) : filteredKbs.length === 0 ? (
            <div className="knowledge-sidebar-empty">
              <p className="text-xs theme-muted">{k.noKB[lang]}</p>
              <button type="button" onClick={() => openCreateModal()} className="knowledge-quick-link">
                <HardDrive className="h-3.5 w-3.5" /> {k.tabLocal[lang]}
              </button>
            </div>
          ) : (
            filteredKbs.map(renderKbItem)
          )}
        </div>
      </div>

      {/* Main */}
      <div className={`knowledge-main flex-1 min-w-0 flex flex-col ${activeDoc ? "border-r theme-border" : ""}`}>
        <div className="flex-1 overflow-y-auto p-6">
        {!activeKb ? (
          <div className="knowledge-empty-hero">
            <Database className="mb-4 h-12 w-12 opacity-30" />
            <p className="mb-6 theme-muted">{k.selectKB[lang]}</p>
            <div className="knowledge-source-cards">
              <button type="button" className="knowledge-source-card knowledge-source-local" onClick={() => openCreateModal()}>
                <div className="knowledge-source-card-icon"><FolderOpen className="h-6 w-6" /></div>
                <h3>{k.sourceLocal[lang]}</h3>
                <p>{k.sourceLocalDesc[lang]}</p>
                <span className="knowledge-source-formats">{k.localFormats[lang]}</span>
              </button>
            </div>
          </div>
        ) : (
          <div>
            {activeKbMeta && (
              <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="knowledge-kb-icon-lg knowledge-kb-icon-local">
                      <FolderOpen className="h-5 w-5" />
                    </div>
                    <h2 className="text-lg font-semibold theme-text">{activeKbMeta.name}</h2>
                    <span className="knowledge-kb-badge knowledge-kb-badge-local">
                      {accessText(activeKbMeta)}
                    </span>
                    {activeKbMeta.can_manage && (
                      <button type="button" className="agents-btn-secondary px-2 py-1 text-xs" onClick={() => void openShare(activeKbMeta)}>
                        <Shield className="h-3.5 w-3.5" /> {lang === "zh" ? "权限" : "Access"}
                      </button>
                    )}
                    {activeKbMeta.can_manage && (
                      <button type="button" className="agents-btn-secondary px-2 py-1 text-xs" onClick={() => void openFaq()}>
                        {lang === "zh" ? "问答" : "FAQ"}
                      </button>
                    )}
                    {activeKbMeta.can_manage && (
                      <button type="button" className="agents-btn-secondary px-2 py-1 text-xs" onClick={() => void openWecom()}>
                        {lang === "zh" ? "企微文档" : "WeCom"}
                      </button>
                    )}
                  </div>
                  {activeKbMeta.description && (
                    <p className="mt-1 text-sm text-slate-400">{activeKbMeta.description}</p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">{activeKbMeta.embedding_model}</p>
                </div>
              </div>
            )}

            <div className="mb-6 flex flex-wrap gap-3">
              <input
                type="text"
                className="theme-input knowledge-search-input flex-1 min-w-[12rem] rounded-lg px-4 py-2 text-sm"
                placeholder={k.searchPlaceholder[lang]}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && search()}
              />
              <button type="button" onClick={search} disabled={searching} className="agents-btn-primary disabled:opacity-50">
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                {k.search[lang]}
              </button>
              {activeKbMeta?.can_manage && (
              <button type="button" onClick={() => fileRef.current?.click()} className="agents-btn-secondary">
                <Upload className="h-4 w-4" /> {k.upload[lang]}
              </button>
              )}
              <input ref={fileRef} type="file" className="hidden" accept=".pdf,.docx,.txt,.md,.html,.png,.jpg,.jpeg,.webp" onChange={upload} />
            </div>

            {searchResults.length > 0 && (
              <div className="mb-6">
                <h3 className="mb-3 text-sm font-semibold text-white">{k.searchResults[lang]}</h3>
                <div className="space-y-3">
                  {searchResults.map((r, i) => (
                    <div key={i} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-4">
                      <div className="mb-2 flex justify-between text-xs text-slate-500">
                        <span>{r.document_name}</span>
                        <span className="text-green-400">{k.score[lang]}: {r.score.toFixed(3)}</span>
                      </div>
                      <p className="text-sm text-slate-300 line-clamp-3">{r.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <h3 className="mb-3 text-sm font-semibold text-white">
              {k.documents[lang]} ({docs.length})
            </h3>
            {docsLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" /> {c.loading[lang]}
              </div>
            ) : docs.length === 0 ? (
              <p className="text-sm text-slate-500">{c.noData[lang]}</p>
            ) : (
              <div className="space-y-2">
                {docs.map((doc) => (
                  <div
                    key={doc.id}
                    className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 transition-colors ${
                      activeDoc?.id === doc.id
                        ? "border-blue-500/50 bg-blue-600/10"
                        : "border-[#2d2d4e] bg-[#1a1a2e] hover:border-blue-500/30 hover:bg-white/[0.03]"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => openDoc(doc)}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                      <div className="min-w-0">
                        <p className="truncate text-sm text-white">{doc.filename}</p>
                        <p className="text-xs text-slate-500">
                          {doc.chunk_count} {k.chunks[lang]} · {doc.file_type}
                        </p>
                      </div>
                    </button>
                    <div className="ml-3 flex shrink-0 items-center gap-3">
                      <span className="hidden items-center gap-1 text-xs text-blue-400 sm:flex">
                        <Eye className="h-3.5 w-3.5" /> {k.viewContent[lang]}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-xs ${doc.status === "ready" ? "bg-green-500/20 text-green-400" : doc.status === "processing" ? "bg-yellow-500/20 text-yellow-400" : "bg-red-500/20 text-red-400"}`}>
                        {doc.stage === "ready" ? "就绪" : doc.stage === "error" ? "失败" : doc.status}
                      </span>
                      {doc.stage_error && <span className="max-w-[140px] truncate text-xs text-red-300" title={doc.stage_error}>{doc.stage_error}</span>}
                      {activeKbMeta?.can_manage && (
                        <button type="button" className="text-xs text-slate-400 hover:text-white" onClick={(e) => { e.stopPropagation(); void retryDoc(doc.id); }}>重建</button>
                      )}
                      {activeKbMeta?.can_manage && (
                      <button
                        type="button"
                        disabled={deletingDocId === doc.id}
                        onClick={(e) => void deleteDoc(doc.id, e)}
                        className="text-slate-500 transition-colors hover:text-red-400 disabled:opacity-50"
                        title={k.deleteDocConfirm[lang]}
                      >
                        {deletingDocId === doc.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!activeDoc && docs.length > 0 && (
              <p className="mt-4 text-xs text-slate-500">{k.clickToView[lang]}</p>
            )}
          </div>
        )}
        </div>
      </div>

      {/* Content viewer */}
      {activeKb && activeDoc && (
        <div className="w-[min(480px,40vw)] shrink-0 flex flex-col bg-[#12121f]">
          <div className="flex items-center justify-between border-b border-[#2d2d4e] px-4 py-3">
            <div className="min-w-0 pr-3">
              <h3 className="text-sm font-semibold text-white truncate">{activeDoc.filename}</h3>
              <p className="text-xs text-slate-500">{k.contentTitle[lang]}</p>
            </div>
            <button
              onClick={closeViewer}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white/5 hover:text-white transition-colors"
              aria-label={k.closeViewer[lang]}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {contentLoading ? (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
                <Loader2 className="h-5 w-5 animate-spin" /> {k.loadingContent[lang]}
              </div>
            ) : !docContent?.content?.trim() ? (
              <p className="text-sm text-slate-500">{k.noContent[lang]}</p>
            ) : markdownMode ? (
              <MarkdownView size="sm">{docContent.content}</MarkdownView>
            ) : (
              <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300 font-sans">
                {docContent.content}
              </pre>
            )}
          </div>
        </div>
      )}


      {faqOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-3 text-lg font-semibold theme-text">问答条目</h2>
            <input className="theme-input mb-2 w-full rounded-lg px-3 py-2 text-sm" placeholder="标准问" value={faqQuestion} onChange={(e) => setFaqQuestion(e.target.value)} />
            <textarea className="theme-input mb-2 w-full rounded-lg px-3 py-2 text-sm" rows={2} placeholder="相似问，一行一条" value={faqSimilar} onChange={(e) => setFaqSimilar(e.target.value)} />
            <textarea className="theme-input mb-2 w-full rounded-lg px-3 py-2 text-sm" rows={2} placeholder="反例问，一行一条。命中后不使用这条答案" value={faqNegative} onChange={(e) => setFaqNegative(e.target.value)} />
            <textarea className="theme-input mb-3 w-full rounded-lg px-3 py-2 text-sm" rows={3} placeholder="答案" value={faqAnswer} onChange={(e) => setFaqAnswer(e.target.value)} />
            <button type="button" className="agents-btn-primary mb-3" onClick={() => void saveFaq()}>添加</button>
            <div className="flex flex-col gap-2">
              {faqRows.map((row) => (
                <div key={row.id} className="flex items-start justify-between gap-2 text-sm">
                  <span className="theme-text">{row.standard_question}</span>
                  <button type="button" className="text-xs text-slate-400" onClick={() => { if (activeKb) { void knowledgeApi.deleteFaq(activeKb, row.id).then(() => setFaqRows((items) => items.filter((item) => item.id !== row.id))); } }}>删除</button>
                </div>
              ))}
            </div>
            <div className="mt-4 flex justify-end">
              <button type="button" className="text-sm theme-muted" onClick={() => setFaqOpen(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}
      {wecomOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card w-full max-w-lg p-6">
            <h2 className="mb-3 text-lg font-semibold theme-text">同步企业微信文档</h2>
            <label className="mb-2 flex items-center gap-2 text-sm theme-text">
              <input type="checkbox" checked={wecomEnabled} onChange={(e) => setWecomEnabled(e.target.checked)} /> 启用，每 15 分钟同步一次
            </label>
            <input className="theme-input mb-2 w-full rounded-lg px-3 py-2 text-sm" placeholder="企业 ID" value={wecomCorp} onChange={(e) => setWecomCorp(e.target.value)} />
            <input className="theme-input mb-2 w-full rounded-lg px-3 py-2 text-sm" placeholder="文档应用 Secret，留空则保持原值" type="password" value={wecomSecret} onChange={(e) => setWecomSecret(e.target.value)} />
            <textarea className="theme-input mb-2 w-full rounded-lg px-3 py-2 text-sm" rows={4} placeholder="文档 ID，一行一个" value={wecomDocsText} onChange={(e) => setWecomDocsText(e.target.value)} />
            {wecomStatus && <p className="mb-2 text-xs theme-muted">{wecomStatus}</p>}
            <div className="flex justify-end gap-3">
              <button type="button" className="text-sm theme-muted" onClick={() => setWecomOpen(false)}>关闭</button>
              <button type="button" className="agents-btn-secondary" onClick={() => void saveWecom(false)}>保存</button>
              <button type="button" className="agents-btn-primary" onClick={() => void saveWecom(true)}>保存并同步</button>
            </div>
          </div>
        </div>
      )}
      {shareOpen && activeKbMeta && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-1 text-lg font-semibold theme-text">{lang === "zh" ? "资料库权限" : "Library access"}</h2>
            <p className="mb-4 text-xs theme-muted">{activeKbMeta.name}</p>
            <div className="mb-4 flex gap-2">
              <button type="button" className={`rounded-lg px-3 py-1.5 text-sm ${shareVisibility === "private" ? "bg-blue-600 text-white" : "border theme-border theme-text"}`} onClick={() => setShareVisibility("private")}>
                {lang === "zh" ? "私有" : "Private"}
              </button>
              <button type="button" className={`rounded-lg px-3 py-1.5 text-sm ${shareVisibility === "public" ? "bg-blue-600 text-white" : "border theme-border theme-text"}`} onClick={() => setShareVisibility("public")}>
                {lang === "zh" ? "公开" : "Public"}
              </button>
            </div>
            <p className="mb-3 text-xs theme-muted">
              {lang === "zh"
                ? "私有时只有自己和下面的个人、部门能看。公开后所有登录用户都能看。"
                : "Private libraries are visible to you and the people or departments below. Public libraries are visible to every signed-in user."}
            </p>
            <div className="mb-3 flex gap-2">
              <input className="theme-input flex-1 rounded-lg px-3 py-2 text-sm" placeholder={lang === "zh" ? "搜索姓名或工号" : "Name or employee no"} value={shareQuery} onChange={(e) => setShareQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void findPeople()} />
              <button type="button" className="agents-btn-secondary" onClick={() => void findPeople()}>{lang === "zh" ? "查找" : "Find"}</button>
            </div>
            {shareUsers.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2">
                {shareUsers.map((person) => (
                  <button key={person.id} type="button" className="rounded-full border theme-border px-2 py-1 text-xs theme-text" onClick={() => addGrant({ grantee_type: "user", grantee_id: person.id, label: person.employee_no ? `${person.display_name}（${person.employee_no}）` : person.display_name })}>
                    {person.display_name}{person.employee_no ? ` ${person.employee_no}` : ""}
                  </button>
                ))}
              </div>
            )}
            <div className="mb-3 flex gap-2">
              <select className="theme-input flex-1 rounded-lg px-3 py-2 text-sm" value={shareDeptId} onChange={(e) => setShareDeptId(e.target.value)}>
                <option value="">{lang === "zh" ? "选择部门" : "Department"}</option>
                {shareDepts.map((dept) => <option key={dept.id} value={dept.id}>{dept.name}</option>)}
              </select>
              <button type="button" className="agents-btn-secondary" onClick={() => {
                const dept = shareDepts.find((item) => item.id === shareDeptId);
                if (dept) addGrant({ grantee_type: "department", grantee_id: dept.id, label: dept.name });
              }}>{lang === "zh" ? "添加部门" : "Add"}</button>
            </div>
            <div className="mb-4 flex flex-wrap gap-2">
              {shareGrants.length === 0 ? <span className="text-xs theme-muted">{lang === "zh" ? "还没有共享对象" : "No grants"}</span> : shareGrants.map((grant) => (
                <button key={`${grant.grantee_type}-${grant.grantee_id}`} type="button" className="rounded-full bg-blue-600/15 px-2 py-1 text-xs text-blue-300" onClick={() => setShareGrants((items) => items.filter((item) => !(item.grantee_type === grant.grantee_type && item.grantee_id === grant.grantee_id)))}>
                  {grant.grantee_type === "department" ? (lang === "zh" ? "部门 " : "Dept ") : ""}{grant.label} ×
                </button>
              ))}
            </div>
            <div className="flex justify-end gap-3">
              <button type="button" onClick={() => setShareOpen(false)} className="text-sm theme-muted">{c.cancel[lang]}</button>
              <button type="button" onClick={() => void saveShare()} disabled={shareSaving} className="agents-btn-primary disabled:opacity-50">
                {shareSaving ? c.loading[lang] : (lang === "zh" ? "保存" : "Save")}
              </button>
            </div>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-4 text-lg font-semibold theme-text">{k.newKB[lang]}</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.name[lang]}</label>
                <input type="text" className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.description[lang]}</label>
                <input type="text" className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{k.embeddingModel[lang]}</label>
                <select className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" value={form.embedding_model} onChange={(e) => setForm((f) => ({ ...f, embedding_model: e.target.value }))}>
                  {embedOptions.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" onClick={() => setShowCreate(false)} className="text-sm theme-muted">{c.cancel[lang]}</button>
              <button type="button" onClick={create} disabled={creating} className="agents-btn-primary disabled:opacity-50">
                {creating ? c.loading[lang] : c.create[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
