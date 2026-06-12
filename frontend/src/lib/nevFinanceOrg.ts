/** Manufacturing finance org tree — used for layout and sorting. */
export type OrgCadence = "daily" | "weekly" | "monthly";

export interface OrgNodeSpec {
  templateId: string;
  level: number;
  rank: number;
  reportsTo: string | null;
  cadence: OrgCadence;
  cadenceLabel: { zh: string; en: string };
  shortTitle: { zh: string; en: string };
}

export const NEV_FINANCE_ORG: OrgNodeSpec[] = [
  {
    templateId: "nev-cfo-monthly-board",
    level: 1,
    rank: 0,
    reportsTo: null,
    cadence: "monthly",
    cadenceLabel: { zh: "每月 · 3 日", en: "Monthly · 3rd" },
    shortTitle: { zh: "CFO", en: "CFO" },
  },
  {
    templateId: "nev-vp-finance-weekly",
    level: 2,
    rank: 0,
    reportsTo: "nev-cfo-monthly-board",
    cadence: "weekly",
    cadenceLabel: { zh: "每周 · 周一", en: "Weekly · Mon" },
    shortTitle: { zh: "财务 VP", en: "VP Finance" },
  },
  {
    templateId: "nev-controller-manufacturing-daily",
    level: 3,
    rank: 0,
    reportsTo: "nev-vp-finance-weekly",
    cadence: "daily",
    cadenceLabel: { zh: "每日 + 周五", en: "Daily + Fri" },
    shortTitle: { zh: "财务控制", en: "Controller" },
  },
  {
    templateId: "nev-treasury-weekly",
    level: 3,
    rank: 1,
    reportsTo: "nev-vp-finance-weekly",
    cadence: "weekly",
    cadenceLabel: { zh: "每周 · 周一", en: "Weekly · Mon" },
    shortTitle: { zh: "司库", en: "Treasury" },
  },
  {
    templateId: "nev-fpa-rolling-weekly",
    level: 3,
    rank: 2,
    reportsTo: "nev-vp-finance-weekly",
    cadence: "weekly",
    cadenceLabel: { zh: "每周 · 周一", en: "Weekly · Mon" },
    shortTitle: { zh: "FP&A", en: "FP&A" },
  },
  {
    templateId: "nev-tax-subsidy-monthly",
    level: 3,
    rank: 3,
    reportsTo: "nev-vp-finance-weekly",
    cadence: "monthly",
    cadenceLabel: { zh: "每月 · 5 日", en: "Monthly · 5th" },
    shortTitle: { zh: "税务政策", en: "Tax" },
  },
  {
    templateId: "nev-cost-accounting-weekly",
    level: 4,
    rank: 0,
    reportsTo: "nev-controller-manufacturing-daily",
    cadence: "weekly",
    cadenceLabel: { zh: "每周 · 周一", en: "Weekly · Mon" },
    shortTitle: { zh: "成本会计", en: "Cost" },
  },
];

export const ORG_BY_TEMPLATE = Object.fromEntries(
  NEV_FINANCE_ORG.map((n) => [n.templateId, n]),
) as Record<string, OrgNodeSpec>;

export function orgSpecForEmployee(metadata?: Record<string, unknown> | null): OrgNodeSpec | null {
  const tid = metadata?.template_id;
  if (typeof tid === "string" && ORG_BY_TEMPLATE[tid]) return ORG_BY_TEMPLATE[tid];
  return null;
}

export function sortByOrg<T extends { metadata?: Record<string, unknown> | null }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const oa = orgSpecForEmployee(a.metadata);
    const ob = orgSpecForEmployee(b.metadata);
    if (oa && ob) return oa.level - ob.level || oa.rank - ob.rank;
    if (oa) return -1;
    if (ob) return 1;
    return 0;
  });
}

export function buildOrgLevels(
  employees: Array<{
    id: string;
    name: string;
    title: string | null;
    task_count: number;
    status: string;
    metadata?: Record<string, unknown> | null;
  }>,
): Map<number, typeof employees> {
  const sorted = sortByOrg(employees);
  const levels = new Map<number, typeof employees>();
  for (const emp of sorted) {
    const spec = orgSpecForEmployee(emp.metadata);
    const level = spec?.level ?? 99;
    if (!levels.has(level)) levels.set(level, []);
    levels.get(level)!.push(emp);
  }
  for (const [, list] of levels) {
    list.sort((a, b) => {
      const ra = orgSpecForEmployee(a.metadata)?.rank ?? 0;
      const rb = orgSpecForEmployee(b.metadata)?.rank ?? 0;
      return ra - rb;
    });
  }
  return levels;
}
