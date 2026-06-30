"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  FileSpreadsheet,
  Pencil,
  Plus,
  PlusCircle,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { SheetMappingEditor } from "@/components/excel-parser/SheetMappingEditor";
import { useExcelParserStore } from "@/lib/excelParser/store";
import type { ExcelTemplate, SheetMapping } from "@/lib/excelParser/types";
import { getFieldCount, getSheetNames } from "@/lib/excelParser/utils";
import { useLangStore } from "@/lib/langStore";

const TYPE_SUGGESTIONS = ["BS", "PL", "CF", "XS"];

function DeleteModal({
  name,
  onConfirm,
  onCancel,
  t,
}: {
  name: string;
  onConfirm: () => void;
  onCancel: () => void;
  t: (zh: string, en: string) => string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="theme-card w-full max-w-md">
        <div className="mb-3 flex items-center gap-2 text-amber-400">
          <AlertTriangle className="h-6 w-6" />
          <h3 className="text-lg font-semibold theme-text">{t("确认删除", "Confirm delete")}</h3>
        </div>
        <p className="text-sm theme-muted">
          {t(`确定要删除模板「${name}」吗？此操作不可撤销。`, `Delete template "${name}"? This cannot be undone.`)}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary px-4 py-2 text-sm">{t("取消", "Cancel")}</button>
          <button type="button" onClick={onConfirm} className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-500">{t("删除", "Delete")}</button>
        </div>
      </div>
    </div>
  );
}

