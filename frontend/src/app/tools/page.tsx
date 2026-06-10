"use client";

import { useEffect, useState } from "react";
import { Zap, Globe, Calculator, Link2, Clock } from "lucide-react";
import { toolsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

interface Tool { name: string; description: string; }

const toolIcons: Record<string, React.FC<{ className?: string }>> = {
  web_search: Globe,
  calculator: Calculator,
  http_request: Link2,
  get_datetime: Clock,
};

export default function ToolsPage() {
  const { lang } = useLangStore();
  const t = translations.tools;
  const [tools, setTools] = useState<Tool[]>([]);

  useEffect(() => {
    toolsApi.list().then(({ data }) => setTools(data)).catch(() => {});
  }, []);

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">{t.title[lang]}</h1>
        <p className="text-slate-400">{t.subtitle[lang]}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {tools.map((tool) => {
          const Icon = toolIcons[tool.name] || Zap;
          return (
            <div key={tool.name} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5">
              <div className="mb-3 flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-orange-500/10">
                  <Icon className="h-5 w-5 text-orange-400" />
                </div>
                <div>
                  <h3 className="font-semibold text-white">{tool.name}</h3>
                  <span className="rounded bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-500">{t.builtin[lang]}</span>
                </div>
              </div>
              <p className="text-sm text-slate-400 leading-relaxed">{tool.description}</p>
            </div>
          );
        })}
      </div>

      <div className="mt-8 rounded-xl border border-dashed border-[#2d2d4e] p-6 text-center">
        <Zap className="mx-auto mb-3 h-8 w-8 text-slate-600" />
        <p className="text-slate-400 font-medium">{t.customTitle[lang]}</p>
        <p className="text-slate-500 text-sm mt-1">{t.customDesc[lang]}</p>
      </div>
    </div>
  );
}
