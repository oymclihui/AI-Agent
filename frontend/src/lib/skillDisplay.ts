import type { Lang } from "@/lib/i18n";

type I18nBlock = {
  display_name?: string | Record<string, string>;
  description?: string | Record<string, string>;
};

export function pickSkillField(
  i18n: I18nBlock | undefined,
  field: "display_name" | "description",
  lang: Lang,
  fallback: string,
): string {
  if (!i18n?.[field]) return fallback;
  const block = i18n[field];
  if (typeof block === "string") return block || fallback;
  const other = lang === "zh" ? "en" : "zh";
  return block[lang]?.trim() || block[other]?.trim() || fallback;
}

export function localizeSkillFields<T extends { display_name: string; description: string; metadata?: { i18n?: I18nBlock } }>(
  skill: T,
  lang: Lang,
): { display_name: string; description: string } {
  const i18n = skill.metadata?.i18n;
  return {
    display_name: pickSkillField(i18n, "display_name", lang, skill.display_name),
    description: pickSkillField(i18n, "description", lang, skill.description),
  };
}
