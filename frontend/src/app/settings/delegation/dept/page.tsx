"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, FileSpreadsheet, Search, Users } from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { organizationApi } from "@/lib/api";
import { canDelegateDept } from "@/lib/permissions";
import { useAuthStore } from "@/lib/authStore";
import PermissionImportPanel from "@/components/organization/PermissionImportPanel";
import { clsx } from "clsx";

interface OrgUser {
  id: string;
  display_name: string;
  employee_no?: string | null;
  primary_department_id?: string | null;
  primary_department_name?: string | null;
  roles: { role_code: string; scope_department_id?: string | null }[];
  user_tier?: string;
}

interface Department {
  id: string;
  name: string;
}

interface RoleDef {
  role_code: string;
  label_zh: string;
  label_en: string;
}

const DEPT_ROLES = ["operator", "dept_leader", "auditor"];
const SCOPED = new Set(["dept_leader", "auditor"]);

export default function DeptDelegationPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const d = translations.delegation;
  const o = translations.organization;
  const c = translations.common;
  const allowed = canDelegateDept(user);

  const [users, setUsers] = useState<OrgUser[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [primaryDept, setPrimaryDept] = useState("");
  const [roles, setRoles] = useState<Record<string, boolean>>({});
  const [scopeDept, setScopeDept] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showImport, setShowImport] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [u, dept, rolesRes] = await Promise.all([
        organizationApi.delegationDeptUsers(),
        organizationApi.delegationDepartments(),
        organizationApi.delegatableRoles(),
      ]);
      setUsers(u.data);
      setDepartments(dept.data);
      setRoleDefs(rolesRes.data);
      if (!selectedId && u.data.length) setSelectedId(u.data[0].id);
    } catch {
      toast.error(o.loadFail[lang]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (allowed) load();
    else setLoading(false);
  }, [allowed]);

  const selected = useMemo(() => users.find((u) => u.id === selectedId) ?? null, [users, selectedId]);

  useEffect(() => {
    if (!selected) return;
    setPrimaryDept(selected.primary_department_id ?? "");
    const r: Record<string, boolean> = {};
    const s: Record<string, string> = {};
    for (const code of DEPT_ROLES) r[code] = false;
    for (const item of selected.roles) {
      if (DEPT_ROLES.includes(item.role_code)) {
        r[item.role_code] = true;
        if (item.scope_department_id) s[item.role_code] = item.scope_department_id;
      }
    }
    setRoles(r);
    setScopeDept(s);
  }, [selected]);

  const roleLabel = (code: string) => {
    const def = roleDefs.find((r) => r.role_code === code);
    return def ? (lang === "zh" ? def.label_zh : def.label_en) : code;
  };

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) =>
      [u.display_name, u.employee_no, u.primary_department_name].filter(Boolean).join(" ").toLowerCase().includes(q),
    );
  }, [users, search]);

  const applyPreset = (code: string) => {
    const r: Record<string, boolean> = {};
    for (const c of DEPT_ROLES) r[c] = c === code;
    setRoles(r);
    if (SCOPED.has(code) && primaryDept) setScopeDept({ [code]: primaryDept });
    else setScopeDept({});
  };

  const save = async () => {
    if (!selectedId) return;
    const payloadRoles = DEPT_ROLES.filter((code) => roles[code]).map((code) => ({
      role_code: code,
      scope_department_id: scopeDept[code] || null,
    }));
    try {
      await organizationApi.updateDeptDelegation(selectedId, {
        primary_department_id: primaryDept || null,
        roles: payloadRoles,
      });
      toast.success(d.saveOk[lang]);
      await load();
    } catch {
      toast.error(o.loadFail[lang]);
    }
  };

  if (!allowed) {
    return (
      <div className="p-8">
        <Link href="/settings" className="mb-6 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
          <ArrowLeft className="h-4 w-4" /> {d.backSettings[lang]}
        </Link>
        <div className="theme-card p-8 text-center theme-muted">{d.forbidden[lang]}</div>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8">
      <Link href="/settings" className="mb-4 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
        <ArrowLeft className="h-4 w-4" /> {d.backSettings[lang]}
      </Link>
      <h1 className="text-2xl font-bold theme-text">{d.deptTitle[lang]}</h1>
      <p className="mt-1 text-sm theme-muted">{d.deptSubtitle[lang]}</p>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="theme-btn-secondary text-sm" onClick={() => setShowImport((v) => !v)}>
          <FileSpreadsheet className="mr-1 inline h-4 w-4" />
          {o.tabImport[lang]}
        </button>
      </div>

      {showImport && (
        <div className="mt-4">
          <PermissionImportPanel mode="delegation" roleLabel={roleLabel} compact onApplied={() => void load()} />
        </div>
      )}

      {loading ? (
        <p className="mt-8 theme-muted">{c.loading[lang]}</p>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[280px_1fr]">
          <div className="theme-card p-4">
            <div className="relative mb-3">
              <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 theme-muted" />
              <input
                className="theme-input w-full rounded-lg border py-1.5 pl-8 pr-2 text-xs"
                placeholder={o.searchUser[lang]}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold theme-text">
              <Users className="h-4 w-4" /> {o.selectUser[lang]}
            </h2>
            <ul className="max-h-[480px] space-y-1 overflow-y-auto">
              {filteredUsers.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(u.id)}
                    className={clsx("w-full rounded-lg px-3 py-2 text-left text-sm", selectedId === u.id ? "nav-item-active" : "nav-item-idle")}
                  >
                    <div className="font-medium">{u.display_name}</div>
                    <div className="text-xs theme-muted">{u.primary_department_name || u.employee_no}</div>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {selected && (
            <div className="theme-card p-6">
              <h2 className="mb-4 font-semibold theme-text">{selected.display_name}</h2>
              <div className="mb-4 flex flex-wrap gap-2">
                {DEPT_ROLES.map((code) => (
                  <button key={code} type="button" className="rounded-full border theme-border px-2.5 py-1 text-xs" onClick={() => applyPreset(code)}>
                    {roleLabel(code)}
                  </button>
                ))}
              </div>
              <label className="mb-1 block text-xs theme-muted">{o.primaryDept[lang]}</label>
              <select
                className="theme-input mb-4 w-full rounded-lg border px-3 py-2 text-sm"
                value={primaryDept}
                onChange={(e) => setPrimaryDept(e.target.value)}
              >
                <option value="">—</option>
                {departments.map((dep) => (
                  <option key={dep.id} value={dep.id}>{dep.name}</option>
                ))}
              </select>

              <p className="mb-2 text-xs theme-muted">{d.assignRoles[lang]}</p>
              <div className="space-y-3">
                {DEPT_ROLES.map((code) => (
                  <div key={code} className="rounded-lg border theme-border p-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={!!roles[code]}
                        onChange={(e) => setRoles((prev) => ({ ...prev, [code]: e.target.checked }))}
                      />
                      {roleLabel(code)}
                    </label>
                    {roles[code] && SCOPED.has(code) && (
                      <select
                        className="theme-input mt-2 w-full rounded-lg border px-2 py-1 text-xs"
                        value={scopeDept[code] ?? ""}
                        onChange={(e) => setScopeDept((prev) => ({ ...prev, [code]: e.target.value }))}
                      >
                        <option value="">{lang === "zh" ? "管辖部门" : "Scope department"}</option>
                        {departments.map((dep) => (
                          <option key={dep.id} value={dep.id}>{dep.name}</option>
                        ))}
                      </select>
                    )}
                  </div>
                ))}
              </div>
              <button onClick={save} className="theme-btn-primary mt-4">{o.saveUser[lang]}</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
