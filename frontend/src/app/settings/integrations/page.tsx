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
  const [wecomEnabled, setWecomEnabled] = useState(false);
  const [wecomBotId, setWecomBotId] = useState("");
  const [wecomSecret, setWecomSecret] = useState("");
  const [wecomSecretSet, setWecomSecretSet] = useState(false);
  const [wecomChats, setWecomChats] = useState("");
  const [wecomBindings, setWecomBindings] = useState("");
  const [wecomSaving, setWecomSaving] = useState(false);
  const [wecomTesting, setWecomTesting] = useState(false);

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
    integrationsApi.wecom()
      .then(({ data }) => {
        const row = data as { enabled?: boolean; bot_id?: string; secret_set?: boolean; chat_ids?: string[]; bindings?: { wecom_userid?: string; login?: string }[] };
        setWecomEnabled(!!row.enabled);
        setWecomBotId(row.bot_id || "");
        setWecomSecretSet(!!row.secret_set);
        setWecomChats((row.chat_ids || []).join("\n"));
        const binds = (row.bindings || []) as { wecom_userid?: string; login?: string }[];
        setWecomBindings(binds.map((item) => `${item.wecom_userid}=${item.login}`).join("\n"));
      })
      .catch(() => {});
  }, [authReady, allowed, lang, o.loadFail]);

  const saveWecom = async () => {
    setWecomSaving(true);
    try {
      const chat_ids = wecomChats.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean);
      const { data } = await integrationsApi.saveWecom({
        enabled: wecomEnabled,
        bot_id: wecomBotId.trim(),
        secret: wecomSecret.trim() || undefined,
        chat_ids,
        bindings: wecomBindings.split(/\n+/).map((item) => item.trim()).filter(Boolean),
      });
      const row = data as { secret_set?: boolean; chat_ids?: string[] };
      setWecomSecret("");
      setWecomSecretSet(!!row.secret_set);
      setWecomChats((row.chat_ids || chat_ids).join("\n"));
      toast.success(lang === "zh" ? "企业微信推送已保存" : "WeCom push saved");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || (lang === "zh" ? "保存失败" : "Save failed"));
    } finally {
      setWecomSaving(false);
    }
  };

  const testWecom = async () => {
    setWecomTesting(true);
    try {
      const { data } = await integrationsApi.testWecom();
      const row = data as { ok?: boolean; skipped?: boolean; reason?: string; error?: string; sent?: string[] };
      if (row.ok) toast.success(lang === "zh" ? `已发送到 ${(row.sent || []).join("、")}` : "Sent");
      else toast.error(row.error || row.reason || (lang === "zh" ? "测试未发出" : "Test was not sent"));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || (lang === "zh" ? "测试失败" : "Test failed"));
    } finally {
      setWecomTesting(false);
    }
  };

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

          <div className="theme-card p-6 lg:col-span-2">
            <h2 className="text-lg font-semibold theme-text">{lang === "zh" ? "企业微信 · 数字员工推送" : "WeCom employee push"}</h2>
            <p className="mt-1 text-sm theme-muted">
              {lang === "zh"
                ? "企业微信里发给机器人的文字会进入平台对话。绑定 userid 后按该账号回答；没绑定的只记在管理员会话里。任务完成后仍可把报告摘要推给接收人。"
                : "After a task completes, the bot long connection sends a summary to these user ids."}
            </p>
            <label className="mt-4 flex items-center gap-2 text-sm theme-text">
              <input type="checkbox" checked={wecomEnabled} onChange={(e) => setWecomEnabled(e.target.checked)} />
              {lang === "zh" ? "启用推送" : "Enable push"}
            </label>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="block text-xs theme-muted">
                BotID
                <input className="input mt-1 w-full text-sm" value={wecomBotId} onChange={(e) => setWecomBotId(e.target.value)} />
              </label>
              <label className="block text-xs theme-muted">
                Secret
                <input
                  className="input mt-1 w-full text-sm"
                  type="password"
                  value={wecomSecret}
                  placeholder={wecomSecretSet ? (lang === "zh" ? "已保存，留空则不修改" : "Saved") : ""}
                  onChange={(e) => setWecomSecret(e.target.value)}
                />
              </label>
            </div>
            <label className="mt-3 block text-xs theme-muted">
              {lang === "zh" ? "接收人 userid，一行一个" : "Recipient user ids, one per line"}
              <textarea className="input mt-1 w-full min-h-[88px] text-sm" value={wecomChats} onChange={(e) => setWecomChats(e.target.value)} />
            </label>
            <label className="mt-3 block text-xs theme-muted">
              {lang === "zh" ? "账号绑定，一行一个：企业微信userid=平台工号或邮箱" : "Bindings"}
              <textarea className="input mt-1 w-full min-h-[88px] text-sm" value={wecomBindings} onChange={(e) => setWecomBindings(e.target.value)} />
            </label>
            <div className="mt-3 flex gap-2">
              <button type="button" className="btn-primary px-3 py-1.5 text-sm" disabled={wecomSaving} onClick={saveWecom}>
                {wecomSaving ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "保存" : "Save")}
              </button>
              <button type="button" className="btn-secondary px-3 py-1.5 text-sm" disabled={wecomTesting} onClick={testWecom}>
                {wecomTesting ? (lang === "zh" ? "发送中…" : "Sending…") : (lang === "zh" ? "发送测试" : "Send test")}
              </button>
            </div>
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
