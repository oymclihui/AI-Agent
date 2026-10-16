"use client";

import { useCallback, useEffect, useState } from "react";
import { TrendingUp, RotateCcw, Zap, Activity, Clock, CheckCircle2, XCircle } from "lucide-react";
import { ChartRenderer } from "@/components/ChartRenderer";
import { getAuthToken } from "@/lib/authStore";
import { useLangStore } from "@/lib/langStore";

interface ModelVersion {
  id: number;
  data_source_id: string;
  model_type: string;
  version: number;
  file_path: string;
  metrics: Record<string, unknown> | null;
  status: string;
  trained_rows: number | null;
  created_at: string | null;
}

interface ModelGroup {
  data_source_id: string;
  data_source_name?: string;
  production: Record<string, ModelVersion>;
  versions: ModelVersion[];
}

interface TrainingLog {
  id: number;
  model_id: number | null;
  data_source_id: string;
  trigger_query: string;
  sample_rows: number | null;
  val_mae: number | null;
  val_r2: number | null;
  promoted: boolean;
  duration_ms: number | null;
  note: string | null;
  created_at: string | null;
}

const STATUS_STYLES: Record<string, string> = {
  production: "bg-emerald-100 text-emerald-700 border-emerald-300",
  candidate: "bg-blue-100 text-blue-700 border-blue-300",
  retired: "bg-gray-100 text-gray-500 border-gray-300",
};

