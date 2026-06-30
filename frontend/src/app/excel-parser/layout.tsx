"use client";

import { FileSpreadsheet } from "lucide-react";
import ExcelParserNav from "@/components/excel-parser/ExcelParserNav";
import { useLangStore } from "@/lib/langStore";

export default function ExcelParserLayout({ children }: { children: React.ReactNode }) {
  const { lang } = useLangStore();

  return (
    <div className="mx-auto max-w-6xl flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mb-2 flex items-center gap-2 theme-muted">
        <FileSpreadsheet className="h-5 w-5 text-blue-400" />
        <span className="text-xs uppercase tracking-wide">
          {lang === "zh" ? "Excel 模板批量解析" : "Excel template batch parser"}
        </span>
      </div>
      <ExcelParserNav />
      {children}
    </div>
  );
}
