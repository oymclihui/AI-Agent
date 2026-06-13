"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cpu, CheckCircle, Server, Cloud, Plus, Pencil, Trash2, Star, Loader2, PlugZap, Search } from "lucide-react";
import { modelsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { agentAvatarTone } from "@/lib/agentCatalog";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";
import { ModelKeysPanel, type ModelKeyOption } from "@/components/ModelKeysPanel";
import toast from "react-hot-toast";

interface Model {
  provider: string; model: string; context_window?: number;
  note?: string; size_gb?: number; type?: string;
}

interface InferenceParams {
  temperature?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  max_tokens?: number | null;
  frequency_penalty?: number | null;
  presence_penalty?: number | null;
  repetition_penalty?: number | null;
  stop?: string[] | null;
  seed?: number | null;
  timeout?: number | null;
  num_ctx?: number | null;
}

interface Config {
  id: string; name: string; provider: string; model_id: string;
  base_url?: string | null;
  is_default: boolean; context_window: number | null;
  cost_per_1k_input: number | null; cost_per_1k_output: number | null;
  inference_params?: InferenceParams;
}

const PROVIDERS = ["ollama", "openai", "anthropic", "azure"] as const;

type ProviderFilter = "all" | (typeof PROVIDERS)[number];

const PROVIDER_SCENES: Array<{
  id: ProviderFilter;
  title: { zh: string; en: string };
  subtitle: { zh: string; en: string };
  tone: string;
}> = [
  {
    id: "ollama",
    title: { zh: "Ollama 本地", en: "Ollama Local" },
    subtitle: { zh: "私有化部署 · 离线推理", en: "Private deployment · offline inference" },
    tone: "agents-scene-finance",
  },
  {
    id: "openai",
    title: { zh: "OpenAI", en: "OpenAI" },
    subtitle: { zh: "GPT 系列云端模型", en: "GPT family cloud models" },
    tone: "agents-scene-data",
  },
  {
    id: "anthropic",
    title: { zh: "Anthropic", en: "Anthropic" },
    subtitle: { zh: "Claude 系列模型", en: "Claude family models" },
    tone: "agents-scene-content",
  },
  {
    id: "azure",
    title: { zh: "Azure OpenAI", en: "Azure OpenAI" },
    subtitle: { zh: "企业级 Azure 接入", en: "Enterprise Azure access" },
    tone: "agents-scene-tech",
  },
];

const providerBadgeClass = (provider: string) => {
  const map: Record<string, string> = {
    openai: "agents-badge agents-badge-chat",
    anthropic: "agents-badge agents-badge-master",
    ollama: "agents-badge agents-badge-beta",
    azure: "agents-badge",
  };
  return map[provider] ?? "agents-badge";
};

const emptyInference = {
  temperature: "",
  top_p: "",
  top_k: "",
  max_tokens: "",
  frequency_penalty: "",
  presence_penalty: "",
  repetition_penalty: "",
  stop: "",
  seed: "",
  timeout: "",
  num_ctx: "",
};

const emptyForm = {
  name: "",
  provider: "ollama",
  model_id: "",
  base_url: "",
  context_window: "",
  cost_per_1k_input: "",
  cost_per_1k_output: "",
  is_default: false,
  ...emptyInference,
};

type FormState = typeof emptyForm;

function numOrEmpty(v: number | null | undefined): string {
  return v != null ? String(v) : "";
}

function inferenceFromConfig(cfg: Config): Partial<FormState> {
  const p = cfg.inference_params || {};
  return {
    temperature: numOrEmpty(p.temperature),
    top_p: numOrEmpty(p.top_p),
    top_k: numOrEmpty(p.top_k),
    max_tokens: numOrEmpty(p.max_tokens),
    frequency_penalty: numOrEmpty(p.frequency_penalty),
    presence_penalty: numOrEmpty(p.presence_penalty),
    repetition_penalty: numOrEmpty(p.repetition_penalty),
    stop: p.stop?.length ? p.stop.join(", ") : "",
    seed: numOrEmpty(p.seed),
    timeout: numOrEmpty(p.timeout),
    num_ctx: numOrEmpty(p.num_ctx),
  };
}

function buildInferencePayload(form: FormState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const numFields = [
    "temperature", "top_p", "top_k", "max_tokens",
    "frequency_penalty", "presence_penalty", "repetition_penalty",
    "seed", "timeout", "num_ctx",
  ] as const;
  for (const key of numFields) {
    const raw = form[key].trim();
    if (raw) out[key] = Number(raw);
  }
  const stopRaw = form.stop.trim();
  if (stopRaw) {
    out.stop = stopRaw.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return out;
}

function inferenceSummary(p?: InferenceParams): string | null {
  if (!p) return null;
  const parts: string[] = [];
  if (p.temperature != null) parts.push(`T=${p.temperature}`);
  if (p.top_p != null) parts.push(`top_p=${p.top_p}`);
  if (p.max_tokens != null) parts.push(`max=${p.max_tokens}`);
  return parts.length ? parts.join(" · ") : null;
}

export default function ModelsPage() {
  const { lang } = useLangStore();
  const m = translations.models;
  const c = translations.common;
  const chatT = translations.chat;

  const [models, setModels] = useState<Model[]>([]);
  const [configs, setConfigs] = useState<Config[]>([]);
  const [ollamaOnline, setOllamaOnline] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testingForm, setTestingForm] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>("all");

  const load = useCallback(async () => {
    try {
      const [{ data: available }, { data: cfgList }] = await Promise.all([
        modelsApi.listAvailable(),
        modelsApi.listConfigs(),
      ]);
      setModels(available);
      setOllamaOnline(available.some((x: Model) => x.provider === "ollama"));
      setConfigs(cfgList);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load");
    }
  }, [lang]);

  useEffect(() => { load(); }, [load]);

  const filteredConfigs = useMemo(() => {
    let list = [...configs];
    if (providerFilter !== "all") list = list.filter((cfg) => cfg.provider === providerFilter);
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (cfg) =>
          cfg.name.toLowerCase().includes(q) ||
          cfg.model_id.toLowerCase().includes(q) ||
          cfg.provider.toLowerCase().includes(q),
      );
    }
    return list.sort((a, b) => (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0));
  }, [configs, providerFilter, searchQuery]);

  const modelKeyOptions = useMemo<ModelKeyOption[]>(
    () => configs.map((cfg) => ({
      provider: cfg.provider,
      model_id: cfg.model_id,
      label: `${cfg.name} (${cfg.provider}/${cfg.model_id})`,
    })),
    [configs],
  );

  const filteredModels = useMemo(() => {
    let list = [...models];
    if (providerFilter !== "all") list = list.filter((mod) => mod.provider === providerFilter);
    const q = searchQuery.trim().toLowerCase();
    if (q) list = list.filter((mod) => mod.model.toLowerCase().includes(q) || mod.provider.toLowerCase().includes(q));
    return list;
  }, [models, providerFilter, searchQuery]);

  const sceneModels = (provider: ProviderFilter) => {
    const source = provider === "all" ? models : models.filter((mod) => mod.provider === provider);
    return source.slice(0, 4).map((mod) => mod.model);
  };

  const modelInitial = (name: string) => (name.trim()[0] || "M").toUpperCase();

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm);
    setShowModal(true);
  };

  const openEdit = (cfg: Config) => {
    setEditingId(cfg.id);
    setForm({
      name: cfg.name,
      provider: cfg.provider,
      model_id: cfg.model_id,
      base_url: cfg.base_url || "",
      context_window: cfg.context_window != null ? String(cfg.context_window) : "",
      cost_per_1k_input: cfg.cost_per_1k_input != null ? String(cfg.cost_per_1k_input) : "",
      cost_per_1k_output: cfg.cost_per_1k_output != null ? String(cfg.cost_per_1k_output) : "",
      is_default: cfg.is_default,
      ...emptyInference,
      ...inferenceFromConfig(cfg),
    });
    setShowModal(true);
  };

  const buildPayload = () => {
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      provider: form.provider,
      model_id: form.model_id.trim(),
      is_default: form.is_default,
      inference_params: buildInferencePayload(form),
    };
    if (form.base_url.trim()) payload.base_url = form.base_url.trim();
    if (form.context_window.trim()) payload.context_window = Number(form.context_window);
    if (form.cost_per_1k_input.trim()) payload.cost_per_1k_input = Number(form.cost_per_1k_input);
    if (form.cost_per_1k_output.trim()) payload.cost_per_1k_output = Number(form.cost_per_1k_output);
    return payload;
  };

  const saveConfig = async () => {
    if (!form.name.trim() || !form.model_id.trim()) {
      toast.error(m.nameRequired[lang]);
      return;
    }
    setSaving(true);
    try {
      const payload = buildPayload();
      if (editingId) {
        await modelsApi.updateConfig(editingId, payload);
        toast.success(m.updateOk[lang]);
      } else {
        await modelsApi.createConfig(payload);
        toast.success(m.createOk[lang]);
      }
      setShowModal(false);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? m.saveFailed[lang]);
    } finally {
      setSaving(false);
    }
  };

  const deleteConfig = async (cfg: Config) => {
    if (!confirm(m.deleteConfirm[lang])) return;
    try {
      await modelsApi.deleteConfig(cfg.id);
      toast.success(m.deleteOk[lang]);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? m.deleteFailed[lang]);
    }
  };

  const setDefault = async (cfg: Config) => {
    if (cfg.is_default) return;
    try {
      await modelsApi.setDefaultConfig(cfg.id);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? m.saveFailed[lang]);
    }
  };

  const showTestResult = (data: { ok: boolean; message?: string; latency_ms?: number; preview?: string | null }) => {
    if (data.ok) {
      const extra = data.preview ? `: ${String(data.preview).slice(0, 80)}` : "";
      toast.success(`${m.testOk[lang]} (${data.latency_ms ?? 0}ms)${extra}`);
    } else {
      toast.error(data.message ? `${m.testFail[lang]}: ${data.message}` : m.testFail[lang]);
    }
  };

  const testConfig = async (cfg: Config) => {
    setTestingId(cfg.id);
    try {
      const { data } = await modelsApi.testConfigConnection(cfg.id);
      showTestResult(data);
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
      const detail = res?.data?.detail;
      if (res?.status === 404 && (detail === "Not Found" || !detail)) {
        toast.error(
          lang === "zh"
            ? "测试接口未找到，请重启后端（start_backend.ps1）后重试"
            : "Test API not found — restart the backend and try again",
        );
      } else {
        toast.error(detail ? `${m.testFail[lang]}: ${detail}` : m.testFail[lang]);
      }
    } finally {
      setTestingId(null);
    }
  };

  const testFormConnection = async () => {
    if (!form.provider.trim() || !form.model_id.trim()) {
      toast.error(m.testNeedFields[lang]);
      return;
    }
    setTestingForm(true);
    try {
      const { data } = await modelsApi.testConnection({
        provider: form.provider,
        model_id: form.model_id.trim(),
        base_url: form.base_url.trim() || undefined,
      });
      showTestResult(data);
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
      const detail = res?.data?.detail;
      if (res?.status === 404 && (detail === "Not Found" || !detail)) {
        toast.error(
          lang === "zh"
            ? "测试接口未找到，请重启后端（start_backend.ps1）后重试"
            : "Test API not found — restart the backend and try again",
        );
      } else {
        toast.error(detail ? `${m.testFail[lang]}: ${detail}` : m.testFail[lang]);
      }
    } finally {
      setTestingForm(false);
    }
  };

  const infField = (key: keyof typeof emptyInference, placeholder: string, step = "any") => (
    <input
      type="number"
      step={step}
      placeholder={placeholder}
      className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
      value={form[key]}
      onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
    />
  );

  const providerFilters: ProviderFilter[] = ["all", ...PROVIDERS];

  return (
    <div className="agents-hub">
      <div className="agents-hub-header">
        <div>
          <h1>{m.title[lang]}</h1>
          <p>{m.subtitle[lang]}</p>
        </div>
        <div className="agents-hub-actions">
          <button type="button" onClick={openCreate} className="agents-btn-primary">
            <Plus className="h-4 w-4" /> {m.newConfig[lang]}
          </button>
        </div>
      </div>

      {ollamaOnline && (
        <div className="hub-status-banner">
          <Server className="h-4 w-4" />
          {m.serverOnline[lang]}
        </div>
      )}

      <div className="agents-hub-toolbar">
        <div className="agents-hub-search">
          <Search className="h-4 w-4 shrink-0 theme-muted" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={m.searchPlaceholder[lang]}
          />
        </div>
      </div>

      <section className="hub-section">
        <div className="agents-card p-5">
          <ModelKeysPanel lang={lang} modelOptions={modelKeyOptions} />
        </div>
      </section>

      {models.length > 0 && (
        <section className="agents-featured">
          <h2 className="agents-featured-title">{m.featuredTitle[lang]}</h2>
          <CapsuleScrollRow
            scrollStep={268}
            scrollLeftLabel={chatT.scrollLeft[lang]}
            scrollRightLabel={chatT.scrollRight[lang]}
            innerClassName="agents-featured-scroll"
          >
            {PROVIDER_SCENES.map((scene) => {
              const items = sceneModels(scene.id);
              return (
                <button
                  key={scene.id}
                  type="button"
                  className={`agents-scene-card ${scene.tone}`}
                  onClick={() => setProviderFilter(scene.id)}
                >
                  <div>
                    <h3>{lang === "zh" ? scene.title.zh : scene.title.en}</h3>
                    <p>{lang === "zh" ? scene.subtitle.zh : scene.subtitle.en}</p>
                  </div>
                  <ul className="agents-scene-list">
                    {items.length > 0 ? (
                      items.map((name) => <li key={name}>{name}</li>)
                    ) : (
                      <li>{lang === "zh" ? "暂无模型" : "No models"}</li>
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
          {providerFilters.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setProviderFilter(id)}
              className={`agents-filter-pill${providerFilter === id ? " agents-filter-pill-active" : ""}`}
            >
              {id === "all" ? m.filterAll[lang] : id}
            </button>
          ))}
        </CapsuleScrollRow>
      </div>

      <section className="hub-section">
        <h2 className="hub-section-title">{m.activeConfigs[lang]}</h2>
        {configs.length === 0 ? (
          <div className="agents-empty py-12">
            <Cpu className="mb-4 h-10 w-10 opacity-40" />
            <p>{lang === "zh" ? "暂无配置，点击「新建配置」添加。" : "No configs yet. Click New Config."}</p>
          </div>
        ) : filteredConfigs.length === 0 ? (
          <p className="text-sm theme-muted">{lang === "zh" ? "没有匹配的配置" : "No matching configs"}</p>
        ) : (
          <div className="agents-grid">
            {filteredConfigs.map((cfg) => {
              const summary = inferenceSummary(cfg.inference_params);
              return (
                <article key={cfg.id} className="agents-card">
                  <div className="agents-card-top">
                    <div className={`agents-avatar ${agentAvatarTone(cfg.id)}`} aria-hidden>
                      {modelInitial(cfg.model_id)}
                    </div>
                    <div className="agents-card-head">
                      <div className="agents-card-title-row">
                        <h3 title={cfg.model_id}>{cfg.model_id}</h3>
                        {cfg.is_default && (
                          <span className="agents-badge agents-badge-chat">
                            <CheckCircle className="mr-0.5 inline h-3 w-3" />
                            {m.defaultBadge[lang]}
                          </span>
                        )}
                      </div>
                      <p className="agents-card-role">{cfg.name}</p>
                    </div>
                  </div>
                  <div className="agents-card-tags">
                    <span className={providerBadgeClass(cfg.provider)}>{cfg.provider}</span>
                    {cfg.context_window && (
                      <span className="agents-tag">{(cfg.context_window / 1000).toFixed(0)}K {m.contextWindow[lang]}</span>
                    )}
                    {summary && <span className="agents-tag">{summary}</span>}
                  </div>
                  {cfg.base_url && (
                    <p className="agents-card-desc truncate">{cfg.base_url}</p>
                  )}
                  <div className="agents-card-footer">
                    <span className="agents-card-meta">{cfg.provider}/{cfg.model_id}</span>
                    <div className="agents-card-actions">
                      <button
                        type="button"
                        onClick={() => testConfig(cfg)}
                        disabled={testingId === cfg.id}
                        className="agents-icon-btn"
                        title={m.testConnection[lang]}
                      >
                        {testingId === cfg.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5" />}
                      </button>
                      {!cfg.is_default && (
                        <button type="button" onClick={() => setDefault(cfg)} className="agents-icon-btn" title={m.setDefault[lang]}>
                          <Star className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button type="button" onClick={() => openEdit(cfg)} className="agents-icon-btn" title={m.editConfig[lang]}>
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" onClick={() => deleteConfig(cfg)} className="agents-icon-btn agents-icon-btn-danger" title={m.deleteConfig[lang]}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="hub-section">
        <h2 className="hub-section-title">{m.available[lang]}</h2>
        <div className="agents-grid">
          {filteredModels.map((mod, i) => {
            const isCloud = mod.type === "cloud" || mod.model.includes(":cloud");
            return (
              <article key={`${mod.provider}-${mod.model}-${i}`} className="agents-card">
                <div className="agents-card-top">
                  <div className={`agents-avatar ${agentAvatarTone(mod.model)}`} aria-hidden>
                    <Cpu className="h-4 w-4" />
                  </div>
                  <div className="agents-card-head">
                    <div className="agents-card-title-row">
                      <h3 title={mod.model}>{mod.model}</h3>
                      <span className={providerBadgeClass(mod.provider)}>{mod.provider}</span>
                    </div>
                    <p className="agents-card-role">
                      {isCloud ? m.cloudModel[lang] : mod.size_gb != null && mod.size_gb > 0 ? m.localModel[lang] : mod.provider}
                    </p>
                  </div>
                </div>
                <div className="agents-card-tags">
                  {mod.context_window && (
                    <span className="agents-tag">{(mod.context_window / 1000).toFixed(0)}K {m.contextWindow[lang]}</span>
                  )}
                  {mod.size_gb != null && mod.size_gb > 0 && (
                    <span className="agents-tag">{mod.size_gb.toFixed(1)} GB</span>
                  )}
                  {isCloud && (
                    <span className="agents-tag"><Cloud className="mr-0.5 inline h-3 w-3" />{m.cloudModel[lang]}</span>
                  )}
                </div>
                {mod.note && <p className="agents-card-desc">{mod.note}</p>}
              </article>
            );
          })}
        </div>
      </section>

      <section className="hub-section">
        <div className="agents-card p-5">
          <h2 className="hub-section-title">{m.setupTitle[lang]}</h2>
          <div className="space-y-4 text-sm theme-muted">
            <div>
              <p className="mb-1 font-medium theme-text">OpenAI</p>
              <p>{m.setupOpenAI[lang]} <code className="rounded bg-[var(--hover)] px-1 text-[var(--primary)]">OPENAI_API_KEY</code></p>
            </div>
            <div>
              <p className="mb-1 font-medium theme-text">Ollama</p>
              <p>{m.setupOllama[lang]} <code className="rounded bg-[var(--hover)] px-1 text-[var(--primary)]">ollama pull qwen3.6:35b</code></p>
            </div>
          </div>
        </div>
      </section>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="theme-card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <h2 className="mb-4 text-lg font-semibold theme-text">
              {editingId ? m.editConfig[lang] : m.newConfig[lang]}
            </h2>
            <div className="space-y-3">
              <input
                placeholder={m.configName[lang]}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
              <select
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                value={form.provider}
                onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
              >
                {PROVIDERS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <input
                placeholder={m.modelId[lang]}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 font-mono text-sm theme-text"
                value={form.model_id}
                onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}
              />
              <input
                placeholder={m.baseUrl[lang]}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                value={form.base_url}
                onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
              />
              <input
                type="number"
                placeholder={m.contextWindow[lang]}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                value={form.context_window}
                onChange={(e) => setForm((f) => ({ ...f, context_window: e.target.value }))}
              />
              <div className="flex gap-2">
                <input
                  type="number"
                  step="0.00001"
                  placeholder={m.costIn[lang]}
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                  value={form.cost_per_1k_input}
                  onChange={(e) => setForm((f) => ({ ...f, cost_per_1k_input: e.target.value }))}
                />
                <input
                  type="number"
                  step="0.00001"
                  placeholder={m.costOut[lang]}
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                  value={form.cost_per_1k_output}
                  onChange={(e) => setForm((f) => ({ ...f, cost_per_1k_output: e.target.value }))}
                />
              </div>

              <div className="border-t border-[var(--border)] pt-3">
                <h3 className="mb-1 text-sm font-medium theme-text">{m.inferenceTitle[lang]}</h3>
                <p className="mb-3 text-xs theme-muted">{m.inferenceHint[lang]}</p>
                <div className="grid grid-cols-2 gap-2">
                  {infField("temperature", m.temperature[lang], "0.1")}
                  {infField("top_p", m.topP[lang], "0.05")}
                  {infField("top_k", m.topK[lang], "1")}
                  {infField("max_tokens", m.maxTokens[lang], "1")}
                  {infField("frequency_penalty", m.frequencyPenalty[lang], "0.1")}
                  {infField("presence_penalty", m.presencePenalty[lang], "0.1")}
                  {infField("repetition_penalty", m.repetitionPenalty[lang], "0.05")}
                  {infField("seed", m.seed[lang], "1")}
                  {infField("timeout", m.timeout[lang], "1")}
                  {infField("num_ctx", m.numCtx[lang], "512")}
                </div>
                <input
                  placeholder={m.stopSequences[lang]}
                  className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-sm theme-text"
                  value={form.stop}
                  onChange={(e) => setForm((f) => ({ ...f, stop: e.target.value }))}
                />
              </div>

              <label className="flex items-center gap-2 text-sm theme-muted">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
                />
                {m.asDefault[lang]}
              </label>
            </div>
            <div className="mt-6 flex justify-between gap-3">
              <button
                type="button"
                onClick={testFormConnection}
                disabled={testingForm || saving}
                className="agents-btn-secondary agents-btn-teal disabled:opacity-50"
              >
                {testingForm ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
                {m.testConnection[lang]}
              </button>
              <div className="flex gap-3">
                <button type="button" onClick={() => setShowModal(false)} className="text-sm theme-muted">{c.cancel[lang]}</button>
                <button type="button" onClick={saveConfig} disabled={saving} className="agents-btn-primary disabled:opacity-50">
                  {saving ? c.loading[lang] : c.save[lang]}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