function TemplateEditor({
  template,
  onSave,
  onCancel,
  t,
}: {
  template: ExcelTemplate | null;
  onSave: (data: { name: string; type: string; sheet_mappings: SheetMapping[] }) => void;
  onCancel: () => void;
  t: (zh: string, en: string) => string;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState("BS");
  const [sheetMappings, setSheetMappings] = useState<SheetMapping[]>([{ sheet_name: "", field_mapping: [] }]);
  const [expandedSheets, setExpandedSheets] = useState<Set<number>>(new Set([0]));

  useEffect(() => {
    if (template) {
      setName(template.name);
      setType(template.type);
      const mappings = template.sheet_mappings?.length ? template.sheet_mappings : [{ sheet_name: "", field_mapping: [] }];
      setSheetMappings(mappings);
      setExpandedSheets(new Set([0]));
    } else {
      setName("");
      setType("BS");
      setSheetMappings([{ sheet_name: "", field_mapping: [] }]);
      setExpandedSheets(new Set([0]));
    }
  }, [template]);

  const toggleExpand = (index: number) => {
    setExpandedSheets((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const copyFromAbove = (index: number) => {
    if (index === 0) return;
    const above = sheetMappings[index - 1].field_mapping;
    const updated = [...sheetMappings];
    updated[index] = { ...updated[index], field_mapping: Array.isArray(above) ? [...above] : { ...above } };
    setSheetMappings(updated);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      name: name.trim(),
      type,
      sheet_mappings: sheetMappings.filter((sm) => sm.sheet_name.trim()),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm theme-muted">{t("模板名称", "Template name")}</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="input w-full" required />
        </div>
        <div>
          <label className="mb-1 block text-sm theme-muted">{t("模板类型", "Type")}</label>
          <input type="text" value={type} onChange={(e) => setType(e.target.value)} className="input w-full" list="excel-type-suggestions" />
          <datalist id="excel-type-suggestions">
            {TYPE_SUGGESTIONS.map((s) => <option key={s} value={s} />)}
          </datalist>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold theme-text">{t("工作表与字段映射", "Sheets & field mapping")}</h3>
          <button
            type="button"
            onClick={() => {
              setSheetMappings([...sheetMappings, { sheet_name: "", field_mapping: [] }]);
              setExpandedSheets((prev) => new Set([...prev, sheetMappings.length]));
            }}
            className="btn-primary flex items-center gap-1 px-2 py-1 text-xs"
          >
            <PlusCircle className="h-3.5 w-3.5" />
            {t("添加 Sheet", "Add sheet")}
          </button>
        </div>
        <p className="text-xs theme-muted">
          {t("每个 Sheet 绑定独立字段映射；解析时按顺序匹配首个存在的 Sheet", "Each sheet has its own mapping; first matching sheet wins")}
        </p>
        <div className="space-y-3">
          {sheetMappings.map((sm, idx) => (
            <SheetMappingEditor
              key={idx}
              sheetMapping={sm}
              index={idx}
              isFirst={idx === 0}
              isLast={sheetMappings.length <= 1}
              isExpanded={expandedSheets.has(idx)}
              onToggleExpand={() => toggleExpand(idx)}
              onChange={(newSm) => {
                const updated = [...sheetMappings];
                updated[idx] = newSm;
                setSheetMappings(updated);
              }}
              onRemove={() => setSheetMappings(sheetMappings.filter((_, i) => i !== idx))}
              onCopyFromAbove={() => copyFromAbove(idx)}
            />
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="btn-secondary flex items-center gap-1 px-4 py-2 text-sm">
          <X className="h-4 w-4" />
          {t("取消", "Cancel")}
        </button>
        <button type="submit" className="btn-primary flex items-center gap-1 px-4 py-2 text-sm">
          <Save className="h-4 w-4" />
          {template ? t("保存修改", "Save") : t("创建模板", "Create")}
        </button>
      </div>
    </form>
  );
}

export default function ExcelParserConfigPage() {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const {
    templates,
    currentTemplate,
    templatesLoading,
    fetchTemplates,
    createTemplate,
    updateTemplate,
    deleteTemplate,
    setCurrentTemplate,
  } = useExcelParserStore();

  const [showEditor, setShowEditor] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ExcelTemplate | null>(null);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleSave = async (data: { name: string; type: string; sheet_mappings: SheetMapping[] }) => {
    try {
      if (currentTemplate) await updateTemplate(currentTemplate.id, data);
      else await createTemplate(data);
      setShowEditor(false);
      setCurrentTemplate(null);
    } catch { /* toast in store */ }
  };

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold theme-text">{t("模板配置", "Template config")}</h1>
          <p className="mt-1 text-sm theme-muted">{t("管理 Excel 解析模板，配置 Sheet 与单元格映射", "Manage templates and cell mappings")}</p>
        </div>
        <button
          type="button"
          onClick={() => { setCurrentTemplate(null); setShowEditor(true); }}
          className="btn-primary flex items-center gap-1 px-4 py-2 text-sm"
        >
          <Plus className="h-4 w-4" />
          {t("新建模板", "New template")}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2 space-y-3">
          <h3 className="text-sm font-semibold theme-text">{t("模板列表", "Templates")}</h3>
          {templatesLoading ? (
            <p className="theme-muted text-sm">{t("加载中…", "Loading…")}</p>
          ) : templates.length === 0 ? (
            <div className="theme-card flex flex-col items-center py-12">
              <FileSpreadsheet className="h-12 w-12 theme-muted opacity-40" />
              <p className="mt-3 text-sm theme-muted">{t("暂无模板", "No templates")}</p>
            </div>
          ) : (
            templates.map((tpl) => (
              <div
                key={tpl.id}
                role="button"
                tabIndex={0}
                onClick={() => { setCurrentTemplate(tpl); setShowEditor(true); }}
                onKeyDown={(e) => e.key === "Enter" && (setCurrentTemplate(tpl), setShowEditor(true))}
                className={`theme-card cursor-pointer transition-all ${currentTemplate?.id === tpl.id ? "ring-2 ring-blue-500" : ""}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="font-semibold theme-text truncate">{tpl.name}</h4>
                      <span className="rounded bg-blue-500/15 px-2 py-0.5 text-xs text-blue-400">{tpl.type}</span>
                    </div>
                    <p className="mt-1 text-xs theme-muted">
                      {t("工作表", "Sheets")}: {getSheetNames(tpl)} · {t("字段", "Fields")}: {getFieldCount(tpl)}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button type="button" onClick={(e) => { e.stopPropagation(); setCurrentTemplate(tpl); setShowEditor(true); }} className="rounded p-1.5 theme-muted hover:theme-text">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button type="button" onClick={(e) => { e.stopPropagation(); setDeleteTarget(tpl); }} className="rounded p-1.5 text-red-400 hover:text-red-300">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="lg:col-span-3">
          {showEditor ? (
            <div className="theme-card">
              <h3 className="mb-4 text-lg font-semibold theme-text">
                {currentTemplate ? t("编辑模板", "Edit template") : t("新建模板", "New template")}
              </h3>
              <TemplateEditor
                template={currentTemplate}
                onSave={handleSave}
                onCancel={() => { setShowEditor(false); setCurrentTemplate(null); }}
                t={t}
              />
            </div>
          ) : (
            <div className="theme-card flex flex-col items-center justify-center py-16 theme-muted">
              <FileSpreadsheet className="mb-4 h-16 w-16 opacity-30" />
              <p className="text-sm">{t("选择左侧模板编辑，或创建新模板", "Select a template or create a new one")}</p>
            </div>
          )}
        </div>
      </div>

      {deleteTarget && (
        <DeleteModal
          name={deleteTarget.name}
          onConfirm={async () => {
            try {
              await deleteTemplate(deleteTarget.id);
              setDeleteTarget(null);
              if (currentTemplate?.id === deleteTarget.id) {
                setShowEditor(false);
                setCurrentTemplate(null);
              }
            } catch { /* toast */ }
          }}
          onCancel={() => setDeleteTarget(null)}
          t={t}
        />
      )}
    </>
  );
}
