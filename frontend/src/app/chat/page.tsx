"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Plus, MessageSquare, Paperclip, X, Sparkles, Trash2, Mic } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatApi, agentsApi, streamResponse, streamResponseForm } from "@/lib/api";
import { getAuthToken } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";
import { clsx } from "clsx";
import { useVoiceInput } from "@/hooks/useVoiceInput";

interface AttachmentMeta {
  filename: string;
  size?: number;
  kind?: string;
}

interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
  metadata?: { attachments?: AttachmentMeta[] };
}

interface Conversation { id: string; title: string | null; agent_id: string | null; created_at: string; }
interface Agent { id: string; name: string; role: string; }

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ChatPage() {
  const { lang } = useLangStore();
  const t = translations.chat;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const suggestAbortRef = useRef<AbortController | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const appendVoiceText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setInput((prev) => (prev.trim() ? `${prev.trim()} ${trimmed}` : trimmed));
  }, []);

  const { isRecording, isProcessing, toggle: toggleVoice } = useVoiceInput(
    lang,
    streaming,
  );

  const handleVoiceClick = async () => {
    try {
      await toggleVoice(appendVoiceText);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.toLowerCase().includes("permission") || msg.toLowerCase().includes("notallowed")) {
        toast.error(t.voiceDenied[lang]);
      } else {
        toast.error(msg ? `${t.voiceFailed[lang]}: ${msg}` : t.voiceFailed[lang]);
      }
    }
  };

  useEffect(() => {
    chatApi.listConversations().then(({ data }) => setConversations(data)).catch(() => {});
    agentsApi.list(lang).then(({ data }) => setAgents(data)).catch(() => {});
  }, [lang]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  const fetchSuggestions = useCallback(async (files: File[]) => {
    suggestAbortRef.current?.abort();
    if (!files.length) {
      setSuggestedQuestions([]);
      setSuggestLoading(false);
      return;
    }
    const controller = new AbortController();
    suggestAbortRef.current = controller;
    setSuggestLoading(true);
    setSuggestedQuestions([]);
    try {
      const result = await chatApi.suggestQuestions(
        files,
        lang,
        selectedAgent || undefined,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setSuggestedQuestions(result.questions?.slice(0, 3) ?? []);
    } catch {
      if (!controller.signal.aborted) {
        setSuggestedQuestions([]);
      }
    } finally {
      if (!controller.signal.aborted) {
        setSuggestLoading(false);
      }
    }
  }, [lang, selectedAgent]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchSuggestions(pendingFiles);
    }, 400);
    return () => clearTimeout(timer);
  }, [pendingFiles, fetchSuggestions]);

  useEffect(() => {
    return () => suggestAbortRef.current?.abort();
  }, []);

  const newConversation = async () => {
    try {
      const { data } = await chatApi.createConversation({
        title: t.newChat[lang],
        agent_id: selectedAgent || null,
      });
      setConversations((c) => [data, ...c]);
      setActiveConv(data.id);
      setMessages([]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${t.createFailed[lang]}: ${detail}` : t.createFailed[lang]);
    }
  };

  const loadMessages = async (convId: string) => {
    setActiveConv(convId);
    try {
      const { data } = await chatApi.getMessages(convId);
      setMessages(data);
    } catch {
      toast.error(t.loadFailed[lang]);
    }
  };

  const deleteConversation = async (convId: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (!confirm(t.deleteChatConfirm[lang])) return;
    try {
      await chatApi.deleteConversation(convId);
      setConversations((c) => c.filter((x) => x.id !== convId));
      if (activeConv === convId) {
        setActiveConv(null);
        setMessages([]);
      }
      toast.success(t.deleteOk[lang]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${t.deleteFailed[lang]}: ${detail}` : t.deleteFailed[lang]);
    }
  };

  const clearAllConversations = async () => {
    if (!conversations.length) return;
    if (!confirm(t.clearAllConfirm[lang])) return;
    try {
      await chatApi.deleteAllConversations();
      setConversations([]);
      setActiveConv(null);
      setMessages([]);
      toast.success(t.deleteOk[lang]);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${t.deleteFailed[lang]}: ${detail}` : t.deleteFailed[lang]);
    }
  };

  const appendAssistant = (content: string) => {
    setMessages((m) => [
      ...m,
      {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: content || t.emptyResponse[lang],
        created_at: new Date().toISOString(),
      },
    ]);
  };

  const onFilesSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files || []);
    if (!picked.length) return;
    setPendingFiles((prev) => {
      const names = new Set(prev.map((f) => `${f.name}-${f.size}`));
      const merged = [...prev];
      for (const f of picked) {
        const key = `${f.name}-${f.size}`;
        if (!names.has(key)) merged.push(f);
      }
      return merged;
    });
    e.target.value = "";
  };

  const removePendingFile = (index: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const applySuggestion = (question: string) => {
    setInput(question);
  };

  const saveAsSkill = async () => {
    if (!activeConv) return;
    try {
      await chatApi.saveAsSkill(activeConv, { title: messages[0]?.content?.slice(0, 40) || undefined });
      toast.success(t.saveAsSkillOk[lang]);
    } catch {
      toast.error(t.saveExportFailed[lang]);
    }
  };

  const saveToKnowledge = async () => {
    if (!activeConv) return;
    try {
      await chatApi.saveToKnowledge(activeConv, {});
      toast.success(t.saveToKbOk[lang]);
    } catch {
      toast.error(t.saveExportFailed[lang]);
    }
  };

  const send = async () => {
    const hasText = input.trim().length > 0;
    const hasFiles = pendingFiles.length > 0;
    if ((!hasText && !hasFiles) || streaming) return;

    let convId = activeConv;
    if (!convId) {
      try {
        const title = hasText ? input.slice(0, 40) : pendingFiles[0]?.name || t.newChat[lang];
        const { data } = await chatApi.createConversation({
          title,
          agent_id: selectedAgent || null,
        });
        convId = data.id;
        setActiveConv(convId);
        setConversations((c) => [data, ...c]);
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        toast.error(detail ? `${t.createFailed[lang]}: ${detail}` : t.createFailed[lang]);
        return;
      }
    }

    const msg = hasText ? input.trim() : t.analyzePrompt[lang];
    const attachmentsMeta = pendingFiles.map((f) => ({
      filename: f.name,
      size: f.size,
    }));

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: msg,
      created_at: new Date().toISOString(),
      metadata: attachmentsMeta.length ? { attachments: attachmentsMeta } : undefined,
    };
    setMessages((m) => [...m, userMsg]);
    const filesToSend = [...pendingFiles];
    setInput("");
    setPendingFiles([]);
    setSuggestedQuestions([]);
    setStreaming(true);
    setStreamingContent("");

    let full = "";
    let streamError = "";
    try {
      if (filesToSend.length > 0) {
        const form = chatApi.sendMessageWithFiles(convId!, msg, filesToSend, true);
        for await (const token of streamResponseForm(`/chat/conversations/${convId}/messages`, form)) {
          full += token;
          setStreamingContent(full);
        }
      } else {
        for await (const token of streamResponse(`/chat/conversations/${convId}/messages`, {
          message: msg,
          stream: true,
        })) {
          full += token;
          setStreamingContent(full);
        }
      }
    } catch (err: unknown) {
      streamError = err instanceof Error ? err.message : "";
    }

    if (!full) {
      if (streamError) {
        toast.error(`${t.replyFailed[lang]}: ${streamError}`);
        setStreaming(false);
        setStreamingContent("");
        return;
      }
      try {
        if (filesToSend.length > 0) {
          const form = chatApi.sendMessageWithFiles(convId!, msg, filesToSend, false);
          const response = await fetch(`/api/v1/chat/conversations/${convId}/messages`, {
            method: "POST",
            body: form,
            headers: getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {},
          });
          if (!response.ok) {
            const text = await response.text();
            let detail = text;
            try {
              detail = JSON.parse(text)?.detail ?? text;
            } catch {
              /* keep raw text */
            }
            throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
          }
          const data = await response.json();
          full = data?.content ?? "";
        } else {
          const { data } = await chatApi.sendMessage(convId!, { message: msg, stream: false });
          full = data?.content ?? "";
        }
      } catch (err: unknown) {
        const detail =
          (err instanceof Error ? err.message : "") ||
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          streamError;
        toast.error(detail ? `${t.replyFailed[lang]}: ${detail}` : t.replyFailed[lang]);
        setStreaming(false);
        setStreamingContent("");
        return;
      }
    }

    appendAssistant(full);
    setStreamingContent("");
    setStreaming(false);
  };

  const canSend = (input.trim().length > 0 || pendingFiles.length > 0) && !streaming;

  return (
    <div className="flex h-screen">
      <div className="theme-surface flex w-56 flex-col border-r theme-border">
        <div className="p-3">
          <div className="mb-3 flex gap-2">
            <select
              className="flex-1 rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
              value={selectedAgent}
              onChange={(e) => setSelectedAgent(e.target.value)}
            >
              <option value="">{t.noAgent[lang]}</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <button onClick={newConversation} className="rounded-lg bg-blue-600 p-1.5 text-white hover:bg-blue-700 transition-colors">
              <Plus className="h-4 w-4" />
            </button>
          </div>
          {conversations.length > 0 && (
            <button
              type="button"
              onClick={clearAllConversations}
              className="mb-2 w-full rounded-lg border border-red-500/20 px-2 py-1 text-[11px] text-red-400 hover:bg-red-500/10"
            >
              {t.clearAllChats[lang]}
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-2">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              className={clsx(
                "group mb-1 flex items-center gap-1 rounded-lg transition-colors",
                activeConv === conv.id ? "panel-list-item-active" : "panel-list-item-idle hover:bg-[var(--hover)]",
              )}
            >
              <button
                onClick={() => loadMessages(conv.id)}
                className="min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm text-inherit transition-colors"
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                  <span className="line-clamp-1">{conv.title || t.untitled[lang]}</span>
                </div>
              </button>
              <button
                type="button"
                onClick={(e) => deleteConversation(conv.id, e)}
                className="mr-1 shrink-0 rounded p-1 text-slate-600 opacity-0 transition-opacity hover:bg-red-500/20 hover:text-red-400 group-hover:opacity-100"
                title={t.deleteChat[lang]}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-1 flex-col">
        {activeConv && messages.length > 0 && (
          <div className="flex gap-2 border-b border-[#2d2d4e] bg-[#1a1a2e]/80 px-6 py-2">
            <button
              type="button"
              onClick={saveAsSkill}
              disabled={streaming}
              className="rounded-lg border border-[#2d2d4e] px-3 py-1 text-xs text-slate-300 hover:border-blue-500/40 hover:text-blue-300 disabled:opacity-40"
            >
              {t.saveAsSkill[lang]}
            </button>
            <button
              type="button"
              onClick={saveToKnowledge}
              disabled={streaming}
              className="rounded-lg border border-[#2d2d4e] px-3 py-1 text-xs text-slate-300 hover:border-green-500/40 hover:text-green-300 disabled:opacity-40"
            >
              {t.saveToKnowledge[lang]}
            </button>
          </div>
        )}
        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {messages.length === 0 && !streaming && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <MessageSquare className="mb-4 h-12 w-12 text-slate-600" />
              <p className="text-slate-400">{t.empty[lang]}</p>
              <p className="mt-1 text-sm text-slate-500">{t.emptyHint[lang]}</p>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={clsx("flex", msg.role === "user" ? "justify-end" : "justify-start")}>
              <div
                className={clsx(
                  "max-w-2xl rounded-2xl px-4 py-3 text-sm",
                  msg.role === "user"
                    ? "rounded-br-sm bg-blue-600 text-white"
                    : "rounded-bl-sm border border-[#2d2d4e] bg-[#1a1a2e] text-slate-200"
                )}
              >
                {msg.metadata?.attachments && msg.metadata.attachments.length > 0 && (
                  <div className={clsx("mb-2 flex flex-wrap gap-1.5", msg.role === "user" ? "" : "")}>
                    {msg.metadata.attachments.map((a) => (
                      <span
                        key={`${a.filename}-${a.size}`}
                        className={clsx(
                          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px]",
                          msg.role === "user" ? "bg-blue-500/40 text-blue-50" : "bg-slate-700/50 text-slate-300",
                        )}
                      >
                        <Paperclip className="h-3 w-3 shrink-0" />
                        {a.filename}
                        {a.size != null && <span className="opacity-70">({formatFileSize(a.size)})</span>}
                      </span>
                    ))}
                  </div>
                )}
                {msg.role === "assistant" ? (
                  <div className="prose prose-sm prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>
                ) : msg.content}
              </div>
            </div>
          ))}
          {streaming && !streamingContent && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm border border-[#2d2d4e] bg-[#1a1a2e] px-4 py-3 text-sm text-slate-400">
                <span className="flex gap-1">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400 [animation-delay:0ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400 [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400 [animation-delay:300ms]" />
                </span>
                <span className="text-xs text-slate-500">{t.thinking[lang]}</span>
              </div>
            </div>
          )}
          {streaming && streamingContent && (
            <div className="flex justify-start">
              <div className="max-w-2xl rounded-2xl rounded-bl-sm border border-[#2d2d4e] bg-[#1a1a2e] px-4 py-3 text-sm text-slate-200">
                <div className="prose prose-sm prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
                </div>
                <span className="ml-1 inline-block h-4 w-1 animate-pulse bg-blue-400" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-[#2d2d4e] bg-[#1a1a2e] p-4">
          {pendingFiles.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {pendingFiles.map((file, idx) => (
                <span
                  key={`${file.name}-${file.size}-${idx}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1 text-xs text-slate-300"
                >
                  <Paperclip className="h-3 w-3 text-blue-400" />
                  <span className="max-w-[200px] truncate">{file.name}</span>
                  <span className="text-slate-500">{formatFileSize(file.size)}</span>
                  <button
                    type="button"
                    onClick={() => removePendingFile(idx)}
                    className="rounded p-0.5 text-slate-500 hover:bg-red-500/20 hover:text-red-400"
                    aria-label={t.removeFile[lang]}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </span>
              ))}
            </div>
          )}
          {(suggestLoading || suggestedQuestions.length > 0) && pendingFiles.length > 0 && (
            <div className="mb-3 rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-2">
              <div className="mb-2 flex items-center gap-1.5 text-xs text-blue-300">
                <Sparkles className="h-3.5 w-3.5" />
                {suggestLoading ? t.analyzingFiles[lang] : t.suggestedTitle[lang]}
              </div>
              {!suggestLoading && (
                <div className="flex flex-col gap-1.5">
                  {suggestedQuestions.map((q, i) => (
                    <button
                      key={`${i}-${q.slice(0, 24)}`}
                      type="button"
                      onClick={() => applySuggestion(q)}
                      disabled={streaming}
                      className="rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-left text-xs text-slate-200 transition-colors hover:border-blue-500/40 hover:bg-blue-600/10 disabled:opacity-40"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-xl border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-3">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={onFilesSelected}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={streaming || isRecording || isProcessing}
              className="rounded-lg p-2 text-slate-400 hover:bg-white/5 hover:text-blue-400 disabled:opacity-40"
              title={t.attachFiles[lang]}
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={handleVoiceClick}
              disabled={streaming || isProcessing}
              className={clsx(
                "rounded-lg p-2 transition-colors disabled:opacity-40",
                isRecording
                  ? "bg-red-500/20 text-red-400 animate-pulse"
                  : isProcessing
                    ? "text-blue-400"
                    : "text-slate-400 hover:bg-white/5 hover:text-blue-400",
              )}
              title={
                isRecording
                  ? t.voiceRecording[lang]
                  : isProcessing
                    ? t.voiceProcessing[lang]
                    : t.voiceInput[lang]
              }
            >
              <Mic className="h-4 w-4" />
            </button>
            <textarea
              className="flex-1 resize-none bg-transparent text-sm text-white placeholder-slate-500 focus:outline-none"
              rows={1}
              placeholder={t.placeholder[lang]}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <button
              onClick={send}
              disabled={!canSend || isRecording || isProcessing}
              className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-1.5 text-center text-xs text-slate-600">
            {isRecording
              ? t.voiceRecording[lang]
              : isProcessing
                ? t.voiceProcessing[lang]
                : `${t.hint[lang]} · ${t.fileTypesHint[lang]}`}
          </p>
        </div>
      </div>
    </div>
  );
}
