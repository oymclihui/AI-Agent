"use client";

import { clsx } from "clsx";
import { brandingInitials, useBrandingStore } from "@/lib/brandingStore";

export function BrandMark({
  size = "md",
  showName = true,
  className,
  nameClassName,
  name,
  icon,
}: {
  size?: "sm" | "md" | "lg";
  showName?: boolean;
  className?: string;
  nameClassName?: string;
  name?: string;
  icon?: string | null;
}) {
  const storeName = useBrandingStore((s) => s.systemName);
  const storeIcon = useBrandingStore((s) => s.systemIcon);
  const systemName = name ?? storeName;
  const systemIcon = icon !== undefined ? icon : storeIcon;
  const box =
    size === "sm" ? "h-8 w-8 text-sm" : size === "lg" ? "h-10 w-10 text-base" : "h-8 w-8 text-sm";

  return (
    <div className={clsx("flex items-center gap-2", className)}>
      {systemIcon ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={systemIcon}
          alt=""
          className={clsx(box, "shrink-0 rounded-lg object-cover shadow-sm")}
        />
      ) : (
        <div
          className={clsx(
            box,
            "flex shrink-0 items-center justify-center rounded-lg bg-blue-500 font-bold text-on-primary shadow-sm",
          )}
        >
          {brandingInitials(systemName)}
        </div>
      )}
      {showName && (
        <span className={clsx("font-semibold theme-text truncate", nameClassName)}>
          {systemName}
        </span>
      )}
    </div>
  );
}
