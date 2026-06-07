"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Briefcase, Trash2, ChevronRight, Loader2 } from "lucide-react";
import { agentsApi, employeesApi } from "@/lib/api";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import toast from "react-hot-toast";

interface Employee {
  id: string;
  name: string;
  title: string | null;
  description: string | null;
  status: string;
  agent_id: string;
  timezone: string;
  task_count: number;
}

interface AgentOption { id: string; name: string; role: string; }

export default function EmployeesPage() {
  const { lang } = useLangStore();
  const e = translations.employees;
  const c = translations.common;

  const [items, setItems] = useState<Employee[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "", title: "", description: "", agent_id: "", timezone: "Asia/Shanghai",
  });

  const load = async () => {
    try {
      const { data } = await employeesApi.list();
      setItems(data);
    } catch {
      toast.error(lang === "zh" ? "加载失败" : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    agentsApi.list().then(({ data }) => {
      setAgents(data);
      if (data[0]) setForm((f) => ({ ...f, agent_id: data[0].id }));
    }).catch(() => {});
  }, []);

  const create = async () => {
    if (!form.name.trim() || !form.agent_id) return;
    setSaving(true);
    try {
      await employeesApi.create(form);
      toast.success(c.create[lang] + " OK");
      setShowCreate(false);
      setForm({ name: "", title: "", description: "", agent_id: agents[0]?.id ?? "", timezone: "Asia/Shanghai" });
      load();
    } catch {
      toast.error(lang === "zh" ? "创建失败" : "Create failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm(e.deleteConfirm[lang])) return;
    try {
      await employeesApi.delete(id);
      load();
    } catch {
      toast.error(c.delete[lang] + " failed");
    }
  };

  const agentName = (id: string) => agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);

  return (
    <div className="p-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{e.title[lang]}</h1>
          <p className="text-slate-400">{e.subtitle[lang]}</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" /> {e.newEmployee[lang]}
        </button>
      </div>

      {loading ? (
        <div className="text-slate-400">{c.loading[lang]}</div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#2d2d4e] py-16">
          <Briefcase className="mb-4 h-12 w-12 text-slate-600" />
          <p className="text-slate-400">{e.noEmployees[lang]}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map((emp) => (
            <div key={emp.id} className="rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-5">
              <div className="mb-2 flex items-start justify-between">
                <div>
                  <h3 className="font-semibold text-white">{emp.name}</h3>
                  {emp.title && <p className="text-xs text-blue-400">{emp.title}</p>}
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs ${
                  emp.status === "active" ? "bg-green-500/20 text-green-400" : "bg-slate-500/20 text-slate-400"
                }`}>
                  {emp.status === "active" ? c.active[lang] : e.paused[lang]}
                </span>
              </div>
              <p className="mb-3 line-clamp-2 text-sm text-slate-400">{emp.description}</p>
              <div className="mb-4 flex flex-wrap gap-2 text-xs">
                <span className="rounded bg-slate-700/50 px-2 py-0.5 text-slate-400">{agentName(emp.agent_id)}</span>
                <span className="rounded bg-purple-500/10 px-2 py-0.5 text-purple-400">{e.taskCount[lang]}: {emp.task_count}</span>
              </div>
              <div className="flex gap-2">
                <Link
                  href={`/employees/${emp.id}`}
                  className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-teal-600/20 px-3 py-1.5 text-xs text-teal-400 hover:bg-teal-600/30"
                >
                  {e.openDetail[lang]} <ChevronRight className="h-3 w-3" />
                </Link>
                <button
                  onClick={() => remove(emp.id)}
                  className="rounded-lg px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-xl border border-[#2d2d4e] bg-[#1a1a2e] p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">{e.newEmployee[lang]}</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.name[lang]}</label>
                <input className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={form.name} onChange={(ev) => setForm((f) => ({ ...f, name: ev.target.value }))} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{e.titleField[lang]}</label>
                <input className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={form.title} onChange={(ev) => setForm((f) => ({ ...f, title: ev.target.value }))} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{c.description[lang]}</label>
                <textarea className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white" rows={2}
                  value={form.description} onChange={(ev) => setForm((f) => ({ ...f, description: ev.target.value }))} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">{e.bindAgent[lang]}</label>
                <select className="w-full rounded-lg border border-[#2d2d4e] bg-[#0d0d1a] px-3 py-2 text-sm text-white"
                  value={form.agent_id} onChange={(ev) => setForm((f) => ({ ...f, agent_id: ev.target.value }))}>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({a.role})</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setShowCreate(false)} className="text-sm text-slate-400">{c.cancel[lang]}</button>
              <button onClick={create} disabled={saving || !form.name.trim()}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40">
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}{c.create[lang]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
