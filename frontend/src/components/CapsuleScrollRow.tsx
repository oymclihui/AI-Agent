"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { clsx } from "clsx";

interface CapsuleScrollRowProps {
  children: ReactNode;
  className?: string;
  innerClassName?: string;
  /** Background color for edge fades — matches the parent panel */
  fadeFrom?: "background" | "surface" | "footer";
  /** Center chips when they all fit without scrolling */
  centerWhenFit?: boolean;
  scrollLeftLabel?: string;
  scrollRightLabel?: string;
  /** Pixels to scroll per chevron click */
  scrollStep?: number;
}

export default function CapsuleScrollRow({
  children,
  className,
  innerClassName,
  fadeFrom = "background",
  centerWhenFit = false,
  scrollLeftLabel = "Scroll left",
  scrollRightLabel = "Scroll right",
  scrollStep = 180,
}: CapsuleScrollRowProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [fits, setFits] = useState(true);

  const updateScrollState = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const { scrollLeft, scrollWidth, clientWidth } = el;
    const overflow = scrollWidth > clientWidth + 2;
    setFits(!overflow);
    setCanScrollLeft(overflow && scrollLeft > 4);
    setCanScrollRight(overflow && scrollLeft + clientWidth < scrollWidth - 4);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    updateScrollState();
    el.addEventListener("scroll", updateScrollState, { passive: true });
    const ro = new ResizeObserver(updateScrollState);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", updateScrollState);
      ro.disconnect();
    };
  }, [updateScrollState, children]);

  const scrollBy = (dir: -1 | 1) => {
    scrollRef.current?.scrollBy({ left: dir * scrollStep, behavior: "smooth" });
  };

  const fadeVar =
    fadeFrom === "footer"
      ? "#1a1a2e"
      : fadeFrom === "surface"
        ? "var(--surface)"
        : "var(--background)";

  return (
    <div
      className={clsx("chat-capsule-wrap", className)}
      style={{ ["--capsule-fade" as string]: fadeVar }}
    >
      {canScrollLeft && (
        <>
          <div className="chat-capsule-fade chat-capsule-fade-left" aria-hidden />
          <button
            type="button"
            className="chat-capsule-nav chat-capsule-nav-left"
            onClick={() => scrollBy(-1)}
            aria-label={scrollLeftLabel}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      <div
        ref={scrollRef}
        className={clsx(
          "chat-capsule-scroll",
          centerWhenFit && fits && "chat-capsule-scroll--center",
          canScrollLeft && "chat-capsule-scroll--pad-left",
          canScrollRight && "chat-capsule-scroll--pad-right",
          innerClassName,
        )}
      >
        {children}
      </div>
      {canScrollRight && (
        <>
          <div className="chat-capsule-fade chat-capsule-fade-right" aria-hidden />
          <button
            type="button"
            className="chat-capsule-nav chat-capsule-nav-right"
            onClick={() => scrollBy(1)}
            aria-label={scrollRightLabel}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  );
}
