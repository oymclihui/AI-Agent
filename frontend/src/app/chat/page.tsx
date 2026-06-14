"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Send, Plus, MessageSquare, Paperclip, X, Sparkles, Trash2, Mic, Volume2, Bot, BookOpen, FolderOpen, ChevronRight, Cpu, PlugZap, Layers, Menu, LayoutGrid, Globe } from "lucide-react";
import MarkdownView from "@/components/MarkdownView";
import ChatRichContent from "@/components/ChatRichContent";
import { chatApi, agentsApi, streamChatResponse, streamChatResponseForm, knowledgeApi, skillsApi, modelsApi, authApi, desktopAutomationApi, harnessApi } from "@/lib/api";
import { getAuthToken } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";
import { clsx } from "clsx";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { useVoiceOutput } from "@/hooks/useVoiceOutput";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { useVoiceChatStore } from "@/lib/voiceChatStore";
import { SegmentedControl } from "@/components/SegmentedControl";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";
import {
  CHAT_SCENES,
  capsulesForScene,
  matchAgentByHint,
  type ChatScene,
  type QuickCapsule,
} from "@/lib/chatScenarios";
import { INSPIRE_SESSION_KEY } from "@/lib/inspirationCatalog";
import type { InspirePendingPayload } from "@/lib/launchInspiration";
import {
  CHAT_CONNECTORS,
  connectorLabel,
  connectorMatchesMailbox,
  type ChatConnectorPreset,
} from "@/lib/chatConnectors";

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
  metadata?: { attachments?: AttachmentMeta[]; thinking?: string };
}

interface Conversation {
  id: string;
  title: string | null;
  agent_id: string | null;
  knowledge_base_ids?: string[];
  skills_config?: { skill_id: string; always_load?: boolean; priority?: number }[];
  model_config_id?: string | null;
  connector_id?: string | null;
  web_search_enabled?: boolean;
  created_at: string;
}
interface ModelConfigOption {
  id: string;
  name: string;
  provider: string;
  model_id: string;
  is_default: boolean;
}
interface Agent {
  id: string;
  name: string;
  role: string;
  skills_config?: { skill_id: string }[];
}
interface SkillOption { id: string; display_name: string; status: string; }
interface KnowledgeOption { id: string; name: string; source_type?: string; }

interface DepositSuggestion {
  type: string;
  recommended: boolean;
  title?: string;
  reason: string;
  confidence: number;
}

interface DepositTaskPreview {
  name: string;
  schedule_type?: string;
  cron_expression?: string;
  schedule_label?: string;
  prompt_preview?: string;
}