export default function MLEvolutionPage() {
  const { lang } = useLangStore();
  const [models, setModels] = useState<ModelGroup[]>([]);
  const [logs, setLogs] = useState<TrainingLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [retraining, setRetraining] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);
  const [selectedDs, setSelectedDs] = useState<string>("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [mRes, lRes] = await Promise.all([
        fetch(`"/api/v1"/ml-evolution/models`, { headers: ({ Authorization: `Bearer ${getAuthToken()}` }) }),
        fetch(`"/api/v1"/ml-evolution/logs?limit=200`, { headers: ({ Authorization: `Bearer ${getAuthToken()}` }) }),
      ]);
      const mData = await mRes.json();
      const lData = await lRes.json();
      setModels(mData.items || []);
      setLogs(lData.items || []);
      if (!selectedDs && (mData.items || []).length > 0) {
        setSelectedDs(mData.items[0].data_source_id);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [selectedDs]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRetrain = async (dsId: string) => {
    setRetraining(dsId);
    try {
      await fetch(`"/api/v1"/ml-evolution/retrain`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...({ Authorization: `Bearer ${getAuthToken()}` }) },
        body: JSON.stringify({ data_source_id: dsId }),
      });
      setTimeout(() => fetchData(), 3000);
    } finally {
      setRetraining(null);
    }
  };

  const handleRollback = async (modelId: number) => {
    setRollbackTarget(modelId);
    try {
      await fetch(`"/api/v1"/ml-evolution/rollback/${modelId}`, {
        method: "POST",
        headers: ({ Authorization: `Bearer ${getAuthToken()}` }),
      });
      await fetchData();
    } finally {
      setRollbackTarget(null);
    }
  };

  // Build evolution curve chart data
  const dsLogs = logs.filter(l => !selectedDs || l.data_source_id === selectedDs);
  const promotedLogs = dsLogs.filter(l => l.val_mae !== null).reverse();
  const chartData = {
    type: "line" as const,
    title: lang === "zh" ? "MAE / Accuracy 进化曲线" : "MAE / Accuracy Evolution Curve",
    labels: promotedLogs.map((l, i) => `#${i + 1}`),
    datasets: [
      {
        label: lang === "zh" ? "MAE / Accuracy" : "MAE / Accuracy",
        data: promotedLogs.map(l => Number(l.val_mae?.toFixed(4) || 0)),
      },
    ],
  };

  const dsModels = models.find(m => m.data_source_id === selectedDs);
  const t = lang === "zh" ? {
    title: "模型进化",
    subtitle: "版本时间线 · 进化曲线 · 一键回滚 · 全量重训",
    noData: "暂无模型记录 — 数据积累到 60 行后自动触发首次训练",
    versions: "版本历史",
    production: "现役",
    rollback: "回滚到此版本",
    retrain: "全量重训",
    retraining: "重训中...",
    logs: "训练日志",
    ds: "数据源",
    all: "全部",
    version: "版本",
    type: "类型",
    status: "状态",
    mae: "MAE",
    acc: "Accuracy",
    rows: "样本",
    promoted: "晋升",
    skipped: "跳过",
    query: "触发问题",
    duration: "耗时",
    note: "备注",
    time: "时间",
    loading: "加载中...",
  } : {
    title: "Model Evolution",
    subtitle: "Version timeline · Evolution curve · One-click rollback · Full retrain",
    noData: "No models yet — training triggers automatically when data reaches 60 rows",
    versions: "Version History",
    production: "Production",
    rollback: "Rollback to this",
    retrain: "Full Retrain",
    retraining: "Retraining...",
    logs: "Training Logs",
    ds: "Data Source",
    all: "All",
    version: "Version",
    type: "Type",
    status: "Status",
    mae: "MAE",
    acc: "Accuracy",
    rows: "Rows",
    promoted: "Promoted",
    skipped: "Skipped",
    query: "Trigger Query",
    duration: "Duration",
    note: "Note",
    time: "Time",
    loading: "Loading...",
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-gray-400 text-lg">{t.loading}</div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <TrendingUp className="h-7 w-7 text-indigo-500" />
            {t.title}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t.subtitle}</p>
        </div>
      </div>

      {/* Data Source Selector */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-gray-500">{t.ds}:</span>
        <button
          onClick={() => setSelectedDs("")}
          className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
            !selectedDs ? "bg-indigo-50 border-indigo-300 text-indigo-600" : "border-gray-200 hover:border-indigo-200"
          }`}
        >
          {t.all}
        </button>
        {models.map(m => (
          <button
            key={m.data_source_id}
            onClick={() => setSelectedDs(m.data_source_id)}
            className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
              selectedDs === m.data_source_id ? "bg-indigo-50 border-indigo-300 text-indigo-600" : "border-gray-200 hover:border-indigo-200"
            }`}
          >
            {m.data_source_name || m.data_source_id.slice(0, 8)}
          </button>
        ))}
      </div>

      {models.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-12 text-center">
          <Activity className="h-12 w-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-400">{t.noData}</p>
        </div>
      ) : (
        <>
          {/* Version Timeline + Evolution Curve */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Version Timeline */}
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="flex items-center gap-2 text-lg font-semibold">
                  <Clock className="h-5 w-5 text-indigo-500" />
                  {t.versions}
                </h2>
                {selectedDs && (
                  <button
                    onClick={() => handleRetrain(selectedDs)}
                    disabled={retraining === selectedDs}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-500 text-white text-sm hover:bg-indigo-600 disabled:opacity-50"
                  >
                    <Zap className="h-4 w-4" />
                    {retraining === selectedDs ? t.retraining : t.retrain}
                  </button>
                )}
              </div>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {(dsModels?.versions || models.flatMap(m => m.versions)).map(v => {
                  const metrics = v.metrics || {};
                  const isLstm = v.model_type === "lstm";
                  const metricVal = isLstm
                    ? (metrics.mae as number)?.toFixed(4)
                    : (metrics.accuracy as number)?.toFixed(4);
                  return (
                    <div
                      key={v.id}
                      className={`flex items-center gap-3 rounded-lg border p-3 ${
                        v.status === "production" ? "border-emerald-300 bg-emerald-50" : "border-gray-200"
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-medium">
                            {v.model_type.toUpperCase()} v{v.version}
                          </span>
                          <span className={`px-2 py-0.5 rounded-full text-xs border ${STATUS_STYLES[v.status] || ""}`}>
                            {v.status}
                          </span>
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          {isLstm ? `${t.mae}: ${metricVal}` : `${t.acc}: ${metricVal}`}
                          {" · "}{t.rows}: {v.trained_rows ?? "—"}
                          {" · "}{v.created_at?.slice(0, 19).replace("T", " ") ?? "—"}
                        </div>
                      </div>
                      {v.status !== "production" && (
                        <button
                          onClick={() => handleRollback(v.id)}
                          disabled={rollbackTarget === v.id}
                          className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-600 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                          title={t.rollback}
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          {t.rollback}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Evolution Curve */}
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="flex items-center gap-2 text-lg font-semibold mb-4">
                <TrendingUp className="h-5 w-5 text-indigo-500" />
                {lang === "zh" ? "进化曲线" : "Evolution Curve"}
              </h2>
              {promotedLogs.length > 0 ? (
                <ChartRenderer chart={chartData} />
              ) : (
                <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
                  {lang === "zh" ? "暂无训练指标数据" : "No training metrics yet"}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Training Logs Table */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <h2 className="flex items-center gap-2 text-lg font-semibold p-5 pb-3">
          <Activity className="h-5 w-5 text-indigo-500" />
          {t.logs}
          <span className="text-sm font-normal text-gray-400">({dsLogs.length})</span>
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-t border-gray-100 text-left text-gray-500">
                <th className="px-4 py-2 font-medium">#</th>
                <th className="px-4 py-2 font-medium">{t.query}</th>
                <th className="px-4 py-2 font-medium">{t.rows}</th>
                <th className="px-4 py-2 font-medium">{t.mae}/{t.acc}</th>
                <th className="px-4 py-2 font-medium">{t.status}</th>
                <th className="px-4 py-2 font-medium">{t.duration}</th>
                <th className="px-4 py-2 font-medium">{t.note}</th>
                <th className="px-4 py-2 font-medium">{t.time}</th>
              </tr>
            </thead>
            <tbody>
              {dsLogs.map(log => (
                <tr key={log.id} className="border-t border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-400">{log.id}</td>
                  <td className="px-4 py-2 max-w-[200px] truncate" title={log.trigger_query}>
                    {log.trigger_query || "—"}
                  </td>
                  <td className="px-4 py-2 text-gray-600">{log.sample_rows ?? "—"}</td>
                  <td className="px-4 py-2 font-mono text-gray-700">
                    {log.val_mae !== null ? log.val_mae.toFixed(4) : "—"}
                  </td>
                  <td className="px-4 py-2">
                    {log.promoted ? (
                      <span className="inline-flex items-center gap-1 text-emerald-600">
                        <CheckCircle2 className="h-4 w-4" />{t.promoted}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-gray-400">
                        <XCircle className="h-4 w-4" />{t.skipped}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-gray-600">
                    {log.duration_ms ? `${log.duration_ms}ms` : "—"}
                  </td>
                  <td className="px-4 py-2 max-w-[200px] truncate text-gray-500" title={log.note || ""}>
                    {log.note || "—"}
                  </td>
                  <td className="px-4 py-2 text-gray-400 whitespace-nowrap">
                    {log.created_at?.slice(5, 19).replace("T", " ") ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
