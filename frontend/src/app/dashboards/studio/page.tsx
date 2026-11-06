"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowUp,
  Bell,
  CalendarClock,
  ChevronLeft,
  ExternalLink,
  Gauge,
  History,
  LayoutDashboard,
  Link2,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  Share2,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { dataSourcesApi, formatApiError, studioApi } from "@/lib/api";
import { getAuthToken } from "@/lib/authStore";
import { WidgetCard, type Widget } from "@/components/WidgetRenderer";

interface SourceItem {
  id: string;
  name?: string;
}

interface BoardRow {
  id: string;
  name: string;
  status: string;
  version: number;
  widget_count: number;
  updated_at?: string;
}

interface StudioWidget extends Widget {
  spec_id?: string;
  spec?: Record<string, unknown>;
  rows?: unknown[][];
  facts?: { text?: string }[];
  chart?: Record<string, unknown>;
  error?: string;
  sort_order?: number;
}

interface BoardDetail {
  id: string;
  name: string;
  data_source_id: string;
  status: string;
  version: number;
  filters: unknown[];
  widgets: StudioWidget[];
}

interface VersionRow {
  id: string;
  version: number;
  anchor_status?: string | null;
  created_at?: string | null;
  widget_count: number;
  html_url: string;
}

interface SubRow {
  id: string;
  period: string;
  hour: number;
  minute: number;
  weekday: number;
  channel: string;
  target: string;
  active: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
}

interface RunRow {
  id: string;
  status: string;
  delivered: boolean;
  channel: string;
  summary: { label: string; value: unknown }[];
  error?: string | null;
  created_at?: string | null;
  html_url: string;
}

interface AlertRow {
  id: string;
  name: string;
  metric_name: string;
  metric_expr: string;
  time_field: string;
  lookback: string;
  op: string;
  threshold: number;
  detect?: string;
  zscore_window?: number;
  zscore_sigma?: number;
  interval_minutes: number;
  channel: string;
  target: string;
  active: boolean;
  last_checked_at?: string | null;
  last_value?: number | null;
  last_triggered_at?: string | null;
}

interface AlertEventRow {
  id: string;
  value?: number | null;
  threshold?: number | null;
  message: string;
  notified: boolean;
  created_at?: string | null;
}

const CHANNEL_LABEL: Record<string, string> = {
  message: "站内消息",
  webhook: "Webhook",
  feishu: "飞书",
  email: "邮件",
};

const LOOKBACK_LABEL: Record<string, string> = {
  today: "今天",
  yesterday: "昨天",
  this_month: "本月",
  last_7d: "近 7 天",
};

interface PermRow {
  id: string;
  user_id: string;
  user_name: string;
  employee_no: string;
  dimension_field: string;
  allowed_values: string[];
  note: string;
  active: boolean;
}

interface PermUser {
  id: string;
  display_name: string;
  employee_no: string;
  is_admin: boolean;
}

// 组件类型与 spec 类型的对应关系（与后端 _TYPE_MAP 一致）
const TYPE_MAP: Record<string, string> = {
  timeseries: "trend_line",
  distribution: "share_pie",
  topn: "rank_bar",
  detail: "detail_table",
  aggregate: "kpi_card",
  contribution: "pareto_bar",
  pareto: "pareto_bar",
  breakdown: "bar",
  outlier: "anomaly_scatter",
  forecast: "forecast_line",
  correlation: "scatter",
  cluster: "scatter",
  cohort: "heatmap",
  funnel: "funnel_bar",
  period_compare: "bar",
  whatif: "bar",
  impact: "bar",
};

const SPEC_TYPES = Object.keys(TYPE_MAP);

const TYPE_LABEL: Record<string, string> = {
  aggregate: "汇总指标",
  timeseries: "时间趋势",
  distribution: "分布结构",
  topn: "TOP N 排行",
  detail: "明细表",
  period_compare: "环比/同比",
  contribution: "贡献度",
  breakdown: "父子拆解",
  outlier: "异常检测",
  pareto: "帕累托",
  forecast: "预测",
  correlation: "相关性",
  cluster: "聚类",
  cohort: "同期群留存",
  funnel: "漏斗",
  whatif: "What-if 模拟",
  impact: "事件影响",
};

const WIDGET_LABEL: Record<string, string> = {
  kpi_card: "指标卡",
  trend_line: "折线",
  share_pie: "环形占比",
  rank_bar: "条形排行",
  pareto_bar: "帕累托条",
  forecast_line: "预测线",
  scatter: "散点",
  heatmap: "热力矩阵",
  funnel_bar: "漏斗条",
  anomaly_scatter: "异常条",
  detail_table: "明细表",
  bar: "表格",
};

interface FieldMap {
  date: string;
  amount: string;
  profit: string;
  qty: string;
  cat1: string;
  cat2: string;
  product: string;
  supplier: string;
}

const DEFAULT_FIELDS: FieldMap = {
  date: "RQ",
  amount: "SUM(XSJE)",
  profit: "SUM(ML)",
  qty: "SUM(XSSL)",
  cat1: "FL1MC",
  cat2: "FL2MC",
  product: "SPMC",
  supplier: "GHDWMC",
};

const FIELD_KEY = "aiagnet_studio_fields";

function loadFields(): FieldMap {
  if (typeof window === "undefined") return DEFAULT_FIELDS;
  try {
    const raw = window.localStorage.getItem(FIELD_KEY);
    if (!raw) return DEFAULT_FIELDS;
    return { ...DEFAULT_FIELDS, ...(JSON.parse(raw) as Partial<FieldMap>) };
  } catch {
    return DEFAULT_FIELDS;
  }
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function today(): string {
  return isoDate(new Date());
}

function monthStart(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDate(d);
}

function monthsAgoStart(n: number): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - n);
  return isoDate(d);
}

interface FormState {
  title: string;
  type: string;
  widgetType: string;
  dims: string;
  metrics: string;
  date: string;
  gran: string;
  start: string;
  end: string;
  options: string;
}

function emptyForm(): FormState {
  return {
    title: "",
    type: "forecast",
    widgetType: "forecast_line",
    dims: "",
    metrics: "销售额=SUM(XSJE)",
    date: "RQ",
    gran: "day",
    start: daysAgo(59),
    end: today(),
    options: '{"horizon": 7}',
  };
}

function parseMetrics(text: string): { name: string; expr: string; alias: string }[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, i) => {
      const at = line.indexOf("=");
      const name = at > 0 ? line.slice(0, at).trim() : line;
      const expr = at > 0 ? line.slice(at + 1).trim() : line;
      return { name, expr, alias: `m${i}` };
    });
}

