export type EmployeeTemplateCategoryId =
  | "all"
  | "marketing"
  | "analytics"
  | "data"
  | "engineering"
  | "finance"
  | "security"
  | "design"
  | "research"
  | "ops"
  | "general";

export interface EmployeeTemplateCategory {
  id: EmployeeTemplateCategoryId;
  label: { zh: string; en: string };
}

export const EMPLOYEE_CATEGORIES: EmployeeTemplateCategory[] = [
  { id: "all", label: { zh: "全部", en: "All" } },
  { id: "marketing", label: { zh: "内容营销", en: "Marketing" } },
  { id: "analytics", label: { zh: "数据分析", en: "Analytics" } },
  { id: "data", label: { zh: "数据工程", en: "Data" } },
  { id: "engineering", label: { zh: "技术工程", en: "Engineering" } },
  { id: "finance", label: { zh: "金融投研", en: "Finance" } },
  { id: "security", label: { zh: "安全合规", en: "Security" } },
  { id: "design", label: { zh: "设计交付", en: "Design" } },
  { id: "research", label: { zh: "行业研究", en: "Research" } },
  { id: "ops", label: { zh: "运维保障", en: "Ops" } },
  { id: "general", label: { zh: "通用", en: "General" } },
];

const AVATAR_TONES = [
  "agents-avatar-1",
  "agents-avatar-2",
  "agents-avatar-3",
  "agents-avatar-4",
  "agents-avatar-5",
  "agents-avatar-6",
];

export function employeeAvatarTone(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash + id.charCodeAt(i)) % AVATAR_TONES.length;
  return AVATAR_TONES[hash];
}

export function normalizeTemplateCategory(raw: string): EmployeeTemplateCategoryId {
  const c = (raw || "general").toLowerCase();
  const allowed: EmployeeTemplateCategoryId[] = [
    "marketing", "analytics", "data", "engineering", "finance",
    "security", "design", "research", "ops", "general",
  ];
  return allowed.includes(c as EmployeeTemplateCategoryId)
    ? (c as EmployeeTemplateCategoryId)
    : "general";
}

export function categoryLabel(categoryId: string, lang: "zh" | "en"): string {
  const id = normalizeTemplateCategory(categoryId);
  const found = EMPLOYEE_CATEGORIES.find((c) => c.id === id);
  return found ? found.label[lang] : categoryId;
}
