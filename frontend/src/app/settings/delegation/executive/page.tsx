"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Crown, FileSpreadsheet, Search, Users } from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { organizationApi } from "@/lib/api";
import { canDelegateExec } from "@/lib/permissions";
import { useAuthStore } from "@/lib/authStore";
import { clsx } from "clsx";
import PermissionImportPanel from "@/components/organization/PermissionImportPanel";

interface OrgUser {
  id: string;
  display_name: string;
  employee_no?: string | null;
  primary_department_name?: string | null;
  user_tier?: string;
  roles: { role_code: string }[];
}

interface RoleDef {
  role_code: string;
  label_zh: string;
  label_en: string;
}

const EXEC_ROLES = ["executive", "auditor"];

export default function ExecutiveDelegationPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const d = translations.delegation;
  const o = translations.organization;
  const c = translations.common;
  const allowed = canDelegateExec(user);

  const [users, setUsers] = useState<OrgUser[]>([]);
  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [roles, setRoles] = useState<Record<string, boolean>>({});
  const [userTier, setUserTier] = useState("director");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showImport, setShowImport] = useState(false);
  const isFullAdmin = user?.is_admin || (user?.permissions ?? []).includes("users:manage");

  const load = async () => {
    setLoading(true);
    try {
      const [u, rolesRes] = await Promise.all([
        organizationApi.delegationExecutiveUsers(),
        organizationApi.delegatableRoles(),
      ]);
      setUsers(u.data);
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

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) =>
      [u.display_name, u.employee_no, u.primary_department_name, u.user_tier]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [users, search]);

  useEffect(() => {
    if (!selected) return;
    const r: Record<string, boolean> = {};
    for (const code of EXEC_ROLES) r[code] = false;
    for (const item of selected.roles) {
      if (EXEC_ROLES.includes(item.role_code)) r[item.role_code] = true;
    }
    setRoles(r);
    setUserTier(selected.user_tier || "director");
  }, [selected]);

  const roleLabel = (code: string) => {
    const def = roleDefs.find((r) => r.role_code === code);
    return def ? (lang === "zh" ? def.label_zh : def.label_en) : code;
  };

  const tierLabel = (tier?: string) => {
    if (tier === "executive") return o.tierExecUser[lang];
    if (tier === "director") return o.tierDirector[lang];
    return o.tierStaff[lang];
  };

  const applyPreset = (code: string) => {
    const r: Record<string, boolean> = {};
    for (const c of EXEC_ROLES) r[c] = c === code;
    setRoles(r);
    if (code === "executive") setUserTier("executive");
  };

  const save = async () => {
    if (!selectedId) return;
    const payloadRoles = EXEC_ROLES.filter((code) => roles[code]).map((code) => ({
      role_code: code,
      scope_department_id: null,
    }));
    try {
      await organizationApi.updateExecDelegation(selectedId, {
        roles: payloadRoles,
        ...(isFullAdmin ? { user_tier: userTier } : {}),
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
        <Link href="/settings" className="mb-4 inline-flex items-center gap-2 text-sm theme-muted hover:theme-text">
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
      <h1 className="text-2xl font-bold theme-text">{d.execTitle[lang]}</h1>
      <p className="mt-1 text-sm theme-muted">{d.execSubtitle[lang]}</p>
      <p className="mt-2 text-xs theme-muted">{d.execPoolHint[lang]}</p>

      <div className="mt-4">
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
        <div className="mt-6 space-y-4">
          <div className="relative max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 theme-muted" />
            <input
              className="theme-input w-full rounded-lg border py-2 pl-9 pr-3 text-sm"
              placeholder={o.searchUser[lang]}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
            <div className="theme-card overflow-hidden">
              <table className="w-full min-w-[520px] text-left text-sm">
                <thead>
                  <tr className="border-b theme-border bg-slate-50/50 text-xs theme-muted dark:bg-slate-900/30">
                    <th className="px-4 py-3">{o.colName[lang]}</th>
                    <th className="px-4 py-3">{o.userTier[lang]}</th>
                    <th className="px-4 py-3">{o.colDept[lang]}</th>
                    <th className="px-4 py-3">{o.colRoles[lang]}</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center theme-muted">{o.noUsersMatch[lang]}</td>
                    </tr>
                  ) : (
                    filteredUsers.map((u) => (
                      <tr
                        key={u.id}
                        onClick={() => setSelectedId(u.id)}
                        className={clsx(
                          "cursor-pointer border-b theme-border/60 hover:bg-slate-50/80 dark:hover:bg-slate-900/20",
                          selectedId === u.id && "bg-blue-50/80 dark:bg-blue-950/20",
                        )}
                      >
                        <td className="px-4 py-3">
                          <div className="font-medium">{u.display_name}</div>
                          <div className="text-xs theme-muted">{u.employee_no}</div>
                        </td>
                        <td className="px-4 py-3 theme-muted">{tierLabel(u.user_tier)}</td>
                        <td className="px-4 py-3 theme-muted">{u.primary_department_name || "—"}</td>
                        <td className="px-4 py-3">
                          {u.roles.map((r) => (
                            <span key={r.role_code} className="mr-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs dark:bg-slate-800">
                              {roleLabel(r.role_code)}
                            </span>
                          ))}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {selected ? (
              <div className="theme-card p-5 xl:sticky xl:top-4 xl:self-start">
                <h2 className="mb-1 flex items-center gap-2 font-semibold theme-text">
                  <Crown className="h-4 w-4" /> {selected.display_name}
                </h2>
                <p className="mb-4 text-xs theme-muted">{o.clickRowHint[lang]}</p>

                <div className="mb-4 flex flex-wrap gap-2">
                  {EXEC_ROLES.map((code) => (
                    <button
                      key={code}
                      type="button"
                      className="rounded-full border theme-border px-2.5 py-1 text-xs"
                      onClick={() => applyPreset(code)}
                    >
                      {roleLabel(code)}
                    </button>
                  ))}
                </div>

                {isFullAdmin && (
                  <>
                    <label className="mb-1 block text-xs theme-muted">{o.userTier[lang]}</label>
                    <select
                      className="theme-input mb-4 w-full rounded-lg border px-3 py-2 text-sm"
                      value={userTier}
                      onChange={(e) => setUserTier(e.target.value)}
                    >
                      <option value="staff">{o.tierStaff[lang]}</option>
                      <option value="director">{o.tierDirector[lang]}</option>
                      <option value="executive">{o.tierExecUser[lang]}</option>
                    </select>
                  </>
                )}

                <p className="mb-2 text-xs theme-muted">{d.assignRoles[lang]}</p>
                <div className="space-y-2">
                  {EXEC_ROLES.map((code) => (
                    <label key={code} className="flex items-center gap-2 rounded-lg border theme-border p-3 text-sm">
                      <input
                        type="checkbox"
                        checked={!!roles[code]}
                        onChange={(e) => setRoles((prev) => ({ ...prev, [code]: e.target.checked }))}
                      />
                      {roleLabel(code)}
                    </label>
                  ))}
                </div>
                <button onClick={save} className="theme-btn-primary mt-4 w-full">{o.saveUser[lang]}</button>
              </div>
            ) : (
              <div className="theme-card flex items-center justify-center p-8 theme-muted">
                <Users className="mr-2 h-5 w-5" />
                {o.selectUser[lang]}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
