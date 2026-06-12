"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, Save, AlertTriangle } from "lucide-react";
import { useLangStore } from "@/lib/langStore";
import { translations } from "@/lib/i18n";
import {
  designerUrl,
  INSPIRE_LCE_MSG,
  isLowcodeMessage,
  isLowcodeSaveMessage,
  probeLowcodeDesigner,
  type LowcodeInspirationPayload,
} from "@/lib/lowcodeBridge";
import {
  getInspirationMerged,
  getLowcodePayload,
  saveInspirationOverride,
} from "@/lib/inspirationStore";
import toast from "react-hot-toast";

export default function InspirationLowcodeDesignerPage() {
  const params = useParams();
  const inspireId = String(params.id ?? "");
  const { lang } = useLangStore();
  const ins = translations.inspiration;
  const c = translations.common;

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [packaged, setPackaged] = useState<boolean | null>(null);
  const [iframeError, setIframeError] = useState(false);

  const item = useMemo(() => getInspirationMerged(inspireId), [inspireId]);

  useEffect(() => {
    probeLowcodeDesigner().then(setPackaged);
  }, []);

  const sendInit = useCallback(() => {
    const frame = iframeRef.current?.contentWindow;
    if (!frame || !item) return;
    const payload = getLowcodePayload(item, lang);
    frame.postMessage(
      {
        type: INSPIRE_LCE_MSG.INIT,
        inspireId,
        pageSchema: payload?.pageSchema ?? null,
        projectSchema: payload?.projectSchema ?? null,
      },
      "*",
    );
    setLoading(false);
  }, [inspireId, item, lang]);

  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      if (!isLowcodeMessage(ev.data)) return;
      const { type } = ev.data;
      if (type === INSPIRE_LCE_MSG.REQUEST_INIT && ev.data.inspireId === inspireId) {
        sendInit();
      }
      if (type === INSPIRE_LCE_MSG.READY && ev.data.inspireId === inspireId) {
        setReady(true);
        setIframeError(false);
        sendInit();
      }
      if (isLowcodeSaveMessage(ev.data) && ev.data.inspireId === inspireId) {
        const lowcode: LowcodeInspirationPayload = {
          projectSchema: ev.data.projectSchema,
          pageSchema: ev.data.pageSchema,
        };
        saveInspirationOverride(inspireId, lang, { lowcode });
        ev.source?.postMessage({ type: INSPIRE_LCE_MSG.SAVED_ACK, inspireId }, { targetOrigin: "*" });
        toast.success(ins.lowcodeSaved[lang]);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [inspireId, lang, ins.lowcodeSaved, sendInit]);

  const iframeSrc = designerUrl(inspireId, lang);

  useEffect(() => {
    if (packaged !== true) return;
    const timer = window.setTimeout(() => {
      if (!ready) {
        setIframeError(true);
        setLoading(false);
      }
    }, 12000);
    return () => window.clearTimeout(timer);
  }, [packaged, ready, iframeSrc]);

  if (!item) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 theme-muted">
        <p>{lang === "zh" ? "未找到灵感模板" : "Inspiration template not found"}</p>
        <Link href="/inspiration" className="agents-btn-secondary text-sm">
          {ins.backToGallery[lang]}
        </Link>
      </div>
    );
  }

  if (packaged === false || iframeError) {
    return (
      <div className="inspiration-lce-shell">
        <header className="inspiration-lce-toolbar">
          <Link href="/inspiration" className="inspiration-lce-back">
            <ArrowLeft className="h-4 w-4" />
            {ins.backToGallery[lang]}
          </Link>
          <div className="inspiration-lce-title">
            <h1>{lang === "zh" ? item.title.zh : item.title.en}</h1>
            <p>{ins.lowcodeDesigner[lang]}</p>
          </div>
        </header>
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
          <AlertTriangle className="h-10 w-10 text-amber-500" />
          <h2 className="text-lg font-semibold theme-text">{ins.lowcodeUnavailable[lang]}</h2>
          <p className="max-w-xl text-sm theme-muted leading-relaxed">{ins.lowcodeUnavailableHint[lang]}</p>
          <p className="text-sm theme-muted">{ins.lowcodeUseJsonEdit[lang]}</p>
          <div className="flex flex-wrap justify-center gap-2 pt-2">
            <Link href="/inspiration" className="agents-btn-primary text-sm">
              {ins.backToGallery[lang]}
            </Link>
            <Link href="/chat" className="agents-btn-secondary text-sm">
              {translations.nav.chat[lang]}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="inspiration-lce-shell">
      <header className="inspiration-lce-toolbar">
        <Link href="/inspiration" className="inspiration-lce-back">
          <ArrowLeft className="h-4 w-4" />
          {ins.backToGallery[lang]}
        </Link>
        <div className="inspiration-lce-title">
          <h1>{lang === "zh" ? item.title.zh : item.title.en}</h1>
          <p>{ins.lowcodeDesigner[lang]}</p>
        </div>
        <div className="inspiration-lce-actions">
          {!ready && (
            <span className="flex items-center gap-1 text-xs theme-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {c.loading[lang]}
            </span>
          )}
          <span className="inspiration-json-badge">{ins.lowcodeEngine[lang]}</span>
          <button
            type="button"
            className="agents-btn-secondary text-xs"
            onClick={() => {
              iframeRef.current?.contentWindow?.postMessage({ type: "noop" }, "*");
              toast(ins.lowcodeSaveHint[lang], { icon: <Save className="h-4 w-4" /> });
            }}
          >
            <Save className="h-3.5 w-3.5 inline mr-1" />
            {ins.lowcodeSaveBtn[lang]}
          </button>
        </div>
      </header>

      {loading && packaged === null && (
        <div className="inspiration-lce-loading">
          <Loader2 className="h-8 w-8 animate-spin theme-muted" />
        </div>
      )}

      <iframe
        ref={iframeRef}
        title="LowcodeEngine Designer"
        src={iframeSrc}
        className="inspiration-lce-iframe"
        onLoad={() => {
          setTimeout(sendInit, 300);
        }}
        onError={() => setIframeError(true)}
      />
    </div>
  );
}
