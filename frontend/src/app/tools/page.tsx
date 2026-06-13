"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Zap, Globe, Calculator, Link2, Clock, Search, MousePointer2 } from "lucide-react";
import { toolsApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { agentAvatarTone } from "@/lib/agentCatalog";
import CapsuleScrollRow from "@/components/CapsuleScrollRow";

interface Tool { name: string; description: string; }

type ToolCategory = "all" | "search" | "compute" | "network" | "utility";

const toolIcons: Record<string, React.FC<{ className?: string }>> = {
  web_search: Globe,
  calculator: Calculator,
  http_request: Link2,
  get_datetime: Clock,
  datetime: Clock,
  desktop_list_demos: MousePointer2,
  desktop_replay: MousePointer2,
  desktop_capture: MousePointer2,
};

const TOOL_SCENES: Array<{
  id: ToolCategory;
  title: { zh: string; en: string };
  subtitle: { zh: string; en: string };
  tone: string;
  match: (name: string) => boolean;
}> = [
  {
    id: "search",
    title: { zh: "检索类", en: "Search" },
    subtitle: { zh: "联网搜索与信息获取", en: "Web search and retrieval" },
    tone: "agents-scene-tech",
    match: (n) => n.includes("search"),
  },
  {
    id: "compute",
    title: { zh: "计算类", en: "Compute" },
    subtitle: { zh: "数值计算与逻辑处理", en: "Math and logic" },
    tone: "agents-scene-data",
    match: (n) => n.includes("calc"),
  },
  {
    id: "network",
    title: { zh: "网络类", en: "Network" },
    subtitle: { zh: "HTTP 请求与外部 API", en: "HTTP and external APIs" },
    tone: "agents-scene-finance",
    match: (n) => n.includes("http"),
  },
  {
    id: "utility",
    title: { zh: "实用类", en: "Utility" },
    subtitle: { zh: "时间日期等基础能力", en: "Date, time, and basics" },
    tone: "agents-scene-content",
    match: (n) => n.includes("time") || n.includes("date") || n.includes("desktop"),
  },
];

const CATEGORY_FILTERS: ToolCategory[] = ["all", "search", "compute", "network", "utility"];

function toolCategory(name: string): ToolCategory {
  for (const scene of TOOL_SCENES) {
    if (scene.match(name)) return scene.id;
  }
  return "utility";
}

export default function ToolsPage() {
  const { lang } = useLangStore();
  const t = translations.tools;
  const c = translations.common;
  const chatT = translations.chat;

  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<ToolCategory>("all");

  useEffect(() => {
    toolsApi.list()
      .then(({ data }) => setTools(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filteredTools = useMemo(() => {
    let list = [...tools];
    if (categoryFilter !== "all") {
      list = list.filter((tool) => toolCategory(tool.name) === categoryFilter);
    }
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (tool) =>
          tool.name.toLowerCase().includes(q) ||
          tool.description.toLowerCase().includes(q),
      );
    }
    return list.sort((a, b) => a.name.localeCompare(b.name));
  }, [tools, categoryFilter, searchQuery]);

  const sceneTools = (cat: ToolCategory) => {
    const list = cat === "all" ? tools : tools.filter((tool) => toolCategory(tool.name) === cat);
    return list.slice(0, 4);
  };

  const categoryLabel = (id: ToolCategory) => {
    if (id === "all") return lang === "zh" ? "全部" : "All";
    const scene = TOOL_SCENES.find((s) => s.id === id);
    return scene ? (lang === "zh" ? scene.title.zh : scene.title.en) : id;
  };

  const toolInitial = (name: string) => (name.trim()[0] || "T").toUpperCase();

  return (
    <div className="agents-hub">
      <div className="agents-hub-header">
        <div>
          <h1>{t.title[lang]}</h1>
          <p>{t.subtitle[lang]}</p>
        </div>
        <div className="agents-hub-actions">
          <Link href="/agents" className="agents-btn-secondary">
            {lang === "zh" ? "绑定到智能体" : "Assign to Agents"}
          </Link>
        </div>
      </div>

      <div className="agents-hub-toolbar">
        <div className="agents-hub-search">
          <Search className="h-4 w-4 shrink-0 theme-muted" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t.searchPlaceholder[lang]}
          />
        </div>
      </div>

      {!loading && tools.length > 0 && (
        <section className="agents-featured">
          <h2 className="agents-featured-title">{t.featuredTitle[lang]}</h2>
          <CapsuleScrollRow
            scrollStep={268}
            scrollLeftLabel={chatT.scrollLeft[lang]}
            scrollRightLabel={chatT.scrollRight[lang]}
            innerClassName="agents-featured-scroll"
          >
            {TOOL_SCENES.map((scene) => {
              const items = sceneTools(scene.id);
              return (
                <button
                  key={scene.id}
                  type="button"
                  className={`agents-scene-card ${scene.tone}`}
                  onClick={() => setCategoryFilter(scene.id)}
                >
                  <div>
                    <h3>{lang === "zh" ? scene.title.zh : scene.title.en}</h3>
                    <p>{lang === "zh" ? scene.subtitle.zh : scene.subtitle.en}</p>
                  </div>
                  <ul className="agents-scene-list">
                    {items.length > 0 ? (
                      items.map((item) => <li key={item.name}>{item.name}</li>)
                    ) : (
                      <li>{lang === "zh" ? "暂无工具" : "No tools"}</li>
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
          {CATEGORY_FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setCategoryFilter(id)}
              className={`agents-filter-pill${categoryFilter === id ? " agents-filter-pill-active" : ""}`}
            >
              {categoryLabel(id)}
            </button>
          ))}
        </CapsuleScrollRow>
      </div>

      {loading ? (
        <div className="theme-muted text-sm">{c.loading[lang]}</div>
      ) : filteredTools.length === 0 ? (
        <div className="agents-empty">
          <Zap className="mb-4 h-12 w-12 opacity-40" />
          <p>{lang === "zh" ? "没有匹配的工具" : "No matching tools"}</p>
        </div>
      ) : (
        <div className="agents-grid">
          {filteredTools.map((tool) => {
            const Icon = toolIcons[tool.name] || Zap;
            return (
              <article key={tool.name} className="agents-card">
                <div className="agents-card-top">
                  <div className={`agents-avatar ${agentAvatarTone(tool.name)}`} aria-hidden>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="agents-card-head">
                    <div className="agents-card-title-row">
                      <h3 title={tool.name}>{tool.name}</h3>
                      <span className="agents-badge agents-badge-beta">{t.builtin[lang]}</span>
                    </div>
                    <p className="agents-card-role">{categoryLabel(toolCategory(tool.name))}</p>
                  </div>
                </div>
                <p className="agents-card-desc">{tool.description}</p>
                <div className="agents-card-footer">
                  <span className="agents-card-meta">{toolInitial(tool.name)} · {tool.name}</span>
                  <Link href="/agents" className="agents-summon-btn">
                    {lang === "zh" ? "去绑定" : "Assign"}
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <section className="hub-section">
        <div className="agents-empty py-10">
          <Zap className="mb-3 h-8 w-8 opacity-40" />
          <p className="font-medium theme-text">{t.customTitle[lang]}</p>
          <p className="mt-1 text-sm theme-muted">{t.customDesc[lang]}</p>
        </div>
      </section>
    </div>
  );
}
