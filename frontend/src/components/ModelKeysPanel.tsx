"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { KeyRound } from "lucide-react";
import { authApi, formatApiError } from "@/lib/api";
import { translations } from "@/lib/i18n";

export interface ModelKeyOption {
  provider: string;
  model_id: string;
  label: string;
  base_url?: string | null;
}

interface ModelKeyRow {
  id: string;
  provider: string;
  model_id?: string | null;
  api_key_preview: string;
  base_url?: string | null;
}

interface ModelKeysPanelProps {
  lang: "zh" | "en";
  modelOptions?: ModelKeyOption[];
  className?: string;
}

export function ModelKeysPanel({ lang, modelOptions = [], className = "" }: ModelKeysPanelProps) {
  const s = translations.settings;
  const c = translations.common;

  const [keys, setKeys] = useState<ModelKeyRow[]>([]);
  const [provider, setProvider] = useState("openai");
  const [modelId, setModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const loadKeys = useCallback(() => {
    authApi.listModelKeys()
      .then(({ data }) => setKeys(data as ModelKeyRow[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const providerOptions = useMemo(() => {
    const fromConfigs = [...new Set(modelOptions.map((o) => o.provider))];
    const fromKeys = [...new Set(keys.map((k) => k.provider))];
    const merged = [...new Set([...fromConfigs, ...fromKeys, "openai", "anthropic", "ollama", "azure"])];
    return merged.sort();
  }, [modelOptions, keys]);

  const modelIdOptions = useMemo(
    () => modelOptions.filter((o) => o.provider === provider),
    [modelOptions, provider],
  );

  const saveKey = async () => {
    if (!apiKey.trim()) {
      toast.error(lang === "zh" ? "请填写 API Key" : "Enter API Key");
      return;
    }
    const trimmedBaseUrl = baseUrl.trim();
    if (trimmedBaseUrl.length > 512) {
      toast.error(lang === "zh" ? "Base URL 不能超过 512 个字符" : "Base URL must be at most 512 characters");
      return;
    }
    setSaving(true);
    try {
      await authApi.saveModelKey({
        provider,
        model_id: modelId.trim() || null,
        api_key: apiKey.trim(),
        base_url: trimmedBaseUrl || null,
      });
      setApiKey("");
      toast.success(s.keySaved[lang]);
      loadKeys();
    } catch (err: unknown) {
      toast.error(formatApiError(err, c.saveFailed[lang]));
    } finally {
      setSaving(false);
    }
  };

  const pickModel = (value: string) => {
    if (!value) {
      setModelId("");
      return;
    }
    const opt = modelOptions.find((o) => `${o.provider}::${o.model_id}` === value);
    if (opt) {
      setProvider(opt.provider);
      setModelId(opt.model_id);
      if (opt.base_url) setBaseUrl(opt.base_url);
    }
  };

  return (
    <div className={className}>
      <div className="mb-4 flex items-start gap-3">
        <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-violet-400" />
        <div>
          <h2 className="text-lg font-semibold theme-text">{s.modelKeysTitle[lang]}</h2>
          <p className="mt-1 text-sm theme-muted">{s.modelKeysDesc[lang]}</p>
          {modelOptions.length > 0 && (
            <p className="mt-2 text-xs theme-muted">{s.modelKeysHint[lang]}</p>
          )}
        </div>
      </div>

      {modelOptions.length > 0 && (
        <label className="mb-3 block">
          <span className="mb-1 block text-xs theme-muted">{s.modelKeysPickModel[lang]}</span>
          <select
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
            defaultValue=""
            onChange={(e) => pickModel(e.target.value)}
          >
            <option value="">{s.modelKeysPickPlaceholder[lang]}</option>
            {modelOptions.map((o) => (
              <option key={`${o.provider}::${o.model_id}`} value={`${o.provider}::${o.model_id}`}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="mb-4 grid gap-2 md:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs theme-muted">{s.keyProvider[lang]}</span>
          <select
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              if (!modelOptions.some((o) => o.provider === e.target.value && o.model_id === modelId)) {
                setModelId("");
              }
            }}
          >
            {providerOptions.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs theme-muted">{s.keyModelId[lang]}</span>
          {modelIdOptions.length > 0 ? (
            <select
              className="theme-input w-full rounded-lg border px-3 py-2 text-sm font-mono"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            >
              <option value="">{lang === "zh" ? "（该提供商全部模型）" : "(all models for provider)"}</option>
              {modelIdOptions.map((o) => (
                <option key={o.model_id} value={o.model_id}>{o.model_id}</option>
              ))}
            </select>
          ) : (
            <input
              placeholder={s.keyModelId[lang]}
              className="theme-input w-full rounded-lg border px-3 py-2 text-sm font-mono outline-none focus:border-slate-400"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            />
          )}
        </label>
        <label className="block md:col-span-2">
          <span className="mb-1 block text-xs theme-muted">{s.keyValue[lang]}</span>
          <input
            type="password"
            placeholder={s.keyValue[lang]}
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="block md:col-span-2">
          <span className="mb-1 block text-xs theme-muted">{s.keyBaseUrl[lang]}</span>
          <input
            placeholder={s.keyBaseUrl[lang]}
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm outline-none focus:border-slate-400"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </label>
      </div>
      <button type="button" onClick={() => void saveKey()} disabled={saving} className="theme-btn-primary disabled:opacity-60">
        {saving ? c.loading[lang] : c.save[lang]}
      </button>

      {loading ? (
        <p className="mt-4 text-xs theme-muted">{c.loading[lang]}</p>
      ) : keys.length > 0 ? (
        <ul className="mt-4 space-y-2 text-xs theme-muted">
          {keys.map((k) => (
            <li key={k.id} className="flex items-center justify-between gap-3 rounded border theme-border px-3 py-2">
              <span className="font-mono">
                {k.provider}{k.model_id ? ` / ${k.model_id}` : ""} · {k.api_key_preview}
                {k.base_url ? ` · ${k.base_url}` : ""}
              </span>
              <button
                type="button"
                onClick={() => authApi.deleteModelKey(k.id).then(loadKeys)}
                className="shrink-0 text-red-400"
              >
                {c.delete[lang]}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-xs theme-muted">{s.modelKeysEmpty[lang]}</p>
      )}
    </div>
  );
}
