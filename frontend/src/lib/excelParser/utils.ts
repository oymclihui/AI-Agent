import type { FieldRow, JobApiOut, ParseTask, SheetMapping } from "./types";

export function mappingToRows(mapping: Record<string, string> | FieldRow[]): FieldRow[] {
  if (Array.isArray(mapping)) return mapping;
  return Object.entries(mapping).map(([field_name, cell_ref]) => ({ field_name, cell_ref }));
}

export function rowsToMapping(rows: FieldRow[]): FieldRow[] {
  return rows.filter((row) => row.field_name.trim());
}

export function getSheetNames(t: { sheet_mappings?: SheetMapping[] }): string {
  return (t.sheet_mappings || []).map((sm) => sm.sheet_name).join(" / ");
}

export function getFieldCount(t: { sheet_mappings?: SheetMapping[] }): number {
  if (!t.sheet_mappings?.length) return 0;
  const fm = t.sheet_mappings[0].field_mapping;
  if (Array.isArray(fm)) return fm.filter((x) => x.field_name?.trim()).length;
  return Object.keys(fm || {}).length;
}

export function jobToParseTask(job: JobApiOut): ParseTask {
  const status: ParseTask["status"] =
    job.status === "pending" || job.status === "running"
      ? "running"
      : job.status === "completed"
        ? "completed"
        : job.status === "failed"
          ? "failed"
          : "idle";
  const total = job.success_count + job.failed_count;
  return {
    task_id: job.id,
    status,
    progress: job.progress ?? (status === "completed" ? 100 : 0),
    total: total || job.row_count,
    current_file: "",
    success_count: job.success_count,
    failed_count: job.failed_count,
    error_message: job.error_message ?? undefined,
  };
}

export function errorLogsFromJob(job: JobApiOut) {
  return (job.error_logs || []).map((log) => ({
    file: log.file_path || log.file || "",
    error: log.error,
    time: log.time,
  }));
}
