import { INSPIRE_SESSION_KEY, type InspirationItem } from "@/lib/inspirationCatalog";

export interface InspirePendingPayload {
  inspireId: string;
  prompt: string;
  agentHint?: string;
  scene?: string;
  title: string;
}

export function launchInspiration(
  router: { push: (href: string) => void },
  item: InspirationItem,
  lang: "zh" | "en",
) {
  const payload: InspirePendingPayload = {
    inspireId: item.id,
    prompt: item.prompt[lang],
    agentHint: item.agentHint,
    scene: item.scene,
    title: lang === "zh" ? item.title.zh : item.title.en,
  };
  sessionStorage.setItem(INSPIRE_SESSION_KEY, JSON.stringify(payload));
  router.push("/chat?from=inspire");
}
