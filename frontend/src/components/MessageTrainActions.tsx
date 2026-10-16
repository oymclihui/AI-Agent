"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, Pencil, Play, Sparkles, Star, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { clsx } from "clsx";
import toast from "react-hot-toast";
import type { Lang } from "@/lib/i18n";
import { dataAskApi, dsDistillApi } from "@/lib/api";

type FeedbackKind = "like" | "dislike" | "correction" | "example";

interface TrainTaskState {
  id: number;
  kind?: string;
  status: string;
  progress?: number;
  detail?: Record<string, unknown> | null;
  error?: string | null;
}

interface PreviewState {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  duration_ms: number;
}

const T: Record<string, { zh: string; en: string }> = {
  like: { zh: "点赞", en: "Like" },
  dislike: { zh: "点踩", en: "Dislike" },
  correction: { zh: "纠正 SQL", en: "Correct SQL" },
  example: { zh: "存为示例", en: "Save as example" },
  liked: { zh: "已点赞", en: "Liked" },
  disliked: { zh: "已点踩", en: "Disliked" },
  corrected: { zh: "已纠正", en: "Corrected" },
  saved: { zh: "已存为示例", en: "Saved" },
  submitted: { zh: "反馈已提交，正在蒸馏进问数记忆", en: "Feedback submitted · distilling" },
  queued: { zh: "训练排队中", en: "Queued" },
  running: { zh: "蒸馏中", en: "Distilling" },
  done: { zh: "训练完成", en: "Distill done" },
  failed: { zh: "训练失败", en: "Distill failed" },
  retry: { zh: "重试", en: "Retry" },
  cancel: { zh: "取消", en: "Cancel" },
  submit: { zh: "提交纠正", en: "Submit" },
  sqlPlaceholder: { zh: "粘贴纠正后的 SELECT 语句", en: "Corrected SELECT statement" },
  needSql: { zh: "请填写纠正后的 SQL", en: "Corrected SQL is required" },
  failedMsg: { zh: "反馈提交失败", en: "Feedback failed" },
  trained: { zh: "已参考 {n} 条历史示例", en: "Used {n} past examples" },
  examplesAdded: { zh: "本批新增/更新示例 {n} 条", en: "{n} examples added/updated" },
  noSample: { zh: "暂无可蒸馏样本", en: "No sample to distill" },
  originSql: { zh: "原 SQL", en: "Original SQL" },
  fixedSql: { zh: "修正 SQL", en: "Corrected SQL" },
  preview: { zh: "试跑预览", en: "Test run" },
  previewing: { zh: "试跑中", en: "Running" },
  previewNeed: { zh: "请先试跑预览确认结果", en: "Run preview before saving" },
  previewFail: { zh: "试跑失败", en: "Preview failed" },
  previewOk: { zh: "试跑通过", en: "Preview OK" },
  previewTruncated: { zh: "仅显示前 {n} 行", en: "Showing first {n} rows" },
  needChange: { zh: "修正 SQL 与原 SQL 相同", en: "Corrected SQL equals original" },
};

function pick(key: string, lang: Lang): string {
  const item = T[key];
  return item ? item[lang] : key;
}

