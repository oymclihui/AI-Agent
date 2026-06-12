"use client";

import { useCallback, useEffect, useState } from "react";
import {
  MousePointer2, Plus, Play, Trash2, Circle, RefreshCw,
  Video, Square, Loader2, BookOpen, Library,
} from "lucide-react";
import toast from "react-hot-toast";
import { desktopAutomationApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";

interface Demo {
  id: string;
  name: string;
  description: string | null;
  app_name: string | null;
  status: string;
  step_count: number;
  tags: string[];
}

interface Task {
  id: string;
  demo_id: string | null;
  demo_name: string | null;
  action: string;
  status: string;
  instructions: string | null;
  error_message: string | null;
  created_at: string;
}

interface SidecarStatus {
  online: boolean;
  device_name?: string;
  hostname?: string;
  platform?: string;
}

export default function DesktopAutomationPage() {
  const { lang } = useLangStore();
  const t = translations.desktopAutomation;
  const c = translations.common;

  const [demos, setDemos] = useState<Demo[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [awaitingTasks, setAwaitingTasks] = useState<Task[]>([]);
  const [sidecar, setSidecar] = useState<SidecarStatus>({ online: false });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [captureDemoName, setCaptureDemoName] = useState("");
  const [form, setForm] = useState({ name: "", app_name: "", description: "" });

  const load = useCallback(async () => {
    try {
      const [demosRes, tasksRes, awaitingRes, sidecarRes] = await Promise.all([
        desktopAutomationApi.listDemos(),
        desktopAutomationApi.listTasks(),
        desktopAutomationApi.listAwaitingConfirmation(),
        desktopAutomationApi.sidecarStatus(),
      ]);
      setDemos(demosRes.data);
      setTasks(tasksRes.data);
      setAwaitingTasks(awaitingRes.data);
      setSidecar(sidecarRes.data);
    } catch {
      toast.error(c.loadFailed[lang]);
    } finally {
      setLoading(false);
    }
  }, [c.loadFailed, lang]);

  useEffect(() => {
    load();
    const timer = setInterval(() => {
      desktopAutomationApi.sidecarStatus().then(({ data }) => setSidecar(data)).catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const createDemo = async () => {
    if (!form.name.trim()) return;
    setBusy("create");
    try {
      await desktopAutomationApi.createDemo({
        name: form.name.trim(),
        app_name: form.app_name.trim() || undefined,
        description: form.description.trim() || undefined,
      });
      toast.success(t.created[lang]);
      setShowCreate(false);
      setForm({ name: "", app_name: "", description: "" });
      await load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : c.saveFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const replayDemo = async (demo: Demo) => {
    if (!sidecar.online) {
      toast.error(t.sidecarRequired[lang]);
      return;
    }
    setBusy(demo.id);
    try {
      await desktopAutomationApi.replay({ demo_id: demo.id, confirmed: true });
      toast.success(t.replayStarted[lang]);
      await load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const depositDemo = async (demo: Demo, target: "skill" | "knowledge") => {
    setBusy(`deposit-${demo.id}-${target}`);
    try {
      await desktopAutomationApi.depositDemo(demo.id, { target, use_llm: true });
      toast.success(target === "skill" ? t.depositSkillOk[lang] : t.depositKnowledgeOk[lang]);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const deleteDemo = async (demo: Demo) => {
    if (!window.confirm(`${t.delete[lang]}: ${demo.name}?`)) return;
    setBusy(demo.id);
    try {
      await desktopAutomationApi.deleteDemo(demo.id);
      await load();
    } catch {
      toast.error(c.deleteFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const startCapture = async () => {
    if (!sidecar.online) {
      toast.error(t.sidecarRequired[lang]);
      return;
    }
    setBusy("capture-start");
    try {
      await desktopAutomationApi.captureStart({});
      toast.success(t.captureStarted[lang]);
      await load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const stopCapture = async () => {
    if (!captureDemoName.trim()) {
      toast.error(t.captureNameRequired[lang]);
      return;
    }
    if (!sidecar.online) {
      toast.error(t.sidecarRequired[lang]);
      return;
    }
    setBusy("capture-stop");
    try {
      await desktopAutomationApi.captureStop({ demo_name: captureDemoName.trim() });
      toast.success(t.captureStopped[lang]);
      setCaptureDemoName("");
      await load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const approveAwaitingTask = async (taskId: string) => {
    setBusy(`confirm-${taskId}`);
    try {
      await desktopAutomationApi.confirmTask(taskId);
      toast.success(t.confirmApproved[lang]);
      await load();
    } catch {
      toast.error(c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  const rejectAwaitingTask = async (taskId: string) => {
    setBusy(`reject-${taskId}`);
    try {
      await desktopAutomationApi.rejectTask(taskId);
      toast.success(t.confirmRejected[lang]);
      await load();
    } catch {
      toast.error(c.actionFailed[lang]);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="theme-surface border-b theme-border px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold theme-text">
              <MousePointer2 className="h-6 w-6 text-blue-500" />
              {t.title[lang]}
            </h1>
            <p className="mt-1 text-sm theme-muted">{t.subtitle[lang]}</p>
            <p className="mt-2 text-xs theme-muted">{t.agentHint[lang]}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => load()}
              className="nav-item-idle rounded-lg px-3 py-2 text-sm"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <span
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ${
                sidecar.online ? "bg-emerald-500/15 text-emerald-600" : "bg-amber-500/15 text-amber-700"
              }`}
            >
              <Circle className={`h-2 w-2 ${sidecar.online ? "fill-emerald-500" : "fill-amber-500"}`} />
              {sidecar.online ? t.sidecarOnline[lang] : t.sidecarOffline[lang]}
              {sidecar.device_name ? ` · ${sidecar.device_name}` : ""}
            </span>
          </div>
        </div>
        <p className="mt-3 rounded-lg bg-blue-500/10 px-3 py-2 font-mono text-xs theme-muted">
          {t.sidecarHint[lang]}
        </p>
      </header>

      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20 theme-muted">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-2">
            {/* Demos */}
            <section className="theme-surface rounded-xl border theme-border p-4">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-medium theme-text">{t.demos[lang]}</h2>
                <button
                  type="button"
                  onClick={() => setShowCreate(true)}
                  className="inline-flex items-center gap-1 rounded-lg bg-blue-500 px-3 py-1.5 text-sm text-on-primary"
                >
                  <Plus className="h-4 w-4" />
                  {t.newDemo[lang]}
                </button>
              </div>

              <div className="mb-4 flex flex-wrap gap-2 rounded-lg border theme-border p-3">
                <button
                  type="button"
                  disabled={busy === "capture-start"}
                  onClick={startCapture}
                  className="inline-flex items-center gap-1 rounded-lg bg-red-500/90 px-3 py-1.5 text-sm text-white disabled:opacity-50"
                >
                  <Video className="h-4 w-4" />
                  {t.captureStart[lang]}
                </button>
                <input
                  value={captureDemoName}
                  onChange={(e) => setCaptureDemoName(e.target.value)}
                  placeholder={t.demoName[lang]}
                  className="min-w-[140px] flex-1 rounded-lg border theme-border bg-transparent px-3 py-1.5 text-sm"
                />
                <button
                  type="button"
                  disabled={busy === "capture-stop"}
                  onClick={stopCapture}
                  className="inline-flex items-center gap-1 rounded-lg border theme-border px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  <Square className="h-4 w-4" />
                  {t.captureStop[lang]}
                </button>
              </div>

              {demos.length === 0 ? (
                <p className="py-8 text-center text-sm theme-muted">{t.emptyDemos[lang]}</p>
              ) : (
                <ul className="space-y-2">
                  {demos.map((demo) => (
                    <li
                      key={demo.id}
                      className="flex items-start justify-between gap-2 rounded-lg border theme-border px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium theme-text">{demo.name}</p>
                        <p className="text-xs theme-muted">
                          {demo.app_name || "—"} · {demo.status} · {demo.step_count} steps
                        </p>
                        {demo.description && (
                          <p className="mt-1 text-xs theme-muted line-clamp-2">{demo.description}</p>
                        )}
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          disabled={!!busy}
                          onClick={() => depositDemo(demo, "skill")}
                          className="rounded p-1.5 text-violet-500 hover:bg-violet-500/10"
                          title={t.depositSkill[lang]}
                        >
                          <BookOpen className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          disabled={!!busy}
                          onClick={() => depositDemo(demo, "knowledge")}
                          className="rounded p-1.5 text-emerald-500 hover:bg-emerald-500/10"
                          title={t.depositKnowledge[lang]}
                        >
                          <Library className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          disabled={busy === demo.id}
                          onClick={() => replayDemo(demo)}
                          className="rounded p-1.5 text-blue-500 hover:bg-blue-500/10"
                          title={t.replay[lang]}
                        >
                          <Play className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          disabled={busy === demo.id}
                          onClick={() => deleteDemo(demo)}
                          className="rounded p-1.5 text-red-500 hover:bg-red-500/10"
                          title={t.delete[lang]}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {awaitingTasks.length > 0 && (
              <section className="theme-surface rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                <h2 className="mb-3 font-medium text-amber-100">{t.awaitingConfirm[lang]}</h2>
                <ul className="space-y-2">
                  {awaitingTasks.map((task) => (
                    <li
                      key={task.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/20 px-3 py-2 text-sm"
                    >
                      <div className="min-w-0">
                        <p className="font-medium theme-text">{task.demo_name || task.action}</p>
                        {task.instructions && (
                          <p className="text-xs theme-muted line-clamp-2">{task.instructions}</p>
                        )}
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <button
                          type="button"
                          disabled={!!busy}
                          onClick={() => approveAwaitingTask(task.id)}
                          className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-700 disabled:opacity-50"
                        >
                          {t.confirmApprove[lang]}
                        </button>
                        <button
                          type="button"
                          disabled={!!busy}
                          onClick={() => rejectAwaitingTask(task.id)}
                          className="rounded border theme-border px-3 py-1 text-xs theme-muted hover:bg-black/10 disabled:opacity-50"
                        >
                          {t.confirmReject[lang]}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Tasks */}
            <section className="theme-surface rounded-xl border theme-border p-4">
              <h2 className="mb-4 font-medium theme-text">{t.tasks[lang]}</h2>
              {tasks.length === 0 ? (
                <p className="py-8 text-center text-sm theme-muted">{t.emptyTasks[lang]}</p>
              ) : (
                <ul className="max-h-[520px] space-y-2 overflow-auto">
                  {tasks.map((task) => (
                    <li key={task.id} className="rounded-lg border theme-border px-3 py-2 text-sm">
                      <div className="flex justify-between gap-2">
                        <span className="font-medium theme-text">{task.action}</span>
                        <span className="text-xs theme-muted">{task.status}</span>
                      </div>
                      {task.demo_name && (
                        <p className="text-xs theme-muted">{task.demo_name}</p>
                      )}
                      {task.error_message && (
                        <p className="mt-1 text-xs text-red-500">{task.error_message}</p>
                      )}
                      <p className="mt-1 text-[10px] theme-muted">
                        {new Date(task.created_at).toLocaleString()}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="theme-surface w-full max-w-md rounded-xl border theme-border p-5 shadow-xl">
            <h3 className="mb-4 font-semibold theme-text">{t.newDemo[lang]}</h3>
            <div className="space-y-3">
              <input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder={t.demoName[lang]}
                className="w-full rounded-lg border theme-border bg-transparent px-3 py-2 text-sm"
              />
              <input
                value={form.app_name}
                onChange={(e) => setForm((f) => ({ ...f, app_name: e.target.value }))}
                placeholder={t.appName[lang]}
                className="w-full rounded-lg border theme-border bg-transparent px-3 py-2 text-sm"
              />
              <textarea
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder={t.description[lang]}
                rows={3}
                className="w-full rounded-lg border theme-border bg-transparent px-3 py-2 text-sm"
              />
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded-lg px-4 py-2 text-sm nav-item-idle"
              >
                {c.cancel[lang]}
              </button>
              <button
                type="button"
                disabled={busy === "create"}
                onClick={createDemo}
                className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-on-primary disabled:opacity-50"
              >
                {c.create[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
