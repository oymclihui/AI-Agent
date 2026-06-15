"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft, Plus, Play, Trash2, Loader2, Clock, History, Eye, Download, BookOpen,
} from "lucide-react";
import { employeesApi, knowledgeApi, desktopAutomationApi, agentsApi, workflowsApi } from "@/lib/api";
import { resolveRunArtifacts, downloadAuthed, type RunArtifact } from "@/lib/artifacts";
import { getAuthToken } from "@/lib/authStore";
import { ArtifactDownloadButton } from "@/components/ArtifactDownloadButton";
import MarkdownView from "@/components/MarkdownView";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

type TaskType = "agent" | "desktop_automation" | "workflow" | "crew";
interface WorkflowOption { id: string; name: string; }
interface AgentOption { id: string; name: string; }
interface Employee {
  id: string; name: string; title: string | null; description: string | null;
  status: string; agent_id: string; timezone: string;
}

interface Task {
  id: string; name: string; description: string | null; enabled: boolean;
  schedule_type: "cron" | "interval"; cron_expression: string | null;
  interval_seconds: number | null; timezone: string;
  task_type?: string;
  task_config: { prompt?: string; demo_name?: string; demo_id?: string; instructions?: string };
  last_run_at: string | null; next_run_at: string | null; last_status: string | null;
}

interface DemoOption { id: string; name: string; }

interface Run {
  id: string; status: string; triggered_by: string; task_name?: string | null;
  output_data: {
    output?: string;
    artifacts?: Array<{ filename: string; download_url: string }>;
    saved_to_kb_id?: string;
    report_filename?: string;
  } | null;
  error_message: string | null;
  duration_ms: number | null; created_at: string;
}

interface KnowledgeOption { id: string; name: string; }

const CRON_PRESETS = [
  { key: "5min", cron: null, interval: 300, labelKey: "preset5min" as const },
  { key: "hourly", cron: "0 * * * *", interval: null, labelKey: "presetHourly" as const },
  { key: "daily9", cron: "0 9 * * *", interval: null, labelKey: "presetDaily9" as const },
  { key: "weekday9", cron: "0 9 * * 1-5", interval: null, labelKey: "presetWeekday9" as const },
];

