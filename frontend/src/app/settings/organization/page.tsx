"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Building2,
  FileSpreadsheet,
  Search,
  Shield,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { organizationApi } from "@/lib/api";
import { canManageOrg } from "@/lib/permissions";
import { useClientAuth } from "@/hooks/useClientAuth";
import { SegmentedControl } from "@/components/SegmentedControl";
import PermissionImportPanel from "@/components/organization/PermissionImportPanel";
import { clsx } from "clsx";

type Tab = "depts" | "users" | "import" | "preview";

interface Department {
  id: string;
  name: string;
  code?: string | null;
  parent_id?: string | null;
  path: string;
  level: number;
  leader_user_id?: string | null;
  leader_name?: string | null;
  liaison_user_id?: string | null;
  liaison_name?: string | null;
  dept_tier?: string;
  member_count: number;
  is_active: boolean;
}

interface OrgUser {
  id: string;
  display_name: string;
  employee_no?: string | null;
  email?: string | null;
  is_active: boolean;
  user_tier?: string;
  primary_department_id?: string | null;
  primary_department_name?: string | null;
  roles: { role_code: string; scope_department_id?: string | null }[];
  permissions: string[];
}

interface RoleDef {
  role_code: string;
  label_zh: string;
  label_en: string;
  permissions: string[];
}

interface Preview {
  user_id: string;
  display_name: string;
  permissions: string[];
  data_scope: string;
  visible_user_count: number;
  visible_department_count: number;
  can_view_dashboard: boolean;
  can_manage_org: boolean;
  department_paths: string[];
  roles: { role_code: string; scope_department_id?: string | null }[];
}

const ALL_ROLE_CODES = [
  "super_admin",
  "org_admin",
  "executive",
  "dept_leader",
  "operator",
  "auditor",
  "dept_liaison",
  "executive_assistant",
];

const SCOPED_ROLES = new Set(["dept_leader", "executive", "auditor", "dept_liaison"]);

type RolePresetId = "operator" | "dept_leader" | "dept_liaison" | "auditor" | "executive";

const ROLE_PRESETS: Record<RolePresetId, { roles: string[]; user_tier?: string }> = {
  operator: { roles: ["operator"], user_tier: "staff" },
  dept_leader: { roles: ["dept_leader"], user_tier: "staff" },
  dept_liaison: { roles: ["dept_liaison"], user_tier: "staff" },
  auditor: { roles: ["auditor"], user_tier: "staff" },
  executive: { roles: ["executive"], user_tier: "executive" },
};

