"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, MessageSquare, Shield } from "lucide-react";
import toast from "react-hot-toast";
import { useLangStore } from "@/lib/langStore";
import { useAuthStore } from "@/lib/authStore";
import { translations } from "@/lib/i18n";
import { integrationsApi } from "@/lib/api";
import { canManageOrg } from "@/lib/permissions";
import { useClientAuth } from "@/hooks/useClientAuth";

interface AdminStatus {
  feishu: {
    enabled: boolean;
    app_id?: string | null;
    verification_token_set: boolean;
    events_url: string;
  };
  dingtalk: {
    enabled: boolean;
    robot_webhook_set: boolean;
    events_url: string;
  };
  im_bot_user_id?: string | null;
}

export default function IntegrationsPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const { ready: authReady } = useClientAuth();
  const i = translations.integrations;
  const o = translations.organization;
  const c = translations.common;
  const allowed = authReady && canManageOrg(user);

  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!authReady) return;
    if (!allowed) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(false);
    integrationsApi.adminStatus()
      .then(({ data }) => setStatus(data))
      .catch(() => {
        setStatus(null);
        setLoadError(true);
        toast.error(o.loadFail[lang]);
      })
      .finally(() => setLoading(false));
  }, [authReady, allowed, lang, o.loadFail]);

  const badge = (ok: boolean, okLabel: string, failLabel: string) => (
    <span className={`rounded-full px-2 py-0.5 text-xs ${ok ? "bg-emerald-500/15 text-emerald-400" : "bg-slate-500/15 text-slate-400"}`}>
      {ok ? okLabel : failLabel}
    </span>
  );

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
          <ArrowLeft className="h-4 w-4" /> {i.backSettings[lang]}
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
        <ArrowLeft className="h-4 w-4" /> {i.backSettings[lang]}
      </Link>
      <h1 className="flex items-center gap-2 text-2xl font-bold theme-text">
        <MessageSquare className="h-7 w-7" /> {i.title[lang]}
      </h1>
      <p className="mt-1 text-sm theme-muted">{i.subtitle[lang]}</p>
      <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-200/90">
        {i.envHint[lang]}
      </p>

      {loading ? (
        <p className="mt-8 theme-muted">{c.loading?.[lang] ?? "Loading…"}</p>
      ) : loadError ? (
        <p className="mt-8 theme-muted">{o.loadFail[lang]}</p>
      ) : status ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div className="theme-card p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold theme-text">{i.feishu[lang]}</h2>
              {badge(status.feishu.enabled, i.enabled[lang], i.disabled[lang])}
            </div>
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-xs theme-muted">{i.configured[lang]}</dt>
                <dd className="mt-0.5">
                  {badge(!!status.feishu.app_id, i.configured[lang], i.notConfigured[lang])}
                </dd>
              </div>
              <div>
                <dt className="text-xs theme-muted">{i.eventsUrl[lang]}</dt>
                <dd className="mt-0.5 break-all rounded border theme-border bg-black/20 px-2 py-1 font-mono text-xs theme-text">
                  {status.feishu.events_url}
                </dd>
              </div>
              {status.feishu.app_id && (
                <div>
                  <dt className="text-xs theme-muted">App ID</dt>
                  <dd className="mt-0.5 font-mono text-xs theme-text">{status.feishu.app_id}</dd>
                </div>
              )}
            </dl>
          </div>

          <div className="theme-card p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold theme-text">{i.dingtalk[lang]}</h2>
              {badge(status.dingtalk.enabled, i.enabled[lang], i.disabled[lang])}
            </div>
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-xs theme-muted">{i.configured[lang]}</dt>
                <dd className="mt-0.5">
                  {badge(status.dingtalk.robot_webhook_set, i.configured[lang], i.notConfigured[lang])}
                </dd>
              </div>
              <div>
                <dt className="text-xs theme-muted">{i.eventsUrl[lang]}</dt>
                <dd className="mt-0.5 break-all rounded border theme-border bg-black/20 px-2 py-1 font-mono text-xs theme-text">
                  {status.dingtalk.events_url}
                </dd>
              </div>
            </dl>
          </div>

          {status.im_bot_user_id && (
            <div className="theme-card p-6 lg:col-span-2">
              <p className="text-xs theme-muted">IM_BOT_USER_ID</p>
              <p className="mt-1 font-mono text-sm theme-text">{status.im_bot_user_id}</p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
