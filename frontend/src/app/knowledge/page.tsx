"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, Database, Upload, Trash2, Search, FileText, Loader2, X, Eye, Settings, PlugZap } from "lucide-react";
import ReactMarkdown from "react-markdown";
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
  document_count: number;
  embedding_model: string;
  source_type?: "local" | "byd_kms";
  byd_kms?: { api_url: string; user_id: string; has_api_key: boolean } | null;
}
interface Doc {
  id: string;
  filename: string;
  file_type: string;
  status: string;
  chunk_count: number;
  file_size: number | null;
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
const DEFAULT_BYD_KMS_URL = "https://kms-api.byd.com/open-api/1.0/llm/v1/rag-qa";

type KbSourceType = "local" | "byd_kms";

interface BydKmsForm {
  api_url: string;
  user_id: string;
  api_key: string;
}

const EMPTY_BYD_KMS: BydKmsForm = {
  api_url: DEFAULT_BYD_KMS_URL,
  user_id: "",
  api_key: "",
};

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
  const [showSettings, setShowSettings] = useState(false);
  const [creating, setCreating] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [testingByd, setTestingByd] = useState(false);
  const [embedOptions, setEmbedOptions] = useState<string[]>(FALLBACK_EMBEDDINGS);
  const [sourceType, setSourceType] = useState<KbSourceType>("local");
  const [bydKmsForm, setBydKmsForm] = useState<BydKmsForm>(() => ({
    ...EMPTY_BYD_KMS,
    user_id: user?.employee_no || "",
  }));
  const [settingsBydForm, setSettingsBydForm] = useState<BydKmsForm>(EMPTY_BYD_KMS);
  const [form, setForm] = useState({ name: "", description: "", embedding_model: "nomic-embed-text", chunk_size: 1000, chunk_overlap: 200 });
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{ content: string; score: number; document_name: string }[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

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
    if (user?.employee_no && !bydKmsForm.user_id) {
      setBydKmsForm((f) => ({ ...f, user_id: user.employee_no || "" }));
    }
  }, [user?.employee_no, bydKmsForm.user_id]);

  const isBydKb = activeKbMeta?.source_type === "byd_kms";

  const openCreateModal = () => {
    setSourceType("local");
    setBydKmsForm({ ...EMPTY_BYD_KMS, user_id: user?.employee_no || "" });
    setShowCreate(true);
  };

  const openSettings = () => {
    if (!activeKbMeta?.byd_kms) return;
    setSettingsBydForm({
      api_url: activeKbMeta.byd_kms.api_url || DEFAULT_BYD_KMS_URL,
      user_id: activeKbMeta.byd_kms.user_id || "",
      api_key: "",
    });
    setShowSettings(true);
  };

  const runBydTest = async (cfg: BydKmsForm) => {
    if (!cfg.user_id.trim()) {
      toast.error(lang === "zh" ? "请填写 User ID" : "User ID is required");
      return;
    }
    setTestingByd(true);
    try {
      const { data } = await knowledgeApi.testBydKms({
        api_url: cfg.api_url.trim() || DEFAULT_BYD_KMS_URL,
        user_id: cfg.user_id.trim(),
        api_key: cfg.api_key.trim() || undefined,
        test_query: lang === "zh" ? "你好" : "hello",
      });
      if (data.ok) {
        const extra = data.preview ? `: ${String(data.preview).slice(0, 80)}` : "";
        toast.success(`${k.bydKmsTestOk[lang]} (${data.latency_ms}ms)${extra}`);
      } else {
        toast.error(data.message ? `${k.bydKmsTestFail[lang]}: ${data.message}` : k.bydKmsTestFail[lang]);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${k.bydKmsTestFail[lang]}: ${detail}` : k.bydKmsTestFail[lang]);
    } finally {
      setTestingByd(false);
    }
  };

  const saveBydSettings = async () => {
    if (!activeKb) return;
    if (!settingsBydForm.user_id.trim()) {
      toast.error(lang === "zh" ? "请填写 User ID" : "User ID is required");
      return;
    }
    setSavingSettings(true);
    try {
      const payload: Record<string, unknown> = {
        byd_kms: {
          api_url: settingsBydForm.api_url.trim() || DEFAULT_BYD_KMS_URL,
          user_id: settingsBydForm.user_id.trim(),
        },
      };
      if (settingsBydForm.api_key.trim()) {
        (payload.byd_kms as Record<string, string>).api_key = settingsBydForm.api_key.trim();
      }
      const { data } = await knowledgeApi.update(activeKb, payload);
      setActiveKbMeta(data);
      setKbs((prev) => prev.map((item) => (item.id === data.id ? data : item)));
      toast.success(k.bydKmsSaveOk[lang]);
      setShowSettings(false);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${k.bydKmsSaveFail[lang]}: ${detail}` : k.bydKmsSaveFail[lang]);
    } finally {
      setSavingSettings(false);
    }
  };

  const testActiveKbConnection = async () => {
    if (!activeKb) return;
    setTestingByd(true);
    try {
      const { data } = await knowledgeApi.testConnection(activeKb);
      if (data.ok) {
        const extra = data.preview ? `: ${String(data.preview).slice(0, 80)}` : "";
        toast.success(`${k.bydKmsTestOk[lang]} (${data.latency_ms}ms)${extra}`);
      } else {
        toast.error(data.message ? `${k.bydKmsTestFail[lang]}: ${data.message}` : k.bydKmsTestFail[lang]);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${k.bydKmsTestFail[lang]}: ${detail}` : k.bydKmsTestFail[lang]);
    } finally {
      setTestingByd(false);
    }
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

  const create = async () => {
    if (!form.name.trim()) { toast.error(k.nameRequired[lang]); return; }
    if (sourceType === "byd_kms" && !bydKmsForm.user_id.trim()) {
      toast.error(lang === "zh" ? "请填写 User ID" : "User ID is required");
      return;
    }
    setCreating(true);
    try {
      const payload: Record<string, unknown> = {
        name: form.name,
        description: form.description || undefined,
        source_type: sourceType,
        embedding_model: form.embedding_model,
        chunk_size: form.chunk_size,
        chunk_overlap: form.chunk_overlap,
      };
      if (sourceType === "byd_kms") {
        payload.byd_kms = {
          api_url: bydKmsForm.api_url.trim() || DEFAULT_BYD_KMS_URL,
          user_id: bydKmsForm.user_id.trim(),
          ...(bydKmsForm.api_key.trim() ? { api_key: bydKmsForm.api_key.trim() } : {}),
        };
      }
      await knowledgeApi.create(payload);
      toast.success(k.created[lang]);
      setShowCreate(false);
      setForm((f) => ({ ...f, name: "", description: "" }));
      setSourceType("local");
      setBydKmsForm({ ...EMPTY_BYD_KMS, user_id: user?.employee_no || "" });
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
    if (!activeKb || !confirm(k.deleteDocConfirm[lang])) return;
    try {
      await knowledgeApi.deleteDocument(activeKb, docId);
      setDocs((d) => d.filter((doc) => doc.id !== docId));
      if (activeDoc?.id === docId) closeViewer();
      toast.success(k.docDeleted[lang]);
      load();
    } catch {
      toast.error(k.deleteFailed[lang]);
    }
  };

  const markdownMode = docContent
    ? isMarkdown(docContent.file_type, docContent.filename)
    : false;

  return (
    <div className="flex h-screen">
      {/* KB list */}
      <div className="theme-surface flex w-60 shrink-0 flex-col border-r theme-border">
        <div className="flex items-center justify-between border-b theme-border p-3">
          <span className="text-sm font-semibold theme-text">{k.title[lang]}</span>
          <button onClick={openCreateModal} className="rounded-lg bg-blue-600 p-1 text-white hover:bg-blue-700 transition-colors">
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? <p className="text-xs text-slate-500 px-2">{c.loading[lang]}</p> :
            kbs.length === 0 ? <p className="text-xs text-slate-500 px-2 mt-4">{k.noKB[lang]}</p> :
              kbs.map((kb) => (
                <button
                  key={kb.id}
                  onClick={() => openKb(kb)}
                  className={`mb-1 w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${activeKb === kb.id ? "panel-list-item-active" : "panel-list-item-idle hover:bg-[var(--hover)]"}`}
                >
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 shrink-0" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <p className="line-clamp-1 text-xs font-medium">{kb.name}</p>
                        {kb.source_type === "byd_kms" && (
                          <span className="shrink-0 rounded bg-blue-500/15 px-1 py-0.5 text-[9px] text-blue-400">API</span>
                        )}
                      </div>
                      <p className="text-[10px] text-slate-500">
                        {kb.source_type === "byd_kms"
                          ? k.sourceBydKms[lang]
                          : `${kb.document_count} ${k.documents[lang]}`}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
        </div>
      </div>

      {/* Main */}
      <div className={`flex-1 overflow-y-auto p-6 ${activeDoc ? "border-r border-[#2d2d4e]" : ""}`}>
        {!activeKb ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Database className="mb-4 h-12 w-12 text-slate-600" />
            <p className="text-slate-400">{k.selectKB[lang]}</p>
          </div>
        ) : (
          <div>
            {activeKbMeta && (
              <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-semibold text-white">{activeKbMeta.name}</h2>
                    {isBydKb && (
                      <span className="rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] text-blue-300">{k.sourceBydKms[lang]}</span>
                    )}
                  </div>
                  {activeKbMeta.description && (
                    <p className="mt-1 text-sm text-slate-400">{activeKbMeta.description}</p>
                  )}
                  {!isBydKb && (
                    <p className="mt-1 text-xs text-slate-500">{activeKbMeta.embedding_model}</p>
                  )}
                  {isBydKb && activeKbMeta.byd_kms && (
                    <p className="mt-1 text-xs text-slate-500">
                      User ID: {activeKbMeta.byd_kms.user_id} · {activeKbMeta.byd_kms.api_url}
                    </p>
                  )}
                  {isBydKb && (
                    <p className="mt-2 text-xs text-slate-500">{k.bydKmsExternalHint[lang]}</p>
                  )}
                </div>
                {isBydKb && (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={testActiveKbConnection}
                      disabled={testingByd}
                      className="flex items-center gap-1.5 rounded-lg border border-[#2d2d4e] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
                    >
                      {testingByd ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5" />}
                      {testingByd ? k.bydKmsTesting[lang] : k.bydKmsTest[lang]}
                    </button>
                    <button
                      type="button"
                      onClick={openSettings}
                      className="flex items-center gap-1.5 rounded-lg border border-[#2d2d4e] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5"
                    >
                      <Settings className="h-3.5 w-3.5" />
                      {k.bydKmsSettings[lang]}
                    </button>
                  </div>
                )}
              </div>
            )}

            <div className="mb-6 flex gap-3">
              <input
                type="text"
                className="flex-1 rounded-lg border border-[#2d2d4e] bg-[#1a1a2e] px-4 py-2 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:outline-none"
                placeholder={k.searchPlaceholder[lang]}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && search()}
              />
              <button onClick={search} disabled={searching} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors disabled:opacity-50">
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                {k.search[lang]}
              </button>
              {!isBydKb && (
                <button onClick={() => fileRef.current?.click()} className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 transition-colors">
                  <Upload className="h-4 w-4" /> {k.upload[lang]}
                </button>
              )}
              <input ref={fileRef} type="file" className="hidden" accept=".pdf,.docx,.txt,.md,.html" onChange={upload} />
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

            {!isBydKb && (
              <>
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
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => openDoc(doc)}
                    className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition-colors ${
                      activeDoc?.id === doc.id
                        ? "border-blue-500/50 bg-blue-600/10"
                        : "border-[#2d2d4e] bg-[#1a1a2e] hover:border-blue-500/30 hover:bg-white/[0.03]"
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                      <div className="min-w-0">
                        <p className="text-sm text-white truncate">{doc.filename}</p>
                        <p className="text-xs text-slate-500">
                          {doc.chunk_count} {k.chunks[lang]} · {doc.file_type}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 ml-3">
                      <span className="hidden sm:flex items-center gap-1 text-xs text-blue-400">
                        <Eye className="h-3.5 w-3.5" /> {k.viewContent[lang]}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-xs ${doc.status === "ready" ? "bg-green-500/20 text-green-400" : doc.status === "processing" ? "bg-yellow-500/20 text-yellow-400" : "bg-red-500/20 text-red-400"}`}>
                        {doc.status}
                      </span>
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(e) => deleteDoc(doc.id, e)}
                        onKeyDown={(e) => e.key === "Enter" && deleteDoc(doc.id, e as unknown as React.MouseEvent)}
                        className="text-slate-500 hover:text-red-400 transition-colors"
                      >
                        <Trash2 className="h-4 w-4" />
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {!activeDoc && docs.length > 0 && (
              <p className="mt-4 text-xs text-slate-500">{k.clickToView[lang]}</p>
            )}
              </>
            )}
          </div>
        )}
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
              <article className="prose prose-invert prose-sm max-w-none prose-headings:text-white prose-p:text-slate-300 prose-li:text-slate-300 prose-strong:text-white prose-a:text-blue-400">
                <ReactMarkdown>{docContent.content}</ReactMarkdown>
              </article>
            ) : (
              <pre className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300 font-sans">
                {docContent.content}
              </pre>
            )}
          </div>
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">{k.newKB[lang]}</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">{lang === "zh" ? "类型" : "Type"}</label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setSourceType("local")}
                    className={`flex-1 rounded-lg border px-3 py-2 text-xs transition-colors ${sourceType === "local" ? "border-blue-500 bg-blue-600/20 text-blue-300" : "border-[#2d2d4e] text-slate-400 hover:bg-white/5"}`}
                  >
                    {k.sourceLocal[lang]}
                  </button>
                  <button
                    type="button"
                    onClick={() => setSourceType("byd_kms")}
                    className={`flex-1 rounded-lg border px-3 py-2 text-xs transition-colors ${sourceType === "byd_kms" ? "border-blue-500 bg-blue-600/20 text-blue-300" : "border-[#2d2d4e] text-slate-400 hover:bg-white/5"}`}
                  >
                    {k.sourceBydKms[lang]}
                  </button>
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.name[lang]}</label>
                <input type="text" className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.description[lang]}</label>
                <input type="text" className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
              </div>
              {sourceType === "local" ? (
                <div>
                  <label className="mb-1 block text-xs text-slate-400">{k.embeddingModel[lang]}</label>
                  <select className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" value={form.embedding_model} onChange={(e) => setForm((f) => ({ ...f, embedding_model: e.target.value }))}>
                    {embedOptions.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 space-y-3">
                  <p className="text-xs font-medium text-blue-300">{k.bydKmsTitle[lang]}</p>
                  <p className="text-[11px] text-slate-500">{k.bydKmsExternalHint[lang]}</p>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">{k.bydKmsUserId[lang]}</label>
                    <input
                      type="text"
                      className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      value={bydKmsForm.user_id}
                      onChange={(e) => setBydKmsForm((f) => ({ ...f, user_id: e.target.value }))}
                      placeholder={lang === "zh" ? "工号 / User ID" : "Employee no. / User ID"}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">{k.bydKmsApiUrl[lang]}</label>
                    <input
                      type="url"
                      className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      value={bydKmsForm.api_url}
                      onChange={(e) => setBydKmsForm((f) => ({ ...f, api_url: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">{k.bydKmsApiKey[lang]}</label>
                    <input
                      type="password"
                      className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      value={bydKmsForm.api_key}
                      onChange={(e) => setBydKmsForm((f) => ({ ...f, api_key: e.target.value }))}
                      placeholder={k.bydKmsApiKeyHint[lang]}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => runBydTest(bydKmsForm)}
                    disabled={testingByd}
                    className="flex w-full items-center justify-center gap-2 rounded-lg border border-[#2d2d4e] px-3 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-50"
                  >
                    {testingByd ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                    {testingByd ? k.bydKmsTesting[lang] : k.bydKmsTest[lang]}
                  </button>
                </div>
              )}
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowCreate(false)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">{c.cancel[lang]}</button>
              <button onClick={create} disabled={creating} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors disabled:opacity-50">
                {creating ? c.loading[lang] : c.create[lang]}
              </button>
            </div>
          </div>
        </div>
      )}

      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-lg rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">{k.bydKmsSettings[lang]}</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">{k.bydKmsUserId[lang]}</label>
                <input
                  type="text"
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  value={settingsBydForm.user_id}
                  onChange={(e) => setSettingsBydForm((f) => ({ ...f, user_id: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{k.bydKmsApiUrl[lang]}</label>
                <input
                  type="url"
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  value={settingsBydForm.api_url}
                  onChange={(e) => setSettingsBydForm((f) => ({ ...f, api_url: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{k.bydKmsApiKey[lang]}</label>
                <input
                  type="password"
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  value={settingsBydForm.api_key}
                  onChange={(e) => setSettingsBydForm((f) => ({ ...f, api_key: e.target.value }))}
                  placeholder={activeKbMeta?.byd_kms?.has_api_key ? (lang === "zh" ? "留空则不修改" : "Leave empty to keep current") : k.bydKmsApiKeyHint[lang]}
                />
              </div>
              <button
                type="button"
                onClick={() => runBydTest(settingsBydForm)}
                disabled={testingByd}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-[#2d2d4e] px-3 py-2 text-sm text-slate-300 hover:bg-white/5 disabled:opacity-50"
              >
                {testingByd ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                {testingByd ? k.bydKmsTesting[lang] : k.bydKmsTest[lang]}
              </button>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowSettings(false)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">{c.cancel[lang]}</button>
              <button onClick={saveBydSettings} disabled={savingSettings} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors disabled:opacity-50">
                {savingSettings ? c.loading[lang] : c.save[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