export function MessageTrainActions({
  dataSourceId,
  traceId,
  question,
  originalSql,
  memoryHits = 0,
  lang,
}: {
  dataSourceId: string;
  traceId?: number | null;
  question?: string;
  originalSql?: string | null;
  memoryHits?: number;
  lang: Lang;
}) {
  const [feedback, setFeedback] = useState<FeedbackKind | null>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [task, setTask] = useState<TrainTaskState | null>(null);
  const [pending, setPending] = useState<FeedbackKind | null>(null);
  const [openPanel, setOpenPanel] = useState(false);
  const [corrected, setCorrected] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const timerRef = useRef<number | null>(null);

  // 行级 diff（简单 LCS）：仅展示增/删差异行
  const origLines = (originalSql || "").replace(/\r/g, "").split("\n");
  const corrLines = corrected.replace(/\r/g, "").split("\n");
  const n = origLines.length;
  const m = corrLines.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = origLines[i] === corrLines[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const diffLines: { type: "add" | "del"; text: string }[] = [];
  {
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (origLines[i] === corrLines[j]) { i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { diffLines.push({ type: "del", text: origLines[i++] }); }
      else { diffLines.push({ type: "add", text: corrLines[j++] }); }
    }
    while (i < n) diffLines.push({ type: "del", text: origLines[i++] });
    while (j < m) diffLines.push({ type: "add", text: corrLines[j++] });
  }

  const runPreview = async () => {
    const sql = corrected.trim();
    if (!sql) {
      toast.error(pick("needSql", lang));
      return;
    }
    setPreviewLoading(true);
    setPreview(null);
    try {
      const { data } = await dsDistillApi.trainPreview({ data_source_id: dataSourceId, sql, limit: 50 });
      setPreview({
        columns: data?.columns || [],
        rows: data?.rows || [],
        row_count: Number(data?.row_count || 0),
        truncated: Boolean(data?.truncated),
        duration_ms: Number(data?.duration_ms || 0),
      });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : "");
      toast.error(`${pick("previewFail", lang)}: ${detail.slice(0, 160)}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  useEffect(() => {
    if (!taskId) return;
    let stopped = false;
    let ticks = 0;
    const poll = async () => {
      try {
        const { data } = await dataAskApi.trainTask(taskId);
        if (!stopped) setTask(data as TrainTaskState);
        if (data?.status === "done" || data?.status === "failed") return;
      } catch {
        /* 轮询失败不打扰用户 */
      }
      ticks += 1;
      if (ticks < 24 && !stopped) {
        timerRef.current = window.setTimeout(poll, 1500);
      }
    };
    void poll();
    return () => {
      stopped = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [taskId]);

  const submit = async (kind: FeedbackKind, extra?: { corrected_sql?: string; comment?: string }) => {
    if (pending) return;
    setPending(kind);
    try {
      const { data } = await dataAskApi.feedback({
        data_source_id: dataSourceId,
        feedback_type: kind,
        trace_id: traceId ?? undefined,
        question: question || undefined,
        original_sql: originalSql || undefined,
        ...extra,
      });
      setFeedback(kind);
      if (data?.task_id) setTaskId(data.task_id);
      toast.success(pick("submitted", lang), { id: "train-feedback" });
      if (kind === "correction") setOpenPanel(false);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err instanceof Error ? err.message : "");
      toast.error(detail ? `${pick("failedMsg", lang)}: ${detail}` : pick("failedMsg", lang));
    } finally {
      setPending(null);
    }
  };

  const btnCls = (active: boolean) =>
    clsx(
      "inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] transition",
      active
        ? "bg-blue-600/30 text-blue-200 ring-1 ring-blue-500/40"
        : "text-slate-400 hover:bg-slate-700/60 hover:text-slate-200",
    );

  const addedCount =
    task?.detail && typeof task.detail === "object"
      ? Number((task.detail as Record<string, unknown>).created || 0) +
        Number((task.detail as Record<string, unknown>).updated || 0)
      : 0;

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {memoryHits > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-300">
            <Sparkles className="h-3 w-3 shrink-0" />
            {pick("trained", lang).replace("{n}", String(memoryHits))}
          </span>
        )}
        <button type="button" className={btnCls(feedback === "like")} onClick={() => void submit("like")}>
          {pending === "like" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
          {pick("like", lang)}
        </button>
        <button type="button" className={btnCls(feedback === "dislike")} onClick={() => void submit("dislike")}>
          {pending === "dislike" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsDown className="h-3.5 w-3.5" />}
          {pick("dislike", lang)}
        </button>
        <button
          type="button"
          className={btnCls(feedback === "correction" || openPanel)}
          onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            setCorrected((prev) => prev || originalSql || "");
            setOpenPanel(true);
          }}
        >
          <Pencil className="h-3.5 w-3.5" />
          {pick("correction", lang)}
        </button>
        <button
          type="button"
          className={btnCls(feedback === "example")}
          onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            void submit("example");
          }}
        >
          <Star className="h-3.5 w-3.5" />
          {pick("example", lang)}
        </button>
      </div>

      {openPanel && (
        <div className="rounded-lg border border-[#2d2d4e] bg-[#14142a] p-2" onClick={(e) => e.stopPropagation()}>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <div>
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">{pick("originSql", lang)}</div>
              <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-all rounded-md border border-[#2d2d4e] bg-[#0f0f22] px-2 py-1.5 font-mono text-[11px] leading-relaxed text-slate-400">
                {originalSql || "—"}
              </pre>
            </div>
            <div>
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">{pick("fixedSql", lang)}</div>
              <textarea
                value={corrected}
                onChange={(e) => {
                  setCorrected(e.target.value);
                  setPreview(null);
                }}
                rows={6}
                spellCheck={false}
                placeholder={pick("sqlPlaceholder", lang)}
                className="h-44 w-full resize-none rounded-md border border-[#2d2d4e] bg-[#0f0f22] px-2 py-1.5 font-mono text-[11px] leading-relaxed text-slate-200 outline-none focus:border-blue-500/60"
              />
            </div>
          </div>

          {diffLines.length > 0 && (
            <div className="mt-1.5 max-h-32 overflow-auto rounded-md border border-[#2d2d4e] bg-[#0f0f22] px-2 py-1.5 font-mono text-[11px] leading-relaxed">
              {diffLines.map((d, i) => (
                <div
                  key={i}
                  className={clsx(
                    "whitespace-pre-wrap break-all",
                    d.type === "add" ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300",
                  )}
                >
                  {d.type === "add" ? "+ " : "- "}
                  {d.text}
                </div>
              ))}
            </div>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={previewLoading}
              onClick={() => void runPreview()}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-[#2d2d4e] px-2.5 text-[11px] font-medium text-slate-200 transition hover:border-blue-500/50 hover:text-blue-300 disabled:opacity-60"
            >
              {previewLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              {previewLoading ? pick("previewing", lang) : pick("preview", lang)}
            </button>
            <button
              type="button"
              disabled={pending === "correction" || !preview}
              title={preview ? undefined : pick("previewNeed", lang)}
              onClick={() => {
                if (!corrected.trim()) {
                  toast.error(pick("needSql", lang));
                  return;
                }
                void submit("correction", { corrected_sql: corrected.trim() });
              }}
              className="inline-flex h-7 items-center gap-1 rounded-md bg-blue-600 px-2.5 text-[11px] font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {pending === "correction" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pencil className="h-3.5 w-3.5" />}
              {pick("submit", lang)}
            </button>
            <button
              type="button"
              onClick={() => setOpenPanel(false)}
              className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] text-slate-400 transition hover:bg-slate-700/60 hover:text-slate-200"
            >
              <X className="h-3.5 w-3.5" />
              {pick("cancel", lang)}
            </button>
            {preview && (
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-300">
                <CheckCircle2 className="h-3 w-3" />
                {pick("previewOk", lang)} · {preview.row_count} rows · {preview.duration_ms}ms
                {preview.truncated ? ` · ${pick("previewTruncated", lang).replace("{n}", String(preview.rows.length))}` : ""}
              </span>
            )}
          </div>

          {preview && preview.columns.length > 0 && (
            <div className="mt-1.5 max-h-40 overflow-auto rounded-md border border-[#2d2d4e]">
              <table className="w-full border-collapse text-[11px]">
                <thead>
                  <tr className="bg-slate-800/60">
                    {preview.columns.map((c) => (
                      <th key={c} className="px-2 py-1 text-left font-medium text-slate-300">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 8).map((r, i) => (
                    <tr key={i} className="border-t border-[#22224a]">
                      {preview.columns.map((c, j) => (
                        <td key={c} className="max-w-40 truncate px-2 py-1 text-slate-400">{String(r[j] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {feedback && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
          <span>
            {feedback === "like"
              ? pick("liked", lang)
              : feedback === "dislike"
                ? pick("disliked", lang)
                : feedback === "correction"
                  ? pick("corrected", lang)
                  : pick("saved", lang)}
          </span>
          {task && (
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-md px-2 py-0.5",
                task.status === "done"
                  ? "bg-emerald-500/15 text-emerald-300"
                  : task.status === "failed"
                    ? "bg-rose-500/15 text-rose-300"
                    : "bg-slate-700/40 text-slate-300",
              )}
            >
              {(task.status === "queued" || task.status === "running") && (
                <Loader2 className="h-3 w-3 animate-spin" />
              )}
              {task.status === "done"
                ? addedCount > 0
                  ? `${pick("done", lang)} · ${pick("examplesAdded", lang).replace("{n}", String(addedCount))}`
                  : `${pick("done", lang)} · ${pick("noSample", lang)}`
                : task.status === "failed"
                  ? `${pick("failed", lang)}${task.error ? `：${task.error.slice(0, 80)}` : ""}`
                  : pick(task.status, lang)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
