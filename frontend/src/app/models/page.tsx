"use client";

import { useEffect, useState } from "react";
import { Cpu, CheckCircle, Server, Cloud } from "lucide-react";
import { modelsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

interface Model {
  provider: string; model: string; context_window?: number;
  note?: string; size_gb?: number; type?: string;
}
interface Config {
  id: string; name: string; provider: string; model_id: string;
  is_default: boolean; context_window: number | null;
  cost_per_1k_input: number | null; cost_per_1k_output: number | null;
}

const providerColors: Record<string, string> = {
  openai:    "text-green-400 bg-green-400/10 border-green-400/30",
  anthropic: "text-orange-400 bg-orange-400/10 border-orange-400/30",
  ollama:    "text-purple-400 bg-purple-400/10 border-purple-400/30",
  azure:     "text-blue-400 bg-blue-400/10 border-blue-400/30",
};

export default function ModelsPage() {
  const { lang } = useLangStore();
  const m = translations.models;

  const [models, setModels] = useState<Model[]>([]);
  const [configs, setConfigs] = useState<Config[]>([]);
  const [ollamaOnline, setOllamaOnline] = useState(false);

  useEffect(() => {
    modelsApi.listAvailable().then(({ data }) => {
      setModels(data);
      setOllamaOnline(data.some((x: Model) => x.provider === "ollama"));
    });
    modelsApi.listConfigs().then(({ data }) => setConfigs(data));
  }, []);

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">{m.title[lang]}</h1>
        <p className="text-slate-400">{m.subtitle[lang]}</p>
      </div>

      {ollamaOnline && (
        <div className="mb-6 flex items-center gap-2 rounded-xl border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          <Server className="h-4 w-4" />
          {m.serverOnline[lang]}
        </div>
      )}

      {configs.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-white">{m.activeConfigs[lang]}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {configs.map((c) => (
              <div key={c.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${providerColors[c.provider] || "text-slate-400 bg-slate-400/10 border-slate-400/30"}`}>
                    {c.provider}
                  </span>
                  {c.is_default && (
                    <span className="flex items-center gap-1 text-xs text-green-400">
                      <CheckCircle className="h-3 w-3" /> {m.defaultBadge[lang]}
                    </span>
                  )}
                </div>
                <p className="font-medium text-white">{c.model_id}</p>
                <p className="text-xs text-slate-400">{c.name}</p>
                {c.context_window && (
                  <p className="mt-1 text-xs text-slate-500">{(c.context_window / 1000).toFixed(0)}K {m.contextWindow[lang]}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

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
    </div>
  );
}
