"use client";

import { useEffect } from "react";
import { useBrandingStore } from "@/lib/brandingStore";

export default function BrandBootstrap() {
  const fetchBranding = useBrandingStore((s) => s.fetchBranding);
  const systemName = useBrandingStore((s) => s.systemName);
  const loaded = useBrandingStore((s) => s.loaded);

  useEffect(() => {
    void fetchBranding();
  }, [fetchBranding]);

  useEffect(() => {
    if (!loaded) return;
    document.title = `${systemName} - AI Agent Network Platform`;
  }, [loaded, systemName]);

  return null;
}
