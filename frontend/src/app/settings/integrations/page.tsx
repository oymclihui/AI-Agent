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

interface WecomStyle {
  theme: string;
  font_size: string;
  zebra: boolean;
  show_title: boolean;
  show_table: boolean;
  show_chart: boolean;
  table_max_rows: number;
  table_dpi: number;
  table_max_width: number;
  show_thousands: boolean;
  truncate_hint: string;
  chart_type: string;
  show_value_labels: boolean;
  show_legend: boolean;
  show_chart_title: boolean;
  show_analysis: boolean;
  chart_width: number;
  chart_height: number;
  chart_dpi: number;
  chart_max_labels: number;
  text_template: string;
  clip_bytes: number;
  chat_limit: number;
  bind_hint: string;
  empty_hint: string;
  feedback_card: boolean;
  voice_reply: boolean;
  voice_name: string;
  voice_max_chars: number;
  voice_rate: string;
  voice_volume: string;
  voice_pitch: string;
  voice_quiet_from: number;
  voice_quiet_to: number;
  preview_rows: number;
  ask_temperature: number;
  cache_ttl: number;
}

const DEFAULT_STYLE: WecomStyle = {
  theme: "blue",
  font_size: "medium",
  zebra: true,
  show_title: true,
  show_table: true,
  show_chart: true,
  table_max_rows: 0,
  table_dpi: 200,
  table_max_width: 10,
  show_thousands: true,
  truncate_hint: "仅显示前 {n} 行",
  chart_type: "auto",
  show_value_labels: true,
  show_legend: true,
  show_chart_title: false,
  show_analysis: true,
  chart_width: 7.6,
  chart_height: 4.4,
  chart_dpi: 200,
  chart_max_labels: 0,
  text_template: "",
  clip_bytes: 20480,
  chat_limit: 20,
  bind_hint: "",
  empty_hint: "",
  feedback_card: true,
  voice_reply: false,
  voice_name: "zh-CN-XiaoxiaoNeural",
  voice_max_chars: 260,
  voice_rate: "+0%",
  voice_volume: "+0%",
  voice_pitch: "+0Hz",
  voice_quiet_from: -1,
  voice_quiet_to: -1,
  preview_rows: 200,
  ask_temperature: -1,
  cache_ttl: 300,
};

const CHART_TYPES = [
  { key: "auto", label: "自动", labelEn: "Auto" },
  { key: "bar", label: "柱状", labelEn: "Bar" },
  { key: "barh", label: "条形", labelEn: "BarH" },
  { key: "line", label: "折线", labelEn: "Line" },
  { key: "area", label: "面积", labelEn: "Area" },
  { key: "pie", label: "饼图", labelEn: "Pie" },
];

const TABLE_THEMES = [
  { key: "blue", color: "#1e40af", label: "商务蓝", labelEn: "Blue" },
  { key: "green", color: "#0f766e", label: "青绿", labelEn: "Green" },
  { key: "purple", color: "#6d28d9", label: "紫罗兰", labelEn: "Purple" },
  { key: "orange", color: "#c2410c", label: "暖橙", labelEn: "Orange" },
  { key: "dark", color: "#1f2937", label: "石墨黑", labelEn: "Dark" },
];

const TABLE_ZEBRA: Record<string, string> = {
  blue: "#f8fafc",
  green: "#f0fdfa",
  purple: "#faf5ff",
  orange: "#fff7ed",
  dark: "#f3f5f9",
};

const FONT_SIZES = [
  { key: "small", label: "小", labelEn: "S", px: 10 },
  { key: "medium", label: "中", labelEn: "M", px: 11 },
  { key: "large", label: "大", labelEn: "L", px: 12.5 },
];

