"use client";

import { useEffect, useRef, useState } from "react";
import { Send, Plus, MessageSquare } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatApi, agentsApi, streamResponse } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";
import { clsx } from "clsx";

interface Message { id: string; role: string; content: string; created_at: string; }
interface Conversation { id: string; title: string | null; agent_id: string | null; created_at: string; }
interface Agent { id: string; name: string; role: string; }

export default function ChatPage() {
  const { lang } = useLangStore();
  const t = translations.chat;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activeConv, setActiveConv] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatApi.listConversations().then(({ data }) => setConversations(data));
    agentsApi.list().then(({ data }) => setAgents(data));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

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

  const send = async () => {
    if (!input.trim() || streaming) return;

    let convId = activeConv;
    if (!convId) {
      try {
        const { data } = await chatApi.createConversation({
          title: input.slice(0, 40),
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

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    const msg = input;
    setInput("");
    setStreaming(true);
    setStreamingContent("");

    let full = "";
    try {
      for await (const token of streamResponse(`/chat/conversations/${convId}/messages`, {
        message: msg,
        stream: true,
      })) {
        full += token;
        setStreamingContent(full);
      }
    } catch {
      try {
        const { data } = await chatApi.sendMessage(convId!, { message: msg, stream: false });
        full = data?.content ?? "";
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
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

  return (
    <div className="flex h-screen">
      <div className="flex w-56 flex-col border-r border-[#2d2d4e] bg-[#1a1a2e]">
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
        </div>
        <div className="flex-1 overflow-y-auto px-2">
          {conversations.map((conv) => (
            <button
              key={conv.id}
              onClick={() => loadMessages(conv.id)}
              className={clsx(
                "mb-1 w-full rounded-lg px-3 py-2 text-left text-sm transition-colors",
                activeConv === conv.id
                  ? "bg-blue-600/20 text-blue-300"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              )}
            >
              <div className="flex items-center gap-2">
                <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                <span className="line-clamp-1">{conv.title || t.untitled[lang]}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-1 flex-col">
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
          <div className="flex items-end gap-3 rounded-xl border border-[#2d2d4e] bg-[#0d0d1a] px-4 py-3">
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
              disabled={!input.trim() || streaming}
              className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-1.5 text-center text-xs text-slate-600">{t.hint[lang]}</p>
        </div>
      </div>
    </div>
  );
}
