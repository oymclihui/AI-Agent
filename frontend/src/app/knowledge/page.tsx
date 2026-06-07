"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, Database, Upload, Trash2, Search, FileText, Loader2, X, Eye } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { knowledgeApi, modelsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

interface KB {
  id: string;
  name: string;
  description: string | null;
  status: string;
  document_count: number;
  embedding_model: string;
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

function isMarkdown(fileType: string, filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || fileType.toLowerCase();
  return ext === "md" || ext === "markdown";
}

export default function KnowledgePage() {
  const { lang } = useLangStore();
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
    setCreating(true);
    try {
      await knowledgeApi.create(form);
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
      <div className="w-60 shrink-0 border-r border-[#2d2d4e] bg-[#1a1a2e] flex flex-col">
        <div className="p-3 border-b border-[#2d2d4e] flex justify-between items-center">
          <span className="text-sm font-semibold text-white">{k.title[lang]}</span>
          <button onClick={() => setShowCreate(true)} className="rounded-lg bg-blue-600 p-1 text-white hover:bg-blue-700 transition-colors">
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
                  className={`w-full mb-1 rounded-lg px-3 py-2 text-left text-sm transition-colors ${activeKb === kb.id ? "bg-blue-600/20 text-blue-300" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"}`}
                >
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 shrink-0" />
                    <div className="min-w-0">
                      <p className="line-clamp-1 text-xs font-medium">{kb.name}</p>
                      <p className="text-[10px] text-slate-500">{kb.document_count} {k.documents[lang]}</p>
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
              <div className="mb-6">
                <h2 className="text-lg font-semibold text-white">{activeKbMeta.name}</h2>
                {activeKbMeta.description && (
                  <p className="mt-1 text-sm text-slate-400">{activeKbMeta.description}</p>
                )}
                <p className="mt-1 text-xs text-slate-500">{activeKbMeta.embedding_model}</p>
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
              <button onClick={() => fileRef.current?.click()} className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700 transition-colors">
                <Upload className="h-4 w-4" /> {k.upload[lang]}
              </button>
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
          <div className="w-full max-w-md rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">{k.newKB[lang]}</h2>
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
              <button onClick={() => setShowCreate(false)} className="rounded-lg px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">{c.cancel[lang]}</button>
              <button onClick={create} disabled={creating} className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 transition-colors disabled:opacity-50">
                {creating ? c.loading[lang] : c.create[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
