import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Lang } from "./i18n";

interface LangState {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

export const useLangStore = create<LangState>()(
  persist(
    (set) => ({
      lang: "zh",
      setLang: (lang) => set({ lang }),
    }),
    { name: "aiagnet-lang" }
  )
);
