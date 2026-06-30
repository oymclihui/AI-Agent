import { create } from "zustand";
import toast from "react-hot-toast";
import { excelParserApi, formatApiError } from "@/lib/api";
import type {
  ErrorLog,
  ExcelTemplate,
  ParseResult,
  ParseStats,
  ParseTask,
  SheetMapping,
} from "./types";
import { errorLogsFromJob, jobToParseTask } from "./utils";

const defaultParseTask: ParseTask = {
  task_id: "",
  status: "idle",
  progress: 0,
  total: 0,
  current_file: "",
  success_count: 0,
  failed_count: 0,
};

const defaultParseResult: ParseResult = { columns: [], data: [], total: 0 };

const defaultStats: ParseStats = { total: 0, success: 0, failed: 0, last_parse_time: null };

interface ExcelParserState {
  templates: ExcelTemplate[];
  currentTemplate: ExcelTemplate | null;
  templatesLoading: boolean;
  parseTask: ParseTask;
  parseResult: ParseResult;
  parseLoading: boolean;
  errorLogs: ErrorLog[];
  logsLoading: boolean;
  stats: ParseStats;
  statsLoading: boolean;

  fetchTemplates: () => Promise<void>;
  createTemplate: (data: { name: string; type: string; sheet_mappings: SheetMapping[]; description?: string }) => Promise<void>;
  updateTemplate: (id: string, data: Partial<{ name: string; type: string; sheet_mappings: SheetMapping[]; description?: string }>) => Promise<void>;
  deleteTemplate: (id: string) => Promise<void>;
  setCurrentTemplate: (template: ExcelTemplate | null) => void;

  startParse: (opts: {
    templateId: string;
    folderPath?: string;
    dataSourceId?: string;
    recursive: boolean;
    outputFilename?: string;
  }) => Promise<void>;
  pollParseStatus: (taskId: string) => Promise<void>;
  fetchParseResult: (taskId: string) => Promise<void>;
  exportFile: (taskId: string, format: "excel" | "csv", filename: string) => Promise<void>;
  fetchErrorLogs: (taskId: string) => Promise<void>;
  fetchStats: () => Promise<void>;
}

export const useExcelParserStore = create<ExcelParserState>((set, get) => ({
  templates: [],
  currentTemplate: null,
  templatesLoading: false,
  parseTask: defaultParseTask,
  parseResult: defaultParseResult,
  parseLoading: false,
  errorLogs: [],
  logsLoading: false,
  stats: defaultStats,
  statsLoading: false,

  fetchTemplates: async () => {
    set({ templatesLoading: true });
    try {
      const { data } = await excelParserApi.listTemplates();
      set({ templates: (data as { items: ExcelTemplate[] }).items || [], templatesLoading: false });
    } catch (err) {
      set({ templatesLoading: false });
      toast.error(formatApiError(err, "Failed to load templates"));
    }
  },

  createTemplate: async (templateData) => {
    try {
      const id = `tpl_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const { data } = await excelParserApi.createTemplate({ ...templateData, id });
      const created = data as ExcelTemplate;
      set((s) => ({ templates: [...s.templates, created] }));
      toast.success(`模板「${created.name}」创建成功`);
    } catch (err) {
      toast.error(formatApiError(err, "创建模板失败"));
      throw err;
    }
  },

  updateTemplate: async (id, templateData) => {
    try {
      const { data } = await excelParserApi.updateTemplate(id, templateData);
      const updated = data as ExcelTemplate;
      set((s) => ({
        templates: s.templates.map((t) => (t.id === id ? updated : t)),
        currentTemplate: s.currentTemplate?.id === id ? updated : s.currentTemplate,
      }));
      toast.success(`模板「${updated.name}」更新成功`);
    } catch (err) {
      toast.error(formatApiError(err, "更新模板失败"));
      throw err;
    }
  },

  deleteTemplate: async (id) => {
    try {
      await excelParserApi.deleteTemplate(id);
      set((s) => ({
        templates: s.templates.filter((t) => t.id !== id),
        currentTemplate: s.currentTemplate?.id === id ? null : s.currentTemplate,
      }));
      toast.success("模板已删除");
    } catch (err) {
      toast.error(formatApiError(err, "删除模板失败"));
      throw err;
    }
  },

  setCurrentTemplate: (template) => set({ currentTemplate: template }),

  startParse: async ({ templateId, folderPath, dataSourceId, recursive, outputFilename }) => {
    set({ parseLoading: true, parseResult: defaultParseResult });
    try {
      const { data } = await excelParserApi.startJob({
        template_id: templateId,
        folder_path: folderPath || undefined,
        data_source_id: dataSourceId || undefined,
        recursive,
        output_filename: outputFilename || undefined,
      });
      const job = data as Parameters<typeof jobToParseTask>[0];
      set({
        parseTask: { ...jobToParseTask(job), status: "running" },
        parseLoading: true,
      });
      toast.success("解析任务已启动");
    } catch (err) {
      set({ parseLoading: false });
      toast.error(formatApiError(err, "启动解析失败"));
      throw err;
    }
  },

  pollParseStatus: async (taskId) => {
    try {
      const { data } = await excelParserApi.getJob(taskId);
      const job = data as Parameters<typeof jobToParseTask>[0];
      const parseTask = jobToParseTask(job);
      set({
        parseTask,
        parseLoading: parseTask.status === "running",
        errorLogs: errorLogsFromJob(job),
      });
      if (parseTask.status === "completed") {
        await get().fetchParseResult(taskId);
        toast.success(`解析完成！成功 ${parseTask.success_count} 个，失败 ${parseTask.failed_count} 个`);
        get().fetchStats();
      } else if (parseTask.status === "failed") {
        toast.error(parseTask.error_message || "解析失败");
      }
    } catch (err) {
      toast.error(formatApiError(err, "查询解析状态失败"));
    }
  },

  fetchParseResult: async (taskId) => {
    try {
      const { data } = await excelParserApi.getJobResult(taskId);
      const result = data as ParseResult;
      set({ parseResult: result });
    } catch (err) {
      const { data } = await excelParserApi.getJob(taskId);
      const job = data as Parameters<typeof jobToParseTask>[0];
      set({
        parseResult: {
          columns: job.columns || [],
          data: job.result_preview || [],
          total: job.row_count || (job.result_preview || []).length,
        },
      });
      toast.error(formatApiError(err, "获取解析结果失败"));
    }
  },

  exportFile: async (taskId, format, filename) => {
    await excelParserApi.exportJob(taskId, format, filename);
    toast.success(`文件「${filename}」导出成功`);
  },

  fetchErrorLogs: async (taskId) => {
    set({ logsLoading: true });
    try {
      const { data } = await excelParserApi.getJob(taskId);
      const job = data as Parameters<typeof jobToParseTask>[0];
      set({ errorLogs: errorLogsFromJob(job), logsLoading: false });
    } catch (err) {
      set({ logsLoading: false });
      toast.error(formatApiError(err, "获取错误日志失败"));
    }
  },

  fetchStats: async () => {
    set({ statsLoading: true });
    try {
      const { data } = await excelParserApi.globalStats();
      set({ stats: data as ParseStats, statsLoading: false });
    } catch {
      set({ statsLoading: false });
    }
  },
}));
