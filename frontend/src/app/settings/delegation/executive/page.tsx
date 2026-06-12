"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Crown } from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import { organizationApi } from "@/lib/api";
import { canDelegateExec } from "@/lib/permissions";
import { useAuthStore } from "@/lib/authStore";

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

      {loading ? (
        <p className="mt-8 theme-muted">{c.loading[lang]}</p>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[280px_1fr]">
          <div className="theme-card p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold theme-text">
              <Crown className="h-4 w-4" /> {o.selectUser[lang]}
            </h2>
            <ul className="max-h-[480px] space-y-1 overflow-y-auto">
              {users.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(u.id)}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm ${selectedId === u.id ? "nav-item-active" : "nav-item-idle"}`}
                  >
                    <div className="font-medium">{u.display_name}</div>
                    <div className="text-xs theme-muted">
                      {u.user_tier || "staff"} · {u.primary_department_name || u.employee_no}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {selected && (
            <div className="theme-card p-6">
              <h2 className="mb-4 font-semibold theme-text">{selected.display_name}</h2>

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
              <div className="space-y-3">
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
              <button onClick={save} className="theme-btn-primary mt-4">{o.saveUser[lang]}</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
