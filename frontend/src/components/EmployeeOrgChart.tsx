"use client";

import Link from "next/link";
import { Clock } from "lucide-react";
import { employeeAvatarTone } from "@/lib/employeeCatalog";

export interface OrgChartEmployee {
  id: string;
  name: string;
  title: string | null;
  status: string;
  task_count: number;
  department_id?: string | null;
  department_name?: string | null;
  parent_employee_id?: string | null;
  depth?: number;
  cadence_label_zh?: string | null;
  cadence_label_en?: string | null;
  short_title_zh?: string | null;
  short_title_en?: string | null;
}

export interface OrgTreeData {
  title_zh: string;
  title_en: string;
  subtitle_zh: string;
  subtitle_en: string;
  levels: OrgChartEmployee[][];
  unassigned: OrgChartEmployee[];
}

interface Props {
  tree: OrgTreeData;
  lang: "zh" | "en";
  activeLabel: string;
  pausedLabel: string;
  taskCountLabel: string;
  openDetailLabel: string;
}

function initial(name: string) {
  return (name.trim()[0] || "E").toUpperCase();
}

function OrgNode({
  emp,
  lang,
  activeLabel,
  pausedLabel,
  taskCountLabel,
  openDetailLabel,
}: {
  emp: OrgChartEmployee;
  lang: "zh" | "en";
} & Omit<Props, "tree">) {
  const isActive = emp.status === "active";
  const shortTitle = lang === "zh" ? emp.short_title_zh : emp.short_title_en;
  const cadenceLabel = lang === "zh" ? emp.cadence_label_zh : emp.cadence_label_en;

  return (
    <Link href={`/employees/${emp.id}`} className="employees-org-node">
      <div className={`agents-avatar employees-org-avatar ${employeeAvatarTone(emp.id)}`}>
        {initial(emp.name)}
      </div>
      <div className="employees-org-node-body">
        <div className="employees-org-node-title-row">
          <span className="employees-org-node-name">{emp.name}</span>
          {shortTitle && <span className="employees-org-tier">{shortTitle}</span>}
        </div>
        {emp.title && <p className="employees-org-node-role">{emp.title}</p>}
        {emp.department_name && (
          <p className="employees-org-node-dept text-[10px] theme-muted">{emp.department_name}</p>
        )}
        {cadenceLabel && (
          <span className="employees-org-cadence">
            <Clock className="h-3 w-3" />
            {cadenceLabel}
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
  tree,
  lang,
  activeLabel,
  pausedLabel,
  taskCountLabel,
  openDetailLabel,
}: Props) {
  const levelRows = tree.levels.filter((row) => row.length > 0);

  if (levelRows.length === 0 && tree.unassigned.length === 0) {
    return (
      <div className="employees-org-empty">
        <p>
          {lang === "zh"
            ? "暂无组织架构数据。请创建数字员工，或在「组织与权限」中配置部门后点击同步。"
            : "No org chart data yet. Create employees or sync from Organization settings."}
        </p>
      </div>
    );
  }

  return (
    <div className="employees-org-chart">
      <div className="employees-org-chart-header">
        <h2>{lang === "zh" ? tree.title_zh : tree.title_en}</h2>
        <p>{lang === "zh" ? tree.subtitle_zh : tree.subtitle_en}</p>
      </div>

      {levelRows.length > 0 && (
        <div className="employees-org-tree">
          {levelRows.map((row, idx) => {
            const level = row[0]?.depth ?? idx;
            const isLast = idx === levelRows.length - 1;
            return (
              <div key={`level-${level}-${idx}`} className="employees-org-level">
                {!isLast && <div className="employees-org-connector-down" aria-hidden />}
                <div
                  className={`employees-org-row employees-org-row-l${level + 1}`}
                  data-count={row.length}
                >
                  {row.map((emp) => (
                    <OrgNode
                      key={emp.id}
                      emp={emp}
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
      )}

      {tree.unassigned.length > 0 && (
        <div className="employees-org-others">
          <h3>{lang === "zh" ? "未挂接汇报线的员工" : "Unlinked employees"}</h3>
          <div className="employees-org-row">
            {tree.unassigned.map((emp) => (
              <OrgNode
                key={emp.id}
                emp={emp}
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