export default function OrganizationPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const { ready: authReady } = useClientAuth();
  const o = translations.organization;
  const c = translations.common;

  const [tab, setTab] = useState<Tab>("users");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const [newDeptName, setNewDeptName] = useState("");
  const [newDeptCode, setNewDeptCode] = useState("");
  const [newDeptParent, setNewDeptParent] = useState("");
  const [newDeptTier, setNewDeptTier] = useState("business");

  const [search, setSearch] = useState("");
  const [filterDeptId, setFilterDeptId] = useState("");
  const [filterRole, setFilterRole] = useState("");

  const [selectedUserId, setSelectedUserId] = useState("");
  const [editPrimaryDept, setEditPrimaryDept] = useState("");
  const [editUserTier, setEditUserTier] = useState("staff");
  const [editRoles, setEditRoles] = useState<Record<string, boolean>>({});
  const [editScopeDept, setEditScopeDept] = useState<Record<string, string>>({});
  const [editIsActive, setEditIsActive] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(false);

  const [showCreateUser, setShowCreateUser] = useState(false);
  const [newEmployeeNo, setNewEmployeeNo] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPrimaryDept, setNewPrimaryDept] = useState("");
  const [newUserTier, setNewUserTier] = useState("staff");

  const allowed = authReady && canManageOrg(user);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [deptRes, userRes, roleRes] = await Promise.all([
        organizationApi.listDepartments(),
        organizationApi.listUsers(),
        organizationApi.listRoles(),
      ]);
      setDepartments(deptRes.data);
      setOrgUsers(userRes.data);
      setRoleDefs(roleRes.data);
      setForbidden(false);
      if (!selectedUserId && userRes.data.length) {
        setSelectedUserId(userRes.data[0].id);
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) setForbidden(true);
      else toast.error(o.loadFail[lang]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authReady) return;
    if (allowed) loadAll();
    else setLoading(false);
  }, [authReady, allowed]);

  const selectedUser = useMemo(
    () => orgUsers.find((u) => u.id === selectedUserId) ?? null,
    [orgUsers, selectedUserId],
  );

  useEffect(() => {
    if (!selectedUser) return;
    setEditPrimaryDept(selectedUser.primary_department_id ?? "");
    setEditUserTier(selectedUser.user_tier || "staff");
    const roles: Record<string, boolean> = {};
    const scopes: Record<string, string> = {};
    for (const code of ALL_ROLE_CODES) roles[code] = false;
    for (const r of selectedUser.roles) {
      roles[r.role_code] = true;
      if (r.scope_department_id) scopes[r.role_code] = r.scope_department_id;
    }
    setEditRoles(roles);
    setEditScopeDept(scopes);
    setEditIsActive(selectedUser.is_active);
  }, [selectedUser]);

  useEffect(() => {
    if (tab !== "preview" || !selectedUserId || !allowed) return;
    setPreviewLoading(true);
    setPreviewError(false);
    setPreview(null);
    organizationApi.previewPermissions(selectedUserId)
      .then(({ data }) => setPreview(data))
      .catch(() => {
        setPreview(null);
        setPreviewError(true);
      })
      .finally(() => setPreviewLoading(false));
  }, [tab, selectedUserId, allowed]);

  const roleLabel = useCallback(
    (code: string) => {
      const def = roleDefs.find((r) => r.role_code === code);
      if (!def) return code;
      return lang === "zh" ? def.label_zh : def.label_en;
    },
    [roleDefs, lang],
  );

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return orgUsers.filter((u) => {
      if (filterDeptId && u.primary_department_id !== filterDeptId) return false;
      if (filterRole && !u.roles.some((r) => r.role_code === filterRole)) return false;
      if (!q) return true;
      const hay = [u.display_name, u.employee_no, u.email, u.primary_department_name]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [orgUsers, search, filterDeptId, filterRole]);

  const applyRolePreset = (presetId: RolePresetId) => {
    const preset = ROLE_PRESETS[presetId];
    const roles: Record<string, boolean> = {};
    const scopes: Record<string, string> = {};
    for (const code of ALL_ROLE_CODES) roles[code] = false;
    for (const code of preset.roles) {
      roles[code] = true;
      if (SCOPED_ROLES.has(code) && editPrimaryDept) {
        scopes[code] = editPrimaryDept;
      }
    }
    setEditRoles(roles);
    setEditScopeDept(scopes);
    if (preset.user_tier) setEditUserTier(preset.user_tier);
  };

  const clearRoles = () => {
    const roles: Record<string, boolean> = {};
    for (const code of ALL_ROLE_CODES) roles[code] = false;
    roles.operator = true;
    setEditRoles(roles);
    setEditScopeDept({});
    setEditUserTier("staff");
  };

  const createDepartment = async () => {
    if (!newDeptName.trim()) return;
    try {
      await organizationApi.createDepartment({
        name: newDeptName.trim(),
        code: newDeptCode.trim() || null,
        parent_id: newDeptParent || null,
        dept_tier: newDeptTier,
      });
      setNewDeptName("");
      setNewDeptCode("");
      setNewDeptParent("");
      toast.success(o.saved[lang]);
      await loadAll();
    } catch {
      toast.error(o.loadFail[lang]);
    }
  };

  const saveUserRoles = async () => {
    if (!selectedUserId) return;
    const roles = ALL_ROLE_CODES.filter((code) => editRoles[code]).map((code) => ({
      role_code: code,
      scope_department_id: editScopeDept[code] || null,
    }));
    try {
      await organizationApi.updateUser(selectedUserId, {
        primary_department_id: editPrimaryDept || null,
        user_tier: editUserTier,
        is_active: editIsActive,
        roles,
      });
      toast.success(o.saved[lang]);
      await loadAll();
    } catch {
      toast.error(o.loadFail[lang]);
    }
  };

  const createUser = async () => {
    if (!newEmployeeNo.trim() || !newDisplayName.trim() || newPassword.length < 6) return;
    try {
      await organizationApi.createUser({
        employee_no: newEmployeeNo.trim(),
        display_name: newDisplayName.trim(),
        email: newEmail.trim() || null,
        password: newPassword,
        primary_department_id: newPrimaryDept || null,
        user_tier: newUserTier,
        is_active: true,
        roles: [],
      });
      toast.success(o.userCreated[lang]);
      setNewEmployeeNo("");
      setNewDisplayName("");
      setNewEmail("");
      setNewPassword("");
      setNewPrimaryDept("");
      setNewUserTier("staff");
      setShowCreateUser(false);
      await loadAll();
    } catch {
      toast.error(o.loadFail[lang]);
    }
  };

  if (!authReady) {
    return (
      <div className="p-8">
        <p className="theme-muted">{c.loading?.[lang] ?? "Loading…"}</p>
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="p-8">
        <Link href="/settings" className="mb-6 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
          <ArrowLeft className="h-4 w-4" /> {o.backSettings[lang]}
        </Link>
        <div className="theme-card p-8 text-center">
          <Shield className="mx-auto mb-4 h-10 w-10 text-amber-400" />
          <p className="theme-muted">{o.forbidden[lang]}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 lg:p-8">
      <Link href="/settings" className="mb-4 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
        <ArrowLeft className="h-4 w-4" /> {o.backSettings[lang]}
      </Link>
      <h1 className="text-2xl font-bold theme-text">{o.title[lang]}</h1>
      <p className="mt-1 text-sm theme-muted">{o.subtitle[lang]}</p>

      <div className="mt-6">
        <SegmentedControl
          value={tab}
          onChange={(v) => setTab(v as Tab)}
          options={[
            { value: "users", label: o.tabUsers[lang] },
            { value: "import", label: o.tabImport[lang] },
            { value: "depts", label: o.tabDepts[lang] },
            { value: "preview", label: o.tabPreview[lang] },
          ]}
        />
      </div>

      {loading ? (
        <p className="mt-8 theme-muted">{c.loading?.[lang] ?? "Loading…"}</p>
      ) : forbidden ? (
        <p className="mt-8 theme-muted">{o.forbidden[lang]}</p>
      ) : tab === "import" ? (
        <div className="mt-6">
          <PermissionImportPanel mode="org" roleLabel={roleLabel} onApplied={() => void loadAll()} />
        </div>
      ) : tab === "depts" ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div className="theme-card p-6">
            <h2 className="mb-4 flex items-center gap-2 font-semibold theme-text">
              <Building2 className="h-5 w-5" /> {o.tabDepts[lang]}
            </h2>
            <ul className="max-h-96 space-y-2 overflow-y-auto text-sm">
              {departments.map((d) => (
                <li key={d.id} className="rounded-lg border theme-border px-3 py-2" style={{ paddingLeft: `${12 + d.level * 16}px` }}>
                  <div className="font-medium theme-text">{d.name}</div>
                  <div className="text-xs theme-muted">
                    {d.code ? `${d.code} · ` : ""}
                    {o.members[lang]}: {d.member_count}
                    {d.leader_name ? ` · ${o.leader[lang]}: ${d.leader_name}` : ""}
                    {d.liaison_name ? ` · ${o.liaison[lang]}: ${d.liaison_name}` : ""}
                    {d.dept_tier === "executive" ? ` · ${o.tierExecutive[lang]}` : ""}
                  </div>
                  <select
                    className="theme-input mt-2 w-full rounded border px-2 py-1 text-xs"
                    value={d.liaison_user_id || ""}
                    onChange={async (e) => {
                      try {
                        await organizationApi.updateDepartment(d.id, {
                          liaison_user_id: e.target.value || null,
                        });
                        toast.success(o.saved[lang]);
                        await loadAll();
                      } catch {
                        toast.error(o.loadFail[lang]);
                      }
                    }}
                  >
                    <option value="">{o.liaison[lang]} —</option>
                    {orgUsers.map((u) => (
                      <option key={u.id} value={u.id}>{u.display_name}</option>
                    ))}
                  </select>
                </li>
              ))}
            </ul>
          </div>
          <div className="theme-card p-6">
            <h2 className="mb-4 font-semibold theme-text">{o.addDept[lang]}</h2>
            <div className="space-y-3">
              <input
                className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
                placeholder={o.deptName[lang]}
                value={newDeptName}
                onChange={(e) => setNewDeptName(e.target.value)}
              />
              <input
                className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
                placeholder={o.deptCode[lang]}
                value={newDeptCode}
                onChange={(e) => setNewDeptCode(e.target.value)}
              />
              <select
                className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
                value={newDeptParent}
                onChange={(e) => setNewDeptParent(e.target.value)}
              >
                <option value="">{o.noParent[lang]}</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
              <select
                className="theme-input w-full rounded-lg border px-3 py-2 text-sm"
                value={newDeptTier}
                onChange={(e) => setNewDeptTier(e.target.value)}
              >
                <option value="business">{o.tierBusiness[lang]}</option>
                <option value="executive">{o.tierExecutive[lang]}</option>
              </select>
              <button onClick={createDepartment} className="theme-btn-primary">{o.saveDept[lang]}</button>
            </div>
          </div>
        </div>
      ) : tab === "users" ? (
        <div className="mt-6 space-y-4">
          <div className="theme-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-semibold theme-text">{o.createUser[lang]}</h2>
              <button
                type="button"
                onClick={() => setShowCreateUser((v) => !v)}
                className="theme-btn-primary text-sm"
              >
                {showCreateUser ? (lang === "zh" ? "收起" : "Collapse") : o.createUserBtn[lang]}
              </button>
            </div>
            {showCreateUser && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <input className="theme-input rounded-lg border px-3 py-2 text-sm" placeholder={o.employeeNo[lang]} value={newEmployeeNo} onChange={(e) => setNewEmployeeNo(e.target.value)} />
                <input className="theme-input rounded-lg border px-3 py-2 text-sm" placeholder={o.displayName[lang]} value={newDisplayName} onChange={(e) => setNewDisplayName(e.target.value)} />
                <input className="theme-input rounded-lg border px-3 py-2 text-sm" placeholder={o.email[lang]} value={newEmail} onChange={(e) => setNewEmail(e.target.value)} />
                <input type="password" className="theme-input rounded-lg border px-3 py-2 text-sm" placeholder={o.password[lang]} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                <select className="theme-input rounded-lg border px-3 py-2 text-sm" value={newPrimaryDept} onChange={(e) => setNewPrimaryDept(e.target.value)}>
                  <option value="">{o.primaryDept[lang]} —</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
                <select className="theme-input rounded-lg border px-3 py-2 text-sm" value={newUserTier} onChange={(e) => setNewUserTier(e.target.value)}>
                  <option value="staff">{o.tierStaff[lang]}</option>
                  <option value="director">{o.tierDirector[lang]}</option>
                  <option value="executive">{o.tierExecUser[lang]}</option>
                </select>
                <button
                  onClick={createUser}
                  disabled={!newEmployeeNo.trim() || !newDisplayName.trim() || newPassword.length < 6}
                  className="theme-btn-primary disabled:opacity-50 sm:col-span-2 lg:col-span-1"
                >
                  {o.createUserBtn[lang]}
                </button>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-3">
            <div className="relative min-w-[200px] flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 theme-muted" />
              <input
                className="theme-input w-full rounded-lg border py-2 pl-9 pr-3 text-sm"
                placeholder={o.searchUser[lang]}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select className="theme-input rounded-lg border px-3 py-2 text-sm" value={filterDeptId} onChange={(e) => setFilterDeptId(e.target.value)}>
              <option value="">{o.filterDept[lang]}</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
            <select className="theme-input rounded-lg border px-3 py-2 text-sm" value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
              <option value="">{o.filterRole[lang]}</option>
              {ALL_ROLE_CODES.map((code) => (
                <option key={code} value={code}>{roleLabel(code)}</option>
              ))}
            </select>
            <button type="button" className="theme-btn-secondary text-sm" onClick={() => setTab("import")}>
              <FileSpreadsheet className="mr-1 inline h-4 w-4" />
              {o.tabImport[lang]}
            </button>
          </div>

          <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
            <div className="theme-card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead>
                    <tr className="border-b theme-border bg-slate-50/50 text-xs theme-muted dark:bg-slate-900/30">
                      <th className="px-4 py-3">{o.colName[lang]}</th>
                      <th className="px-4 py-3">{o.colEmpNo[lang]}</th>
                      <th className="px-4 py-3">{o.colDept[lang]}</th>
                      <th className="px-4 py-3">{o.colRoles[lang]}</th>
                      <th className="px-4 py-3">{o.colStatus[lang]}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredUsers.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-4 py-8 text-center theme-muted">{o.noUsersMatch[lang]}</td>
                      </tr>
                    ) : (
                      filteredUsers.map((u) => (
                        <tr
                          key={u.id}
                          onClick={() => setSelectedUserId(u.id)}
                          className={clsx(
                            "cursor-pointer border-b theme-border/60 transition-colors hover:bg-slate-50/80 dark:hover:bg-slate-900/20",
                            selectedUserId === u.id && "bg-blue-50/80 dark:bg-blue-950/20",
                          )}
                        >
                          <td className="px-4 py-3 font-medium">{u.display_name}</td>
                          <td className="px-4 py-3 font-mono text-xs theme-muted">{u.employee_no || "—"}</td>
                          <td className="px-4 py-3 theme-muted">{u.primary_department_name || "—"}</td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap gap-1">
                              {u.roles.map((r) => (
                                <span key={r.role_code} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800">
                                  {roleLabel(r.role_code)}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <span className={clsx("text-xs", u.is_active ? "text-emerald-600" : "text-red-500")}>
                              {u.is_active ? o.active[lang] : o.inactive[lang]}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {selectedUser ? (
              <div className="theme-card p-5 xl:sticky xl:top-4 xl:self-start">
                <h2 className="mb-1 font-semibold theme-text">{selectedUser.display_name}</h2>
                <p className="mb-4 text-xs theme-muted">{o.clickRowHint[lang]}</p>

                <p className="mb-2 text-xs font-medium theme-muted">{o.rolePreset[lang]}</p>
                <div className="mb-4 flex flex-wrap gap-2">
                  {(
                    [
                      ["operator", o.presetOperator[lang]],
                      ["dept_leader", o.presetLeader[lang]],
                      ["dept_liaison", o.presetLiaison[lang]],
                      ["auditor", o.presetAuditor[lang]],
                      ["executive", o.presetExecutive[lang]],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className="rounded-full border theme-border px-2.5 py-1 text-xs hover:bg-slate-50 dark:hover:bg-slate-800"
                      onClick={() => applyRolePreset(id)}
                    >
                      {label}
                    </button>
                  ))}
                  <button type="button" className="rounded-full border theme-border px-2.5 py-1 text-xs theme-muted" onClick={clearRoles}>
                    {o.presetClear[lang]}
                  </button>
                </div>

                <label className="mb-1 block text-xs theme-muted">{o.primaryDept[lang]}</label>
                <select className="theme-input mb-3 w-full rounded-lg border px-3 py-2 text-sm" value={editPrimaryDept} onChange={(e) => setEditPrimaryDept(e.target.value)}>
                  <option value="">—</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
                <label className="mb-1 block text-xs theme-muted">{o.userTier[lang]}</label>
                <select className="theme-input mb-3 w-full rounded-lg border px-3 py-2 text-sm" value={editUserTier} onChange={(e) => setEditUserTier(e.target.value)}>
                  <option value="staff">{o.tierStaff[lang]}</option>
                  <option value="director">{o.tierDirector[lang]}</option>
                  <option value="executive">{o.tierExecUser[lang]}</option>
                </select>
                <label className="mb-3 flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={editIsActive} onChange={(e) => setEditIsActive(e.target.checked)} />
                  <span>{o.userActive[lang]}</span>
                </label>
                <p className="mb-2 text-xs theme-muted">{o.roles[lang]}</p>
                <div className="max-h-52 space-y-2 overflow-y-auto">
                  {ALL_ROLE_CODES.map((code) => (
                    <div key={code} className="rounded-lg border theme-border p-2">
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={!!editRoles[code]}
                          onChange={(e) => setEditRoles((prev) => ({ ...prev, [code]: e.target.checked }))}
                        />
                        <span>{roleLabel(code)}</span>
                      </label>
                      {editRoles[code] && SCOPED_ROLES.has(code) && (
                        <select
                          className="theme-input mt-1 w-full rounded border px-2 py-1 text-xs"
                          value={editScopeDept[code] ?? ""}
                          onChange={(e) => setEditScopeDept((prev) => ({ ...prev, [code]: e.target.value }))}
                        >
                          <option value="">{lang === "zh" ? "全公司 / 默认" : "All / default"}</option>
                          {departments.map((d) => (
                            <option key={d.id} value={d.id}>{d.name}</option>
                          ))}
                        </select>
                      )}
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button onClick={saveUserRoles} className="theme-btn-primary flex-1">{o.saveUser[lang]}</button>
                  <button
                    type="button"
                    className="theme-btn-secondary text-sm"
                    onClick={() => { setTab("preview"); }}
                  >
                    {o.tabPreview[lang]}
                  </button>
                </div>
              </div>
            ) : (
              <div className="theme-card flex items-center justify-center p-8 theme-muted">
                <Users className="mr-2 h-5 w-5" />
                {o.selectUser[lang]}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-6 theme-card p-6">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label className="text-sm theme-muted">{o.selectUser[lang]}</label>
            <select className="theme-input rounded-lg border px-3 py-2 text-sm" value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value)}>
              {orgUsers.map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          </div>
          {previewLoading ? (
            <p className="theme-muted">{c.loading?.[lang] ?? "Loading…"}</p>
          ) : previewError ? (
            <p className="theme-muted">{o.loadFail[lang]}</p>
          ) : preview ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div className="rounded-lg border theme-border p-4">
                <p className="text-xs theme-muted">{o.dataScope[lang]}</p>
                <p className="text-lg font-semibold theme-text">{preview.data_scope}</p>
              </div>
              <div className="rounded-lg border theme-border p-4">
                <p className="text-xs theme-muted">{o.visibleUsers[lang]}</p>
                <p className="text-lg font-semibold theme-text">{preview.visible_user_count}</p>
              </div>
              <div className="rounded-lg border theme-border p-4">
                <p className="text-xs theme-muted">{o.visibleDepts[lang]}</p>
                <p className="text-lg font-semibold theme-text">{preview.visible_department_count}</p>
              </div>
              <div className="rounded-lg border theme-border p-4">
                <p className="text-xs theme-muted">{o.canDashboard[lang]}</p>
                <p className="text-lg font-semibold theme-text">{preview.can_view_dashboard ? o.yes[lang] : o.no[lang]}</p>
              </div>
              <div className="rounded-lg border theme-border p-4">
                <p className="text-xs theme-muted">{o.canManageOrg[lang]}</p>
                <p className="text-lg font-semibold theme-text">{preview.can_manage_org ? o.yes[lang] : o.no[lang]}</p>
              </div>
              <div className="rounded-lg border theme-border p-4 sm:col-span-2">
                <p className="text-xs theme-muted">{o.roles[lang]}</p>
                <p className="mt-1 text-sm theme-text">
                  {preview.roles.map((r) => roleLabel(r.role_code)).join("、") || "—"}
                </p>
              </div>
              <div className="rounded-lg border theme-border p-4 sm:col-span-2">
                <p className="text-xs theme-muted">{lang === "zh" ? "有效权限" : "Effective permissions"}</p>
                <p className="mt-1 text-sm theme-text">{preview.permissions.join(", ") || "—"}</p>
              </div>
            </div>
          ) : (
            <p className="theme-muted">{lang === "zh" ? "请选择用户" : "Select a user"}</p>
          )}
        </div>
      )}
    </div>
  );
}
