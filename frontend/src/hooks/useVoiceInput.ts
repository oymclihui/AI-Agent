"use client";

import { useCallback, useRef, useState } from "react";
import { chatApi } from "@/lib/api";

export type VoiceInputState = "idle" | "recording" | "processing";

type SpeechRecognitionCtor = new () => {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: { length: number; [i: number]: { 0: { transcript: string } } } }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

function getBrowserSpeechRecognition(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

async function transcribeWithBrowser(lang: "zh" | "en"): Promise<string> {
  const Ctor = getBrowserSpeechRecognition();
  if (!Ctor) {
    throw new Error("browser speech recognition unavailable");
  }

  return new Promise((resolve, reject) => {
    const recognition = new Ctor();
    recognition.lang = lang === "zh" ? "zh-CN" : "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };

    recognition.onresult = (event) => {
      const parts: string[] = [];
      for (let i = 0; i < event.results.length; i += 1) {
        parts.push(event.results[i][0].transcript);
      }
      try {
        recognition.stop();
      } catch {
        /* already stopped */
      }
      finish(() => resolve(parts.join("").trim()));
    };
    recognition.onerror = (event) => {
      finish(() => reject(new Error(event.error || "speech recognition failed")));
    };
    recognition.onend = () => {
      finish(() => reject(new Error("no speech detected")));
    };

    try {
      recognition.start();
    } catch (err) {
      finish(() => reject(err instanceof Error ? err : new Error("speech recognition failed")));
    }
  });
}

export function useVoiceInput(lang: "zh" | "en", disabled = false) {
  const [state, setState] = useState<VoiceInputState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  const stopRecording = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const recorder = recorderRef.current;
      if (!recorder || recorder.state === "inactive") {
        cleanupStream();
        resolve(null);
        return;
      }
      recorder.onstop = () => {
        const blob = chunksRef.current.length
          ? new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" })
          : null;
        cleanupStream();
        resolve(blob);
      };
      recorder.stop();
    });
  }, [cleanupStream]);

  const transcribe = useCallback(
    async (onText: (text: string) => void): Promise<void> => {
      if (disabled) return;

      if (state === "recording") {
        setState("processing");
        const blob = await stopRecording();
        if (!blob || blob.size < 200) {
          setState("idle");
          throw new Error(lang === "zh" ? "录音太短，请重新说一遍" : "Recording too short");
        }

        try {
          const result = await chatApi.transcribe(blob, lang);
          if (result.text) onText(result.text);
        } catch (apiErr) {
          try {
            const text = await transcribeWithBrowser(lang);
            if (text) onText(text);
          } catch {
            throw apiErr;
          }
        } finally {
          setState("idle");
        }
        return;
      }

      if (state !== "idle") return;

      if (!navigator.mediaDevices?.getUserMedia) {
        setState("processing");
        try {
          const text = await transcribeWithBrowser(lang);
          if (text) onText(text);
        } finally {
          setState("idle");
        }
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm";
        const recorder = new MediaRecorder(stream, { mimeType });
        chunksRef.current = [];
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) chunksRef.current.push(e.data);
        };
        recorder.start(250);
        recorderRef.current = recorder;
        setState("recording");
      } catch (err) {
        cleanupStream();
        setState("idle");
        throw err;
      }
    },
    [disabled, lang, state, stopRecording, cleanupStream],
  );

  const cancel = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.onstop = () => cleanupStream();
      recorderRef.current.stop();
    } else {
      cleanupStream();
    }
    setState("idle");
  }, [cleanupStream]);

  return {
    state,
    isRecording: state === "recording",
    isProcessing: state === "processing",
    toggle: transcribe,
    cancel,
  };
}
