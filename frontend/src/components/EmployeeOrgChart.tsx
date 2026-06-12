"use client";

import Link from "next/link";
import { Clock } from "lucide-react";
import { buildOrgLevels, orgSpecForEmployee, type OrgNodeSpec } from "@/lib/nevFinanceOrg";
import { employeeAvatarTone } from "@/lib/employeeCatalog";

export interface OrgChartEmployee {
  id: string;
  name: string;
  title: string | null;
  task_count: number;
  status: string;
  metadata?: Record<string, unknown> | null;
}

interface Props {
  employees: OrgChartEmployee[];
  lang: "zh" | "en";
  activeLabel: string;
  pausedLabel: string;
  taskCountLabel: string;
  openDetailLabel: string;
  groupTitle?: { zh: string; en: string };
}

function initial(name: string) {
  return (name.trim()[0] || "E").toUpperCase();
}

function OrgNode({
  emp,
  spec,
  lang,
  activeLabel,
  pausedLabel,
  taskCountLabel,
  openDetailLabel,
}: {
  emp: OrgChartEmployee;
  spec: OrgNodeSpec | null;
  lang: "zh" | "en";
} & Omit<Props, "employees" | "groupTitle">) {
  const isActive = emp.status === "active";
  return (
    <Link href={`/employees/${emp.id}`} className="employees-org-node">
      <div className={`agents-avatar employees-org-avatar ${employeeAvatarTone(emp.id)}`}>
        {initial(emp.name)}
      </div>
      <div className="employees-org-node-body">
        <div className="employees-org-node-title-row">
          <span className="employees-org-node-name">{emp.name}</span>
          {spec && (
            <span className="employees-org-tier">{lang === "zh" ? spec.shortTitle.zh : spec.shortTitle.en}</span>
          )}
        </div>
        {emp.title && <p className="employees-org-node-role">{emp.title}</p>}
        {spec && (
          <span className="employees-org-cadence">
            <Clock className="h-3 w-3" />
            {lang === "zh" ? spec.cadenceLabel.zh : spec.cadenceLabel.en}
          </span>
        )}
        <div className="employees-org-node-meta">
          <span className={isActive ? "employees-org-status-active" : "employees-org-status-paused"}>
            {isActive ? activeLabel : pausedLabel}
          </span>
          <span>{taskCountLabel}: {emp.task_count}</span>
        </div>
        <span className="employees-org-node-link">{openDetailLabel} →</span>
      </div>
    </Link>
  );
}

export default function EmployeeOrgChart({
  employees,
  lang,
  activeLabel,
  pausedLabel,
  taskCountLabel,
  openDetailLabel,
  groupTitle,
}: Props) {
  const orgEmployees = employees.filter((e) => orgSpecForEmployee(e.metadata));
  const otherEmployees = employees.filter((e) => !orgSpecForEmployee(e.metadata));

  if (orgEmployees.length === 0) {
    return (
      <div className="employees-org-empty">
        <p>{lang === "zh" ? "暂无带组织架构的数字员工，请从「制造企业财务」模板创建。" : "No org-mapped employees yet."}</p>
      </div>
    );
  }

  const levels = buildOrgLevels(orgEmployees);
  const levelKeys = [...levels.keys()].filter((l) => l < 99).sort((a, b) => a - b);

  return (
    <div className="employees-org-chart">
      {groupTitle && (
        <div className="employees-org-chart-header">
          <h2>{lang === "zh" ? groupTitle.zh : groupTitle.en}</h2>
          <p>
            {lang === "zh"
              ? "层级越高越靠上；连线表示汇报关系；标签为定时任务节奏。"
              : "Higher roles on top; lines show reporting; tags show task cadence."}
          </p>
        </div>
      )}

      <div className="employees-org-tree">
        {levelKeys.map((level, idx) => {
          const row = levels.get(level) ?? [];
          const isLast = idx === levelKeys.length - 1;
          return (
            <div key={level} className="employees-org-level">
              {!isLast && <div className="employees-org-connector-down" aria-hidden />}
              <div
                className={`employees-org-row employees-org-row-l${level}`}
                data-count={row.length}
              >
                {row.map((emp) => (
                  <OrgNode
                    key={emp.id}
                    emp={emp}
                    spec={orgSpecForEmployee(emp.metadata)}
                    lang={lang}
                    activeLabel={activeLabel}
                    pausedLabel={pausedLabel}
                    taskCountLabel={taskCountLabel}
                    openDetailLabel={openDetailLabel}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {otherEmployees.length > 0 && (
        <div className="employees-org-others">
          <h3>{lang === "zh" ? "其他数字员工" : "Other employees"}</h3>
          <div className="employees-org-row">
            {otherEmployees.map((emp) => (
              <OrgNode
                key={emp.id}
                emp={emp}
                spec={null}
                lang={lang}
                activeLabel={activeLabel}
                pausedLabel={pausedLabel}
                taskCountLabel={taskCountLabel}
                openDetailLabel={openDetailLabel}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
