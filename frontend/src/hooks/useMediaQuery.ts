"use client";

import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** True when viewport width <= 767px. Returns false until mounted (SSR-safe). */
export function useIsMobile(): boolean {
  const [mounted, setMounted] = useState(false);
  const matches = useMediaQuery("(max-width: 767px)");

  useEffect(() => {
    setMounted(true);
  }, []);

  return mounted && matches;
}
