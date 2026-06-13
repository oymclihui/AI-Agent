"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Strip markdown/noise before browser TTS. */
export function textForSpeech(raw: string, maxLen = 4000): string {
  const text = raw
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]+`/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/[#*_~>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen)}…`;
}

export function useVoiceOutput(lang: "zh" | "en") {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const load = () => window.speechSynthesis.getVoices();
    load();
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", load);
      window.speechSynthesis.cancel();
    };
  }, []);

  const stop = useCallback(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
    utteranceRef.current = null;
  }, []);

  const speak = useCallback(
    (raw: string): Promise<void> => {
      const text = textForSpeech(raw);
      if (!text) return Promise.resolve();

      if (typeof window === "undefined" || !window.speechSynthesis) {
        return Promise.resolve();
      }

      stop();

      return new Promise((resolve) => {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = lang === "zh" ? "zh-CN" : "en-US";
        utterance.rate = 1;
        utterance.pitch = 1;

        const voices = window.speechSynthesis.getVoices();
        const preferred =
          voices.find((v) => v.lang.startsWith(lang === "zh" ? "zh" : "en") && !v.localService) ||
          voices.find((v) => v.lang.startsWith(lang === "zh" ? "zh" : "en"));
        if (preferred) utterance.voice = preferred;

        utterance.onstart = () => setIsSpeaking(true);
        utterance.onend = () => {
          setIsSpeaking(false);
          utteranceRef.current = null;
          resolve();
        };
        utterance.onerror = () => {
          setIsSpeaking(false);
          utteranceRef.current = null;
          resolve();
        };

        utteranceRef.current = utterance;
        window.speechSynthesis.speak(utterance);
      });
    },
    [lang, stop],
  );

  return { speak, stop, isSpeaking };
}
