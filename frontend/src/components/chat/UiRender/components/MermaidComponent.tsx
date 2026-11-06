"use client";

import { useEffect, useId, useState } from "react";
import type { UiNode, MermaidProps } from "../types";

type MermaidApi = typeof import("mermaid")["default"];

// 全局只初始化一次，避免每条消息重复 initialize
let mermaidPromise: Promise<MermaidApi> | null = null;
// 相同 code 渲染结果缓存，避免重复计算
const svgCache = new Map<string, string>();

function getMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        theme: "default",
        securityLevel: "loose",
        fontFamily: "inherit",
        flowchart: { useMaxWidth: true },
        sequence: { useMaxWidth: true },
      });
      return mod.default;
    });
  }
  return mermaidPromise;
}

/**
 * Mermaid 图表渲染：mermaid 体积较大，使用动态 import 按需加载，
 * 只在消息里出现 Mermaid 组件时才进入浏览器 bundle。
 */
export function MermaidComponent({ node }: { node: UiNode }) {
  const p = (node.props || {}) as unknown as MermaidProps;
  const code = (p.code || "").trim();
  const rawId = useId();
  const renderId = `mermaid-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const [svg, setSvg] = useState<string>(() => svgCache.get(code) || "");
  const [error, setError] = useState<string>("");
  const [zoom, setZoom] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!code) {
      setSvg("");
      setError("");
      return;
    }
    const cached = svgCache.get(code);
    if (cached) {
      setSvg(cached);
      setError("");
      return;
    }
    (async () => {
      try {
        const mermaid = await getMermaid();
        const result = await mermaid.render(renderId, code);
        svgCache.set(code, result.svg);
        if (!cancelled) {
          setSvg(result.svg);
          setError("");
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, renderId]);

  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZoom(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 剪贴板不可用时静默忽略 */
    }
  };

  if (!code) {
    return <div className="text-xs text-slate-400">Mermaid 图表缺少 code</div>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-xs text-rose-700">
        <div className="mb-2 font-medium">图表渲染失败：{error}</div>
        <pre className="max-h-48 overflow-auto rounded bg-slate-100 p-2 text-[11px] leading-relaxed text-slate-700">
          <code>{code}</code>
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="mb-2 h-2 w-24 animate-pulse rounded bg-slate-200" />
        <div className="h-20 w-full animate-pulse rounded bg-slate-100" />
      </div>
    );
  }

  return (
    <div className="ui-mermaid rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-end gap-2 border-b border-slate-100 px-3 py-1.5">
        <button
          type="button"
          onClick={copyCode}
          className="rounded px-2 py-0.5 text-[11px] text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
        >
          {copied ? "已复制" : "复制源码"}
        </button>
        <button
          type="button"
          onClick={() => setZoom(true)}
          className="rounded px-2 py-0.5 text-[11px] text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
        >
          放大
        </button>
      </div>
      <div
        className="overflow-x-auto p-3 [&_svg]:mx-auto [&_svg]:max-w-full"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      {zoom && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80 p-6 backdrop-blur"
          onClick={() => setZoom(false)}
        >
          <div
            className="max-h-full w-full max-w-6xl overflow-auto rounded-xl border border-slate-200 bg-white p-6 [&_svg]:mx-auto [&_svg]:max-w-full"
            onClick={(e) => e.stopPropagation()}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      )}
    </div>
  );
}
