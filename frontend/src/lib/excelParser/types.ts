export interface FieldRow {
  field_name: string;
  cell_ref: string;
}

export interface SheetMapping {
  sheet_name: string;
  field_mapping: Record<string, string> | FieldRow[];
}

export interface ExcelTemplate {
  id: string;
  name: string;
  type: string;
  sheet_mappings: SheetMapping[];
  description?: string | null;
  is_global?: boolean;
  created_at: string;
  updated_at: string;
}

export type ParseStatus = "idle" | "running" | "completed" | "failed";

export interface ParseTask {
  task_id: string;
  status: ParseStatus;
  progress: number;
  total: number;
  current_file: string;
  success_count: number;
  failed_count: number;
  error_message?: string;
}

export interface ParseResult {
  columns: string[];
  data: Record<string, unknown>[];
  total: number;
}

export interface ErrorLog {
  file: string;
  error: string;
  time: string;
}

export interface ParseStats {
  total: number;
  success: number;
  failed: number;
  last_parse_time: string | null;
}

export interface JobApiOut {
  id: string;
  template_id: string;
  data_source_id?: string | null;
  folder_path?: string | null;
  status: string;
  progress: number;
  row_count: number;
  success_count: number;
  failed_count: number;
  output_file?: string | null;
  columns: string[];
  result_preview: Record<string, unknown>[];
  error_message?: string | null;
  error_logs: { file?: string; file_path?: string; error: string; time: string }[];
}
