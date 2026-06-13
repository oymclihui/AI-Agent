import { create } from "zustand";
import { persist } from "zustand/middleware";

interface VoiceChatState {
  /** Full voice dialog: auto-send after STT + TTS for assistant reply */
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
  toggle: () => void;
}

export const useVoiceChatStore = create<VoiceChatState>()(
  persist(
    (set, get) => ({
      enabled: false,
      setEnabled: (enabled) => set({ enabled }),
      toggle: () => set({ enabled: !get().enabled }),
    }),
    { name: "aiagnet-voice-chat" },
  ),
);
