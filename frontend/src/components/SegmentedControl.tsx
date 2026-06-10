"use client";

import { clsx } from "clsx";

type Option<T extends string> = { value: T; label: string };

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Option<T>[];
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div
      className={clsx("segment-control", size === "sm" && "segment-control-sm", className)}
      role="tablist"
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={value === opt.value}
          onClick={() => onChange(opt.value)}
          className={clsx("segment-option", value === opt.value && "segment-option-active")}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
