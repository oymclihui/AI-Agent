"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { downloadArtifact } from "@/lib/artifacts";
import type { Lang } from "@/lib/i18n";
import {
  closeArtifactPanel,
  closeArtifactTab,
  getArtifactResult,
  openArtifact,
  reloadArtifact,
  setArtifactDevice,
  subscribeArtifactResult,
  toggleArtifactFullscreen,
  toggleArtifactSource,
} from "@/lib/artifactResultStore";

type Props = { lang: Lang };

export default function ArtifactResultPanel({ lang }: Props) {
  const state = useSyncExternalStore(subscribeArtifactResult, getArtifactResult, getArtifactResult);
  const zh = lang !== "en";
  const current = state.artifacts.find((item) => item.filename === state.active) ?? null;
  const [sourceText, setSourceText] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState(false);

  useEffect(() => {
    setSourceText(null);
    setSourceError(false);
  }, [current?.previewUrl, state.reload]);

  useEffect(() => {
    if (!state.source || !current || sourceText !== null) return;
    let cancelled = false;
    fetch(current.previewUrl, { credentials: "same-origin" })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setSourceText(text);
      })
      .catch(() => {
        if (!cancelled) setSourceError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [state.source, current, sourceText]);

  if (state.artifacts.length === 0) return null;

  if (!state.open || !current) {
    return (
      <button
        type="button"
        onClick={() => openArtifact(state.artifacts[state.artifacts.length - 1].filename)}
        className="theme-card m-2 h-fit shrink-0 px-2 py-3 text-xs hover:border-blue-400"
      >
        {zh ? `产物 ${state.artifacts.length}` : `Files ${state.artifacts.length}`}
      </button>
    );
  }

  const frameClass = state.device === "phone" ? "mx-auto h-full w-[390px] max-w-full border-x theme-border bg-white" : "h-full w-full bg-white";

  return (
    <aside
      className={
        state.fullscreen
          ? "theme-bg fixed inset-0 z-[60] flex flex-col"
          : "theme-bg flex h-full w-[min(42rem,46vw)] min-w-[22rem] shrink-0 flex-col border-l theme-border"
      }
    >
      <div className="flex items-center gap-1 border-b theme-border px-2 py-1">
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
          {state.tabs.map((filename) => (
            <button
              key={filename}
              type="button"
              onClick={() => openArtifact(filename)}
              className={`flex max-w-[12rem] items-center gap-1 rounded px-2 py-1 text-xs ${
                filename === state.active ? "bg-[var(--nav-active-bg)] text-[var(--nav-active-text)]" : "theme-muted hover:bg-[var(--hover)]"
              }`}
            >
              <span className="truncate">{filename}</span>
              <span
                role="button"
                aria-label={zh ? "关闭页签" : "Close tab"}
                className="theme-muted hover:text-[var(--foreground)]"
                onClick={(event) => {
                  event.stopPropagation();
                  closeArtifactTab(filename);
                }}
              >
                ×
              </span>
            </button>
          ))}
        </div>
        <button type="button" className="theme-muted shrink-0 px-2 text-xs hover:text-[var(--foreground)]" onClick={() => toggleArtifactFullscreen()}>
          {state.fullscreen ? (zh ? "退出全屏" : "Exit") : (zh ? "全屏" : "Full")}
        </button>
        <button type="button" className="theme-muted shrink-0 px-2 text-xs hover:text-[var(--foreground)]" onClick={() => closeArtifactPanel()}>
          {zh ? "收起" : "Hide"}
        </button>
      </div>
      <div className="flex items-center gap-2 border-b theme-border px-3 py-2">
        <div className="theme-muted min-w-0 flex-1 truncate text-xs">{current.previewUrl}</div>
        <button type="button" className="theme-text text-xs" onClick={() => setArtifactDevice(state.device === "phone" ? "desktop" : "phone")}>
          {state.device === "phone" ? (zh ? "桌面" : "Desktop") : (zh ? "手机" : "Phone")}
        </button>
        <button type="button" className="theme-text text-xs" onClick={() => reloadArtifact()}>
          {zh ? "刷新" : "Reload"}
        </button>
        <button type="button" className={`text-xs ${state.source ? "text-blue-600" : "theme-text"}`} onClick={() => toggleArtifactSource()}>
          {state.source ? (zh ? "预览" : "Preview") : (zh ? "源码" : "Code")}
        </button>
        <button
          type="button"
          className="theme-text text-xs"
          onClick={() => {
            downloadArtifact(`${current.previewUrl}?download=1`, current.filename).catch(() => {
              window.open(`${current.previewUrl}?download=1`, "_blank", "noopener,noreferrer");
            });
          }}
        >
          {zh ? "下载" : "Download"}
        </button>
      </div>
      <div className="theme-bg min-h-0 flex-1">
        {state.source ? (
          <pre className="theme-text h-full overflow-auto whitespace-pre-wrap bg-[var(--prose-code-bg)] p-3 text-xs">
            {sourceError ? (zh ? "源码加载失败" : "Failed to load source") : sourceText ?? "…"}
          </pre>
        ) : (
          <iframe
            key={`${current.filename}-${state.reload}`}
            title={current.filename}
            sandbox="allow-scripts allow-forms allow-popups"
            src={`${current.previewUrl}?v=${state.reload}`}
            className={`bg-white ${frameClass}`}
          />
        )}
      </div>
    </aside>
  );
}
