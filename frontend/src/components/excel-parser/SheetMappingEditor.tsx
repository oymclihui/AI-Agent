"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Copy,
  MinusCircle,
  PlusCircle,
} from "lucide-react";
import type { FieldRow, SheetMapping } from "@/lib/excelParser/types";
import { mappingToRows, rowsToMapping } from "@/lib/excelParser/utils";
import { useLangStore } from "@/lib/langStore";

export function SheetMappingEditor({
  sheetMapping,
  index,
  isFirst,
  isLast,
  isExpanded,
  onToggleExpand,
  onChange,
  onRemove,
  onCopyFromAbove,
  readOnly = false,
}: {
  sheetMapping: SheetMapping;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onChange: (sm: SheetMapping) => void;
  onRemove?: () => void;
  onCopyFromAbove?: () => void;
  readOnly?: boolean;
}) {
  const { lang } = useLangStore();
  const t = (zh: string, en: string) => (lang === "zh" ? zh : en);

  const [localFields, setLocalFields] = useState<FieldRow[]>(() => {
    const rows = mappingToRows(sheetMapping.field_mapping);
    return rows.length > 0 ? rows : [{ field_name: "", cell_ref: "" }];
  });

  useEffect(() => {
    const rows = mappingToRows(sheetMapping.field_mapping);
    setLocalFields(rows.length > 0 ? rows : [{ field_name: "", cell_ref: "" }]);
  }, [sheetMapping]);

  const updateSheetName = (value: string) => {
    onChange({ ...sheetMapping, sheet_name: value });
  };

  const updateField = (fi: number, key: keyof FieldRow, value: string) => {
    const updated = [...localFields];
    updated[fi] = { ...updated[fi], [key]: value };
    setLocalFields(updated);
    onChange({ ...sheetMapping, field_mapping: rowsToMapping(updated) });
  };

  const addField = () => setLocalFields([...localFields, { field_name: "", cell_ref: "" }]);

  const removeField = (fi: number) => {
    const updated = localFields.filter((_, i) => i !== fi);
    const finalFields = updated.length > 0 ? updated : [{ field_name: "", cell_ref: "" }];
    setLocalFields(finalFields);
    onChange({ ...sheetMapping, field_mapping: rowsToMapping(finalFields) });
  };

  const moveField = (fi: number, dir: -1 | 1) => {
    const ni = fi + dir;
    if (ni < 0 || ni >= localFields.length) return;
    const updated = [...localFields];
    [updated[fi], updated[ni]] = [updated[ni], updated[fi]];
    setLocalFields(updated);
    onChange({ ...sheetMapping, field_mapping: rowsToMapping(updated) });
  };

  const fieldCount = localFields.filter((f) => f.field_name.trim()).length;

  return (
    <div className="theme-card overflow-hidden !p-0">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-black/5 dark:hover:bg-white/5"
        onClick={onToggleExpand}
      >
        <span className="rounded bg-blue-500/15 px-2 py-0.5 font-mono text-xs text-blue-400">#{index + 1}</span>
        <span className="flex-1 font-medium theme-text">{sheetMapping.sheet_name || t("(未命名 Sheet)", "(Unnamed sheet)")}</span>
        <span className="text-xs theme-muted">{fieldCount} {t("个字段", "fields")}</span>
        {isExpanded ? <ChevronUp className="h-4 w-4 theme-muted" /> : <ChevronDown className="h-4 w-4 theme-muted" />}
      </button>

      {isExpanded && (
        <div className="space-y-3 border-t theme-border p-4">
          <div>
            <label className="mb-1 block text-sm theme-muted">{t("工作表名称", "Sheet name")}</label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                value={sheetMapping.sheet_name}
                onChange={(e) => updateSheetName(e.target.value)}
                placeholder={t("例如：BS、Sheet1", "e.g. BS, Sheet1")}
                className="input min-w-[200px] flex-1"
                required
                readOnly={readOnly}
              />
              {!readOnly && !isFirst && onCopyFromAbove && (
                <button type="button" onClick={onCopyFromAbove} className="btn-secondary flex items-center gap-1 px-3 py-2 text-sm">
                  <Copy className="h-3.5 w-3.5" />
                  {t("复制上方映射", "Copy from above")}
                </button>
              )}
              {!readOnly && !isLast && onRemove && (
                <button type="button" onClick={onRemove} className="text-red-400 hover:text-red-300" title={t("删除 Sheet", "Remove sheet")}>
                  <MinusCircle className="h-5 w-5" />
                </button>
              )}
            </div>
            <p className="mt-1 text-xs theme-muted">
              {isFirst
                ? t("首选 Sheet，解析时按顺序匹配", "Primary sheet — matched first in order")
                : t("备选 Sheet，当前面的不存在时使用", "Fallback sheet when earlier sheets are missing")}
            </p>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-sm theme-muted">{t("字段映射", "Field mapping")}</label>
              {!readOnly && (
                <button type="button" onClick={addField} className="btn-primary flex items-center gap-1 px-2 py-1 text-xs">
                  <PlusCircle className="h-3.5 w-3.5" />
                  {t("添加字段", "Add field")}
                </button>
              )}
            </div>
            <div className="overflow-x-auto rounded-lg border theme-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b theme-border bg-black/5 dark:bg-white/5">
                    <th className="px-3 py-2 text-left theme-muted">{t("字段名称", "Field")}</th>
                    <th className="px-3 py-2 text-left theme-muted">{t("单元格", "Cell")}</th>
                    <th className="w-20 px-2 py-2 text-center theme-muted">{t("顺序", "Order")}</th>
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {localFields.map((field, fi) => (
                    <tr key={fi} className="border-t theme-border">
                      <td className="px-3 py-2">
                        <input
                          type="text"
                          value={field.field_name}
                          onChange={(e) => updateField(fi, "field_name", e.target.value)}
                          placeholder={t("字段名", "Field name")}
                          className="input py-1.5"
                          readOnly={readOnly}
                        />
                      </td>
                      <td className="px-3 py-2">
                        <input
                          type="text"
                          value={field.cell_ref}
                          onChange={(e) => updateField(fi, "cell_ref", e.target.value)}
                          placeholder="B3"
                          className="input py-1.5 font-mono"
                          readOnly={readOnly}
                        />
                      </td>
                      <td className="px-2 py-2">
                        {!readOnly && (
                        <div className="flex justify-center gap-1">
                          <button type="button" disabled={fi === 0} onClick={() => moveField(fi, -1)} className="p-1 disabled:opacity-30">
                            <ChevronUp className="h-3.5 w-3.5" />
                          </button>
                          <button type="button" disabled={fi === localFields.length - 1} onClick={() => moveField(fi, 1)} className="p-1 disabled:opacity-30">
                            <ChevronDown className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        {!readOnly && localFields.length > 1 && (
                          <button type="button" onClick={() => removeField(fi)} className="text-red-400">
                            <MinusCircle className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
