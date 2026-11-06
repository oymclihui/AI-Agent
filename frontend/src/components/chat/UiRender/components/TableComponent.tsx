"use client";

import { useMemo, useState } from "react";
import type { UiNode, TableProps } from "../types";

export function TableComponent({ node }: { node: UiNode }) {
  const props = (node.props || {}) as unknown as unknown as TableProps;
  const { columns = [], rows = [], columnTypes = [], sortable = true } = props;

  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sortedRows = useMemo(() => {
    if (!sortable || sortCol === null) return rows;
    const type = columnTypes[sortCol] || "text";
    return [...(rows || [])].sort((a, b) => {
      const av = a[sortCol];
      const bv = b[sortCol];
      let cmp = 0;
      if (type === "number") cmp = (Number(av) || 0) - (Number(bv) || 0);
      else cmp = String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortCol, sortDir, sortable, columnTypes]);

  const handleSort = (i: number) => {
    if (!sortable) return;
    if (sortCol === i) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortCol(i);
      setSortDir("asc");
    }
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((col, i) => (
              <th
                key={i}
                onClick={() => handleSort(i)}
                className={`px-3 py-2 text-left font-medium text-slate-700 ${sortable ? "cursor-pointer hover:bg-slate-100" : ""}`}
              >
                {col}
                {sortable && sortCol === i && (sortDir === "asc" ? " ▲" : " ▼")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, ri) => (
            <tr key={ri} className="border-t border-slate-100 hover:bg-slate-50">
              {row.map((cell, ci) => {
                const type = columnTypes[ci] || "text";
                const align = type === "number" ? "text-right tabular-nums" : "";
                return (
                  <td key={ci} className={`px-3 py-2 text-slate-700 ${align}`}>
                    {typeof cell === "number" && type === "number" ? cell.toLocaleString() : String(cell)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
