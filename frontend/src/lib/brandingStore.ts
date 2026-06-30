import { create } from "zustand";
import { systemApi } from "@/lib/api";

export const DEFAULT_SYSTEM_NAME = "AI-AGENT";

interface BrandingState {
  systemName: string;
  systemIcon: string | null;
  loaded: boolean;
  fetchBranding: () => Promise<void>;
  setBranding: (data: { system_name: string; system_icon?: string | null }) => void;
}

export const useBrandingStore = create<BrandingState>((set) => ({
  systemName: DEFAULT_SYSTEM_NAME,
  systemIcon: null,
  loaded: false,
  fetchBranding: async () => {
    try {
      const { data } = await systemApi.getBranding();
      const branding = data as { system_name: string; system_icon?: string | null };
      set({
        systemName: branding.system_name?.trim() || DEFAULT_SYSTEM_NAME,
        systemIcon: branding.system_icon || null,
        loaded: true,
      });
    } catch {
      set({ loaded: true });
    }
  },
  setBranding: (data) =>
    set({
      systemName: data.system_name?.trim() || DEFAULT_SYSTEM_NAME,
      systemIcon: data.system_icon ?? null,
      loaded: true,
    }),
}));

export function brandingInitials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "AI";
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}
