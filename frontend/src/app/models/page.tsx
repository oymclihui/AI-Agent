"use client";

import { useCallback, useEffect, useState } from "react";
import { Cpu, CheckCircle, Server, Cloud, Plus, Pencil, Trash2, Star } from "lucide-react";
import { modelsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
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

const providerColors: Record<string, string> = {
  openai:    "text-green-400 bg-green-400/10 border-green-400/30",
  anthropic: "text-orange-400 bg-orange-400/10 border-orange-400/30",
  ollama:    "text-purple-400 bg-purple-400/10 border-purple-400/30",
  azure:     "text-blue-400 bg-blue-400/10 border-blue-400/30",
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

  const [models, setModels] = useState<Model[]>([]);
  const [configs, setConfigs] = useState<Config[]>([]);
  const [ollamaOnline, setOllamaOnline] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);

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

  const infField = (key: keyof typeof emptyInference, placeholder: string, step = "any") => (
    <input
      type="number"
      step={step}
      placeholder={placeholder}
      className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
      value={form[key]}
      onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
    />
  );

  return (
    <div className="p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">{m.title[lang]}</h1>
          <p className="text-slate-400">{m.subtitle[lang]}</p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" /> {m.newConfig[lang]}
        </button>
      </div>

      {ollamaOnline && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          <Server className="h-4 w-4" />
          {m.serverOnline[lang]}
        </div>
      )}

      <div className="mb-8">
        <h2 className="mb-4 text-lg font-semibold text-white">{m.activeConfigs[lang]}</h2>
        {configs.length === 0 ? (
          <p className="text-sm text-slate-500">{lang === "zh" ? "暂无配置，点击「新建配置」添加。" : "No configs yet. Click New Config."}</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {configs.map((cfg) => {
              const summary = inferenceSummary(cfg.inference_params);
              return (
                <div key={cfg.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-4">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-xs ${providerColors[cfg.provider] || "text-slate-400 bg-slate-400/10 border-slate-400/30"}`}>
                      {cfg.provider}
                    </span>
                    {cfg.is_default && (
                      <span className="flex items-center gap-1 text-xs text-green-400">
                        <CheckCircle className="h-3 w-3" /> {m.defaultBadge[lang]}
                      </span>
                    )}
                  </div>
                  <p className="font-medium text-white">{cfg.model_id}</p>
                  <p className="text-xs text-slate-400">{cfg.name}</p>
                  {cfg.base_url && (
                    <p className="mt-1 truncate text-[10px] text-slate-500">{cfg.base_url}</p>
                  )}
                  {cfg.context_window && (
                    <p className="mt-1 text-xs text-slate-500">{(cfg.context_window / 1000).toFixed(0)}K {m.contextWindow[lang]}</p>
                  )}
                  {summary && (
                    <p className="mt-1 text-[10px] text-cyan-400/80">{summary}</p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {!cfg.is_default && (
                      <button
                        onClick={() => setDefault(cfg)}
                        className="flex items-center gap-1 rounded-lg bg-amber-600/15 px-2 py-1 text-xs text-amber-300 hover:bg-amber-600/25"
                      >
                        <Star className="h-3 w-3" /> {m.setDefault[lang]}
                      </button>
                    )}
                    <button
                      onClick={() => openEdit(cfg)}
                      className="flex items-center gap-1 rounded-lg bg-slate-600/20 px-2 py-1 text-xs text-slate-300 hover:bg-slate-600/30"
                    >
                      <Pencil className="h-3 w-3" /> {m.editConfig[lang]}
                    </button>
                    <button
                      onClick={() => deleteConfig(cfg)}
                      className="flex items-center gap-1 rounded-lg bg-red-600/15 px-2 py-1 text-xs text-red-400 hover:bg-red-600/25"
                    >
                      <Trash2 className="h-3 w-3" /> {m.deleteConfig[lang]}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <h2 className="mb-4 text-lg font-semibold text-white">{m.available[lang]}</h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {models.map((mod, i) => {
          const isCloud = mod.type === "cloud" || mod.model.includes(":cloud");
          return (
            <div key={i} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-slate-400" />
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${providerColors[mod.provider] || "text-slate-400 bg-slate-400/10 border-slate-400/30"}`}>
                    {mod.provider}
                  </span>
                </div>
                {isCloud ? (
                  <span className="flex items-center gap-1 text-[10px] text-cyan-400"><Cloud className="h-3 w-3" />{m.cloudModel[lang]}</span>
                ) : mod.size_gb != null && mod.size_gb > 0 ? (
                  <span className="flex items-center gap-1 text-[10px] text-purple-400"><Server className="h-3 w-3" />{m.localModel[lang]}</span>
                ) : null}
              </div>
              <p className="font-medium text-white">{mod.model}</p>
              {mod.context_window && (
                <p className="mt-1 text-xs text-slate-500">{(mod.context_window / 1000).toFixed(0)}K {m.contextWindow[lang]}</p>
              )}
              {mod.size_gb != null && mod.size_gb > 0 && (
                <p className="text-xs text-slate-500">{mod.size_gb.toFixed(1)} GB</p>
              )}
              {mod.note && <p className="mt-1 text-xs text-yellow-500">{mod.note}</p>}
            </div>
          );
        })}
      </div>

      <div className="mt-8 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">{m.setupTitle[lang]}</h2>
        <div className="space-y-4 text-sm text-slate-400">
          <div>
            <p className="mb-1 font-medium text-white">OpenAI</p>
            <p>{m.setupOpenAI[lang]} <code className="rounded bg-slate-800 px-1 text-blue-400">OPENAI_API_KEY</code></p>
          </div>
          <div>
            <p className="mb-1 font-medium text-white">Ollama</p>
            <p>{m.setupOllama[lang]} <code className="rounded bg-slate-800 px-1 text-blue-400">ollama pull qwen3.6:35b</code></p>
          </div>
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">
              {editingId ? m.editConfig[lang] : m.newConfig[lang]}
            </h2>
            <div className="space-y-3">
              <input
                placeholder={m.configName[lang]}
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
              <select
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={form.provider}
                onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
              >
                {PROVIDERS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <input
                placeholder={m.modelId[lang]}
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white font-mono"
                value={form.model_id}
                onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}
              />
              <input
                placeholder={m.baseUrl[lang]}
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={form.base_url}
                onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
              />
              <input
                type="number"
                placeholder={m.contextWindow[lang]}
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={form.context_window}
                onChange={(e) => setForm((f) => ({ ...f, context_window: e.target.value }))}
              />
              <div className="flex gap-2">
                <input
                  type="number"
                  step="0.00001"
                  placeholder={m.costIn[lang]}
                  className="flex-1 rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={form.cost_per_1k_input}
                  onChange={(e) => setForm((f) => ({ ...f, cost_per_1k_input: e.target.value }))}
                />
                <input
                  type="number"
                  step="0.00001"
                  placeholder={m.costOut[lang]}
                  className="flex-1 rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={form.cost_per_1k_output}
                  onChange={(e) => setForm((f) => ({ ...f, cost_per_1k_output: e.target.value }))}
                />
              </div>

              <div className="border-t border-[#2d2d4e] pt-3">
                <h3 className="mb-1 text-sm font-medium text-white">{m.inferenceTitle[lang]}</h3>
                <p className="mb-3 text-xs text-slate-500">{m.inferenceHint[lang]}</p>
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
                  className="mt-2 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={form.stop}
                  onChange={(e) => setForm((f) => ({ ...f, stop: e.target.value }))}
                />
              </div>

              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
                />
                {m.asDefault[lang]}
              </label>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowModal(false)} className="text-sm text-slate-400">{c.cancel[lang]}</button>
              <button
                onClick={saveConfig}
                disabled={saving}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? c.loading[lang] : c.save[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