export default function StudioPage() {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [dsId, setDsId] = useState("");
  const [boards, setBoards] = useState<BoardRow[]>([]);
  const [boardId, setBoardId] = useState("");
  const [board, setBoard] = useState<BoardDetail | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<FieldMap>(DEFAULT_FIELDS);
  const [showFields, setShowFields] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [renameBoardValue, setRenameBoardValue] = useState("");
  const [shareUrl, setShareUrl] = useState("");
  // P3：订阅 / 告警 / 嵌入
  const [showSubs, setShowSubs] = useState(false);
  const [subs, setSubs] = useState<SubRow[]>([]);
  const [subForm, setSubForm] = useState({ period: "daily", hour: 8, minute: 0, weekday: 0, channel: "message", target: "" });
  const [subRuns, setSubRuns] = useState<Record<string, RunRow[]>>({});
  const [showAlerts, setShowAlerts] = useState(false);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [alertForm, setAlertForm] = useState({
    name: "", metric_name: "负毛利额", metric_expr: "SUM(CASE WHEN ML < 0 THEN ML ELSE 0 END)",
    time_field: "RQ", lookback: "this_month", op: "<", threshold: 0, channel: "message", target: "",
    detect: "threshold", zscore_window: 28, zscore_sigma: 3,
  });
  const [alertEvents, setAlertEvents] = useState<Record<string, AlertEventRow[]>>({});
  const [checkResults, setCheckResults] = useState<Record<string, string>>({});
  // P4：行级权限（管理员）
  const [showPerms, setShowPerms] = useState(false);
  const [perms, setPerms] = useState<PermRow[]>([]);
  const [permUsers, setPermUsers] = useState<PermUser[]>([]);
  const [permForm, setPermForm] = useState({ user_id: "", dimension_field: "FL1MC", values: "", note: "" });
  // P6：预聚合与缓存（管理员）
  interface PreaggRow {
    id: string;
    name: string;
    source_table: string;
    dimensions: string[];
    metrics: { name: string; expr: string; alias: string }[];
    time_field: string;
    granularity: string;
    refresh_interval_min: number;
    active: boolean;
    last_refresh_at: string | null;
    last_status: string;
    last_rows: number;
  }
  const [showPreaggs, setShowPreaggs] = useState(false);
  const [preaggs, setPreaggs] = useState<PreaggRow[]>([]);
  const [cacheTtl, setCacheTtl] = useState<number | null>(null);
  const [preaggForm, setPreaggForm] = useState({
    name: "", dims: "FL1MC", metrics: "销售额=SUM(XSJE), 销量=SUM(XSSL)",
    time_field: "RQ", granularity: "day", interval: "60",
  });

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  useEffect(() => {
    setFields(loadFields());
    dataSourcesApi
      .list()
      .then((res) => {
        const items: SourceItem[] = res.data?.items || res.data || [];
        setSources(items);
        if (!items.length) return;
        const qs = new URLSearchParams(window.location.search);
        const wanted = qs.get("ds");
        const board = qs.get("board");
        const found = wanted ? items.find((s) => s.id === wanted) : null;
        setDsId(found ? found.id : items[0].id);
        if (board) setBoardId(board);
      })
      .catch(() => setSources([]));
  }, []);

  const loadBoards = useCallback(async (sid: string) => {
    if (!sid) return;
    setListLoading(true);
    try {
      const { data } = await studioApi.list(sid);
      const items: BoardRow[] = (data as { items?: BoardRow[] })?.items || [];
      setBoards(items);
      setBoardId((prev) => (prev && items.some((b) => b.id === prev) ? prev : items[0]?.id || ""));
    } catch (e) {
      toast.error(formatApiError(e, "看板列表加载失败"));
      setBoards([]);
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    if (dsId) void loadBoards(dsId);
  }, [dsId, loadBoards]);

  const loadBoard = useCallback(async (id: string) => {
    if (!id) {
      setBoard(null);
      return;
    }
    setDetailLoading(true);
    try {
      const { data } = await studioApi.get(id);
      setBoard(data as BoardDetail);
    } catch (e) {
      toast.error(formatApiError(e, "看板加载失败"));
      setBoard(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBoard(boardId);
    if (typeof window !== "undefined") {
      const qs = new URLSearchParams(window.location.search);
      qs.set("ds", dsId);
      if (boardId) qs.set("board", boardId);
      else qs.delete("board");
      window.history.replaceState(null, "", `${window.location.pathname}?${qs.toString()}`);
    }
  }, [boardId, dsId, loadBoard]);

  const widgets = useMemo<StudioWidget[]>(() => board?.widgets || [], [board]);

  const createBoard = async () => {
    if (!dsId) return;
    setBusy(true);
    try {
      const name = newName.trim() || `${sources.find((s) => s.id === dsId)?.name || "数据源"} · 自助看板`;
      const { data } = await studioApi.create({ data_source_id: dsId, name });
      setNewName("");
      await loadBoards(dsId);
      setBoardId((data as { id: string }).id);
      toast.success("看板已创建");
    } catch (e) {
      toast.error(formatApiError(e, "创建失败"));
    } finally {
      setBusy(false);
    }
  };

  const renameBoard = async () => {
    if (!board || !renameBoardValue.trim() || renameBoardValue === board.name) {
      setRenaming(false);
      return;
    }
    try {
      await studioApi.patch(board.id, { name: renameBoardValue.trim() });
      setRenaming(false);
      await loadBoards(dsId);
      await loadBoard(board.id);
    } catch (e) {
      toast.error(formatApiError(e, "重命名失败"));
    }
  };

  useEffect(() => {
    if (board) setRenameBoardValue(board.name);
  }, [board]);

  const removeBoard = async () => {
    if (!board) return;
    if (!window.confirm(`删除看板「${board.name}」及其卡片与快照？`)) return;
    setBusy(true);
    try {
      await studioApi.remove(board.id);
      setBoardId("");
      await loadBoards(dsId);
      toast.success("看板已删除");
    } catch (e) {
      toast.error(formatApiError(e, "删除失败"));
    } finally {
      setBusy(false);
    }
  };

  const buildSpec = (): Record<string, unknown> => {
    const dims = form.dims
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const metrics = parseMetrics(form.metrics);
    const spec: Record<string, unknown> = {
      type: form.type,
      data_source_id: dsId,
      dimensions: dims,
      metrics,
      limit: 200,
      options: form.options.trim() ? JSON.parse(form.options) : {},
    };
    if (form.title.trim()) spec.name = form.title.trim();
    if (form.date.trim()) {
      spec.time_range = {
        field: form.date.trim(),
        granularity: form.gran,
        start: form.start || null,
        end: form.end || null,
      };
    }
    return spec;
  };

  const addWidget = async () => {
    if (!board) return;
    let spec: Record<string, unknown>;
    try {
      spec = buildSpec();
    } catch (e) {
      toast.error("options 不是合法 JSON");
      return;
    }
    setBusy(true);
    try {
      await studioApi.addWidget(board.id, {
        title: form.title.trim() || `${TYPE_LABEL[form.type] || form.type}卡片`,
        widget_type: form.widgetType,
        spec,
        layout: { x: 0, y: 0, w: 6, h: 5 },
      });
      setShowAdd(false);
      setForm(emptyForm());
      await loadBoard(board.id);
      await loadBoards(dsId);
      toast.success("卡片已添加");
    } catch (e) {
      toast.error(formatApiError(e, "添加卡片失败"));
    } finally {
      setBusy(false);
    }
  };

  const patchWidget = async (w: StudioWidget, payload: Record<string, unknown>) => {
    if (!board) return;
    try {
      await studioApi.patchWidget(board.id, w.id, payload);
      await loadBoard(board.id);
    } catch (e) {
      toast.error(formatApiError(e, "更新卡片失败"));
    }
  };

  const moveWidget = async (index: number, dir: -1 | 1) => {
    const other = widgets[index + dir];
    const current = widgets[index];
    if (!other || !current) return;
    const a = current.sort_order ?? index;
    const b = other.sort_order ?? index + dir;
    try {
      await studioApi.patchWidget(board!.id, current.id, { sort_order: b });
      await studioApi.patchWidget(board!.id, other.id, { sort_order: a });
      await loadBoard(board!.id);
    } catch (e) {
      toast.error(formatApiError(e, "排序失败"));
    }
  };

  const changeWidth = async (w: StudioWidget, width: number) => {
    const layout = w.layout || {};
    await patchWidget(w, {
      layout: { x: layout.x ?? 0, y: layout.y ?? 0, w: width, h: layout.h ?? 5 },
    });
  };

  const removeWidget = async (w: StudioWidget) => {
    if (!board) return;
    if (!window.confirm(`删除卡片「${w.title || w.widget_type}」？`)) return;
    try {
      await studioApi.deleteWidget(board.id, w.id);
      await loadBoard(board.id);
      await loadBoards(dsId);
    } catch (e) {
      toast.error(formatApiError(e, "删除卡片失败"));
    }
  };

  const publish = async () => {
    if (!board) return;
    setBusy(true);
    try {
      const { data } = await studioApi.publish(board.id);
      const out = data as { version: number; widgets: number; errors: number; html_url: string };
      await loadBoards(dsId);
      await loadBoard(board.id);
      toast.success(`已发布 v${out.version}（${out.widgets} 个卡片${out.errors ? `，${out.errors} 个失败` : ""}）`);
      window.open(withToken(out.html_url), "_blank", "noopener");
    } catch (e) {
      toast.error(formatApiError(e, "发布失败"));
    } finally {
      setBusy(false);
    }
  };

  const openVersions = async () => {
    if (!board) return;
    setShowVersions(true);
    try {
      const { data } = await studioApi.versions(board.id);
      setVersions((data as { items?: VersionRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "版本加载失败"));
    }
  };

  const withToken = (url: string): string => {
    const token = getAuthToken();
    if (!token) return url;
    return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
  };

  const share = async () => {
    if (!board) return;
    const url = withToken(studioApi.htmlUrl(board.id));
    const absolute = `${window.location.origin}${url}`;
    setShareUrl(absolute);
    const okText = "分享链接已复制（需登录态，链接内已带 token）";
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(absolute);
        toast.success(okText);
        return;
      }
      const ta = document.createElement("textarea");
      ta.value = absolute;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) toast.success(okText);
    } catch {
      /* 链接已显示在页面中，可直接选中复制 */
    }
  };

  // ── P3：订阅 ──
  const loadSubs = useCallback(async () => {
    if (!board) return;
    try {
      const { data } = await studioApi.listSubs(board.id);
      setSubs((data as { items?: SubRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "订阅加载失败"));
    }
  }, [board]);

  const openSubs = async () => {
    setShowSubs(true);
    await loadSubs();
  };

  const createSub = async () => {
    if (!board) return;
    if (subForm.channel !== "message" && !subForm.target.trim()) {
      toast.error("该渠道需要填写目标地址");
      return;
    }
    try {
      await studioApi.createSub(board.id, { ...subForm, target: subForm.target.trim() });
      toast.success("订阅已创建");
      await loadSubs();
    } catch (e) {
      toast.error(formatApiError(e, "创建订阅失败"));
    }
  };

  const toggleSub = async (s: SubRow) => {
    try {
      await studioApi.patchSub(s.id, { active: !s.active });
      await loadSubs();
    } catch (e) {
      toast.error(formatApiError(e, "更新失败"));
    }
  };

  const removeSub = async (s: SubRow) => {
    if (!window.confirm("删除该订阅？")) return;
    try {
      await studioApi.deleteSub(s.id);
      await loadSubs();
    } catch (e) {
      toast.error(formatApiError(e, "删除失败"));
    }
  };

  const runSubNow = async (s: SubRow) => {
    try {
      const { data } = await studioApi.runSub(s.id);
      const r = data as { delivered: boolean; error?: string | null };
      if (r.delivered) toast.success("已投递一次");
      else toast.error(`投递失败：${r.error || "未知原因"}`);
      await loadSubs();
      await loadSubRuns(s.id);
    } catch (e) {
      toast.error(formatApiError(e, "投递失败"));
    }
  };

  const loadSubRuns = async (sid: string) => {
    try {
      const { data } = await studioApi.subRuns(sid);
      setSubRuns((prev) => ({ ...prev, [sid]: (data as { items?: RunRow[] })?.items || [] }));
    } catch {
      /* ignore */
    }
  };

  // ── P3：嵌入链接 ──
  const makeEmbed = async () => {
    if (!board) return;
    try {
      const { data } = await studioApi.embedLink(board.id, 30);
      const out = data as { url: string; expires_days: number };
      setShareUrl(out.url);
      toast.success(`嵌入链接已生成（${out.expires_days} 天有效，无需登录）`);
    } catch (e) {
      toast.error(formatApiError(e, "生成嵌入链接失败"));
    }
  };

  // ── P3：告警 ──
  const loadAlerts = useCallback(async () => {
    if (!dsId) return;
    try {
      const { data } = await studioApi.listAlerts(dsId);
      setAlerts((data as { items?: AlertRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "告警规则加载失败"));
    }
  }, [dsId]);

  const openAlerts = async () => {
    setShowAlerts(true);
    await loadAlerts();
  };

  const createAlert = async () => {
    if (!dsId) return;
    if (!alertForm.name.trim() || !alertForm.metric_expr.trim()) {
      toast.error("请填写规则名称与指标表达式");
      return;
    }
    try {
      await studioApi.createAlert({ ...alertForm, data_source_id: dsId, name: alertForm.name.trim() });
      setAlertForm((prev) => ({ ...prev, name: "" }));
      toast.success("告警规则已创建");
      await loadAlerts();
    } catch (e) {
      toast.error(formatApiError(e, "创建失败"));
    }
  };

  const toggleAlert = async (r: AlertRow) => {
    try {
      await studioApi.patchAlert(r.id, { active: !r.active });
      await loadAlerts();
    } catch (e) {
      toast.error(formatApiError(e, "更新失败"));
    }
  };

  const removeAlert = async (r: AlertRow) => {
    if (!window.confirm(`删除规则「${r.name}」？`)) return;
    try {
      await studioApi.deleteAlert(r.id);
      await loadAlerts();
    } catch (e) {
      toast.error(formatApiError(e, "删除失败"));
    }
  };

  const checkAlertNow = async (r: AlertRow) => {
    try {
      const { data } = await studioApi.checkAlert(r.id);
      const out = data as {
        value: number | null; violated: boolean; notified: boolean;
        detail?: { z?: number; mean?: number } | null;
      };
      setCheckResults((prev) => ({
        ...prev,
        [r.id]: out.value === null
          ? "无数据"
          : `${out.value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} · ${
              out.violated
                ? out.detail?.z !== undefined
                  ? `异常（偏离基线 ${out.detail.z >= 0 ? "+" : ""}${out.detail.z.toFixed(1)}σ）`
                  : "已越界"
                : "正常"
            }${out.notified ? " · 已通知" : ""}`,
      }));
      await loadAlerts();
      await loadAlertEvents(r.id);
    } catch (e) {
      toast.error(formatApiError(e, "检查失败"));
    }
  };

  const loadAlertEvents = async (rid: string) => {
    try {
      const { data } = await studioApi.alertEvents(rid);
      setAlertEvents((prev) => ({ ...prev, [rid]: (data as { items?: AlertEventRow[] })?.items || [] }));
    } catch {
      /* ignore */
    }
  };

  // ── P4：行级权限（管理员） ──
  const openPerms = async () => {
    setShowPerms(true);
    try {
      const [{ data: pu }, { data: pl }] = await Promise.all([
        studioApi.permUsers(),
        studioApi.listRowPerms(dsId),
      ]);
      setPermUsers((pu as { items?: PermUser[] })?.items || []);
      setPerms((pl as { items?: PermRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "行级权限加载失败（需管理员）"));
      setShowPerms(false);
    }
  };

  const createPerm = async () => {
    if (!dsId) return;
    if (!permForm.user_id || !permForm.dimension_field.trim()) {
      toast.error("请选择用户并填写维度字段");
      return;
    }
    const values = permForm.values
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await studioApi.createRowPerm({
        data_source_id: dsId,
        user_id: permForm.user_id,
        dimension_field: permForm.dimension_field.trim(),
        allowed_values: values,
        note: permForm.note.trim(),
      });
      setPermForm((p) => ({ ...p, user_id: "", values: "", note: "" }));
      toast.success(values.length ? "行级权限已创建" : "已创建（空值=该用户不可见任何行）");
      const { data } = await studioApi.listRowPerms(dsId);
      setPerms((data as { items?: PermRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "创建失败"));
    }
  };

  const togglePerm = async (p: PermRow) => {
    try {
      await studioApi.patchRowPerm(p.id, { active: !p.active });
      const { data } = await studioApi.listRowPerms(dsId);
      setPerms((data as { items?: PermRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "更新失败"));
    }
  };

  const removePerm = async (p: PermRow) => {
    if (!window.confirm(`删除 ${p.user_name || p.user_id} 在 ${p.dimension_field} 上的行级权限？`)) return;
    try {
      await studioApi.deleteRowPerm(p.id);
      const { data } = await studioApi.listRowPerms(dsId);
      setPerms((data as { items?: PermRow[] })?.items || []);
    } catch (e) {
      toast.error(formatApiError(e, "删除失败"));
    }
  };

  // ── P6：预聚合与缓存（管理员） ──
  const reloadPreaggs = useCallback(async () => {
    if (!dsId) return;
    const { data: pl } = await studioApi.listPreaggs(dsId);
    setPreaggs((pl as { items?: PreaggRow[] })?.items || []);
  }, [dsId]);

  const openPreaggs = async () => {
    setShowPreaggs(true);
    try {
      const [{ data: ci }] = await Promise.all([studioApi.cacheInfo(), reloadPreaggs()]);
      setCacheTtl((ci as { ttl?: number })?.ttl ?? null);
    } catch (e) {
      toast.error(formatApiError(e, "预聚合加载失败（需管理员）"));
      setShowPreaggs(false);
    }
  };

  const createPreaggNow = async () => {
    if (!dsId) return;
    if (!preaggForm.name.trim()) {
      toast.error("请填写预聚合名称");
      return;
    }
    const dims = preaggForm.dims.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    const metrics = preaggForm.metrics
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((pair, i) => {
        const eq = pair.indexOf("=");
        const name = eq >= 0 ? pair.slice(0, eq).trim() : pair;
        const expr = eq >= 0 ? pair.slice(eq + 1).trim() : pair;
        return { name, expr, alias: `m${i}` };
      });
    if (!dims.length || !metrics.length) {
      toast.error("请至少填写一个维度和一个指标");
      return;
    }
    try {
      const { data } = await studioApi.createPreagg({
        data_source_id: dsId,
        name: preaggForm.name.trim(),
        dimensions: dims,
        metrics,
        time_field: preaggForm.time_field.trim(),
        granularity: preaggForm.granularity,
        refresh_interval_min: Number(preaggForm.interval) || 60,
      });
      const row = data as PreaggRow;
      toast.success(
        row?.last_status === "ok"
          ? `预聚合已创建并完成首次刷新（${row.last_rows} 行）`
          : "预聚合已创建（首次刷新失败，请查看状态）",
      );
      setPreaggForm((p) => ({ ...p, name: "" }));
      await reloadPreaggs();
    } catch (e) {
      toast.error(formatApiError(e, "创建失败"));
    }
  };

  const refreshPreaggNow = async (p: PreaggRow) => {
    try {
      const { data } = await studioApi.refreshPreagg(p.id);
      toast.success(data?.ok ? `已刷新（${data.rows} 行）` : `刷新失败：${data?.error || ""}`);
      await reloadPreaggs();
    } catch (e) {
      toast.error(formatApiError(e, "刷新失败"));
    }
  };

  const togglePreagg = async (p: PreaggRow) => {
    try {
      await studioApi.patchPreagg(p.id, { active: !p.active });
      await reloadPreaggs();
    } catch (e) {
      toast.error(formatApiError(e, "更新失败"));
    }
  };

  const removePreagg = async (p: PreaggRow) => {
    if (!window.confirm(`删除预聚合「${p.name}」及其本地物化表？`)) return;
    try {
      await studioApi.deletePreagg(p.id);
      toast.success("预聚合已删除");
      await reloadPreaggs();
    } catch (e) {
      toast.error(formatApiError(e, "删除失败"));
    }
  };

  const clearCacheNow = async () => {
    try {
      const { data } = await studioApi.clearAnalysisCache();
      toast.success(`已清理 ${data?.deleted ?? 0} 条查询缓存（TTL ${data?.ttl ?? "-"} 秒）`);
    } catch (e) {
      toast.error(formatApiError(e, "清理失败"));
    }
  };

  const applyPreset = (key: string) => {
    const f = fields;
    const mtd = { start: monthStart(), end: today() };
    const d60 = { start: daysAgo(59), end: today() };
    const dims = (d: string) => d;
    switch (key) {
      case "forecast":
        setForm({
          ...emptyForm(),
          title: "本月销售预测",
          type: "forecast",
          widgetType: "forecast_line",
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "day",
          start: d60.start,
          end: d60.end,
          options: '{"horizon": 7}',
        });
        break;
      case "outlier":
        setForm({
          ...emptyForm(),
          title: "异常商品",
          type: "outlier",
          widgetType: "anomaly_scatter",
          dims: dims(f.product),
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: '{"threshold": 2}',
        });
        break;
      case "structure":
        setForm({
          ...emptyForm(),
          title: "品类结构",
          type: "distribution",
          widgetType: "share_pie",
          dims: dims(f.cat1),
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: "{}",
        });
        break;
      case "contribution":
        setForm({
          ...emptyForm(),
          title: "二级品类贡献度",
          type: "contribution",
          widgetType: "pareto_bar",
          dims: dims(f.cat2),
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: "{}",
        });
        break;
      case "pareto":
        setForm({
          ...emptyForm(),
          title: "商品帕累托",
          type: "pareto",
          widgetType: "pareto_bar",
          dims: dims(f.product),
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: '{"cutoff": 80}',
        });
        break;
      case "correlation":
        setForm({
          ...emptyForm(),
          title: "销售额 × 毛利相关性",
          type: "correlation",
          widgetType: "scatter",
          dims: dims(f.product),
          metrics: `销售额=${f.amount}\n毛利=${f.profit}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: "{}",
        });
        break;
      case "cluster":
        setForm({
          ...emptyForm(),
          title: "商品分群",
          type: "cluster",
          widgetType: "scatter",
          dims: dims(f.product),
          metrics: `销售额=${f.amount}\n毛利=${f.profit}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: '{"k": 4}',
        });
        break;
      case "cohort":
        setForm({
          ...emptyForm(),
          title: "商品同期群留存",
          type: "cohort",
          widgetType: "heatmap",
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "month",
          start: monthsAgoStart(11),
          end: today(),
          options: JSON.stringify({ entity_field: f.product }),
        });
        break;
      case "funnel":
        setForm({
          ...emptyForm(),
          title: "销售漏斗",
          type: "funnel",
          widgetType: "funnel_bar",
          dims: dims(f.cat1),
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: JSON.stringify({
            stages: [
              { name: "全部", min: 0 },
              { name: "销售额 ≥ 1 万", min: 10000 },
              { name: "销售额 ≥ 10 万", min: 100000 },
            ],
          }),
        });
        break;
      case "compare":
        setForm({
          ...emptyForm(),
          title: "月度环比",
          type: "period_compare",
          widgetType: "bar",
          metrics: `销售额=${f.amount}\n毛利=${f.profit}`,
          date: f.date,
          gran: "month",
          start: monthsAgoStart(5),
          end: today(),
          options: '{"mode": "mom"}',
        });
        break;
      case "whatif":
        setForm({
          ...emptyForm(),
          title: "What-if 提价模拟",
          type: "whatif",
          widgetType: "bar",
          dims: dims(f.cat1),
          metrics: `销售额=${f.amount}\n销量=${f.qty}\n毛利=${f.profit}`,
          date: f.date,
          gran: "month",
          start: mtd.start,
          end: mtd.end,
          options: '{"price_change_pct": 5, "elasticity": -1.5}',
        });
        break;
      case "impact":
        setForm({
          ...emptyForm(),
          title: "事件影响分析",
          type: "impact",
          widgetType: "bar",
          metrics: `销售额=${f.amount}`,
          date: f.date,
          gran: "day",
          start: daysAgo(14),
          end: today(),
          options: JSON.stringify({
            event_date: daysAgo(7),
            treatment: { field: f.cat1, value: "生鲜" },
          }),
        });
        break;
      default:
        break;
    }
    setShowAdd(true);
  };

  const saveFields = (next: FieldMap) => {
    setFields(next);
    try {
      window.localStorage.setItem(FIELD_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  const presets: { key: string; label: string }[] = [
    { key: "forecast", label: "本月预测" },
    { key: "outlier", label: "异常商品" },
    { key: "structure", label: "品类结构" },
    { key: "contribution", label: "贡献度" },
    { key: "pareto", label: "帕累托" },
    { key: "correlation", label: "相关性" },
    { key: "cluster", label: "商品分群" },
    { key: "cohort", label: "同期群" },
    { key: "funnel", label: "漏斗" },
    { key: "compare", label: "环比" },
    { key: "whatif", label: "What-if" },
    { key: "impact", label: "事件影响" },
  ];

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <LayoutDashboard className="h-7 w-7 text-indigo-500" />
            自助看板
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            卡片只引用分析定义，数字由数据库实时计算；发布后生成可回溯的版本快照。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={dsId}
            onChange={(e) => {
              setDsId(e.target.value);
              setBoardId("");
            }}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
          >
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name || s.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setShowFields((v) => !v)}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:border-indigo-300 hover:text-indigo-600"
          >
            字段设置
          </button>
          <Link
            href="/dashboards"
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm hover:border-indigo-300 hover:text-indigo-600"
          >
            经营看板
          </Link>
        </div>
      </div>

      {showFields && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="mb-2 text-xs text-gray-500">
            预设卡片与字段映射绑定：改这里即可适配其他数据源（仅影响新添加的卡片）。
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(Object.keys(fields) as (keyof FieldMap)[]).map((key) => (
              <label key={key} className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">
                  {{
                    date: "日期字段",
                    amount: "销售额表达式",
                    profit: "毛利表达式",
                    qty: "销量表达式",
                    cat1: "一级品类字段",
                    cat2: "二级品类字段",
                    product: "商品字段",
                    supplier: "供货单位字段",
                  }[key]}
                </span>
                <input
                  value={fields[key]}
                  onChange={(e) => saveFields({ ...fields, [key]: e.target.value })}
                  className="w-full rounded border border-gray-200 px-2 py-1 font-mono text-xs"
                />
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-3">
          <div className="rounded-xl border border-gray-200 bg-white p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium text-gray-700">看板列表</span>
              <button
                type="button"
                onClick={() => dsId && void loadBoards(dsId)}
                className="rounded p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-600"
                title="刷新"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${listLoading ? "animate-spin" : ""}`} />
              </button>
            </div>
            <div className="space-y-1">
              {boards.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => setBoardId(b.id)}
                  className={`w-full rounded-lg border px-2 py-1.5 text-left text-xs ${
                    b.id === boardId
                      ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                      : "border-transparent hover:bg-gray-50"
                  }`}
                >
                  <div className="truncate font-medium">{b.name || "未命名"}</div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-gray-400">
                    <span>{b.widget_count} 卡片</span>
                    <span className={b.status === "published" ? "text-emerald-600" : "text-amber-600"}>
                      {b.status === "published" ? `已发布 v${Math.max(b.version - 1, 1)}` : `草稿 v${b.version}`}
                    </span>
                  </div>
                </button>
              ))}
              {!boards.length && !listLoading && (
                <div className="py-4 text-center text-xs text-gray-400">暂无看板</div>
              )}
            </div>
            <div className="mt-3 space-y-2">
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="新看板名称（可选）"
                className="w-full rounded border border-gray-200 px-2 py-1.5 text-xs"
              />
              <button
                type="button"
                onClick={createBoard}
                disabled={!dsId || busy}
                className="flex w-full items-center justify-center gap-1 rounded-lg bg-indigo-600 px-2 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                <Plus className="h-3.5 w-3.5" /> 新建看板
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3">
            <div className="mb-2 text-xs font-medium text-gray-700">快速添加</div>
            <div className="flex flex-wrap gap-1.5">
              {presets.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  disabled={!board}
                  onClick={() => applyPreset(p.key)}
                  className="rounded-full border border-gray-200 px-2 py-1 text-[11px] text-gray-600 hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-40"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </aside>

        <main className="min-w-0 space-y-3">
          {!board ? (
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-16 text-center text-sm text-gray-400">
              {boards.length ? "选择一个看板，或新建一个" : "先新建一个看板，再添加卡片"}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3">
                <div className="flex min-w-0 items-center gap-2">
                  <ChevronLeft
                    className="h-4 w-4 cursor-pointer text-gray-400 hover:text-gray-600"
                    onClick={() => setBoardId("")}
                  />
                  {renaming ? (
                    <input
                      autoFocus
                      value={renameBoardValue}
                      onChange={(e) => setRenameBoardValue(e.target.value)}
                      onBlur={renameBoard}
                      onKeyDown={(e) => e.key === "Enter" && void renameBoard()}
                      className="rounded border border-indigo-300 px-2 py-0.5 text-sm"
                    />
                  ) : (
                    <h2
                      className="cursor-text truncate text-base font-semibold"
                      onClick={() => setRenaming(true)}
                      title="点击重命名"
                    >
                      {board.name}
                    </h2>
                  )}
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] ${
                      board.status === "published"
                        ? "bg-emerald-500/10 text-emerald-600"
                        : "bg-amber-500/10 text-amber-600"
                    }`}
                  >
                    {board.status === "published"
                      ? `已发布 v${Math.max(board.version - 1, 1)}`
                      : `草稿 v${board.version}`}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowAdd(true)}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <Plus className="h-3.5 w-3.5" /> 添加卡片
                  </button>
                  <button
                    type="button"
                    onClick={openVersions}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <History className="h-3.5 w-3.5" /> 版本
                  </button>
                  <button
                    type="button"
                    onClick={share}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <Share2 className="h-3.5 w-3.5" /> 分享
                  </button>
                  <button
                    type="button"
                    onClick={openSubs}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <CalendarClock className="h-3.5 w-3.5" /> 订阅
                  </button>
                  <button
                    type="button"
                    onClick={openAlerts}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <Bell className="h-3.5 w-3.5" /> 告警
                  </button>
                  <button
                    type="button"
                    onClick={makeEmbed}
                    disabled={board.status !== "published"}
                    title={board.status !== "published" ? "请先发布看板" : "生成免登录只读链接"}
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-40"
                  >
                    <Link2 className="h-3.5 w-3.5" /> 嵌入
                  </button>
                  <button
                    type="button"
                    onClick={openPerms}
                    title="行级权限（管理员）：限定用户可见的维度值"
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" /> 权限
                  </button>
                  <button
                    type="button"
                    onClick={openPreaggs}
                    title="预聚合与查询缓存（管理员）：常用口径本地物化 + 结果缓存"
                    className="flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-indigo-300 hover:text-indigo-600"
                  >
                    <Gauge className="h-3.5 w-3.5" /> 预聚合
                  </button>
                  <button
                    type="button"
                    onClick={removeBoard}
                    className="flex items-center gap-1 rounded-lg border border-rose-200 px-3 py-1.5 text-xs text-rose-600 hover:bg-rose-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> 删除
                  </button>
                  <button
                    type="button"
                    onClick={publish}
                    disabled={busy}
                    className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
                    发布
                  </button>
                </div>
              </div>

              {shareUrl && (
                <div className="flex flex-wrap items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs">
                  <span className="text-indigo-700">分享链接（含登录 token）：</span>
                  <input
                    readOnly
                    value={shareUrl}
                    onFocus={(e) => e.currentTarget.select()}
                    className="min-w-0 flex-1 rounded border border-indigo-200 bg-white px-2 py-1 font-mono text-[11px]"
                  />
                  <a
                    href={shareUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded border border-indigo-200 px-2 py-1 text-indigo-600 hover:bg-white"
                  >
                    打开
                  </a>
                  <button
                    type="button"
                    onClick={() => setShareUrl("")}
                    className="text-indigo-400 hover:text-indigo-600"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}

              {detailLoading ? (
                <div className="flex items-center justify-center rounded-xl border border-gray-200 bg-white p-16 text-sm text-gray-400">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 正在计算卡片数据…
                </div>
              ) : widgets.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-300 bg-white p-16 text-center text-sm text-gray-400">
                  还没有卡片，点击左侧「快速添加」选择模板
                </div>
              ) : (
                <div className="studio-widget-grid grid grid-cols-12 gap-3">
                  {widgets.map((w, index) => (
                    <WidgetCard
                      key={w.id}
                      widget={{ ...w, columns: w.columns || [], data: { columns: w.columns || [], rows: w.rows || [] } }}
                      style={{
                        gridColumn: `span ${Math.min(Math.max(w.layout?.w || 6, 3), 12)} / span ${Math.min(
                          Math.max(w.layout?.w || 6, 3),
                          12,
                        )}`,
                      }}
                      toolbar={
                        <>
                          <button
                            type="button"
                            onClick={() => void moveWidget(index, -1)}
                            disabled={index === 0}
                            className="rounded border border-gray-200 p-1 text-gray-400 hover:bg-gray-50 disabled:opacity-30"
                            title="上移"
                          >
                            <ArrowUp className="h-3 w-3" />
                          </button>
                          <button
                            type="button"
                            onClick={() => void moveWidget(index, 1)}
                            disabled={index === widgets.length - 1}
                            className="rounded border border-gray-200 p-1 text-gray-400 hover:bg-gray-50 disabled:opacity-30"
                            title="下移"
                          >
                            <ArrowDown className="h-3 w-3" />
                          </button>
                          <button
                            type="button"
                            onClick={() => void changeWidth(w, (w.layout?.w || 6) === 12 ? 6 : 12)}
                            className="rounded border border-gray-200 px-1.5 py-0.5 text-[10px] text-gray-500 hover:bg-gray-50"
                            title="切换宽度"
                          >
                            {(w.layout?.w || 6) === 12 ? "半宽" : "全宽"}
                          </button>
                          <button
                            type="button"
                            onClick={() => void removeWidget(w)}
                            className="rounded border border-rose-200 p-1 text-rose-500 hover:bg-rose-50"
                            title="删除卡片"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </>
                      }
                    />
                  ))}
                </div>
              )}

              {widgets.some((w) => w.error) && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700">
                  {widgets.filter((w) => w.error).map((w) => (
                    <div key={w.id}>
                      「{w.title}」计算失败：{w.error}
                    </div>
                  ))}
                </div>
              )}

              {board.status === "published" && (
                <div className="text-right text-[11px] text-gray-400">
                  <a
                    href={withToken(studioApi.htmlUrl(board.id))}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 hover:text-indigo-600"
                  >
                    打开最近发布快照 <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">添加卡片</h3>
              <button type="button" onClick={() => setShowAdd(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mb-3 flex flex-wrap gap-1.5">
              {presets.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => applyPreset(p.key)}
                  className="rounded-full border border-gray-200 px-2 py-1 text-[11px] text-gray-600 hover:border-indigo-300 hover:text-indigo-600"
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">卡片标题</span>
                <input
                  value={form.title}
                  onChange={(e) => set("title", e.target.value)}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">分析类型</span>
                <select
                  value={form.type}
                  onChange={(e) => {
                    const t = e.target.value;
                    setForm((prev) => ({ ...prev, type: t, widgetType: TYPE_MAP[t] || "detail_table" }));
                  }}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  {SPEC_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {TYPE_LABEL[t] || t}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">组件类型</span>
                <select
                  value={form.widgetType}
                  onChange={(e) => set("widgetType", e.target.value)}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  {Object.keys(WIDGET_LABEL).map((t) => (
                    <option key={t} value={t}>
                      {WIDGET_LABEL[t]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">维度字段（逗号分隔）</span>
                <input
                  value={form.dims}
                  onChange={(e) => set("dims", e.target.value)}
                  placeholder="FL1MC, FL2MC"
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label className="text-xs text-gray-600 sm:col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">指标（每行 名称=表达式）</span>
                <textarea
                  value={form.metrics}
                  onChange={(e) => set("metrics", e.target.value)}
                  rows={3}
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">时间字段</span>
                <input
                  value={form.date}
                  onChange={(e) => set("date", e.target.value)}
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">时间粒度</span>
                <select
                  value={form.gran}
                  onChange={(e) => set("gran", e.target.value)}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  {["day", "week", "month", "quarter", "year"].map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">开始日期</span>
                <input
                  type="date"
                  value={form.start}
                  onChange={(e) => set("start", e.target.value)}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <label className="text-xs text-gray-600">
                <span className="mb-1 block text-[11px] text-gray-400">结束日期</span>
                <input
                  type="date"
                  value={form.end}
                  onChange={(e) => set("end", e.target.value)}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <label className="text-xs text-gray-600 sm:col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">
                  算子参数 options（JSON，如 {`{"horizon":7}`} / {`{"k":4}`}）
                </span>
                <textarea
                  value={form.options}
                  onChange={(e) => set("options", e.target.value)}
                  rows={3}
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600"
              >
                取消
              </button>
              <button
                type="button"
                onClick={addWidget}
                disabled={busy || !board}
                className="flex items-center gap-1 rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} 添加
              </button>
            </div>
            <p className="mt-2 text-[11px] text-gray-400">
              添加时会立即执行一次校验；数字全部由数据库计算并带事实溯源，失败原因会显示在卡片上。
            </p>
          </div>
        </div>
      )}

      {showVersions && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[80vh] w-full max-w-lg overflow-auto rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">发布版本</h3>
              <button type="button" onClick={() => setShowVersions(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            {!versions.length ? (
              <div className="py-8 text-center text-sm text-gray-400">还没有发布过</div>
            ) : (
              <div className="space-y-1.5">
                {versions.map((v) => (
                  <div
                    key={v.id}
                    className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2 text-xs"
                  >
                    <div>
                      <span className="font-medium">v{v.version}</span>
                      <span className="ml-2 text-gray-400">
                        {v.widget_count} 卡片 · {v.anchor_status === "pass" ? "全部成功" : "含失败"}
                      </span>
                      <div className="mt-0.5 text-[10px] text-gray-400">
                        {v.created_at ? v.created_at.slice(0, 19).replace("T", " ") : "—"}
                      </div>
                    </div>
                    <a
                      href={withToken(v.html_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-gray-600 hover:border-indigo-300 hover:text-indigo-600"
                    >
                      查看 <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {showSubs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">订阅推送</h3>
              <button type="button" onClick={() => setShowSubs(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl border border-gray-200 p-3 text-xs sm:grid-cols-6">
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">周期</span>
                <select
                  value={subForm.period}
                  onChange={(e) => setSubForm((p) => ({ ...p, period: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  <option value="hourly">每小时</option>
                  <option value="daily">每天</option>
                  <option value="weekly">每周</option>
                </select>
              </label>
              {subForm.period === "weekly" && (
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">星期</span>
                  <select
                    value={subForm.weekday}
                    onChange={(e) => setSubForm((p) => ({ ...p, weekday: Number(e.target.value) }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  >
                    {["一", "二", "三", "四", "五", "六", "日"].map((d, i) => (
                      <option key={i} value={i}>周{d}</option>
                    ))}
                  </select>
                </label>
              )}
              {subForm.period !== "hourly" && (
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">时</span>
                  <input
                    type="number" min={0} max={23} value={subForm.hour}
                    onChange={(e) => setSubForm((p) => ({ ...p, hour: Number(e.target.value) }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  />
                </label>
              )}
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">分</span>
                <input
                  type="number" min={0} max={59} value={subForm.minute}
                  onChange={(e) => setSubForm((p) => ({ ...p, minute: Number(e.target.value) }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">渠道</span>
                <select
                  value={subForm.channel}
                  onChange={(e) => setSubForm((p) => ({ ...p, channel: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  {Object.entries(CHANNEL_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </label>
              <label className="col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">
                  目标{subForm.channel === "message" ? "（留空=站内「看板订阅推送」会话）" : subForm.channel === "webhook" ? " URL" : subForm.channel === "feishu" ? " chat_id" : " 邮箱"}
                </span>
                <input
                  value={subForm.target}
                  onChange={(e) => setSubForm((p) => ({ ...p, target: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <div className="col-span-2 flex items-end sm:col-span-6">
                <button
                  type="button"
                  onClick={createSub}
                  className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white"
                >
                  <Plus className="h-3.5 w-3.5" /> 创建订阅
                </button>
                <span className="ml-2 text-[11px] text-gray-400">到点自动生成快照并投递（北京时间）</span>
              </div>
            </div>
            {!subs.length ? (
              <div className="py-6 text-center text-sm text-gray-400">还没有订阅</div>
            ) : (
              <div className="space-y-2">
                {subs.map((s) => (
                  <div key={s.id} className="rounded-lg border border-gray-200 p-3 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-medium">
                          {{ hourly: "每小时", daily: "每天", weekly: "每周" }[s.period] || s.period}
                          {s.period === "weekly" && ` 周${"一二三四五六日"[s.weekday]}`}
                          {s.period !== "hourly" && ` ${String(s.hour).padStart(2, "0")}`}:{String(s.minute).padStart(2, "0")}
                        </span>
                        <span className="ml-2 text-gray-400">{CHANNEL_LABEL[s.channel] || s.channel}</span>
                        <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] ${s.active ? "bg-emerald-500/10 text-emerald-600" : "bg-gray-100 text-gray-400"}`}>
                          {s.active ? "启用" : "停用"}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button type="button" onClick={() => void runSubNow(s)} title="立即投递一次"
                          className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                          <Play className="h-3 w-3" /> 投递
                        </button>
                        <button type="button" onClick={() => void loadSubRuns(s.id)}
                          className="rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                          记录
                        </button>
                        <button type="button" onClick={() => void toggleSub(s)}
                          className="rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                          {s.active ? "停用" : "启用"}
                        </button>
                        <button type="button" onClick={() => void removeSub(s)}
                          className="rounded border border-rose-200 px-2 py-1 text-rose-500 hover:bg-rose-50">
                          删除
                        </button>
                      </div>
                    </div>
                    <div className="mt-1 text-[11px] text-gray-400">
                      下次投递：{s.next_run_at ? new Date(s.next_run_at).toLocaleString("zh-CN") : "—"}
                      {s.last_run_at && ` · 上次：${new Date(s.last_run_at).toLocaleString("zh-CN")}`}
                    </div>
                    {(subRuns[s.id] || []).length > 0 && (
                      <div className="mt-2 space-y-1 border-t border-gray-100 pt-2">
                        {(subRuns[s.id] || []).slice(0, 5).map((r) => (
                          <div key={r.id} className="flex items-center justify-between text-[11px]">
                            <span className={r.status === "ok" && r.delivered ? "text-emerald-600" : "text-rose-500"}>
                              {r.created_at ? new Date(r.created_at).toLocaleString("zh-CN") : "—"} ·{" "}
                              {r.status === "ok" ? (r.delivered ? "已投递" : `未送达 ${r.error || ""}`) : `失败 ${r.error || ""}`}
                            </span>
                            {r.status === "ok" && (
                              <a href={withToken(r.html_url)} target="_blank" rel="noreferrer"
                                className="text-indigo-500 hover:underline">
                                快照
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {showAlerts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">阈值告警</h3>
              <button type="button" onClick={() => setShowAlerts(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mb-4 space-y-2 rounded-xl border border-gray-200 p-3 text-xs">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <label className="col-span-2">
                  <span className="mb-1 block text-[11px] text-gray-400">规则名称</span>
                  <input
                    value={alertForm.name}
                    onChange={(e) => setAlertForm((p) => ({ ...p, name: e.target.value }))}
                    placeholder="如：负毛利监控"
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  />
                </label>
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">指标名</span>
                  <input
                    value={alertForm.metric_name}
                    onChange={(e) => setAlertForm((p) => ({ ...p, metric_name: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  />
                </label>
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">时间字段</span>
                  <input
                    value={alertForm.time_field}
                    onChange={(e) => setAlertForm((p) => ({ ...p, time_field: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                  />
                </label>
                <label className="col-span-2">
                  <span className="mb-1 block text-[11px] text-gray-400">指标表达式（SQL 聚合）</span>
                  <input
                    value={alertForm.metric_expr}
                    onChange={(e) => setAlertForm((p) => ({ ...p, metric_expr: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                  />
                </label>
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">统计口径</span>
                  <select
                    value={alertForm.lookback}
                    onChange={(e) => setAlertForm((p) => ({ ...p, lookback: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  >
                    {Object.entries(LOOKBACK_LABEL).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">检测方式</span>
                  <select
                    value={alertForm.detect}
                    onChange={(e) => setAlertForm((p) => ({ ...p, detect: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  >
                    <option value="threshold">阈值比较</option>
                    <option value="zscore">z-score 异常检测</option>
                  </select>
                </label>
                {alertForm.detect === "zscore" ? (
                  <>
                    <label>
                      <span className="mb-1 block text-[11px] text-gray-400">基线窗口（天）</span>
                      <input
                        type="number" min={7} max={180} value={alertForm.zscore_window}
                        onChange={(e) => setAlertForm((p) => ({ ...p, zscore_window: Number(e.target.value) }))}
                        className="w-full rounded border border-gray-200 px-2 py-1.5"
                      />
                    </label>
                    <label>
                      <span className="mb-1 block text-[11px] text-gray-400">灵敏度（σ 倍数）</span>
                      <input
                        type="number" min={0.5} max={10} step={0.5} value={alertForm.zscore_sigma}
                        onChange={(e) => setAlertForm((p) => ({ ...p, zscore_sigma: Number(e.target.value) }))}
                        className="w-full rounded border border-gray-200 px-2 py-1.5"
                      />
                    </label>
                  </>
                ) : (
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">条件</span>
                  <span className="flex gap-1">
                    <select
                      value={alertForm.op}
                      onChange={(e) => setAlertForm((p) => ({ ...p, op: e.target.value }))}
                      className="w-16 rounded border border-gray-200 px-1 py-1.5"
                    >
                      {[">", ">=", "<", "<=", "==", "!="].map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                    <input
                      type="number" value={alertForm.threshold}
                      onChange={(e) => setAlertForm((p) => ({ ...p, threshold: Number(e.target.value) }))}
                      className="w-full rounded border border-gray-200 px-2 py-1.5"
                    />
                  </span>
                </label>
                )}
                <label>
                  <span className="mb-1 block text-[11px] text-gray-400">渠道</span>
                  <select
                    value={alertForm.channel}
                    onChange={(e) => setAlertForm((p) => ({ ...p, channel: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  >
                    {Object.entries(CHANNEL_LABEL).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </label>
                <label className="col-span-2 sm:col-span-3">
                  <span className="mb-1 block text-[11px] text-gray-400">目标（站内消息可留空）</span>
                  <input
                    value={alertForm.target}
                    onChange={(e) => setAlertForm((p) => ({ ...p, target: e.target.value }))}
                    className="w-full rounded border border-gray-200 px-2 py-1.5"
                  />
                </label>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={createAlert}
                  className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white"
                >
                  <Plus className="h-3.5 w-3.5" /> 创建规则
                </button>
                <span className="text-[11px] text-gray-400">默认每小时检查一次，越界即通知（24 小时冷却防重复）</span>
              </div>
            </div>
            {!alerts.length ? (
              <div className="py-6 text-center text-sm text-gray-400">还没有告警规则</div>
            ) : (
              <div className="space-y-2">
                {alerts.map((r) => (
                  <div key={r.id} className="rounded-lg border border-gray-200 p-3 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-medium">{r.name}</span>
                        <span className="ml-2 text-gray-500 font-mono">{r.metric_expr}</span>
                        <span className="ml-2 text-gray-400">
                          {LOOKBACK_LABEL[r.lookback] || r.lookback} ·{" "}
                          {r.detect === "zscore"
                            ? `±${r.zscore_sigma ?? 3}σ（${r.zscore_window ?? 28} 天基线）`
                            : `${r.op} ${r.threshold}`}
                        </span>
                        <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] ${r.active ? "bg-emerald-500/10 text-emerald-600" : "bg-gray-100 text-gray-400"}`}>
                          {r.active ? "启用" : "停用"}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button type="button" onClick={() => void checkAlertNow(r)}
                          className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                          <Play className="h-3 w-3" /> 检查
                        </button>
                        <button type="button" onClick={() => void loadAlertEvents(r.id)}
                          className="rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                          事件
                        </button>
                        <button type="button" onClick={() => void toggleAlert(r)}
                          className="rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                          {r.active ? "停用" : "启用"}
                        </button>
                        <button type="button" onClick={() => void removeAlert(r)}
                          className="rounded border border-rose-200 px-2 py-1 text-rose-500 hover:bg-rose-50">
                          删除
                        </button>
                      </div>
                    </div>
                    <div className="mt-1 text-[11px] text-gray-400">
                      最近值：{r.last_value === null || r.last_value === undefined
                        ? "—"
                        : r.last_value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}
                      {r.last_checked_at && ` · 检查于 ${new Date(r.last_checked_at).toLocaleString("zh-CN")}`}
                      {checkResults[r.id] && <span className="ml-2 text-indigo-600">{checkResults[r.id]}</span>}
                    </div>
                    {(alertEvents[r.id] || []).length > 0 && (
                      <div className="mt-2 space-y-1 border-t border-gray-100 pt-2">
                        {(alertEvents[r.id] || []).slice(0, 5).map((e) => (
                          <div key={e.id} className="text-[11px] text-gray-500">
                            <span className={e.notified ? "text-rose-500" : "text-gray-400"}>●</span>{" "}
                            {e.created_at ? new Date(e.created_at).toLocaleString("zh-CN") : "—"} · {e.message}
                            {!e.notified && <span className="text-gray-400">（冷却中未通知）</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {showPerms && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">行级权限（管理员）</h3>
              <button type="button" onClick={() => setShowPerms(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mb-3 text-[11px] text-gray-400">
              限定用户在当前数据源上可见的维度值；所有分析、看板卡片、告警口径在 SQL 出口统一注入，管理员不受限。
            </p>
            <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl border border-gray-200 p-3 text-xs sm:grid-cols-4">
              <label className="col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">用户</span>
                <select
                  value={permForm.user_id}
                  onChange={(e) => setPermForm((p) => ({ ...p, user_id: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  <option value="">请选择用户</option>
                  {permUsers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.display_name}
                      {u.employee_no ? `（${u.employee_no}）` : ""}
                      {u.is_admin ? " · 管理员" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">维度字段</span>
                <input
                  value={permForm.dimension_field}
                  onChange={(e) => setPermForm((p) => ({ ...p, dimension_field: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label className="col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">可见值（逗号分隔；留空 = 不可见任何行）</span>
                <input
                  value={permForm.values}
                  onChange={(e) => setPermForm((p) => ({ ...p, values: e.target.value }))}
                  placeholder="生鲜, 食品"
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <label className="col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">备注</span>
                <input
                  value={permForm.note}
                  onChange={(e) => setPermForm((p) => ({ ...p, note: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <div className="col-span-2 flex items-center gap-2 sm:col-span-4">
                <button
                  type="button"
                  onClick={createPerm}
                  className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white"
                >
                  <Plus className="h-3.5 w-3.5" /> 创建权限
                </button>
              </div>
            </div>
            {!perms.length ? (
              <div className="py-6 text-center text-sm text-gray-400">还没有行级权限配置</div>
            ) : (
              <div className="space-y-2">
                {perms.map((p) => (
                  <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 p-3 text-xs">
                    <div className="min-w-0">
                      <span className="font-medium">{p.user_name || p.user_id.slice(0, 8)}</span>
                      {p.employee_no && <span className="ml-1 text-gray-400">（{p.employee_no}）</span>}
                      <span className="ml-2 font-mono text-gray-500">{p.dimension_field}</span>
                      <span className="ml-2 text-gray-600">
                        {p.allowed_values.length ? `∈ {${p.allowed_values.join("、")}}` : "∅ 不可见任何行"}
                      </span>
                      {p.note && <span className="ml-2 text-[11px] text-gray-400">{p.note}</span>}
                      <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] ${p.active ? "bg-emerald-500/10 text-emerald-600" : "bg-gray-100 text-gray-400"}`}>
                        {p.active ? "生效中" : "已停用"}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button type="button" onClick={() => void togglePerm(p)}
                        className="rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                        {p.active ? "停用" : "启用"}
                      </button>
                      <button type="button" onClick={() => void removePerm(p)}
                        className="rounded border border-rose-200 px-2 py-1 text-rose-500 hover:bg-rose-50">
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      {showPreaggs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">预聚合与缓存（管理员）</h3>
              <button type="button" onClick={() => setShowPreaggs(false)} className="text-gray-400 hover:text-gray-600">
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mb-3 text-[11px] text-gray-400">
              预聚合把「维度 × 指标」口径定时物化到本地，分析命中注册口径时直接出数（秒开），未命中自动回退直查；
              查询结果缓存 TTL {cacheTtl ?? "-"} 秒，同口径 + 同权限签名共享。仅支持可重聚合指标（SUM/COUNT/MIN/MAX）。
            </p>
            <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl border border-gray-200 p-3 text-xs sm:grid-cols-4">
              <label className="col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">名称</span>
                <input
                  value={preaggForm.name}
                  onChange={(e) => setPreaggForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder="品类日汇总"
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <label className="col-span-2">
                <span className="mb-1 block text-[11px] text-gray-400">维度字段（逗号分隔，最多 4 个）</span>
                <input
                  value={preaggForm.dims}
                  onChange={(e) => setPreaggForm((p) => ({ ...p, dims: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label className="col-span-2 sm:col-span-4">
                <span className="mb-1 block text-[11px] text-gray-400">指标（名称=表达式，逗号分隔；仅 SUM/COUNT/MIN/MAX）</span>
                <input
                  value={preaggForm.metrics}
                  onChange={(e) => setPreaggForm((p) => ({ ...p, metrics: e.target.value }))}
                  placeholder="销售额=SUM(XSJE), 销量=SUM(XSSL)"
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">时间字段</span>
                <input
                  value={preaggForm.time_field}
                  onChange={(e) => setPreaggForm((p) => ({ ...p, time_field: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5 font-mono"
                />
              </label>
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">粒度</span>
                <select
                  value={preaggForm.granularity}
                  onChange={(e) => setPreaggForm((p) => ({ ...p, granularity: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                >
                  <option value="day">按日</option>
                  <option value="month">按月</option>
                  <option value="">不分期</option>
                </select>
              </label>
              <label>
                <span className="mb-1 block text-[11px] text-gray-400">刷新间隔（分钟）</span>
                <input
                  value={preaggForm.interval}
                  onChange={(e) => setPreaggForm((p) => ({ ...p, interval: e.target.value }))}
                  className="w-full rounded border border-gray-200 px-2 py-1.5"
                />
              </label>
              <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
                <button
                  type="button"
                  onClick={createPreaggNow}
                  className="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white"
                >
                  <Plus className="h-3.5 w-3.5" /> 创建并刷新
                </button>
              </div>
              <div className="col-span-2 flex items-center gap-2 sm:col-span-3 sm:justify-end">
                <button
                  type="button"
                  onClick={clearCacheNow}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs hover:border-amber-300 hover:text-amber-600"
                >
                  清空查询缓存
                </button>
              </div>
            </div>
            {!preaggs.length ? (
              <div className="py-6 text-center text-sm text-gray-400">还没有预聚合注册</div>
            ) : (
              <div className="space-y-2">
                {preaggs.map((p) => (
                  <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 p-3 text-xs">
                    <div className="min-w-0">
                      <span className="font-medium">{p.name}</span>
                      <span className="ml-2 font-mono text-gray-500">
                        {p.dimensions.join(" × ")}
                        {p.granularity ? ` × ${p.granularity === "day" ? "日" : "月"}(${p.time_field})` : ""}
                      </span>
                      <span className="ml-2 text-gray-600">
                        {p.metrics.map((m) => m.name || m.alias).join("、")}
                      </span>
                      <span className="ml-2 text-[11px] text-gray-400">
                        每 {p.refresh_interval_min} 分钟 · {p.last_rows} 行
                        {p.last_refresh_at ? ` · 刷新于 ${p.last_refresh_at.slice(5, 16).replace("T", " ")}` : ""}
                      </span>
                      <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] ${p.active ? "bg-emerald-500/10 text-emerald-600" : "bg-gray-100 text-gray-400"}`}>
                        {p.active ? (p.last_status === "ok" ? "生效中" : `异常：${p.last_status.slice(0, 30)}`) : "已停用"}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button type="button" onClick={() => void refreshPreaggNow(p)}
                        className="flex items-center gap-1 rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                        <RefreshCw className="h-3 w-3" /> 刷新
                      </button>
                      <button type="button" onClick={() => void togglePreagg(p)}
                        className="rounded border border-gray-200 px-2 py-1 hover:border-indigo-300 hover:text-indigo-600">
                        {p.active ? "停用" : "启用"}
                      </button>
                      <button type="button" onClick={() => void removePreagg(p)}
                        className="rounded border border-rose-200 px-2 py-1 text-rose-500 hover:bg-rose-50">
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
