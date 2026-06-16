"use client";

import { useRef, useState } from "react";
import { Download, FileSpreadsheet, Upload } from "lucide-react";
import toast from "react-hot-toast";
import { clsx } from "clsx";
import { formatApiError, organizationApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

export interface ImportRow {
  row_number: number;
  employee_no: string;
  display_name: string;
  primary_department_name?: string;
  roles: string[];
  status: string;
  message: string;
}

interface ImportPreview {
  total: number;
  ok: number;
  warning: number;
  error: number;
  rows: ImportRow[];
}

interface PermissionImportPanelProps {
  mode: "org" | "delegation";
  roleLabel: (code: string) => string;
  onApplied?: () => void;
  compact?: boolean;
}

export default function PermissionImportPanel({
  mode,
  roleLabel,
  onApplied,
  compact = false,
}: PermissionImportPanelProps) {
  const { lang } = useLangStore();
  const o = translations.organization;
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const statsText = preview
    ? o.importStats[lang]
        .replace("{total}", String(preview.total))
        .replace("{ok}", String(preview.ok))
        .replace("{warn}", String(preview.warning))
        .replace("{err}", String(preview.error))
    : "";

  const downloadTemplate = async (includeCurrent = false) => {
    try {
      if (mode === "org") {
        await organizationApi.downloadPermissionTemplate(includeCurrent);
      } else {
        await organizationApi.downloadDelegationPermissionTemplate();
      }
    } catch (err) {
      toast.error(formatApiError(err, o.loadFail[lang]));
    }
  };

  const uploadFile = async (file: File) => {
    setBusy(true);
    try {
      const { data } =
        mode === "org"
          ? await organizationApi.previewPermissionImport(file)
          : await organizationApi.previewDelegationPermissionImport(file);
      setPreview(data);
    } catch (err) {
      toast.error(formatApiError(err, o.loadFail[lang]));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const applyImport = async () => {
    if (!preview?.rows.length) return;
    setBusy(true);
    try {
      const { data } =
        mode === "org"
          ? await organizationApi.applyPermissionImport(preview.rows)
          : await organizationApi.applyDelegationPermissionImport(preview.rows);
      toast.success(
        lang === "zh"
          ? `${o.importApplied[lang]}：${data.applied} 条已更新`
          : `${o.importApplied[lang]}: ${data.applied} updated`,
      );
      setPreview(null);
      onApplied?.();
    } catch (err) {
      toast.error(formatApiError(err, o.loadFail[lang]));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={clsx("theme-card", compact ? "p-4" : "p-6")}>
      {!compact && (
        <>
          <h2 className="flex items-center gap-2 font-semibold theme-text">
            <FileSpreadsheet className="h-5 w-5" /> {o.importTitle[lang]}
          </h2>
          <p className="mt-2 text-sm theme-muted">{o.importHint[lang]}</p>
        </>
      )}
      {compact && <p className="mb-3 text-sm theme-muted">{o.importHint[lang]}</p>}

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          className="theme-btn-secondary inline-flex items-center gap-2 text-sm"
          onClick={() => void downloadTemplate(false)}
        >
          <Download className="h-4 w-4" /> {o.downloadTemplate[lang]}
        </button>
        {mode === "org" && (
          <button
            type="button"
            className="theme-btn-secondary inline-flex items-center gap-2 text-sm"
            onClick={() => void downloadTemplate(true)}
          >
            <Download className="h-4 w-4" /> {o.exportCurrent[lang]}
          </button>
        )}
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.xls"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void uploadFile(file);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          disabled={busy}
          className="theme-btn-primary inline-flex items-center gap-2 text-sm disabled:opacity-50"
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="h-4 w-4" /> {o.uploadFile[lang]}
        </button>
        {preview && preview.ok > 0 && (
          <button
            type="button"
            disabled={busy}
            className="theme-btn-primary text-sm disabled:opacity-50"
            onClick={() => void applyImport()}
          >
            {o.importApply[lang]} ({preview.ok})
          </button>
        )}
      </div>

      {preview && (
        <div className="mt-4">
          <p className="mb-3 text-sm theme-muted">{statsText}</p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b theme-border text-xs theme-muted">
                  <th className="py-2 pr-3">#</th>
                  <th className="py-2 pr-3">{o.colEmpNo[lang]}</th>
                  <th className="py-2 pr-3">{o.colName[lang]}</th>
                  <th className="py-2 pr-3">{o.colRoles[lang]}</th>
                  <th className="py-2 pr-3">{o.colStatus[lang]}</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.row_number} className="border-b theme-border/60">
                    <td className="py-2 pr-3 theme-muted">{row.row_number}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{row.employee_no}</td>
                    <td className="py-2 pr-3">{row.display_name}</td>
                    <td className="py-2 pr-3">
                      {row.roles.map((code) => (
                        <span key={code} className="mr-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800">
                          {roleLabel(code)}
                        </span>
                      ))}
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={clsx(
                          "rounded px-2 py-0.5 text-xs",
                          row.status === "ok" && "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
                          row.status === "warning" && "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
                          row.status === "error" && "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
                        )}
                      >
                        {row.status === "ok" ? o.importRowOk[lang] : row.status === "warning" ? o.importRowWarn[lang] : o.importRowErr[lang]}
                      </span>
                      <p className="mt-0.5 text-xs theme-muted">{row.message}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
