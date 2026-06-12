"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Building2, Shield, Users } from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { organizationApi } from "@/lib/api";
import { canManageOrg } from "@/lib/permissions";
import { SegmentedControl } from "@/components/SegmentedControl";

type Tab = "depts" | "users" | "preview";

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

export default function OrganizationPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const o = translations.organization;
  const c = translations.common;

  const [tab, setTab] = useState<Tab>("depts");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const [newDeptName, setNewDeptName] = useState("");
  const [newDeptCode, setNewDeptCode] = useState("");
  const [newDeptParent, setNewDeptParent] = useState("");
  const [newDeptTier, setNewDeptTier] = useState("business");

  const [selectedUserId, setSelectedUserId] = useState("");
  const [editPrimaryDept, setEditPrimaryDept] = useState("");
  const [editUserTier, setEditUserTier] = useState("staff");
  const [editRoles, setEditRoles] = useState<Record<string, boolean>>({});
  const [editScopeDept, setEditScopeDept] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);

  const allowed = canManageOrg(user);

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
    if (allowed) loadAll();
    else setLoading(false);
  }, [allowed]);

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
  }, [selectedUser]);

  useEffect(() => {
    if (tab !== "preview" || !selectedUserId || !allowed) return;
    organizationApi.previewPermissions(selectedUserId)
      .then(({ data }) => setPreview(data))
      .catch(() => setPreview(null));
  }, [tab, selectedUserId, allowed]);

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
        roles,
      });
      toast.success(o.saved[lang]);
      await loadAll();
    } catch {
      toast.error(o.loadFail[lang]);
    }
  };

  const roleLabel = (code: string) => {
    const def = roleDefs.find((r) => r.role_code === code);
    if (!def) return code;
    return lang === "zh" ? def.label_zh : def.label_en;
  };

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
            { value: "depts", label: o.tabDepts[lang] },
            { value: "users", label: o.tabUsers[lang] },
            { value: "preview", label: o.tabPreview[lang] },
          ]}
        />
      </div>

      {loading ? (
        <p className="mt-8 theme-muted">{c.loading?.[lang] ?? "Loading…"}</p>
      ) : forbidden ? (
        <p className="mt-8 theme-muted">{o.forbidden[lang]}</p>
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
        <div className="mt-6 grid gap-6 lg:grid-cols-[280px_1fr]">
          <div className="theme-card p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold theme-text">
              <Users className="h-4 w-4" /> {o.selectUser[lang]}
            </h2>
            <ul className="max-h-[480px] space-y-1 overflow-y-auto">
              {orgUsers.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedUserId(u.id)}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm ${selectedUserId === u.id ? "nav-item-active" : "nav-item-idle"}`}
                  >
                    <div className="font-medium">{u.display_name}</div>
                    <div className="text-xs theme-muted">{u.employee_no || u.email}</div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {selectedUser && (
            <div className="theme-card p-6">
              <h2 className="mb-4 font-semibold theme-text">{selectedUser.display_name}</h2>
              <label className="mb-1 block text-xs theme-muted">{o.primaryDept[lang]}</label>
              <select
                className="theme-input mb-4 w-full rounded-lg border px-3 py-2 text-sm"
                value={editPrimaryDept}
                onChange={(e) => setEditPrimaryDept(e.target.value)}
              >
                <option value="">—</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
              <label className="mb-1 block text-xs theme-muted">{o.userTier[lang]}</label>
              <select
                className="theme-input mb-4 w-full rounded-lg border px-3 py-2 text-sm"
                value={editUserTier}
                onChange={(e) => setEditUserTier(e.target.value)}
              >
                <option value="staff">{o.tierStaff[lang]}</option>
                <option value="director">{o.tierDirector[lang]}</option>
                <option value="executive">{o.tierExecUser[lang]}</option>
              </select>
              <p className="mb-2 text-xs theme-muted">{o.roles[lang]}</p>
              <div className="space-y-3">
                {ALL_ROLE_CODES.map((code) => (
                  <div key={code} className="rounded-lg border theme-border p-3">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={!!editRoles[code]}
                        onChange={(e) => setEditRoles((prev) => ({ ...prev, [code]: e.target.checked }))}
                      />
                      <span>{roleLabel(code)}</span>
                      <span className="text-xs theme-muted">({code})</span>
                    </label>
                    {editRoles[code] && ["dept_leader", "executive", "auditor", "dept_liaison"].includes(code) && (
                      <select
                        className="theme-input mt-2 w-full rounded-lg border px-2 py-1 text-xs"
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
              <button onClick={saveUserRoles} className="theme-btn-primary mt-4">{o.saveUser[lang]}</button>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-6 theme-card p-6">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label className="text-sm theme-muted">{o.selectUser[lang]}</label>
            <select
              className="theme-input rounded-lg border px-3 py-2 text-sm"
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
            >
              {orgUsers.map((u) => (
                <option key={u.id} value={u.id}>{u.display_name}</option>
              ))}
            </select>
          </div>
          {preview ? (
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
                <p className="mt-1 text-sm theme-text">{preview.permissions.join(", ") || "—"}</p>
              </div>
            </div>
          ) : (
            <p className="theme-muted">{c.loading?.[lang] ?? "Loading…"}</p>
          )}
        </div>
      )}
    </div>
  );
}
