"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { BookOpen, Check, Layers, Pencil, Plus, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import { analysisStudioApi, dataSourcesApi } from "@/lib/api";
import { useClientAuth } from "@/hooks/useClientAuth";

interface DataSourceItem {
  id: string;
  name: string;
  driver: string;
}

interface SectionIn {
  title: string;
  question: string;
  chart: string;
  role?: string;
}

interface TemplateItem {
  id: string;
  name: string;
  keywords: string[];
  sections: SectionIn[];
  enabled: boolean;
}

interface GoldenItem {
  id: string;
  question: string;
  sql_text: string;
  use_count: number;
}

const TABS = [
  { key: "templates", label: "分析模板", icon: Layers },
  { key: "golden", label: "金标问答", icon: Check },
  { key: "semantic", label: "语义模型", icon: BookOpen },
] as const;

const EMPTY_SECTION: SectionIn = { title: "", question: "", chart: "auto", role: "auto" };

export default function TrainingStudioPage() {
  const { ready } = useClientAuth();
  const [sources, setSources] = useState<DataSourceItem[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("templates");

  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [editing, setEditing] = useState<TemplateItem | null>(null);
  const [formName, setFormName] = useState("");
  const [formKeywords, setFormKeywords] = useState("");
  const [formSections, setFormSections] = useState<SectionIn[]>([{ ...EMPTY_SECTION }]);

  const [goldens, setGoldens] = useState<GoldenItem[]>([]);
  const [gQuestion, setGQuestion] = useState("");
  const [gSql, setGSql] = useState("");

  const [presets, setPresets] = useState<{ metrics: string[]; dimensions: string[]; samples: string[] }>({
    metrics: [],
    dimensions: [],
    samples: [],
  });

  useEffect(() => {
    if (!ready) return;
    dataSourcesApi
      .list()
      .then(({ data }) => {
        const items = (data?.items ?? data ?? []) as DataSourceItem[];
        setSources(items);
        if (items.length) setSourceId((prev) => prev || items[0].id);
      })
      .catch(() => toast.error("数据源加载失败"));
  }, [ready]);

  const loadTemplates = useCallback(() => {
    if (!sourceId) return;
    analysisStudioApi
      .templates(sourceId)
      .then(({ data }) => setTemplates(data.items || []))
      .catch(() => toast.error("模板加载失败"));
  }, [sourceId]);

  const loadGoldens = useCallback(() => {
    if (!sourceId) return;
    dataSourcesApi
      .goldenQueries(sourceId)
      .then(({ data }) => setGoldens(data.items || []))
      .catch(() => toast.error("金标加载失败"));
  }, [sourceId]);

  useEffect(() => {
    if (!sourceId) return;
    loadTemplates();
    loadGoldens();
    analysisStudioApi
      .presets(sourceId)
      .then(({ data }) => setPresets({ metrics: data.metrics || [], dimensions: data.dimensions || [], samples: data.samples || [] }))
      .catch(() => undefined);
  }, [sourceId, loadTemplates, loadGoldens]);

  const resetForm = () => {
    setEditing(null);
    setFormName("");
    setFormKeywords("");
    setFormSections([{ ...EMPTY_SECTION }]);
  };

  const startEdit = (tpl: TemplateItem) => {
    setEditing(tpl);
    setFormName(tpl.name);
    setFormKeywords((tpl.keywords || []).join("，"));
    setFormSections(tpl.sections?.length ? tpl.sections.map((s) => ({ ...EMPTY_SECTION, ...s })) : [{ ...EMPTY_SECTION }]);  };

  const saveTemplate = async () => {
    const name = formName.trim();
    const keywords = formKeywords.split(/[，,、]/).map((k) => k.trim()).filter(Boolean);
    const sections = formSections
      .map((s) => ({ title: s.title.trim() || s.question.trim().slice(0, 20), question: s.question.trim(), chart: s.chart || "auto" }))
      .filter((s) => s.question);
    if (!name || !keywords.length || !sections.length) {
      toast.error("请填写模板名、至少一个命中词和一个分析节");
      return;
    }
    try {
      if (editing) {
        await analysisStudioApi.updateTemplate(editing.id, { name, keywords, sections });
        toast.success("模板已更新");
      } else {
        await analysisStudioApi.createTemplate({ data_source_id: sourceId, name, keywords, sections });
        toast.success("模板已创建");
      }
      resetForm();
      loadTemplates();
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "保存失败（需管理员权限）");
    }
  };

  const removeTemplate = async (id: string) => {
    if (!confirm("确认删除该模板？")) return;
    try {
      await analysisStudioApi.deleteTemplate(id);
      toast.success("已删除");
      if (editing?.id === id) resetForm();
      loadTemplates();
    } catch {
      toast.error("删除失败");
    }
  };

  const addGolden = async () => {
    if (!gQuestion.trim() || !gSql.trim()) {
      toast.error("请填写问题和 SQL");
      return;
    }
    try {
      await dataSourcesApi.saveGoldenQuery(sourceId, { question: gQuestion.trim(), sql_text: gSql.trim() });
      toast.success("金标已保存");
      setGQuestion("");
      setGSql("");
      loadGoldens();
    } catch {
      toast.error("保存失败");
    }
  };

  return (
    <div className="mx-auto w-full max-w-6xl p-4 md:p-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold theme-text">训练工作台</h1>
          <p className="mt-1 text-sm theme-muted">配置一句话分析的模板、金标问答与语义口径。</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs theme-muted">数据源</span>
          <select
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            className="rounded-lg border theme-border bg-transparent px-3 py-1.5 text-sm theme-text"
          >
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}（{s.driver}）
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition ${
              tab === key ? "border-blue-400 text-blue-500" : "theme-border theme-muted"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === "templates" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            {templates.length === 0 && (
              <div className="rounded-xl border theme-border theme-surface p-4 text-sm theme-muted">
                还没有模板。新建后，「一句话分析」遇到命中词会按模板逐节出表出图。
              </div>
            )}
            {templates.map((tpl) => (
              <div key={tpl.id} className="rounded-xl border theme-border theme-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="font-medium theme-text">{tpl.name}</h3>
                    <p className="mt-1 text-xs theme-muted">命中词：{(tpl.keywords || []).join("、") || "无"}</p>
                    <p className="mt-1 text-xs theme-muted">{tpl.sections?.length || 0} 个分析节</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button type="button" onClick={() => startEdit(tpl)} className="btn-secondary p-1.5" title="编辑">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" onClick={() => removeTemplate(tpl.id)} className="btn-secondary p-1.5" title="删除">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <ul className="mt-3 space-y-1">
                  {(tpl.sections || []).map((s, i) => (
                    <li key={i} className="text-xs theme-muted">
                      · {s.title || s.question} <span className="opacity-60">（{s.chart || "auto"}）</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="rounded-xl border theme-border theme-surface p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-medium theme-text">{editing ? "编辑模板" : "新建模板"}</h3>
              {editing && (
                <button type="button" onClick={resetForm} className="text-xs theme-muted hover:text-blue-500">
                  取消编辑
                </button>
              )}
            </div>
            <label className="mb-1 block text-xs theme-muted">模板名</label>
            <input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="例如：门店经营日报"
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-1.5 text-sm theme-text"
            />
            <label className="mb-1 block text-xs theme-muted">命中词（逗号分隔，任一命中即启用）</label>
            <input
              value={formKeywords}
              onChange={(e) => setFormKeywords(e.target.value)}
              placeholder="例如：经营日报，门店分析，销售汇总"
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-1.5 text-sm theme-text"
            />

            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs theme-muted">分析节（依次执行）</span>
              <button
                type="button"
                onClick={() => setFormSections((prev) => [...prev, { ...EMPTY_SECTION }])}
                className="inline-flex items-center gap-1 text-xs text-blue-500"
              >
                <Plus className="h-3.5 w-3.5" /> 添加
              </button>
            </div>
            <div className="space-y-3">
              {formSections.map((sec, i) => (
                <div key={i} className="rounded-lg border theme-border p-3">
                  <div className="mb-2 flex gap-2">
                    <input
                      value={sec.title}
                      onChange={(e) =>
                        setFormSections((prev) => prev.map((s, si) => (si === i ? { ...s, title: e.target.value } : s)))
                      }
                      placeholder="标题（如：核心指标）"
                      className="flex-1 rounded-lg border theme-border bg-transparent px-2 py-1 text-xs theme-text"
                    />
                    <select
                      value={sec.chart}
                      onChange={(e) =>
                        setFormSections((prev) => prev.map((s, si) => (si === i ? { ...s, chart: e.target.value } : s)))
                      }
                      className="rounded-lg border theme-border bg-transparent px-2 py-1 text-xs theme-text"
                    >
                      {["auto", "bar", "line", "pie", "table"].map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                    <select
                      value={sec.role}
                      onChange={(e) =>
                        setFormSections((prev) => prev.map((s, si) => (si === i ? { ...s, role: e.target.value } : s)))
                      }
                      className="rounded-lg border theme-border bg-transparent px-2 py-1 text-xs theme-text"
                    >
                      {[["auto", "自动（首节=核心）"], ["kpi", "核心指标（含深度分析）"], ["detail", "明细表格"]].map(([v, l]) => (
                        <option key={v} value={v}>{l}</option>
                      ))}
                    </select>
                    {formSections.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setFormSections((prev) => prev.filter((_, si) => si !== i))}
                        className="text-xs text-red-500"
                      >
                        删除
                      </button>
                    )}
                  </div>
                  <textarea
                    value={sec.question}
                    onChange={(e) =>
                      setFormSections((prev) => prev.map((s, si) => (si === i ? { ...s, question: e.target.value } : s)))
                    }
                    placeholder="这一节要问的问题，可用 {q} 代指用户原话。如：按门店统计销售额、毛利额和客流"
                    rows={2}
                    className="w-full rounded-lg border theme-border bg-transparent px-2 py-1 text-xs theme-text"
                  />
                </div>
              ))}
            </div>

            <button type="button" onClick={saveTemplate} className="btn-primary mt-4 w-full px-4 py-2 text-sm">
              {editing ? "保存修改" : "创建模板"}
            </button>
          </div>
        </div>
      )}

      {tab === "golden" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            {goldens.length === 0 && (
              <div className="rounded-xl border theme-border theme-surface p-4 text-sm theme-muted">还没有金标问答。</div>
            )}
            {goldens.map((g) => (
              <div key={g.id} className="rounded-xl border theme-border theme-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-medium theme-text">{g.question}</h3>
                  <span className="shrink-0 text-xs theme-muted">使用 {g.use_count} 次</span>
                </div>
                <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-black/5 p-2 text-xs theme-muted dark:bg-white/5">
                  {g.sql_text}
                </pre>
              </div>
            ))}
          </div>
          <div className="rounded-xl border theme-border theme-surface p-4">
            <h3 className="mb-3 font-medium theme-text">新增金标</h3>
            <label className="mb-1 block text-xs theme-muted">问题</label>
            <input
              value={gQuestion}
              onChange={(e) => setGQuestion(e.target.value)}
              placeholder="与用户问法一致"
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-1.5 text-sm theme-text"
            />
            <label className="mb-1 block text-xs theme-muted">确认过的 SQL</label>
            <textarea
              value={gSql}
              onChange={(e) => setGSql(e.target.value)}
              rows={8}
              placeholder="SELECT ..."
              className="mb-3 w-full rounded-lg border theme-border bg-transparent px-3 py-1.5 font-mono text-xs theme-text"
            />
            <button type="button" onClick={addGolden} className="btn-primary w-full px-4 py-2 text-sm">
              保存金标
            </button>
          </div>
        </div>
      )}

      {tab === "semantic" && (
        <div className="rounded-xl border theme-border theme-surface p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-medium theme-text">语义模型概览</h3>
            {sourceId && (
              <Link href={`/data-sources/${sourceId}`} className="text-sm text-blue-500 hover:underline">
                去数据源详情页编辑完整语义模型 →
              </Link>
            )}
          </div>
          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border theme-border p-3">
              <div className="text-xs theme-muted">指标</div>
              <div className="mt-1 text-lg font-semibold theme-text">{presets.metrics.length}</div>
            </div>
            <div className="rounded-lg border theme-border p-3">
              <div className="text-xs theme-muted">维度</div>
              <div className="mt-1 text-lg font-semibold theme-text">{presets.dimensions.length}</div>
            </div>
            <div className="rounded-lg border theme-border p-3">
              <div className="text-xs theme-muted">推荐问法</div>
              <div className="mt-1 text-lg font-semibold theme-text">{presets.samples.length}</div>
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h4 className="mb-2 text-sm font-medium theme-text">指标</h4>
              <div className="flex flex-wrap gap-1.5">
                {presets.metrics.map((m) => (
                  <span key={m} className="rounded-full bg-blue-500/10 px-2 py-0.5 text-xs text-blue-500">
                    {m}
                  </span>
                ))}
                {presets.metrics.length === 0 && <span className="text-xs theme-muted">未配置</span>}
              </div>
            </div>
            <div>
              <h4 className="mb-2 text-sm font-medium theme-text">维度</h4>
              <div className="flex flex-wrap gap-1.5">
                {presets.dimensions.map((d) => (
                  <span key={d} className="rounded-full bg-green-500/10 px-2 py-0.5 text-xs text-green-600">
                    {d}
                  </span>
                ))}
                {presets.dimensions.length === 0 && <span className="text-xs theme-muted">未配置</span>}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
