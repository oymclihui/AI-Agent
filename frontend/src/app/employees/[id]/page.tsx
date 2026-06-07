"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft, Plus, Play, Trash2, Loader2, Clock, History,
} from "lucide-react";
import { employeesApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

interface Employee {
  id: string; name: string; title: string | null; description: string | null;
  status: string; agent_id: string; timezone: string;
}

interface Task {
  id: string; name: string; description: string | null; enabled: boolean;
  schedule_type: "cron" | "interval"; cron_expression: string | null;
  interval_seconds: number | null; timezone: string; task_config: { prompt?: string };
  last_run_at: string | null; next_run_at: string | null; last_status: string | null;
}

interface Run {
  id: string; status: string; triggered_by: string;
  output_data: { output?: string } | null; error_message: string | null;
  duration_ms: number | null; created_at: string;
}

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
  const [taskForm, setTaskForm] = useState({
    name: "",
    description: "",
    schedule_type: "cron" as "cron" | "interval",
    cron_expression: "0 9 * * 1-5",
    interval_seconds: 3600,
    prompt: "",
    enabled: true,
  });

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

  const createTask = async () => {
    if (!taskForm.name.trim() || !taskForm.prompt.trim()) return;
    try {
      await employeesApi.createTask(id, {
        name: taskForm.name,
        description: taskForm.description,
        schedule_type: taskForm.schedule_type,
        cron_expression: taskForm.schedule_type === "cron" ? taskForm.cron_expression : null,
        interval_seconds: taskForm.schedule_type === "interval" ? taskForm.interval_seconds : null,
        task_config: { prompt: taskForm.prompt },
        enabled: taskForm.enabled,
      });
      setShowTaskModal(false);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ?? (lang === "zh" ? "创建失败" : "Create failed"));
    }
  };

  const runTask = async (taskId: string) => {
    setRunningId(taskId);
    try {
      await employeesApi.runTask(id, taskId);
      toast.success(e.runOk[lang]);
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
                      <p className="mt-1 line-clamp-2 text-xs text-slate-400">{task.task_config?.prompt}</p>
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
        runs.length === 0 ? (
          <p className="text-slate-500">{e.noRuns[lang]}</p>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <div key={run.id} className="rounded-lg border border-[#2d2d4e] bg-[#1a1a2e] p-3 text-sm">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs ${
                    run.status === "completed" ? "bg-green-500/20 text-green-400" :
                    run.status === "failed" ? "bg-red-500/20 text-red-400" : "bg-slate-500/20 text-slate-400"
                  }`}>{run.status}</span>
                  <span className="text-xs text-slate-500">{run.triggered_by}</span>
                  <span className="text-xs text-slate-500">{fmtTime(run.created_at)}</span>
                  {run.duration_ms != null && <span className="text-xs text-slate-500">{run.duration_ms}ms</span>}
                </div>
                {run.output_data?.output && (
                  <p className="line-clamp-4 whitespace-pre-wrap text-slate-300">{run.output_data.output}</p>
                )}
                {run.error_message && <p className="text-red-400">{run.error_message}</p>}
              </div>
            ))}
          </div>
        )
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
              <textarea placeholder={e.prompt[lang]} rows={4}
                className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                value={taskForm.prompt} onChange={(ev) => setTaskForm((f) => ({ ...f, prompt: ev.target.value }))} />
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