function ThinkingBlock({
  content,
  lang,
  streaming = false,
}: {
  content: string;
  lang: "zh" | "en";
  streaming?: boolean;
}) {
  const t = translations.chat;
  const [open, setOpen] = useState(streaming);

  useEffect(() => {
    if (streaming) setOpen(true);
  }, [streaming]);

  if (!content.trim()) return null;

  return (
    <div className="mb-2 rounded-lg border border-violet-500/25 bg-violet-950/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-violet-300 hover:text-violet-200"
      >
        <ChevronRight className={clsx("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <Sparkles className="h-3.5 w-3.5 shrink-0 opacity-80" />
        <span>{streaming ? t.thinking[lang] : t.thinkingProcess[lang]}</span>
      </button>
      {open && (
        <div className="max-h-64 overflow-y-auto border-t border-violet-500/20 px-3 py-2 text-xs leading-relaxed text-violet-200/85">
          <MarkdownView size="xs">{content}</MarkdownView>
          {streaming && <span className="ml-0.5 inline-block h-3 w-0.5 animate-pulse bg-violet-400" />}
        </div>
      )}
    </div>
  );
}

interface DepositOffer {
  worth_deposit: boolean;
  draft_id: string;
  suggestions: DepositSuggestion[];
  draft?: {
    skill_title?: string;
    knowledge_title?: string;
    agent_name?: string;
    employee_name?: string;
    employee_title?: string;
    employee_description?: string;
    tasks?: DepositTaskPreview[];
  };
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ChatPage() {
  const router = useRouter();
  const { lang } = useLangStore();
  const t = translations.chat;
  const isMobile = useIsMobile();
  const [convDrawerOpen, setConvDrawerOpen] = useState(false);

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
  const [streamingThinking, setStreamingThinking] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<string>("");
  const [selectedSkill, setSelectedSkill] = useState<string>("");
  const [selectedKbId, setSelectedKbId] = useState<string>("");
  const [selectedModelConfigId, setSelectedModelConfigId] = useState<string>("");
  const [selectedConnector, setSelectedConnector] = useState<string>("");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [modelConfigs, setModelConfigs] = useState<ModelConfigOption[]>([]);
  const [mailboxSaved, setMailboxSaved] = useState<{
    email: string;
    imap_host: string;
    imap_port: number;
  } | null>(null);
  const [connectorSetup, setConnectorSetup] = useState<ChatConnectorPreset | null>(null);
  const [connectorEmail, setConnectorEmail] = useState("");
  const [connectorPassword, setConnectorPassword] = useState("");
  const [depositOffer, setDepositOffer] = useState<DepositOffer | null>(null);
  const [depositLoading, setDepositLoading] = useState(false);
  const [depositConfirming, setDepositConfirming] = useState(false);
  const [depositSelected, setDepositSelected] = useState<Set<string>>(new Set());
  const [depositDraftOnly, setDepositDraftOnly] = useState(false);
  const depositDismissedRef = useRef<Set<string>>(new Set());
  const depositOfferRef = useRef<DepositOffer | null>(null);
  const depositSuggestAbortRef = useRef<AbortController | null>(null);
  const [pendingDesktopTasks, setPendingDesktopTasks] = useState<Array<{
    id: string; demo_name?: string | null; action: string; instructions?: string | null;
  }>>([]);
  const [desktopConfirmBusy, setDesktopConfirmBusy] = useState<string | null>(null);
  const [pendingHarnessActions, setPendingHarnessActions] = useState<Array<{
    id: string; tool_name: string; tool_args?: Record<string, unknown>; risk_level?: string;
  }>>([]);
  const [harnessConfirmBusy, setHarnessConfirmBusy] = useState<string | null>(null);
  const [scene, setScene] = useState<ChatScene>("office");
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeOption[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const appendVoiceText = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setInput((prev) => (prev.trim() ? `${prev.trim()} ${trimmed}` : trimmed));
  }, []);

  const voiceDialog = useVoiceChatStore((s) => s.enabled);
  const setVoiceDialog = useVoiceChatStore((s) => s.setEnabled);

  const { speak, stop: stopSpeaking, isSpeaking } = useVoiceOutput(lang);
  const { isRecording, isProcessing, toggle: toggleVoice } = useVoiceInput(
    lang,
    streaming || isSpeaking,
  );

  const sendRef = useRef<
    (text?: string, opts?: { fromVoice?: boolean }) => Promise<string | null>
  >(async () => null);

  const inspirePendingRef = useRef<InspirePendingPayload | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const agentId = params.get("agent");
    if (agentId) setSelectedAgent(agentId);

    if (params.get("from") === "inspire") {
      try {
        const raw = sessionStorage.getItem(INSPIRE_SESSION_KEY);
        if (raw) {
          inspirePendingRef.current = JSON.parse(raw) as InspirePendingPayload;
          sessionStorage.removeItem(INSPIRE_SESSION_KEY);
          window.history.replaceState({}, "", "/chat");
        }
      } catch {
        /* ignore */
      }
    }
  }, []);

  useEffect(() => {
    const payload = inspirePendingRef.current;
    if (!payload) return;
    setInput(payload.prompt);
    if (payload.scene) setScene(payload.scene as ChatScene);
    if (payload.agentHint && agents.length) {
      const id = matchAgentByHint(agents, payload.agentHint);
      if (id) setSelectedAgent(id);
    }
    inspirePendingRef.current = null;
    toast.success(translations.inspiration.loadedInChat[lang], { duration: 4000 });
  }, [agents, lang]);

  useEffect(() => {
    chatApi.listConversations().then(({ data }) => setConversations(data)).catch(() => {});
    agentsApi.list(lang).then(({ data }) => setAgents(data)).catch(() => {});
    skillsApi.list(lang).then(({ data }) => {
      setSkills((data as SkillOption[]).filter((s) => s.status === "active"));
    }).catch(() => {});
    knowledgeApi.list().then(({ data }) => setKnowledgeBases(data)).catch(() => {});
    modelsApi.listConfigs().then(({ data }) => {
      const configs = data as ModelConfigOption[];
      setModelConfigs(configs);
      setSelectedModelConfigId((prev) => prev || configs.find((c) => c.is_default)?.id || "");
    }).catch(() => {});
    authApi.getMailbox().then(({ data }) => {
      if (data) setMailboxSaved(data);
    }).catch(() => {});
  }, [lang]);

  const loadPendingDesktop = useCallback(async () => {
    try {
      const { data } = await desktopAutomationApi.listAwaitingConfirmation();
      setPendingDesktopTasks((data as typeof pendingDesktopTasks) || []);
    } catch {
      setPendingDesktopTasks([]);
    }
  }, []);

  const loadPendingHarness = useCallback(async () => {
    try {
      const { data } = await harnessApi.listAwaitingActions();
      setPendingHarnessActions((data as typeof pendingHarnessActions) || []);
    } catch {
      setPendingHarnessActions([]);
    }
  }, []);

  const loadPendingActions = useCallback(async () => {
    await Promise.all([loadPendingDesktop(), loadPendingHarness()]);
  }, [loadPendingDesktop, loadPendingHarness]);

  useEffect(() => {
    loadPendingActions();
    const timer = setInterval(loadPendingActions, 8000);
    return () => clearInterval(timer);
  }, [loadPendingActions, activeConv]);

  useEffect(() => {
    if (isMobile && !activeConv) setConvDrawerOpen(true);
  }, [isMobile, activeConv]);

  const approveDesktopTask = async (taskId: string) => {
    setDesktopConfirmBusy(taskId);
    try {
      await desktopAutomationApi.confirmTask(taskId);
      toast.success(t.desktopConfirmOk[lang]);
      await loadPendingActions();
    } catch {
      toast.error(translations.common.actionFailed[lang]);
    } finally {
      setDesktopConfirmBusy(null);
    }
  };

  const rejectDesktopTask = async (taskId: string) => {
    setDesktopConfirmBusy(taskId);
    try {
      await desktopAutomationApi.rejectTask(taskId);
      toast.success(t.desktopConfirmRejected[lang]);
      await loadPendingActions();
    } catch {
      toast.error(translations.common.actionFailed[lang]);
    } finally {
      setDesktopConfirmBusy(null);
    }
  };

  const approveHarnessAction = async (actionId: string) => {
    setHarnessConfirmBusy(actionId);
    try {
      await harnessApi.confirmAction(actionId);
      toast.success(t.harnessConfirmOk[lang]);
      await loadPendingActions();
    } catch {
      toast.error(translations.common.actionFailed[lang]);
    } finally {
      setHarnessConfirmBusy(null);
    }
  };

  const rejectHarnessAction = async (actionId: string) => {
    setHarnessConfirmBusy(actionId);
    try {
      await harnessApi.rejectAction(actionId);
      toast.success(t.harnessConfirmRejected[lang]);
      await loadPendingActions();
    } catch {
      toast.error(translations.common.actionFailed[lang]);
    } finally {
      setHarnessConfirmBusy(null);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent, streamingThinking]);

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

  const sceneOptions = CHAT_SCENES.map((s) => ({
    value: s.value,
    label: lang === "zh" ? s.label.zh : s.label.en,
  }));
  const visibleCapsules = capsulesForScene(scene);

  const applyCapsule = (cap: QuickCapsule) => {
    setInput(lang === "zh" ? cap.prompt.zh : cap.prompt.en);
    const agentId = matchAgentByHint(agents, cap.agentHint);
    if (agentId) setSelectedAgent(agentId);
  };

  const depositTypeLabel = (type: string) => {
    const map: Record<string, { zh: string; en: string }> = {
      skill: t.depositTypeSkill,
      knowledge: t.depositTypeKnowledge,
      agent: t.depositTypeAgent,
      employee: t.depositTypeEmployee,
    };
    return map[type]?.[lang] ?? type;
  };

  const fetchDepositSuggestion = useCallback(async (convId: string, force = false) => {
    if (!force && depositDismissedRef.current.has(convId)) return;
    depositSuggestAbortRef.current?.abort();
    const controller = new AbortController();
    depositSuggestAbortRef.current = controller;
    setDepositLoading(true);
    try {
      const { data } = await chatApi.suggestDeposit(convId, lang, controller.signal);
      if (controller.signal.aborted) return;
      if (!data.worth_deposit || !data.draft_id) {
        setDepositOffer(null);
        depositOfferRef.current = null;
        if (force) {
          toast(t.depositNoContent[lang], { icon: "ℹ️" });
        }
        return;
      }
      const offer = data as DepositOffer;
      const recommended = offer.suggestions.filter((s) => s.recommended).map((s) => s.type);
      setDepositSelected(
        new Set(recommended.length > 0 ? recommended : offer.suggestions.map((s) => s.type)),
      );
      setDepositDraftOnly(false);
      setDepositOffer(offer);
      depositOfferRef.current = offer;
    } catch (err: unknown) {
      if (controller.signal.aborted) return;
      setDepositOffer(null);
      depositOfferRef.current = null;
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const isTimeout = (err as { code?: string })?.code === "ECONNABORTED";
      toast.error(
        detail
          ? `${t.depositSuggestFailed[lang]}: ${detail}`
          : isTimeout
            ? `${t.depositSuggestFailed[lang]} (${lang === "zh" ? "请求超时，分析耗时较长" : "timeout"})`
            : t.depositSuggestFailed[lang],
      );
    } finally {
      setDepositLoading(false);
    }
  }, [lang]);

  const dismissDeposit = () => {
    if (activeConv) depositDismissedRef.current.add(activeConv);
    setDepositOffer(null);
    depositOfferRef.current = null;
  };

  const toggleDepositType = (type: string) => {
    setDepositSelected((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const confirmDeposit = async () => {
    if (!activeConv || !depositOffer?.draft_id || depositSelected.size === 0) return;
    setDepositConfirming(true);
    try {
      const { data } = await chatApi.confirmDeposit(activeConv, {
        draft_id: depositOffer.draft_id,
        types: Array.from(depositSelected),
        activate_employee: !depositDraftOnly,
      });
      toast.success(t.depositConfirmOk[lang]);
      setDepositOffer(null);
      depositOfferRef.current = null;
      depositDismissedRef.current.add(activeConv);
      if (data.employee_id) {
        toast(
          (toastInstance) => (
            <span className="flex items-center gap-2 text-sm">
              {t.depositEmployeeLink[lang]}
              <button
                type="button"
                className="text-blue-400 underline"
                onClick={() => {
                  router.push(`/employees/${data.employee_id}`);
                  toast.dismiss(toastInstance.id);
                }}
              >
                →
              </button>
            </span>
          ),
          { duration: 6000 },
        );
      } else if (data.agent_id) {
        router.push("/agents");
      }
      try {
        const { data: conv } = await chatApi.getConversation(activeConv);
        applyConversationContext(conv);
        setConversations((list) => list.map((c) => (c.id === conv.id ? conv : c)));
      } catch {
        /* ignore */
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const detailStr = typeof detail === "string" ? detail : "";
      if (detailStr.includes("Deposit draft not found") || detailStr.includes("suggest-deposit again")) {
        toast(t.depositDraftExpired[lang], { icon: "⚠️" });
        await fetchDepositSuggestion(activeConv, true);
        return;
      }
      toast.error(detailStr ? `${t.depositConfirmFailed[lang]}: ${detailStr}` : t.depositConfirmFailed[lang]);
    } finally {
      setDepositConfirming(false);
    }
  };

  const onSkillChange = (skillId: string) => {
    setSelectedSkill(skillId);
    let agentId = selectedAgent;
    if (skillId) {
      const bound = agents.find((a) =>
        (a.skills_config || []).some((b) => b.skill_id === skillId),
      );
      if (bound) {
        agentId = bound.id;
        setSelectedAgent(bound.id);
      }
    }
    void syncContextToServer({
      skills_config: skillId ? [{ skill_id: skillId, always_load: true, priority: 0 }] : [],
      agent_id: agentId || null,
    });
  };

  const onAgentChange = (agentId: string) => {
    setSelectedAgent(agentId);
    void syncContextToServer({ agent_id: agentId || null });
  };

  const onKbChange = (kbId: string) => {
    setSelectedKbId(kbId);
    void syncContextToServer({ knowledge_base_ids: kbId ? [kbId] : [] });
  };

  const onModelChange = (modelId: string) => {
    setSelectedModelConfigId(modelId);
    void syncContextToServer({ model_config_id: modelId || null });
  };

  const onConnectorChange = (connectorId: string) => {
    setSelectedConnector(connectorId);
    if (!connectorId) {
      void syncContextToServer({ connector_id: null });
      return;
    }
    const preset = CHAT_CONNECTORS.find((c) => c.id === connectorId);
    if (!preset) return;
    if (!connectorMatchesMailbox(connectorId, mailboxSaved)) {
      setConnectorSetup(preset);
      setConnectorEmail(mailboxSaved?.email || "");
      setConnectorPassword("");
      return;
    }
    void syncContextToServer({ connector_id: connectorId });
  };

  const saveConnectorSetup = async () => {
    if (!connectorSetup) return;
    if (!connectorPassword.trim() && !mailboxSaved) {
      toast.error(t.connectorNeedPassword[lang]);
      return;
    }
    try {
      const connectorId = connectorSetup.id;
      await authApi.saveMailbox({
        email: connectorEmail.trim() || undefined,
        mailbox_password: connectorPassword.trim() || undefined,
        imap_host: connectorSetup.imap_host,
        imap_port: connectorSetup.imap_port,
        imap_use_ssl: connectorSetup.imap_use_ssl,
      });
      const { data } = await authApi.getMailbox();
      if (data) setMailboxSaved(data);
      setSelectedConnector(connectorId);
      setConnectorSetup(null);
      setConnectorPassword("");
      toast.success(t.connectorSaved[lang]);
      void syncContextToServer({ connector_id: connectorId });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${t.connectorSaveFailed[lang]}: ${detail}` : t.connectorSaveFailed[lang]);
    }
  };

  const applyConversationContext = (conv: Conversation) => {
    if (conv.agent_id) setSelectedAgent(conv.agent_id);
    else setSelectedAgent("");
    if (conv.model_config_id) setSelectedModelConfigId(conv.model_config_id);
    if (conv.connector_id) setSelectedConnector(conv.connector_id);
    else setSelectedConnector("");
    setWebSearchEnabled(Boolean(conv.web_search_enabled));
    const kbIds = conv.knowledge_base_ids || [];
    setSelectedKbId(kbIds[0] || "");
    const skillIds = (conv.skills_config || []).map((s) => s.skill_id);
    setSelectedSkill(skillIds[0] || "");
  };

  const syncContextToServer = async (overrides?: {
    agent_id?: string | null;
    knowledge_base_ids?: string[];
    skills_config?: { skill_id: string; always_load: boolean; priority: number }[];
    model_config_id?: string | null;
    connector_id?: string | null;
    web_search_enabled?: boolean;
  }) => {
    if (!activeConv) return;
    const skillId = overrides?.skills_config?.[0]?.skill_id ?? selectedSkill;
    const kbIds = overrides?.knowledge_base_ids ?? (selectedKbId ? [selectedKbId] : []);
    const payload = {
      agent_id: overrides?.agent_id !== undefined ? overrides.agent_id : (selectedAgent || null),
      knowledge_base_ids: kbIds,
      skills_config: overrides?.skills_config ?? (
        skillId ? [{ skill_id: skillId, always_load: true, priority: 0 }] : []
      ),
      model_config_id: overrides?.model_config_id !== undefined
        ? overrides.model_config_id
        : (selectedModelConfigId || null),
      connector_id: overrides?.connector_id !== undefined
        ? overrides.connector_id
        : (selectedConnector || null),
      web_search_enabled: overrides?.web_search_enabled !== undefined
        ? overrides.web_search_enabled
        : webSearchEnabled,
    };
    try {
      const { data } = await chatApi.updateContext(activeConv, payload);
      setConversations((list) => list.map((c) => (c.id === data.id ? data : c)));
    } catch {
      /* non-blocking */
    }
  };

  const conversationContext = () => {
    const skills_config = selectedSkill
      ? [{ skill_id: selectedSkill, always_load: true, priority: 0 }]
      : [];
    return {
      agent_id: selectedAgent || null,
      knowledge_base_ids: selectedKbId ? [selectedKbId] : [],
      skills_config,
      model_config_id: selectedModelConfigId || null,
      connector_id: selectedConnector || null,
      web_search_enabled: webSearchEnabled,
    };
  };

  const messageExtras = () => ({
    model_config_id: selectedModelConfigId || null,
    connector_id: selectedConnector || null,
    web_search_enabled: webSearchEnabled,
  });

  const contextSummary = () => {
    const parts: string[] = [];
    const modelCfg = modelConfigs.find((m) => m.id === selectedModelConfigId);
    if (modelCfg) parts.push(modelCfg.name);
    const agent = agents.find((a) => a.id === selectedAgent);
    if (agent) parts.push(agent.name);
    const skill = skills.find((s) => s.id === selectedSkill);
    if (skill) parts.push(skill.display_name);
    const kb = knowledgeBases.find((k) => k.id === selectedKbId);
    if (kb) parts.push(kb.name);
    if (selectedConnector) parts.push(connectorLabel(selectedConnector, lang));
    if (webSearchEnabled) parts.push(t.webSearch[lang]);
    return parts.join(" · ");
  };

  const newConversation = async () => {
    try {
      const { data } = await chatApi.createConversation({
        title: t.newChat[lang],
        ...conversationContext(),
      });
      setConversations((c) => [data, ...c]);
      setActiveConv(data.id);
      setMessages([]);
      setDepositOffer(null);
      if (isMobile) setConvDrawerOpen(false);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `${t.createFailed[lang]}: ${detail}` : t.createFailed[lang]);
    }
  };

  const loadMessages = async (convId: string) => {
    setActiveConv(convId);
    setDepositOffer(null);
    if (isMobile) setConvDrawerOpen(false);
    try {
      const { data: conv } = await chatApi.getConversation(convId);
      applyConversationContext(conv);
      setConversations((list) => {
        const exists = list.some((c) => c.id === conv.id);
        return exists ? list.map((c) => (c.id === conv.id ? conv : c)) : [conv, ...list];
      });
    } catch {
      const conv = conversations.find((c) => c.id === convId);
      if (conv) applyConversationContext(conv);
    }
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

  const appendAssistant = (content: string, thinking?: string) => {
    setMessages((m) => [
      ...m,
      {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: content || t.emptyResponse[lang],
        created_at: new Date().toISOString(),
        metadata: thinking ? { thinking } : undefined,
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

  const send = async (
    textOverride?: string,
    opts?: { fromVoice?: boolean },
  ): Promise<string | null> => {
    const messageText = (textOverride ?? input).trim();
    const hasText = messageText.length > 0;
    const hasFiles = pendingFiles.length > 0;
    if ((!hasText && !hasFiles) || streaming) return null;

    let convId = activeConv;
    if (!convId) {
      try {
        const title = hasText ? messageText.slice(0, 40) : pendingFiles[0]?.name || t.newChat[lang];
        const { data } = await chatApi.createConversation({
          title,
          ...conversationContext(),
        });
        convId = data.id;
        setActiveConv(convId);
        setConversations((c) => [data, ...c]);
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        toast.error(detail ? `${t.createFailed[lang]}: ${detail}` : t.createFailed[lang]);
        return null;
      }
    }

    const msg = hasText ? messageText : t.analyzePrompt[lang];
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
    if (!textOverride) {
      setInput("");
      setPendingFiles([]);
    }
    setSuggestedQuestions([]);
    setStreaming(true);
    setStreamingContent("");
    setStreamingThinking("");

    if (webSearchEnabled) {
      toast.loading(t.webSearchSearching[lang], { id: "web-search", duration: 8000 });
    }

    let full = "";
    let thinking = "";
    let streamError = "";
    try {
      if (filesToSend.length > 0) {
        const form = chatApi.sendMessageWithFiles(convId!, msg, filesToSend, true, messageExtras());
        for await (const event of streamChatResponseForm(`/chat/conversations/${convId}/messages`, form)) {
          if (event.thinking) {
            thinking += event.thinking;
            setStreamingThinking(thinking);
          }
          if (event.token) {
            full += event.token;
            setStreamingContent(full);
          }
        }
      } else {
        for await (const event of streamChatResponse(`/chat/conversations/${convId}/messages`, {
          message: msg,
          stream: true,
          ...messageExtras(),
        })) {
          if (event.thinking) {
            thinking += event.thinking;
            setStreamingThinking(thinking);
          }
          if (event.token) {
            full += event.token;
            setStreamingContent(full);
          }
        }
      }
    } catch (err: unknown) {
      streamError = err instanceof Error ? err.message : "";
    } finally {
      toast.dismiss("web-search");
    }

    if (!full) {
      if (streamError) {
        toast.error(`${t.replyFailed[lang]}: ${streamError}`);
        setStreaming(false);
        setStreamingContent("");
        setStreamingThinking("");
        return null;
      }
      try {
        if (filesToSend.length > 0) {
          const form = chatApi.sendMessageWithFiles(convId!, msg, filesToSend, false, messageExtras());
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
          thinking = data?.thinking ?? thinking;
        } else {
          const { data } = await chatApi.sendMessage(convId!, { message: msg, stream: false, ...messageExtras() });
          full = data?.content ?? "";
          thinking = data?.thinking ?? thinking;
        }
      } catch (err: unknown) {
        const detail =
          (err instanceof Error ? err.message : "") ||
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          streamError;
        toast.error(detail ? `${t.replyFailed[lang]}: ${detail}` : t.replyFailed[lang]);
        setStreaming(false);
        setStreamingContent("");
        setStreamingThinking("");
        return null;
      }
    }

    appendAssistant(full, thinking || undefined);
    setStreamingContent("");
    setStreamingThinking("");
    setStreaming(false);
    void loadPendingActions();
    if (convId && full.trim()) {
      const hasOpenDeposit =
        depositOfferRef.current?.draft_id && activeConv === convId;
      if (!hasOpenDeposit) {
        void fetchDepositSuggestion(convId);
      }
    }

    if (opts?.fromVoice && voiceDialog && full.trim()) {
      void speak(full);
    }
    return full.trim() ? full : null;
  };

  sendRef.current = send;

  const handleVoiceClick = async () => {
    if (isSpeaking) {
      stopSpeaking();
      return;
    }
    try {
      await toggleVoice(async (text) => {
        const trimmed = text.trim();
        if (!trimmed) return;
        if (voiceDialog) {
          stopSpeaking();
          await sendRef.current(trimmed, { fromVoice: true });
        } else {
          appendVoiceText(trimmed);
        }
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.toLowerCase().includes("permission") || msg.toLowerCase().includes("notallowed")) {
        toast.error(t.voiceDenied[lang]);
      } else {
        toast.error(msg ? `${t.voiceFailed[lang]}: ${msg}` : t.voiceFailed[lang]);
      }
    }
  };

  const handleQaChoice = (text: string) => {
    if (streaming) return;
    void send(text);
  };

  const canSend = (input.trim().length > 0 || pendingFiles.length > 0) && !streaming;

  const activeConvTitle =
    conversations.find((c) => c.id === activeConv)?.title?.trim() || t.untitled[lang];

  return (
    <div className="chat-page flex h-full min-h-0">
      {convDrawerOpen && isMobile && (
        <button
          type="button"
          className="chat-mobile-backdrop md:hidden"
          onClick={() => setConvDrawerOpen(false)}
          aria-label={t.closeDrawer[lang]}
        />
      )}
      <div
        className={clsx(
          "chat-conv-sidebar theme-surface flex flex-col border-r theme-border",
          isMobile
            ? clsx(
                "chat-conv-drawer fixed inset-y-0 left-0 z-50 w-[min(18rem,88vw)] transition-transform duration-200 ease-out md:relative md:z-auto md:w-56 md:translate-x-0",
                convDrawerOpen ? "translate-x-0" : "-translate-x-full",
              )
            : "relative w-56 shrink-0",
        )}
      >
        <div className="p-3">
          <button
            onClick={newConversation}
            className="mb-3 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t.newChat[lang]}
          </button>
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

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="chat-mobile-header md:hidden">
          <button
            type="button"
            onClick={() => setConvDrawerOpen(true)}
            className="rounded-lg p-2 text-slate-400 hover:bg-[var(--hover)] hover:text-white"
            aria-label={t.openConversations[lang]}
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="chat-mobile-header-title">{activeConv ? activeConvTitle : t.conversations[lang]}</span>
          <Link
            href="/home"
            className="rounded-lg p-2 text-slate-400 hover:bg-[var(--hover)] hover:text-white"
            title={t.moreModules[lang]}
            aria-label={t.moreModules[lang]}
          >
            <LayoutGrid className="h-5 w-5" />
          </Link>
        </div>
        {activeConv && messages.length > 0 && (
          <div className="chat-export-bar">
            <button
              type="button"
              onClick={saveAsSkill}
              disabled={streaming}
              className="chat-export-btn chat-export-btn-skill"
            >
              {t.saveAsSkill[lang]}
            </button>
            <button
              type="button"
              onClick={saveToKnowledge}
              disabled={streaming}
              className="chat-export-btn chat-export-btn-kb"
            >
              {t.saveToKnowledge[lang]}
            </button>
            <button
              type="button"
              onClick={() => activeConv && fetchDepositSuggestion(activeConv, true)}
              disabled={streaming || depositLoading}
              className="chat-export-btn chat-export-btn-skill ml-auto"
            >
              <span className="inline-flex items-center gap-1">
                <Layers className="h-3 w-3" />
                {depositLoading ? t.depositAnalyzing[lang] : t.depositTitle[lang]}
              </span>
            </button>
          </div>
        )}
        <div className="flex-1 space-y-4 overflow-y-auto p-3 md:p-6">
          {messages.length === 0 && !streaming && (
            <div className="flex h-full flex-col items-center justify-center px-4 text-center">
              <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-500/10">
                <MessageSquare className="h-8 w-8 text-blue-400" />
              </div>
              <h2 className="mb-2 text-xl font-semibold text-white">{t.heroTitle[lang]}</h2>
              <p className="mb-6 max-w-md text-sm text-slate-400">{t.heroSubtitle[lang]}</p>
              <SegmentedControl
                value={scene}
                onChange={setScene}
                options={sceneOptions}
                className="mb-6"
              />
              <CapsuleScrollRow
                className="max-w-2xl w-full"
                centerWhenFit
                scrollLeftLabel={t.scrollLeft[lang]}
                scrollRightLabel={t.scrollRight[lang]}
              >
                {visibleCapsules.map((cap) => (
                  <button
                    key={cap.id}
                    type="button"
                    onClick={() => applyCapsule(cap)}
                    className="chat-capsule-chip"
                  >
                    {lang === "zh" ? cap.label.zh : cap.label.en}
                  </button>
                ))}
              </CapsuleScrollRow>
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
                {msg.role === "assistant" && msg.metadata?.thinking && (
                  <ThinkingBlock content={msg.metadata.thinking} lang={lang} />
                )}
                {msg.role === "assistant" ? (
                  <ChatRichContent
                    size="sm"
                    lang={lang}
                    onChoiceSelect={handleQaChoice}
                    choicesDisabled={streaming}
                  >
                    {msg.content}
                  </ChatRichContent>
                ) : msg.content}
              </div>
            </div>
          ))}
          {streaming && streamingThinking && (
            <div className="flex justify-start">
              <div className="max-w-2xl">
                <ThinkingBlock content={streamingThinking} lang={lang} streaming />
              </div>
            </div>
          )}
          {streaming && !streamingContent && !streamingThinking && (
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
                <ChatRichContent
                  size="sm"
                  highlight={false}
                  lang={lang}
                  streaming
                >
                  {streamingContent}
                </ChatRichContent>
                <span className="ml-1 inline-block h-4 w-1 animate-pulse bg-blue-400" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="shrink-0 border-t border-[#2d2d4e] bg-[#1a1a2e] p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:p-4">
          {messages.length > 0 && (
            <div className="mb-3 flex items-center gap-2">
              <SegmentedControl
                value={scene}
                onChange={setScene}
                options={sceneOptions}
                size="sm"
              />
              <CapsuleScrollRow
                className="flex-1 min-w-0"
                fadeFrom="footer"
                scrollLeftLabel={t.scrollLeft[lang]}
                scrollRightLabel={t.scrollRight[lang]}
              >
                {visibleCapsules.map((cap) => (
                  <button
                    key={cap.id}
                    type="button"
                    onClick={() => applyCapsule(cap)}
                    className="chat-capsule-chip text-xs py-1"
                  >
                    {lang === "zh" ? cap.label.zh : cap.label.en}
                  </button>
                ))}
              </CapsuleScrollRow>
            </div>
          )}
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
          {pendingDesktopTasks.length > 0 && (
            <div className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-3">
              <h4 className="mb-2 text-sm font-medium text-amber-100">{t.desktopConfirmTitle[lang]}</h4>
              <div className="space-y-2">
                {pendingDesktopTasks.map((task) => (
                  <div key={task.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/20 bg-[#0d0d1a] px-3 py-2 text-xs">
                    <span className="text-slate-200">
                      {task.demo_name || task.action}
                      {task.instructions ? ` · ${task.instructions}` : ""}
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={desktopConfirmBusy === task.id}
                        onClick={() => approveDesktopTask(task.id)}
                        className="rounded bg-emerald-600 px-2 py-1 text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {t.desktopConfirmApprove[lang]}
                      </button>
                      <button
                        type="button"
                        disabled={desktopConfirmBusy === task.id}
                        onClick={() => rejectDesktopTask(task.id)}
                        className="rounded border border-slate-600 px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                      >
                        {t.desktopConfirmReject[lang]}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {pendingHarnessActions.length > 0 && (
            <div className="mb-3 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3 py-3">
              <h4 className="mb-2 text-sm font-medium text-violet-100">{t.harnessConfirmTitle[lang]}</h4>
              <div className="space-y-2">
                {pendingHarnessActions.map((action) => (
                  <div key={action.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-violet-500/20 bg-[#0d0d1a] px-3 py-2 text-xs">
                    <span className="text-slate-200">
                      {action.tool_name}
                      {action.risk_level ? ` · ${action.risk_level}` : ""}
                      {action.tool_args && Object.keys(action.tool_args).length > 0
                        ? ` · ${JSON.stringify(action.tool_args).slice(0, 80)}`
                        : ""}
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={harnessConfirmBusy === action.id}
                        onClick={() => approveHarnessAction(action.id)}
                        className="rounded bg-emerald-600 px-2 py-1 text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {t.harnessConfirmApprove[lang]}
                      </button>
                      <button
                        type="button"
                        disabled={harnessConfirmBusy === action.id}
                        onClick={() => rejectHarnessAction(action.id)}
                        className="rounded border border-slate-600 px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                      >
                        {t.harnessConfirmReject[lang]}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {(depositLoading || depositOffer) && messages.length > 0 && (
            <div className="chat-deposit-panel">
              <h4 className="flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-blue-400" />
                {depositLoading ? t.depositAnalyzing[lang] : t.depositTitle[lang]}
              </h4>
              {!depositLoading && depositOffer && (
                <>
                  <p>{t.depositSubtitle[lang]}</p>
                  <div className="chat-deposit-options">
                    {depositOffer.suggestions.map((s) => (
                      <label key={s.type} className="chat-deposit-option">
                        <input
                          type="checkbox"
                          checked={depositSelected.has(s.type)}
                          onChange={() => toggleDepositType(s.type)}
                          disabled={depositConfirming}
                        />
                        <span>
                          <strong>{s.title || depositTypeLabel(s.type)}</strong>
                          {" · "}
                          {depositTypeLabel(s.type)}
                          <small>{s.reason}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                  {depositOffer.draft?.tasks && depositOffer.draft.tasks.length > 0 && (
                    <ul className="chat-deposit-tasks">
                      {depositOffer.draft.tasks.map((task) => (
                        <li key={`${task.name}-${task.cron_expression}`}>
                          {task.name}
                          {task.schedule_label ? ` · ${t.depositSchedule[lang]}: ${task.schedule_label}` : ""}
                          {task.cron_expression ? ` (${task.cron_expression})` : ""}
                        </li>
                      ))}
                    </ul>
                  )}
                  {depositSelected.has("employee") && (
                    <label className="chat-deposit-draft-toggle mb-2">
                      <input
                        type="checkbox"
                        checked={depositDraftOnly}
                        onChange={(e) => setDepositDraftOnly(e.target.checked)}
                        disabled={depositConfirming}
                      />
                      {t.depositDraftOnly[lang]}
                    </label>
                  )}
                  <div className="chat-deposit-actions">
                    <button
                      type="button"
                      onClick={dismissDeposit}
                      disabled={depositConfirming}
                      className="chat-export-btn"
                    >
                      {t.depositDismiss[lang]}
                    </button>
                    <button
                      type="button"
                      onClick={confirmDeposit}
                      disabled={depositConfirming || depositSelected.size === 0}
                      className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-40"
                    >
                      {depositConfirming ? t.depositAnalyzing[lang] : t.depositConfirm[lang]}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
          <div className="chat-input-area rounded-xl border border-[#2d2d4e] bg-[#0d0d1a]">
            <div className="chat-input-toolbar">
              <Cpu className="h-3.5 w-3.5 text-slate-500" />
              <select
                value={selectedModelConfigId}
                onChange={(e) => onModelChange(e.target.value)}
                disabled={streaming}
                title={t.selectModel[lang]}
              >
                <option value="">{t.noModel[lang]}</option>
                {modelConfigs.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.is_default ? " ★" : ""}
                  </option>
                ))}
              </select>
              <Bot className="h-3.5 w-3.5 text-slate-500" />
              <select
                value={selectedAgent}
                onChange={(e) => onAgentChange(e.target.value)}
                disabled={streaming}
                title={t.selectAgent[lang]}
              >
                <option value="">{t.noAgent[lang]}</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              <Sparkles className="h-3.5 w-3.5 text-slate-500" />
              <select
                value={selectedSkill}
                onChange={(e) => onSkillChange(e.target.value)}
                disabled={streaming}
                title={t.selectSkill[lang]}
              >
                <option value="">{t.noSkill[lang]}</option>
                {skills.map((s) => (
                  <option key={s.id} value={s.id}>{s.display_name}</option>
                ))}
              </select>
              <FolderOpen className="h-3.5 w-3.5 text-slate-500" />
              <select
                value={selectedKbId}
                onChange={(e) => onKbChange(e.target.value)}
                disabled={streaming}
                title={t.selectWorkspace[lang]}
              >
                <option value="">{t.noWorkspace[lang]}</option>
                {knowledgeBases.map((kb) => (
                  <option key={kb.id} value={kb.id}>
                    {kb.name}{kb.source_type === "byd_kms" ? (lang === "zh" ? " · 企业" : " · Ent") : (lang === "zh" ? " · 本地" : " · Local")}
                  </option>
                ))}
              </select>
              <PlugZap className="h-3.5 w-3.5 text-slate-500" />
              <select
                value={selectedConnector}
                onChange={(e) => onConnectorChange(e.target.value)}
                disabled={streaming}
                title={t.selectConnector[lang]}
              >
                <option value="">{t.noConnector[lang]}</option>
                {CHAT_CONNECTORS.map((c) => (
                  <option key={c.id} value={c.id}>
                    {lang === "zh" ? c.label.zh : c.label.en}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => {
                  const next = !webSearchEnabled;
                  setWebSearchEnabled(next);
                  toast.success(next ? t.webSearchOn[lang] : t.webSearchOff[lang], { duration: 3500 });
                  void syncContextToServer({ web_search_enabled: next });
                }}
                disabled={streaming}
                title={t.webSearch[lang]}
                className={clsx(
                  "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors",
                  webSearchEnabled
                    ? "bg-blue-600/20 text-blue-300 ring-1 ring-blue-500/40"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
                )}
              >
                <Globe className="h-3.5 w-3.5" />
                <span>{t.webSearch[lang]}</span>
              </button>
            </div>
            <div className="flex items-end gap-2 px-3 py-3">
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
              disabled={streaming || isRecording || isProcessing || isSpeaking}
              className="rounded-lg p-2 text-slate-400 hover:bg-white/5 hover:text-blue-400 disabled:opacity-40"
              title={t.attachFiles[lang]}
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => {
                const next = !voiceDialog;
                setVoiceDialog(next);
                toast.success(next ? t.voiceDialogOn[lang] : t.voiceDialogOffOk[lang], { duration: 3500 });
              }}
              disabled={streaming}
              className={clsx(
                "rounded-lg p-2 transition-colors disabled:opacity-40",
                voiceDialog
                  ? "bg-emerald-500/20 text-emerald-400"
                  : "text-slate-400 hover:bg-white/5 hover:text-emerald-400",
              )}
              title={voiceDialog ? t.voiceDialogOn[lang] : t.voiceDialogOff[lang]}
            >
              <Volume2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={handleVoiceClick}
              disabled={(streaming && !voiceDialog) || (isProcessing && !isRecording)}
              className={clsx(
                "rounded-lg p-2 transition-colors disabled:opacity-40",
                isRecording
                  ? "bg-red-500/20 text-red-400 animate-pulse"
                  : isSpeaking
                    ? "bg-amber-500/20 text-amber-400 animate-pulse"
                  : isProcessing
                    ? "text-blue-400"
                    : voiceDialog
                      ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                      : "text-slate-400 hover:bg-white/5 hover:text-blue-400",
              )}
              title={
                isSpeaking
                  ? t.voiceSpeaking[lang]
                  : isRecording
                    ? t.voiceRecording[lang]
                    : isProcessing
                      ? t.voiceProcessing[lang]
                      : voiceDialog
                        ? t.voiceDialogOn[lang]
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
              onClick={() => void send()}
              disabled={!canSend || isRecording || isProcessing || isSpeaking}
              className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              <Send className="h-4 w-4" />
            </button>
            </div>
          </div>
          {contextSummary() && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
              <BookOpen className="h-3 w-3 shrink-0" />
              <span>{t.workspaceHint[lang]}: {contextSummary()}</span>
            </p>
          )}
          <p className="mt-1.5 text-center text-xs text-slate-600">
            {isSpeaking
              ? t.voiceSpeaking[lang]
              : isRecording
                ? t.voiceRecording[lang]
                : isProcessing
                  ? t.voiceProcessing[lang]
                  : voiceDialog
                    ? t.voiceDialogOn[lang]
                    : `${t.hint[lang]} · ${t.fileTypesHint[lang]}`}
          </p>
        </div>
      </div>

      {connectorSetup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5 shadow-xl">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-white">{t.connectorSetupTitle[lang]}</h3>
                <p className="mt-1 text-xs text-slate-400">{t.connectorSetupDesc[lang]}</p>
                <p className="mt-2 text-xs text-blue-300">
                  {lang === "zh" ? connectorSetup.label.zh : connectorSetup.label.en}
                  {" · "}
                  {connectorSetup.imap_host}:{connectorSetup.imap_port}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setConnectorSetup(null)}
                className="rounded p-1 text-slate-500 hover:bg-white/5 hover:text-slate-300"
                aria-label={translations.common.cancel[lang]}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3">
              <input
                type="email"
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white outline-none focus:border-blue-500/50"
                placeholder={connectorSetup.emailHint?.[lang] || t.connectorEmail[lang]}
                value={connectorEmail}
                onChange={(e) => setConnectorEmail(e.target.value)}
              />
              <input
                type="password"
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white outline-none focus:border-blue-500/50"
                placeholder={connectorSetup.passwordHint?.[lang] || t.connectorPassword[lang]}
                value={connectorPassword}
                onChange={(e) => setConnectorPassword(e.target.value)}
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConnectorSetup(null)}
                className="rounded-lg border border-[#2d2d4e] px-4 py-2 text-sm text-slate-300 hover:bg-white/5"
              >
                {translations.common.cancel[lang]}
              </button>
              <button
                type="button"
                onClick={saveConnectorSetup}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                {t.connectorSave[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