export default function IntegrationsPage() {
  const { lang } = useLangStore();
  const user = useAuthStore((s) => s.user);
  const { ready: authReady } = useClientAuth();
  const i = translations.integrations;
  const o = translations.organization;
  const c = translations.common;
  const allowed = authReady && canManageOrg(user);

  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [imStats, setImStats] = useState<{
    month: string; im_total: number; platform_total: number; im_pct: number;
    items: { channel: string; conversations: number; pct: number }[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [wecomEnabled, setWecomEnabled] = useState(false);
  const [wecomBotId, setWecomBotId] = useState("");
  const [wecomSecret, setWecomSecret] = useState("");
  const [wecomSecretSet, setWecomSecretSet] = useState(false);
  const [wecomChats, setWecomChats] = useState("");
  const [wecomBindings, setWecomBindings] = useState("");
  const [wecomCorpId, setWecomCorpId] = useState("");
  const [wecomCorpSecret, setWecomCorpSecret] = useState("");
  const [wecomCorpSecretSet, setWecomCorpSecretSet] = useState(false);
  const [wecomAutoSync, setWecomAutoSync] = useState(false);
  const [wecomStyle, setWecomStyle] = useState<WecomStyle>(DEFAULT_STYLE);
  const [wecomLastSync, setWecomLastSync] = useState("");
  const [wecomSyncing, setWecomSyncing] = useState(false);
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
        const row = data as {
          enabled?: boolean; bot_id?: string; secret_set?: boolean; chat_ids?: string[];
          bindings?: { wecom_userid?: string; login?: string }[];
          corp_id?: string; corp_secret_set?: boolean; auto_sync?: boolean;
          last_sync?: { at?: string; contacts?: number; added?: number; unmatched?: number };
          style?: Partial<WecomStyle>;
        };
        setWecomEnabled(!!row.enabled);
        setWecomBotId(row.bot_id || "");
        setWecomSecretSet(!!row.secret_set);
        setWecomChats((row.chat_ids || []).join("\n"));
        const binds = (row.bindings || []) as { wecom_userid?: string; login?: string }[];
        setWecomBindings(binds.map((item) => `${item.wecom_userid}=${item.login}`).join("\n"));
        setWecomCorpId(row.corp_id || "");
        setWecomCorpSecretSet(!!row.corp_secret_set);
        setWecomAutoSync(!!row.auto_sync);
        setWecomStyle({ ...DEFAULT_STYLE, ...(row.style || {}) });
        const last = row.last_sync || {};
        setWecomLastSync(
          last.at
            ? `${last.at} · ${lang === "zh" ? "通讯录" : "contacts"} ${last.contacts || 0} · ${lang === "zh" ? "新增" : "added"} ${last.added || 0} · ${lang === "zh" ? "未匹配" : "unmatched"} ${last.unmatched || 0}`
            : "",
        );
      })
      .catch(() => {});
    integrationsApi.imStats()
      .then(({ data }) => setImStats(data as typeof imStats))
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
        corp_id: wecomCorpId.trim(),
        corp_secret: wecomCorpSecret.trim() || undefined,
        auto_sync: wecomAutoSync,
        style: wecomStyle,
      });
      const row = data as { secret_set?: boolean; corp_secret_set?: boolean; chat_ids?: string[] };
      setWecomSecret("");
      setWecomSecretSet(!!row.secret_set);
      setWecomCorpSecret("");
      setWecomCorpSecretSet(!!row.corp_secret_set);
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

  const syncWecomContacts = async () => {
    setWecomSyncing(true);
    try {
      const { data } = await integrationsApi.syncWecomContacts();
      const row = data as {
        contacts?: number; added?: unknown[]; unmatched?: string[]; bindings_total?: number;
        last_sync?: { at?: string; contacts?: number; added?: number; unmatched?: number };
      };
      const last = row.last_sync || {};
      setWecomLastSync(
        last.at
          ? `${last.at} · ${lang === "zh" ? "通讯录" : "contacts"} ${last.contacts || 0} · ${lang === "zh" ? "新增" : "added"} ${last.added || 0} · ${lang === "zh" ? "未匹配" : "unmatched"} ${last.unmatched || 0}`
          : "",
      );
      const refreshed = await integrationsApi.wecom();
      const binds = ((refreshed.data as { bindings?: { wecom_userid?: string; login?: string }[] }).bindings || []);
      setWecomBindings(binds.map((item) => `${item.wecom_userid}=${item.login}`).join("\n"));
      toast.success(
        lang === "zh"
          ? `已同步：通讯录 ${row.contacts || 0} 人，新增映射 ${(row.added || []).length} 条，未匹配 ${(row.unmatched || []).length} 个`
          : `Synced ${row.contacts || 0} contacts, ${(row.added || []).length} added`,
      );
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || (lang === "zh" ? "同步失败" : "Sync failed"));
    } finally {
      setWecomSyncing(false);
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
        <div className="mt-6 space-y-6">
          {imStats && (
            <div className="theme-card p-6">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold theme-text">
                  {lang === "zh" ? `IM 月活（${imStats.month}）` : `IM Monthly Active (${imStats.month})`}
                </h2>
                <span className="text-sm theme-muted">
                  {lang === "zh" ? "目标：IM 月活 ≥ 全平台 30%" : "Target: IM ≥ 30% of platform"}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-6">
                <div>
                  <p className="text-3xl font-bold theme-text">{imStats.im_pct}%</p>
                  <p className="text-xs theme-muted">
                    {lang === "zh" ? "IM 会话占比" : "IM share"}
                  </p>
                </div>
                <div className="min-w-[220px] flex-1">
                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-gray-200">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, Math.max(2, imStats.im_pct * 100 / 30))}%`,
                        background: imStats.im_pct >= 30 ? "#16a34a" : "#d97706",
                      }}
                    />
                  </div>
                  <p className="mt-1 text-xs theme-muted">
                    {imStats.im_total} / {imStats.platform_total}{" "}
                    {lang === "zh" ? "活跃会话" : "active conversations"}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {imStats.items.map((it) => (
                    <span
                      key={it.channel}
                      className="rounded-full border border-gray-200 px-3 py-1 text-xs theme-muted"
                    >
                      {it.channel} · {it.conversations} ({it.pct}%)
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
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
            <div className="mt-4 rounded-lg border border-[#2d2d4e] p-3">
              <p className="text-xs theme-muted">
                {lang === "zh" ? "通讯录自动映射（企微 userid → 平台工号/邮箱）" : "Contacts auto-mapping"}
              </p>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                <label className="block text-xs theme-muted">
                  {lang === "zh" ? "企业ID（corpid）" : "Corp ID"}
                  <input className="input mt-1 w-full text-sm" value={wecomCorpId} onChange={(e) => setWecomCorpId(e.target.value)} />
                </label>
                <label className="block text-xs theme-muted">
                  {lang === "zh" ? "通讯录 Secret（自建应用）" : "Contacts secret"}
                  <input
                    className="input mt-1 w-full text-sm"
                    type="password"
                    value={wecomCorpSecret}
                    placeholder={wecomCorpSecretSet ? (lang === "zh" ? "已保存，留空则不修改" : "Saved") : ""}
                    onChange={(e) => setWecomCorpSecret(e.target.value)}
                  />
                </label>
              </div>
              <label className="mt-3 flex items-center gap-2 text-sm theme-text">
                <input type="checkbox" checked={wecomAutoSync} onChange={(e) => setWecomAutoSync(e.target.checked)} />
                {lang === "zh" ? "新用户首次提问时自动反查并绑定" : "Auto-map on first message"}
              </label>
              <div className="mt-2 flex items-center gap-2">
                <button type="button" className="btn-secondary px-3 py-1.5 text-sm" disabled={wecomSyncing} onClick={syncWecomContacts}>
                  {wecomSyncing ? (lang === "zh" ? "同步中…" : "Syncing…") : (lang === "zh" ? "立即同步通讯录" : "Sync contacts now")}
                </button>
                {wecomLastSync && <span className="text-xs theme-muted">{wecomLastSync}</span>}
              </div>
              <p className="mt-2 text-[11px] theme-muted">
                {lang === "zh"
                  ? "需在企业微信后台创建自建应用并开启「通讯录」读取权限；匹配顺序：userid=工号 → 别名=工号 → 邮箱 → 自定义字段（工号/员工编号）。"
                  : "Requires a custom app with contacts read permission. Match order: userid, alias, email, custom 工号 field."}
              </p>
            </div>
            <label className="mt-3 block text-xs theme-muted">
              {lang === "zh" ? "接收人 userid，一行一个" : "Recipient user ids, one per line"}
              <textarea className="input mt-1 w-full min-h-[88px] text-sm" value={wecomChats} onChange={(e) => setWecomChats(e.target.value)} />
            </label>
            <label className="mt-3 block text-xs theme-muted">
              {lang === "zh" ? "账号绑定，一行一个：企业微信userid=平台工号或邮箱" : "Bindings"}
              <textarea className="input mt-1 w-full min-h-[88px] text-sm" value={wecomBindings} onChange={(e) => setWecomBindings(e.target.value)} />
            </label>
            <div className="mt-4 rounded-lg border border-[#2d2d4e] p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs theme-muted">
                  {lang === "zh" ? "问数显示样式（企微表格 / 图表）" : "Data answer style (table / chart)"}
                </p>
                <button
                  type="button"
                  onClick={() => setWecomStyle(DEFAULT_STYLE)}
                  className="rounded border border-[#2d2d4e] px-2 py-0.5 text-[11px] theme-muted"
                >
                  {lang === "zh" ? "恢复默认" : "Reset"}
                </button>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                <span className="mr-1 text-[11px] theme-muted">{lang === "zh" ? "主题色" : "Theme"}</span>
                {TABLE_THEMES.map((item) => (
                  <button
                    type="button"
                    key={item.key}
                    onClick={() => setWecomStyle({ ...wecomStyle, theme: item.key })}
                    className={`flex items-center gap-1 rounded border px-2 py-1 text-[11px] ${
                      wecomStyle.theme === item.key ? "border-white/60 theme-text" : "border-transparent theme-muted"
                    }`}
                  >
                    <span className="h-3 w-3 rounded-sm" style={{ background: item.color }} />
                    {lang === "zh" ? item.label : item.labelEn}
                  </button>
                ))}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                <span className="mr-1 text-[11px] theme-muted">{lang === "zh" ? "字号" : "Font size"}</span>
                {FONT_SIZES.map((item) => (
                  <button
                    type="button"
                    key={item.key}
                    onClick={() => setWecomStyle({ ...wecomStyle, font_size: item.key })}
                    className={`rounded border px-3 py-1 text-[11px] ${
                      wecomStyle.font_size === item.key ? "border-white/60 theme-text" : "border-transparent theme-muted"
                    }`}
                  >
                    {lang === "zh" ? item.label : item.labelEn}
                  </button>
                ))}
              </div>
              <div className="mt-2 grid gap-1 sm:grid-cols-2">
                {[
                  { key: "zebra", zh: "斑马纹行", en: "Zebra rows" },
                  { key: "show_title", zh: "显示表格标题", en: "Show title" },
                  { key: "show_thousands", zh: "数字千分位", en: "Thousands" },
                ].map((item) => (
                  <label key={item.key} className="flex items-center gap-2 text-sm theme-text">
                    <input
                      type="checkbox"
                      checked={!!wecomStyle[item.key as keyof WecomStyle]}
                      onChange={(e) =>
                        setWecomStyle({ ...wecomStyle, [item.key]: e.target.checked } as WecomStyle)
                      }
                    />
                    {lang === "zh" ? item.zh : item.en}
                  </label>
                ))}
              </div>

              <p className="mt-3 text-[11px] theme-muted">{lang === "zh" ? "表格参数" : "Table"}</p>
              <div className="mt-1 grid gap-2 sm:grid-cols-3">
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "最大行数（0=不限制）" : "Max rows (0 = unlimited)"}
                  <input
                    type="number" min={0} max={1000} className="input mt-1 w-full text-sm"
                    value={wecomStyle.table_max_rows}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, table_max_rows: Number(e.target.value) || DEFAULT_STYLE.table_max_rows })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "清晰度 DPI" : "DPI"}
                  <input
                    type="number" min={100} max={400} step={50} className="input mt-1 w-full text-sm"
                    value={wecomStyle.table_dpi}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, table_dpi: Number(e.target.value) || DEFAULT_STYLE.table_dpi })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "最大宽度（英寸）" : "Max width (in)"}
                  <input
                    type="number" min={4} max={20} step={0.5} className="input mt-1 w-full text-sm"
                    value={wecomStyle.table_max_width}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, table_max_width: Number(e.target.value) || DEFAULT_STYLE.table_max_width })}
                  />
                </label>
              </div>
              <label className="mt-2 block text-[11px] theme-muted">
                {lang === "zh" ? "截断提示文案（{n} 为行数）" : "Truncate hint ({n} = rows)"}
                <input
                  className="input mt-1 w-full text-sm"
                  value={wecomStyle.truncate_hint}
                  onChange={(e) => setWecomStyle({ ...wecomStyle, truncate_hint: e.target.value })}
                />
              </label>

              <p className="mt-3 text-[11px] theme-muted">{lang === "zh" ? "图表参数" : "Chart"}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1">
                {CHART_TYPES.map((item) => (
                  <button
                    type="button"
                    key={item.key}
                    onClick={() => setWecomStyle({ ...wecomStyle, chart_type: item.key })}
                    className={`rounded border px-2 py-1 text-[11px] ${
                      wecomStyle.chart_type === item.key ? "border-white/60 theme-text" : "border-transparent theme-muted"
                    }`}
                  >
                    {lang === "zh" ? item.label : item.labelEn}
                  </button>
                ))}
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-4">
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "宽度（英寸）" : "Width"}
                  <input
                    type="number" min={4} max={14} step={0.2} className="input mt-1 w-full text-sm"
                    value={wecomStyle.chart_width}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, chart_width: Number(e.target.value) || DEFAULT_STYLE.chart_width })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "高度（英寸）" : "Height"}
                  <input
                    type="number" min={2.5} max={10} step={0.2} className="input mt-1 w-full text-sm"
                    value={wecomStyle.chart_height}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, chart_height: Number(e.target.value) || DEFAULT_STYLE.chart_height })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "清晰度 DPI" : "DPI"}
                  <input
                    type="number" min={100} max={400} step={50} className="input mt-1 w-full text-sm"
                    value={wecomStyle.chart_dpi}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, chart_dpi: Number(e.target.value) || DEFAULT_STYLE.chart_dpi })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "标签上限（0 不限）" : "Max labels (0 = all)"}
                  <input
                    type="number" min={0} max={200} className="input mt-1 w-full text-sm"
                    value={wecomStyle.chart_max_labels}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, chart_max_labels: Number(e.target.value) || 0 })}
                  />
                </label>
              </div>
              <div className="mt-2 grid gap-1 sm:grid-cols-2">
                {[
                  { key: "show_value_labels", zh: "显示数值标签", en: "Value labels" },
                  { key: "show_legend", zh: "显示图例", en: "Legend" },
                  { key: "show_chart_title", zh: "显示图表标题", en: "Chart title" },
                ].map((item) => (
                  <label key={item.key} className="flex items-center gap-2 text-sm theme-text">
                    <input
                      type="checkbox"
                      checked={!!wecomStyle[item.key as keyof WecomStyle]}
                      onChange={(e) =>
                        setWecomStyle({ ...wecomStyle, [item.key]: e.target.checked } as WecomStyle)
                      }
                    />
                    {lang === "zh" ? item.zh : item.en}
                  </label>
                ))}
              </div>

              <p className="mt-3 text-[11px] theme-muted">{lang === "zh" ? "文本与发送" : "Text & delivery"}</p>
              <label className="mt-1 block text-[11px] theme-muted">
                {lang === "zh" ? "回答模板（留空用默认：{结论}{分析}{建议}{行数}）" : "Answer template (empty = default)"}
                <textarea
                  className="input mt-1 w-full min-h-[64px] text-xs"
                  placeholder="{结论}\n\n{分析}\n{建议}\n{行数}"
                  value={wecomStyle.text_template}
                  onChange={(e) => setWecomStyle({ ...wecomStyle, text_template: e.target.value })}
                />
              </label>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "文本上限（字节，按 5000 字发送）" : "Text limit (bytes, 5000 characters)"}
                  <input
                    type="number" min={500} max={20480} step={100} className="input mt-1 w-full text-sm"
                    value={wecomStyle.clip_bytes}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, clip_bytes: Number(e.target.value) || DEFAULT_STYLE.clip_bytes })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "接收人上限（1-100）" : "Recipient limit"}
                  <input
                    type="number" min={1} max={100} className="input mt-1 w-full text-sm"
                    value={wecomStyle.chat_limit}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, chat_limit: Number(e.target.value) || DEFAULT_STYLE.chat_limit })}
                  />
                </label>
              </div>
              <p className="mt-3 text-[11px] theme-muted">{lang === "zh" ? "语音播报" : "Voice reply"}</p>
              <div className="mt-1 grid gap-2 sm:grid-cols-3">
                <label className="flex items-center gap-2 text-sm theme-text">
                  <input
                    type="checkbox"
                    checked={!!wecomStyle.voice_reply}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_reply: e.target.checked })}
                  />
                  {lang === "zh" ? "文字回答同时发语音" : "Also send voice"}
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "音色" : "Voice"}
                  <select
                    className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_name}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_name: e.target.value })}
                  >
                    <option value="zh-CN-XiaoxiaoNeural">{lang === "zh" ? "晓晓（女声·默认）" : "Xiaoxiao (F)"}</option>
                    <option value="zh-CN-XiaoyiNeural">{lang === "zh" ? "晓伊（女声）" : "Xiaoyi (F)"}</option>
                    <option value="zh-CN-YunxiNeural">{lang === "zh" ? "云希（男声）" : "Yunxi (M)"}</option>
                    <option value="zh-CN-YunyangNeural">{lang === "zh" ? "云扬（男声）" : "Yunyang (M)"}</option>
                    <option value="zh-CN-YunjianNeural">{lang === "zh" ? "云健（男声）" : "Yunjian (M)"}</option>
                  </select>
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "语音最大字数（40-400）" : "Voice max chars"}
                  <input
                    type="number" min={40} max={400} step={10} className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_max_chars}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_max_chars: Number(e.target.value) || DEFAULT_STYLE.voice_max_chars })}
                  />
                </label>
              </div>
              <div className="mt-1 grid gap-2 sm:grid-cols-3">
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "语速" : "Rate"}
                  <select
                    className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_rate}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_rate: e.target.value })}
                  >
                    <option value="-30%">{lang === "zh" ? "慢 30%" : "-30%"}</option>
                    <option value="-10%">{lang === "zh" ? "慢 10%" : "-10%"}</option>
                    <option value="+0%">{lang === "zh" ? "正常" : "+0%"}</option>
                    <option value="+10%">{lang === "zh" ? "快 10%" : "+10%"}</option>
                    <option value="+30%">{lang === "zh" ? "快 30%" : "+30%"}</option>
                  </select>
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "音量" : "Volume"}
                  <select
                    className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_volume}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_volume: e.target.value })}
                  >
                    <option value="-30%">{lang === "zh" ? "低 30%" : "-30%"}</option>
                    <option value="-10%">{lang === "zh" ? "低 10%" : "-10%"}</option>
                    <option value="+0%">{lang === "zh" ? "正常" : "+0%"}</option>
                    <option value="+10%">{lang === "zh" ? "高 10%" : "+10%"}</option>
                    <option value="+30%">{lang === "zh" ? "高 30%" : "+30%"}</option>
                  </select>
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "音调" : "Pitch"}
                  <select
                    className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_pitch}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_pitch: e.target.value })}
                  >
                    <option value="-10Hz">{lang === "zh" ? "低 10Hz" : "-10Hz"}</option>
                    <option value="-5Hz">{lang === "zh" ? "低 5Hz" : "-5Hz"}</option>
                    <option value="+0Hz">{lang === "zh" ? "正常" : "+0Hz"}</option>
                    <option value="+5Hz">{lang === "zh" ? "高 5Hz" : "+5Hz"}</option>
                    <option value="+10Hz">{lang === "zh" ? "高 10Hz" : "+10Hz"}</option>
                  </select>
                </label>
              </div>
              <div className="mt-1 grid gap-2 sm:grid-cols-3">
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "静音开始（整点，-1 不启用）" : "Quiet from (hour, -1 off)"}
                  <input
                    type="number" min={-1} max={23} step={1} className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_quiet_from}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_quiet_from: Math.max(-1, Math.min(23, Number(e.target.value) || 0)) })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "静音结束（整点，可跨夜）" : "Quiet to"}
                  <input
                    type="number" min={-1} max={23} step={1} className="input mt-1 w-full text-sm"
                    value={wecomStyle.voice_quiet_to}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, voice_quiet_to: Math.max(-1, Math.min(23, Number(e.target.value) || 0)) })}
                  />
                </label>
                <p className="self-end text-[11px] theme-muted">
                  {lang === "zh" ? "如 22 到 8：22 点后到次日 8 点前不发语音。" : "e.g. 22 to 8: no voice at night."}
                </p>
              </div>
              <label className="mt-2 flex items-center gap-2 text-sm theme-text">
                <input
                  type="checkbox"
                  checked={!!wecomStyle.feedback_card}
                  onChange={(e) => setWecomStyle({ ...wecomStyle, feedback_card: e.target.checked })}
                />
                {lang === "zh" ? "发送底部反馈卡片（点赞/点踩）" : "Send feedback card"}
              </label>
              <p className="mt-3 text-[11px] theme-muted">{lang === "zh" ? "问数与文案" : "Data ask & messages"}</p>
              <label className="mt-1 block text-[11px] theme-muted">
                {lang === "zh" ? "未绑定提示（{userid} 会替换成对方 userid）" : "Unbound hint ({userid} placeholder)"}
                <textarea
                  className="input mt-1 w-full min-h-[56px] text-xs"
                  placeholder={lang === "zh" ? "留空用默认提示" : "Empty = default hint"}
                  value={wecomStyle.bind_hint}
                  onChange={(e) => setWecomStyle({ ...wecomStyle, bind_hint: e.target.value })}
                />
              </label>
              <label className="mt-2 block text-[11px] theme-muted">
                {lang === "zh" ? "无文本内容时的提示" : "Empty result hint"}
                <input
                  className="input mt-1 w-full text-sm"
                  placeholder={lang === "zh" ? "留空用默认提示" : "Empty = default"}
                  value={wecomStyle.empty_hint}
                  onChange={(e) => setWecomStyle({ ...wecomStyle, empty_hint: e.target.value })}
                />
              </label>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "结果预览行数（20-500）" : "Preview rows"}
                  <input
                    type="number" min={20} max={500} step={10} className="input mt-1 w-full text-sm"
                    value={wecomStyle.preview_rows}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, preview_rows: Number(e.target.value) || DEFAULT_STYLE.preview_rows })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "模型温度（-1 表示不干预）" : "Temperature (-1 = model default)"}
                  <input
                    type="number" min={-1} max={1} step={0.05} className="input mt-1 w-full text-sm"
                    value={wecomStyle.ask_temperature}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, ask_temperature: Number(e.target.value) })}
                  />
                </label>
                <label className="text-[11px] theme-muted">
                  {lang === "zh" ? "结果缓存（秒，0=不缓存）" : "Cache TTL (0 = off)"}
                  <input
                    type="number" min={0} max={3600} step={30} className="input mt-1 w-full text-sm"
                    value={wecomStyle.cache_ttl}
                    onChange={(e) => setWecomStyle({ ...wecomStyle, cache_ttl: Number(e.target.value) })}
                  />
                </label>
              </div>
              <div className="mt-2 grid gap-1 sm:grid-cols-2">
                {[
                  { key: "show_table", zh: "发送表格图片", en: "Table image" },
                  { key: "show_chart", zh: "发送图表图片", en: "Chart image" },
                  { key: "show_analysis", zh: "显示分析文字", en: "Analysis text" },
                ].map((item) => (
                  <label key={item.key} className="flex items-center gap-2 text-sm theme-text">
                    <input
                      type="checkbox"
                      checked={!!wecomStyle[item.key as keyof WecomStyle]}
                      onChange={(e) =>
                        setWecomStyle({ ...wecomStyle, [item.key]: e.target.checked } as WecomStyle)
                      }
                    />
                    {lang === "zh" ? item.zh : item.en}
                  </label>
                ))}
              </div>
              <div className="mt-3 rounded border border-gray-200 bg-white p-2">
                <p className="mb-1 text-[10px] text-gray-500">{lang === "zh" ? "效果预览" : "Preview"}</p>
                {wecomStyle.show_table ? (
                  <>
                    {wecomStyle.show_title && (
                      <div className="mb-1 text-center font-semibold" style={{ fontSize: 13, color: "#14181f" }}>
                        {lang === "zh" ? "销售额对比" : "Sales"}
                      </div>
                    )}
                    <table
                      className="w-full border-collapse"
                      style={{
                        fontSize:
                          FONT_SIZES.find((f) => f.key === wecomStyle.font_size)?.px || 11,
                      }}
                    >
                      <thead>
                        <tr
                          style={{
                            background:
                              TABLE_THEMES.find((t) => t.key === wecomStyle.theme)?.color || "#1e40af",
                            color: "#fff",
                          }}
                        >
                          <th className="border border-[#e4e7ec] px-2 py-1 text-left font-semibold">
                            {lang === "zh" ? "品类" : "Category"}
                          </th>
                          <th className="border border-[#e4e7ec] px-2 py-1 text-right font-semibold">
                            {lang === "zh" ? "销售额" : "Amount"}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          ["生鲜", wecomStyle.show_thousands ? "2,097,985.53" : "2097985.53"],
                          ["食品", wecomStyle.show_thousands ? "1,458,481.30" : "1458481.30"],
                          ["非食", wecomStyle.show_thousands ? "281,876.56" : "281876.56"],
                        ].map(([k, v], idx) => (
                          <tr
                            key={k}
                            style={{
                              background:
                                wecomStyle.zebra && idx % 2 === 1
                                  ? TABLE_ZEBRA[wecomStyle.theme]
                                  : "#fff",
                              color: "#14181f",
                            }}
                          >
                            <td className="border border-[#e4e7ec] px-2 py-1 text-left">{k}</td>
                            <td className="border border-[#e4e7ec] px-2 py-1 text-right">{v}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <p className="text-[11px] text-gray-500">
                    {lang === "zh" ? "已关闭表格图片，企微只发文本结论" : "Table image off, text only"}
                  </p>
                )}
                {!wecomStyle.show_chart && (
                  <p className="mt-1 text-[10px] text-gray-400">
                    {lang === "zh" ? "图表图片已关闭" : "Chart image off"}
                  </p>
                )}
              </div>
            </div>
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
        </div>
      ) : null}
    </div>
  );
}
