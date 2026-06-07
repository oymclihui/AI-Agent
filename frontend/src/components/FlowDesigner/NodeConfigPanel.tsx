"use client";

import { useEffect, useState } from "react";
import { Sparkles, Loader2, Save } from "lucide-react";
import { workflowsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";
import type { CatalogNode } from "./NodePalette";

interface NodeConfigPanelProps {
  nodeId: string | null;
  catalogNode: CatalogNode | null;
  label: string;
  config: Record<string, unknown>;
  onLabelChange: (label: string) => void;
  onConfigChange: (config: Record<string, unknown>) => void;
  workflowContext?: Record<string, unknown>;
}

function FieldEditor({
  field,
  value,
  onChange,
  credPlaceholder,
  lang,
}: {
  field: Record<string, unknown>;
  value: unknown;
  onChange: (v: unknown) => void;
  credPlaceholder: string;
  lang: "zh" | "en";
}) {
  const type = field.type as string;
  const rawDisplay = field.displayName;
  const displayName = typeof rawDisplay === "string"
    ? rawDisplay
    : (rawDisplay && typeof rawDisplay === "object"
      ? ((rawDisplay as { zh?: string; en?: string })[lang] || (rawDisplay as { en?: string }).en || String(field.name || ""))
      : String(field.name || ""));
  const options = field.options as Array<{ name: string; value: string }> | undefined;

  if (type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} className="rounded" />
        {displayName}
      </label>
    );
  }

  if (type === "options" && options) {
    return (
      <div>
        <label className="mb-1 block text-[10px] text-slate-500">{displayName}</label>
        <select
          value={String(value ?? field.default ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.name}</option>
          ))}
        </select>
      </div>
    );
  }

  if (type === "json") {
    return (
      <div>
        <label className="mb-1 block text-[10px] text-slate-500">{displayName}</label>
        <textarea
          rows={4}
          value={typeof value === "string" ? value : JSON.stringify(value ?? field.default ?? {}, null, 2)}
          onChange={(e) => {
            try { onChange(JSON.parse(e.target.value)); } catch { onChange(e.target.value); }
          }}
          className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 font-mono text-[11px] text-white focus:border-blue-500 focus:outline-none"
        />
      </div>
    );
  }

  if (type === "code") {
    return (
      <div>
        <label className="mb-1 block text-[10px] text-slate-500">{displayName}</label>
        <textarea
          rows={5}
          value={String(value ?? field.default ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 font-mono text-[11px] text-green-300 focus:border-blue-500 focus:outline-none"
        />
      </div>
    );
  }

  if (type === "number") {
    return (
      <div>
        <label className="mb-1 block text-[10px] text-slate-500">{displayName}</label>
        <input
          type="number"
          value={Number(value ?? field.default ?? 0)}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
        />
      </div>
    );
  }

  if (type === "credentials") {
    return (
      <div>
        <label className="mb-1 block text-[10px] text-slate-500">{displayName}</label>
        <input
          type="password"
          placeholder={credPlaceholder}
          value={typeof value === "object" && value ? String((value as Record<string, string>).accessToken || (value as Record<string, string>).apiKey || "") : ""}
          onChange={(e) => onChange({ accessToken: e.target.value })}
          className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
        />
      </div>
    );
  }

  return (
    <div>
      <label className="mb-1 block text-[10px] text-slate-500">
        {displayName}
        {field.required ? " *" : ""}
      </label>
      <input
        type="text"
        value={String(value ?? field.default ?? "")}
        placeholder={String(field.placeholder || "")}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
      />
      {field.description ? <p className="mt-0.5 text-[10px] text-slate-600">{String(field.description)}</p> : null}
    </div>
  );
}

export default function NodeConfigPanel({
  nodeId,
  catalogNode,
  label,
  config,
  onLabelChange,
  onConfigChange,
  workflowContext = {},
}: NodeConfigPanelProps) {
  const { lang } = useLangStore();
  const d = translations.designer;
  const [localConfig, setLocalConfig] = useState(config);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiExplanation, setAiExplanation] = useState("");

  useEffect(() => {
    setLocalConfig(config);
  }, [config, nodeId]);

  if (!nodeId || !catalogNode) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-xs text-slate-500">
        {d.selectNodeHint[lang]}
      </div>
    );
  }

  const updateField = (name: string, value: unknown) => {
    const next = { ...localConfig, [name]: value };
    setLocalConfig(next);
    onConfigChange(next);
  };

  const applyDefaults = () => {
    const next = { ...localConfig };
    for (const prop of catalogNode.properties) {
      const key = prop.name as string;
      if (next[key] === undefined && prop.default !== undefined) {
        next[key] = prop.default;
      }
    }
    setLocalConfig(next);
    onConfigChange(next);
  };

  const runAiConfig = async () => {
    if (!aiPrompt.trim()) {
      toast.error(d.aiPromptRequired[lang]);
      return;
    }
    setAiLoading(true);
    try {
      const { data } = await workflowsApi.configureNode({
        node_id: catalogNode.id,
        prompt: aiPrompt,
        current_config: localConfig,
        workflow_context: workflowContext,
      });
      setLocalConfig(data.config);
      onConfigChange(data.config);
      setAiExplanation(data.explanation || "");
      toast.success(data.parsed ? d.aiSuccess[lang] : d.aiReview[lang]);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || d.aiFailed[lang]);
    } finally {
      setAiLoading(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="border-b border-[#2d2d4e] p-3">
        <div className="mb-2 flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ background: catalogNode.color }} />
          <span className="text-sm font-semibold text-white">{catalogNode.name}</span>
        </div>
        <p className="text-[10px] text-slate-500">{catalogNode.description}</p>
        <div className="mt-2">
          <label className="mb-1 block text-[10px] text-slate-500">{d.nodeLabel[lang]}</label>
          <input
            value={label}
            onChange={(e) => onLabelChange(e.target.value)}
            className="w-full rounded border border-[#2d2d4e] bg-[#0d0d1a] px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="border-b border-[#2d2d4e] bg-purple-950/20 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-purple-300">
          <Sparkles className="h-3.5 w-3.5" /> {d.aiAssistant[lang]}
        </div>
        <textarea
          rows={3}
          value={aiPrompt}
          onChange={(e) => setAiPrompt(e.target.value)}
          placeholder={d.aiPromptPlaceholder[lang]}
          className="w-full rounded border border-purple-500/30 bg-[#0d0d1a] px-2 py-1.5 text-xs text-white placeholder-slate-600 focus:border-purple-500 focus:outline-none"
        />
        <button
          onClick={runAiConfig}
          disabled={aiLoading}
          className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-purple-600 px-3 py-1.5 text-xs text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {aiLoading ? d.aiGenerating[lang] : d.aiGenerate[lang]}
        </button>
        {aiExplanation && (
          <p className="mt-2 text-[10px] text-slate-400 line-clamp-4">{aiExplanation}</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-slate-400">{d.params[lang]}</p>
          <button onClick={applyDefaults} className="flex items-center gap-1 text-[10px] text-blue-400 hover:text-blue-300">
            <Save className="h-3 w-3" /> {d.fillDefaults[lang]}
          </button>
        </div>
        {catalogNode.properties.length === 0 ? (
          <p className="text-xs text-slate-500">{d.noConfig[lang]}</p>
        ) : (
          catalogNode.properties.map((prop) => (
            <FieldEditor
              key={String(prop.name)}
              field={prop}
              value={localConfig[prop.name as string]}
              onChange={(v) => updateField(prop.name as string, v)}
              credPlaceholder={d.credPlaceholder[lang]}
              lang={lang}
            />
          ))
        )}
      </div>
    </div>
  );
}
