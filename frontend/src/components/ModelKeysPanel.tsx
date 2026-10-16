"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";
import { KeyRound } from "lucide-react";
import { authApi, modelsApi, formatApiError } from "@/lib/api";
import { translations } from "@/lib/i18n";

export interface ModelKeyOption {
  provider: string;
  model_id: string;
  label: string;
  base_url?: string | null;
}

interface CatalogModel {
  id: string;
  label: string;
  enterprise_ready: boolean;
}

interface CatalogProvider {
  id: string;
  name: string;
  default_base_url: string;
  base_urls: string[];
  models: CatalogModel[];
}

interface ModelKeyRow {
  id: string;
  provider: string;
  model_id?: string | null;
  api_key_preview: string;
  base_url?: string | null;
  is_default?: boolean;
}

interface ModelKeysPanelProps {
  lang: "zh" | "en";
  modelOptions?: ModelKeyOption[];
  className?: string;
}

export function ModelKeysPanel({ lang, className = "" }: ModelKeysPanelProps) {
  const s = translations.settings;
  const c = translations.common;
  const zh = lang === "zh";

  const [providers, setProviders] = useState<CatalogProvider[]>([]);
  const [keys, setKeys] = useState<ModelKeyRow[]>([]);
  const [provider, setProvider] = useState("deepseek");
  const [modelId, setModelId] = useState("deepseek-v4-pro");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [apiKey, setApiKey] = useState("");
  const [asDefault, setAsDefault] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const loadKeys = useCallback(() => {
    authApi.listModelKeys()
      .then(({ data }) => setKeys(data as ModelKeyRow[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadKeys();
    modelsApi.listProviders()
      .then(({ data }) => {
        const list = (data?.providers || []) as CatalogProvider[];
        setProviders(list);
        const first = list[0];
        if (first) {
          setProvider(first.id);
          setModelId(first.models[0]?.id || "");
          setBaseUrl(first.default_base_url);
        }
      })
      .catch(() => {});
  }, [loadKeys]);

  const current = useMemo(
    () => providers.find((item) => item.id === provider) || null,
    [providers, provider],
  );

  const pickProvider = (id: string) => {
    const item = providers.find((row) => row.id === id);
    setProvider(id);
    setModelId(item?.models[0]?.id || "");
    setBaseUrl(item?.default_base_url || "");
  };

  const saveKey = async () => {
    if (!apiKey.trim() || !modelId) {
      toast.error(zh ? "请选择模型并填写 API Key" : "Choose a model and enter an API key");
      return;
    }
    setSaving(true);
    try {
      await authApi.saveModelKey({
        provider,
        model_id: modelId,
        api_key: apiKey.trim(),
        base_url: baseUrl,
        is_default: asDefault,
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

  const testKey = async () => {
    if (!apiKey.trim() || !modelId) {
      toast.error(zh ? "请选择模型并填写 API Key" : "Choose a model and enter an API key");
      return;
    }
    setTesting(true);
    try {
      const { data } = await authApi.testModelKey({
        provider,
        model_id: modelId,
        api_key: apiKey.trim(),
        base_url: baseUrl,
      });
      if (data?.ok) toast.success(data.message || (zh ? "连接成功" : "Connected"));
      else toast.error(data?.message || (zh ? "连接失败" : "Connection failed"));
    } catch (err: unknown) {
      toast.error(formatApiError(err, zh ? "连接失败" : "Connection failed"));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={className}>
      <div className="mb-4 flex items-start gap-3">
        <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-violet-400" />
        <div>
          <h2 className="text-lg font-semibold theme-text">{zh ? "我的模型" : "My models"}</h2>
          <p className="mt-1 text-sm theme-muted">
            {zh
              ? "Key 只给你自己的对话、问数，以及绑到你工号的企微和微信。定时报告仍用企业模型。"
              : "Your key is used only for your own chat, data questions, and bound WeCom or WeChat. Scheduled reports stay on the company model."}
          </p>
        </div>
      </div>

      <div className="mb-4 grid gap-2 md:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs theme-muted">{zh ? "厂商" : "Provider"}</span>
          <select
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
            value={provider}
            onChange={(e) => pickProvider(e.target.value)}
          >
            {providers.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs theme-muted">{zh ? "模型" : "Model"}</span>
          <select
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm font-mono"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
          >
            {(current?.models || []).map((row) => (
              <option key={row.id} value={row.id}>
                {row.label} ({row.id}){row.enterprise_ready ? (zh ? " · 企业已接入" : " · company") : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block md:col-span-2">
          <span className="mb-1 block text-xs theme-muted">{zh ? "官方接口" : "Official endpoint"}</span>
          <select
            className="theme-input w-full rounded-lg border px-3 py-2 text-sm font-mono"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          >
            {(current?.base_urls || []).map((url) => (
              <option key={url} value={url}>{url}</option>
            ))}
          </select>
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
      </div>
      <label className="mb-4 flex items-center gap-2 text-sm theme-muted">
        <input type="checkbox" checked={asDefault} onChange={(e) => setAsDefault(e.target.checked)} />
        {zh ? "设为我的默认。未指定模型的新对话会用它" : "Use as my default when no model is selected"}
      </label>
      <div className="flex gap-2">
        <button type="button" onClick={() => void testKey()} disabled={testing || saving} className="rounded-lg border theme-border px-3 py-2 text-sm theme-text disabled:opacity-60">
          {testing ? c.loading[lang] : (zh ? "测试连接" : "Test")}
        </button>
        <button type="button" onClick={() => void saveKey()} disabled={saving} className="theme-btn-primary disabled:opacity-60">
          {saving ? c.loading[lang] : c.save[lang]}
        </button>
      </div>

      {loading ? (
        <p className="mt-4 text-xs theme-muted">{c.loading[lang]}</p>
      ) : keys.length > 0 ? (
        <ul className="mt-4 space-y-2 text-xs theme-muted">
          {keys.map((row) => (
            <li key={row.id} className="flex items-center justify-between gap-3 rounded border theme-border px-3 py-2">
              <span className="font-mono">
                {row.provider}{row.model_id ? ` / ${row.model_id}` : ""} · {row.api_key_preview}
                {row.is_default ? (zh ? " · 我的默认" : " · my default") : ""}
              </span>
              <button
                type="button"
                onClick={() => authApi.deleteModelKey(row.id).then(loadKeys)}
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