export default function EmployeeDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const { lang } = useLangStore();
  const e = translations.employees;
  const c = translations.common;

  const [employee, setEmployee] = useState<Employee | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [tab, setTab] = useState<"tasks" | "runs">("tasks");
  const [loading, setLoading] = useState(true);
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [readyArtifacts, setReadyArtifacts] = useState<RunArtifact[]>([]);
  const [viewRun, setViewRun] = useState<Run | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeOption[]>([]);
  const [saveKbId, setSaveKbId] = useState("");
  const [saveKbName, setSaveKbName] = useState("");
  const [savingKbRunId, setSavingKbRunId] = useState<string | null>(null);
  const [downloadingRunId, setDownloadingRunId] = useState<string | null>(null);
  const [taskForm, setTaskForm] = useState({
    name: "",
    description: "",
    schedule_type: "cron" as "cron" | "interval",
    cron_expression: "0 9 * * 1-5",
    interval_seconds: 3600,
    task_type: "agent" as TaskType,
    prompt: "",
    workflow_id: "",
    crew_agent_ids: [] as string[],
    demo_name: "",
    instructions: "",
    enabled: true,
  });
  const [demoOptions, setDemoOptions] = useState<DemoOption[]>([]);
  const [workflowOptions, setWorkflowOptions] = useState<WorkflowOption[]>([]);
  const [agentOptions, setAgentOptions] = useState<AgentOption[]>([]);

  const load = useCallback(async () => {
    try {
      const [{ data: emp }, { data: t }, { data: r }] = await Promise.all([
        employeesApi.get(id),
        employeesApi.listTasks(id),
        employeesApi.listRuns(id),
      ]);
      setEmployee(emp);
      setTasks(t);
      setRuns(r);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [id, lang]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    knowledgeApi.list().then(({ data }) => {
      setKnowledgeBases((data as KnowledgeOption[]).filter((kb) => kb.id));
    }).catch(() => { /* optional */ });
  }, []);

  useEffect(() => {
    if (!showTaskModal) return;
    desktopAutomationApi.listDemos()
      .then(({ data }) => setDemoOptions((data as DemoOption[]) || []))
      .catch(() => setDemoOptions([]));
    workflowsApi.list()
      .then(({ data }) => setWorkflowOptions((data as WorkflowOption[]) || []))
      .catch(() => setWorkflowOptions([]));
    agentsApi.list(undefined, "usable")
      .then(({ data }) => setAgentOptions((data as AgentOption[]) || []))
      .catch(() => setAgentOptions([]));
  }, [showTaskModal]);

  const createTask = async () => {
    if (!taskForm.name.trim()) return;
    if (taskForm.task_type === "agent" && !taskForm.prompt.trim()) return;
    if (taskForm.task_type === "workflow" && !taskForm.workflow_id) {
      toast.error(e.workflowRequired[lang]);
      return;
    }
    if (taskForm.task_type === "crew" && (!taskForm.prompt.trim() || taskForm.crew_agent_ids.length === 0)) {
      toast.error(e.crewRequired[lang]);
      return;
    }
    if (taskForm.task_type === "desktop_automation" && !taskForm.demo_name.trim()) {
      toast.error(e.demoNameRequired[lang]);
      return;
    }
    try {
      const task_config =
        taskForm.task_type === "desktop_automation"
          ? {
              demo_name: taskForm.demo_name.trim(),
              instructions: taskForm.instructions.trim() || undefined,
              timeout_s: 120,
            }
          : taskForm.task_type === "workflow"
            ? {
                workflow_id: taskForm.workflow_id,
                prompt: taskForm.prompt.trim() || undefined,
              }
            : taskForm.task_type === "crew"
              ? {
                  goal: taskForm.prompt.trim(),
                  agent_ids: taskForm.crew_agent_ids,
                  process: "sequential",
                }
              : { prompt: taskForm.prompt };
      await employeesApi.createTask(id, {
        name: taskForm.name,
        description: taskForm.description,
        schedule_type: taskForm.schedule_type,
        cron_expression: taskForm.schedule_type === "cron" ? taskForm.cron_expression : null,
        interval_seconds: taskForm.schedule_type === "interval" ? taskForm.interval_seconds : null,
        task_type: taskForm.task_type,
        task_config,
        enabled: taskForm.enabled,
      });
      setShowTaskModal(false);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? (lang === "zh" ? "创建失败" : "Create failed"));
    }
  };

  const artifactLabel = (a: RunArtifact) => {
    const lower = a.filename.toLowerCase();
    if (lower.endsWith(".pptx")) return e.downloadPptx[lang];
    if (lower.endsWith(".md")) return e.downloadMd[lang];
    return e.downloadFile[lang];
  };

  const downloadRunReport = async (run: Run) => {
    setDownloadingRunId(run.id);
    try {
      const filename = run.output_data?.report_filename
        ?? `employee_report_${run.id.slice(0, 8)}.md`;
      await downloadAuthed(
        employeesApi.downloadRunUrl(id, run.id),
        filename,
        getAuthToken(),
      );
    } catch {
      toast.error(lang === "zh" ? "下载失败" : "Download failed");
    } finally {
      setDownloadingRunId(null);
    }
  };

  const saveRunToKb = async (run: Run) => {
    if (!saveKbId && !saveKbName.trim()) {
      toast.error(lang === "zh" ? "请选择或填写知识库" : "Select or name a knowledge base");
      return;
    }
    setSavingKbRunId(run.id);
    try {
      const { data } = await employeesApi.saveRunToKnowledge(id, run.id, {
        kb_id: saveKbId || undefined,
        kb_name: saveKbName.trim() || undefined,
      });
      toast.success(`${e.saveToKbOk[lang]} · ${data.knowledge_base_name}`);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? e.saveToKbFail[lang]);
    } finally {
      setSavingKbRunId(null);
    }
  };

  const runTask = async (taskId: string) => {
    setRunningId(taskId);
    setReadyArtifacts([]);
    try {
      const { data: run } = await employeesApi.runTask(id, taskId);
      const artifacts = resolveRunArtifacts(run.output_data);
      if (artifacts.length > 0) {
        setReadyArtifacts(artifacts);
      }
      toast.success(
        artifacts.length > 0 ? e.downloadReady[lang] : e.runOk[lang],
      );
      load();
      setTab("runs");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? e.runFailed[lang]);
    } finally {
      setRunningId(null);
    }
  };

  const deleteTask = async (taskId: string) => {
    if (!confirm(c.delete[lang] + "?")) return;
    await employeesApi.deleteTask(id, taskId);
    load();
  };

  const applyPreset = (preset: typeof CRON_PRESETS[number]) => {
    if (preset.interval) {
      setTaskForm((f) => ({
        ...f, schedule_type: "interval", interval_seconds: preset.interval!, cron_expression: "",
      }));
    } else {
      setTaskForm((f) => ({
        ...f, schedule_type: "cron", cron_expression: preset.cron!, interval_seconds: 3600,
      }));
    }
  };

  const fmtTime = (iso: string | null) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString(lang === "zh" ? "zh-CN" : "en-US");
    } catch {
      return iso;
    }
  };

  if (loading) return <div className="p-8 text-slate-400">{c.loading[lang]}</div>;
  if (!employee) return <div className="p-8 text-slate-400">{c.noData[lang]}</div>;

  return (
    <div className="p-8">
      <Link href="/employees" className="mb-4 inline-flex items-center gap-1 text-sm text-slate-400 hover:text-white">
        <ArrowLeft className="h-4 w-4" /> {e.title[lang]}
      </Link>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">{employee.name}</h1>
        {employee.title && <p className="text-blue-400">{employee.title}</p>}
        <p className="mt-2 text-slate-400">{employee.description}</p>
      </div>

      <div className="mb-4 flex gap-2 border-b border-[#2d2d4e]">
        {(["tasks", "runs"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex items-center gap-1 border-b-2 px-4 py-2 text-sm ${
              tab === t ? "border-teal-500 text-teal-400" : "border-transparent text-slate-400"
            }`}
          >
            {t === "tasks" ? <Clock className="h-4 w-4" /> : <History className="h-4 w-4" />}
            {t === "tasks" ? e.tasks[lang] : e.runs[lang]}
          </button>
        ))}
      </div>

      {tab === "tasks" && (
        <>
          <div className="mb-4 rounded-xl border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-100">
            {e.runsHint[lang]}
          </div>
          <div className="mb-4 flex justify-end">
            <button
              onClick={() => setShowTaskModal(true)}
              className="flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm text-white hover:bg-teal-700"
            >
              <Plus className="h-4 w-4" /> {e.newTask[lang]}
            </button>
          </div>
          {tasks.length === 0 ? (
            <p className="text-slate-500">{e.noTasks[lang]}</p>
          ) : (
            <div className="space-y-3">
              {tasks.map((task) => (
                <div key={task.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <h3 className="font-medium text-white">{task.name}</h3>
                      <p className="mt-0.5 text-[10px] uppercase text-teal-500/80">
                        {task.task_type === "desktop_automation"
                          ? e.taskTypeDesktop[lang]
                          : task.task_type === "workflow"
                            ? e.taskTypeWorkflow[lang]
                            : task.task_type === "crew"
                              ? e.taskTypeCrew[lang]
                              : e.taskTypeAgent[lang]}
                      </p>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-400">
                        {task.task_type === "desktop_automation"
                          ? (task.task_config?.demo_name || task.task_config?.demo_id || "—")
                          : task.task_config?.prompt}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
                        <span>{task.schedule_type === "cron" ? task.cron_expression : `${task.interval_seconds}s`}</span>
                        <span>{e.nextRun[lang]}: {fmtTime(task.next_run_at)}</span>
                        {task.last_status && <span>{e.lastRun[lang]}: {task.last_status}</span>}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => runTask(task.id)}
                        disabled={runningId === task.id}
                        className="flex items-center gap-1 rounded-lg bg-blue-600/20 px-3 py-1.5 text-xs text-blue-400 hover:bg-blue-600/30 disabled:opacity-40"
                      >
                        {runningId === task.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                        {e.runNow[lang]}
                      </button>
                      <button onClick={() => deleteTask(task.id)} className="rounded-lg p-1.5 text-red-400 hover:bg-red-500/10">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "runs" && (
        <>
          {readyArtifacts.length > 0 && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-teal-500/40 bg-teal-500/10 p-4">
              <p className="text-sm text-teal-100">{e.downloadReady[lang]}</p>
              <div className="flex flex-wrap gap-2">
                {readyArtifacts.map((a) => (
                  <ArtifactDownloadButton
                    key={a.download_url}
                    artifact={a}
                    label={`${artifactLabel(a)} · ${a.filename}`}
                  />
                ))}
              </div>
            </div>
          )}
          <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-4">
            <div className="min-w-[200px] flex-1">
              <label className="mb-1 block text-xs text-slate-500">{e.selectKb[lang]}</label>
              <select
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={saveKbId}
                onChange={(ev) => setSaveKbId(ev.target.value)}
              >
                <option value="">{lang === "zh" ? "（新建知识库）" : "(Create new KB)"}</option>
                {knowledgeBases.map((kb) => (
                  <option key={kb.id} value={kb.id}>{kb.name}</option>
                ))}
              </select>
            </div>
            {!saveKbId && (
              <div className="min-w-[200px] flex-1">
                <label className="mb-1 block text-xs text-slate-500">{e.newKbName[lang]}</label>
                <input
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={saveKbName}
                  onChange={(ev) => setSaveKbName(ev.target.value)}
                  placeholder={lang === "zh" ? "数字员工报告" : "Employee reports"}
                />
              </div>
            )}
          </div>
        {runs.length === 0 ? (
          <p className="text-slate-500">{e.noRuns[lang]}</p>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => {
              const artifacts = resolveRunArtifacts(run.output_data);
              return (
              <div key={run.id} className="rounded-lg border border-[#2d2d4e] bg-[#1a1a2e] p-3 text-sm">
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                  {run.task_name && (
                    <span className="text-xs font-medium text-white">{run.task_name}</span>
                  )}
                  <span className={`rounded px-1.5 py-0.5 text-xs ${
                    run.status === "completed" ? "bg-green-500/20 text-green-400" :
                    run.status === "failed" ? "bg-red-500/20 text-red-400" : "bg-slate-500/20 text-slate-400"
                  }`}>{run.status}</span>
                  <span className="text-xs text-slate-500">{run.triggered_by}</span>
                  <span className="text-xs text-slate-500">{fmtTime(run.created_at)}</span>
                  {run.duration_ms != null && <span className="text-xs text-slate-500">{run.duration_ms}ms</span>}
                  {run.output_data?.saved_to_kb_id && (
                    <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-xs text-purple-300">
                      {lang === "zh" ? "已入库" : "In KB"}
                    </span>
                  )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                  {run.output_data?.output && (
                    <>
                      <button
                        type="button"
                        onClick={() => setViewRun(run)}
                        className="inline-flex items-center gap-1 rounded-lg bg-blue-600/20 px-3 py-1.5 text-xs text-blue-300 hover:bg-blue-600/30"
                      >
                        <Eye className="h-3.5 w-3.5" /> {e.viewReport[lang]}
                      </button>
                      <button
                        type="button"
                        onClick={() => downloadRunReport(run)}
                        disabled={downloadingRunId === run.id}
                        className="inline-flex items-center gap-1 rounded-lg bg-slate-600/20 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-600/30 disabled:opacity-50"
                      >
                        {downloadingRunId === run.id
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <Download className="h-3.5 w-3.5" />}
                        {e.downloadReport[lang]}
                      </button>
                      <button
                        type="button"
                        onClick={() => saveRunToKb(run)}
                        disabled={savingKbRunId === run.id}
                        className="inline-flex items-center gap-1 rounded-lg bg-purple-600/20 px-3 py-1.5 text-xs text-purple-200 hover:bg-purple-600/30 disabled:opacity-50"
                      >
                        {savingKbRunId === run.id
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <BookOpen className="h-3.5 w-3.5" />}
                        {e.saveToKb[lang]}
                      </button>
                    </>
                  )}
                  {artifacts.length > 0 && artifacts.map((a) => (
                        <ArtifactDownloadButton
                          key={a.download_url}
                          artifact={a}
                          label={`${artifactLabel(a)} · ${a.filename}`}
                          variant="compact"
                        />
                      ))}
                  </div>
                </div>
                {run.output_data?.output && (
                  <div className="line-clamp-4">
                    <MarkdownView size="xs">{run.output_data.output}</MarkdownView>
                  </div>
                )}
                {run.error_message && <p className="text-red-400">{run.error_message}</p>}
              </div>
            );})}
          </div>
        )}
        </>
      )}

      {viewRun && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border border-[#2d2d4e] bg-[#1a1a2e]">
            <div className="flex items-center justify-between border-b border-[#2d2d4e] px-6 py-4">
              <h2 className="text-lg font-semibold text-white">
                {e.reportTitle[lang]}
                {viewRun.task_name ? ` · ${viewRun.task_name}` : ""}
              </h2>
              <button onClick={() => setViewRun(null)} className="text-sm text-slate-400 hover:text-white">
                {c.cancel[lang]}
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4">
              {viewRun.output_data?.output ? (
                <MarkdownView size="md">{viewRun.output_data.output}</MarkdownView>
              ) : (
                <p className="text-sm text-slate-500">—</p>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-[#2d2d4e] px-6 py-4">
              <button
                onClick={() => downloadRunReport(viewRun)}
                className="rounded-lg bg-slate-700 px-4 py-2 text-sm text-white hover:bg-slate-600"
              >
                {e.downloadReport[lang]}
              </button>
              <button
                onClick={() => { saveRunToKb(viewRun); setViewRun(null); }}
                className="rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-500"
              >
                {e.saveToKb[lang]}
              </button>
            </div>
          </div>
        </div>
      )}

      {showTaskModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">{e.newTask[lang]}</h2>
            <div className="space-y-3">
              <input placeholder={e.taskName[lang]}
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={taskForm.name} onChange={(ev) => setTaskForm((f) => ({ ...f, name: ev.target.value }))} />
              <div className="flex flex-wrap gap-2">
                {CRON_PRESETS.map((p) => (
                  <button key={p.key} type="button" onClick={() => applyPreset(p)}
                    className="rounded border border-[#2d2d4e] px-2 py-1 text-xs text-slate-400 hover:border-teal-500/50 hover:text-teal-400">
                    {e[p.labelKey][lang]}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <select className="rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={taskForm.schedule_type}
                  onChange={(ev) => setTaskForm((f) => ({ ...f, schedule_type: ev.target.value as "cron" | "interval" }))}>
                  <option value="cron">{e.scheduleCron[lang]}</option>
                  <option value="interval">{e.scheduleInterval[lang]}</option>
                </select>
                {taskForm.schedule_type === "cron" ? (
                  <input placeholder={e.cron[lang]}
                    className="flex-1 rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white font-mono"
                    value={taskForm.cron_expression}
                    onChange={(ev) => setTaskForm((f) => ({ ...f, cron_expression: ev.target.value }))} />
                ) : (
                  <input type="number" min={60} placeholder={e.interval[lang]}
                    className="flex-1 rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                    value={taskForm.interval_seconds}
                    onChange={(ev) => setTaskForm((f) => ({ ...f, interval_seconds: Number(ev.target.value) }))} />
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-500">{e.taskType[lang]}</label>
                <select
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={taskForm.task_type}
                  onChange={(ev) => setTaskForm((f) => ({
                    ...f,
                    task_type: ev.target.value as TaskType,
                  }))}
                >
                  <option value="agent">{e.taskTypeAgent[lang]}</option>
                  <option value="workflow">{e.taskTypeWorkflow[lang]}</option>
                  <option value="crew">{e.taskTypeCrew[lang]}</option>
                  <option value="desktop_automation">{e.taskTypeDesktop[lang]}</option>
                </select>
              </div>
              {taskForm.task_type === "desktop_automation" ? (
                <>
                  <div>
                    <label className="mb-1 block text-xs text-slate-500">{e.demoName[lang]}</label>
                    <select
                      className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      value={taskForm.demo_name}
                      onChange={(ev) => setTaskForm((f) => ({ ...f, demo_name: ev.target.value }))}
                    >
                      <option value="">{e.selectDemo[lang]}</option>
                      {demoOptions.map((d) => (
                        <option key={d.id} value={d.name}>{d.name}</option>
                      ))}
                    </select>
                  </div>
                  <textarea placeholder={e.instructions[lang]} rows={3}
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                    value={taskForm.instructions}
                    onChange={(ev) => setTaskForm((f) => ({ ...f, instructions: ev.target.value }))} />
                </>
              ) : taskForm.task_type === "workflow" ? (
                <>
                  <div>
                    <label className="mb-1 block text-xs text-slate-500">{e.workflowPick[lang]}</label>
                    <select
                      className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      value={taskForm.workflow_id}
                      onChange={(ev) => setTaskForm((f) => ({ ...f, workflow_id: ev.target.value }))}
                    >
                      <option value="">{e.selectWorkflow[lang]}</option>
                      {workflowOptions.map((w) => (
                        <option key={w.id} value={w.id}>{w.name}</option>
                      ))}
                    </select>
                  </div>
                  <textarea placeholder={e.workflowInput[lang]} rows={3}
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                    value={taskForm.prompt}
                    onChange={(ev) => setTaskForm((f) => ({ ...f, prompt: ev.target.value }))} />
                </>
              ) : taskForm.task_type === "crew" ? (
                <>
                  <textarea placeholder={e.crewGoal[lang]} rows={3}
                    className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                    value={taskForm.prompt}
                    onChange={(ev) => setTaskForm((f) => ({ ...f, prompt: ev.target.value }))} />
                  <div>
                    <label className="mb-1 block text-xs text-slate-500">{e.crewAgents[lang]}</label>
                    <select
                      multiple
                      className="h-28 w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                      value={taskForm.crew_agent_ids}
                      onChange={(ev) => setTaskForm((f) => ({
                        ...f,
                        crew_agent_ids: Array.from(ev.target.selectedOptions, (o) => o.value),
                      }))}
                    >
                      {agentOptions.map((a) => (
                        <option key={a.id} value={a.id}>{a.name}</option>
                      ))}
                    </select>
                  </div>
                </>
              ) : (
                <textarea placeholder={e.prompt[lang]} rows={4}
                  className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={taskForm.prompt} onChange={(ev) => setTaskForm((f) => ({ ...f, prompt: ev.target.value }))} />
              )}
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowTaskModal(false)} className="text-sm text-slate-400">{c.cancel[lang]}</button>
              <button onClick={createTask} className="rounded-lg bg-teal-600 px-4 py-2 text-sm text-white">{c.create[lang]}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
