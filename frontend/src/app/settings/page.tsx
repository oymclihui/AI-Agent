"use client";

import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export default function SettingsPage() {
  const { lang, setLang } = useLangStore();
  const s = translations.settings;
  const c = translations.common;

  return (
    <div className="p-8">
      <h1 className="mb-2 text-2xl font-bold text-white">{s.title[lang]}</h1>
      <p className="mb-8 text-slate-400">{s.subtitle[lang]}</p>

      <div className="mb-6 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
        <h2 className="mb-2 text-lg font-semibold text-white">{s.langTitle[lang]}</h2>
        <p className="mb-4 text-sm text-slate-400">{s.langDesc[lang]}</p>
        <div className="flex rounded-lg overflow-hidden border border-[#2d2d4e] w-fit text-sm">
          <button
            onClick={() => setLang("zh")}
            className={`px-4 py-2 transition-colors ${lang === "zh" ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-white/5"}`}
          >
            {c.chinese[lang]}
          </button>
          <button
            onClick={() => setLang("en")}
            className={`px-4 py-2 border-l border-[#2d2d4e] transition-colors ${lang === "en" ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-white/5"}`}
          >
            {c.english[lang]}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">{s.envVars[lang]}</h2>
        <p className="mb-4 text-sm text-slate-400">{s.envDesc[lang]}</p>
        <div className="space-y-3 font-mono text-sm">
          {[
            { key: "OPENAI_API_KEY", desc: "OpenAI API key for GPT models" },
            { key: "OLLAMA_BASE_URL", desc: "Local Ollama server URL (default: http://localhost:11434)" },
            { key: "VECTOR_STORE_TYPE", desc: "milvus or chroma" },
            { key: "MILVUS_URI", desc: "Remote Milvus server URI" },
            { key: "SECRET_KEY", desc: "Application secret key (min 32 chars)" },
          ].map(({ key, desc }) => (
            <div key={key} className="flex items-start gap-4 rounded-lg border border-[#2d2d4e] p-3">
              <code className="w-48 shrink-0 text-blue-400">{key}</code>
              <span className="mt-0.5 text-xs text-slate-400">{desc}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">{s.apiRef[lang]}</h2>
        <p className="text-sm text-slate-400">
          {s.apiDesc[lang]}{" "}
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
            http://localhost:8000/docs
          </a>
        </p>
      </div>
    </div>
  );
}
