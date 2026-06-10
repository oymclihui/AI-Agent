"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Search, Plus, Minus } from "lucide-react";
import { clsx } from "clsx";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export interface CatalogNode {
  id: string;
  type: string;
  category: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  properties: Array<Record<string, unknown>>;
}

export interface CatalogCategory {
  id: string;
  name: string;
  color: string;
}

interface NodePaletteProps {
  categories: CatalogCategory[];
  nodes: CatalogNode[];
  onAddNode: (node: CatalogNode) => void;
}

export default function NodePalette({ categories, nodes, onAddNode }: NodePaletteProps) {
  const { lang } = useLangStore();
  const d = translations.designer;
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const filtered = useMemo(() => {
    return nodes.filter((n) => {
      const matchCat = activeCategory === "all" || n.category === activeCategory;
      const q = search.toLowerCase();
      const matchSearch = !q || n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q) || n.description.toLowerCase().includes(q);
      return matchCat && matchSearch;
    });
  }, [nodes, search, activeCategory]);

  const grouped = useMemo(() => {
    const map = new Map<string, CatalogNode[]>();
    for (const n of filtered) {
      if (!map.has(n.category)) map.set(n.category, []);
      map.get(n.category)!.push(n);
    }
    return map;
  }, [filtered]);

  const orderedGroups = useMemo(() => {
    const order = categories.map((c) => c.id);
    return [...grouped.entries()].sort((a, b) => {
      const ia = order.indexOf(a[0]);
      const ib = order.indexOf(b[0]);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
  }, [grouped, categories]);

  useEffect(() => {
    if (search.trim()) {
      setExpanded(new Set([...grouped.keys()]));
    }
  }, [search, grouped]);

  const toggleCategory = (catId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(catId)) next.delete(catId);
      else next.add(catId);
      return next;
    });
  };

  const catMeta = (id: string) => categories.find((c) => c.id === id);
  const catName = (id: string) => catMeta(id)?.name || id;

  const chipStyle = (color: string, active: boolean): CSSProperties | undefined => {
    if (!active) return undefined;
    return {
      ["--cat-fg" as string]: color,
      ["--cat-bg" as string]: `color-mix(in srgb, ${color} 34%, var(--surface))`,
      ["--cat-border" as string]: `color-mix(in srgb, ${color} 62%, var(--border))`,
    };
  };

  return (
    <div className="flex h-full flex-col designer-panel">
      <div className="border-b theme-border p-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider designer-panel-muted">{d.nodeLibrary[lang]}</p>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 designer-panel-muted" />
          <input
            className="theme-input w-full rounded-lg border py-1.5 pl-7 pr-2 text-xs outline-none focus:border-blue-400"
            placeholder={d.searchNodes[lang]}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          <button
            onClick={() => setActiveCategory("all")}
            className={clsx(
              "rounded px-2 py-0.5 text-[10px] transition-colors",
              activeCategory === "all" ? "palette-cat-active palette-cat-all" : "palette-cat-idle",
            )}
          >
            {d.all[lang]} ({nodes.length})
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveCategory(c.id)}
              className={clsx(
                "rounded px-2 py-0.5 text-[10px] transition-colors",
                activeCategory === c.id ? "palette-cat-active" : "palette-cat-idle",
              )}
              style={chipStyle(c.color, activeCategory === c.id)}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {orderedGroups.map(([catId, catNodes]) => {
          const isOpen = expanded.has(catId);
          const meta = catMeta(catId);
          return (
          <div key={catId} className="rounded-lg border theme-border bg-[color-mix(in_srgb,var(--surface)_88%,transparent)]">
            <button
              type="button"
              onClick={() => toggleCategory(catId)}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors rounded-lg hover:bg-[var(--hover)]"
            >
              <span
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded border theme-border designer-panel-muted"
                style={meta?.color ? { borderColor: `${meta.color}88`, color: meta.color } : undefined}
              >
                {isOpen ? <Minus className="h-2.5 w-2.5" /> : <Plus className="h-2.5 w-2.5" />}
              </span>
              <span className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase theme-text">
                {catName(catId)}
              </span>
              <span className="shrink-0 text-[10px] designer-panel-muted">{catNodes.length}</span>
            </button>
            {isOpen && (
            <div className="space-y-1 px-1 pb-1.5">
              {catNodes.map((n) => (
                <div
                  key={n.id}
                  className="flex items-stretch gap-1 rounded-lg border border-transparent transition-colors hover:border-[color-mix(in_srgb,var(--border)_80%,transparent)] hover:bg-[var(--hover)]"
                >
                  <div
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("application/reactflow", JSON.stringify(n));
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    className="flex min-w-0 flex-1 cursor-grab items-start gap-2 px-2 py-1.5 active:cursor-grabbing"
                  >
                    <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full" style={{ background: n.color }} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs theme-text">{n.name}</span>
                      <span className="block truncate text-[10px] designer-panel-muted">{n.description}</span>
                    </span>
                  </div>
                  <button
                    type="button"
                    title={d.addNode[lang]}
                    onClick={(e) => {
                      e.stopPropagation();
                      onAddNode(n);
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                    className="mr-1 flex shrink-0 items-center gap-0.5 self-center rounded-md border theme-border px-1.5 py-1 text-[10px] text-blue-500 transition-colors hover:border-blue-400 hover:bg-blue-500/10"
                  >
                    <Plus className="h-3 w-3" />
                    {d.addNode[lang]}
                  </button>
                </div>
              ))}
            </div>
            )}
          </div>
          );
        })}
        <p className="px-1 pt-2 text-[10px] designer-panel-muted">{d.dragHint[lang]}</p>
      </div>
    </div>
  );
}
