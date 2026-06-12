import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface RoleAssignment {
  role_code: string;
  role_label_zh: string;
  role_label_en: string;
  scope_department_id?: string | null;
}

export interface DepartmentBrief {
  id: string;
  name: string;
  code?: string | null;
  path: string;
}

export interface AuthUser {
  id: string;
  employee_no?: string | null;
  email?: string | null;
  display_name: string;
  is_admin?: boolean;
  is_active?: boolean;
  primary_department?: DepartmentBrief | null;
  roles?: RoleAssignment[];
  permissions?: string[];
  data_scope?: string;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  setAuth: (token: string, user: AuthUser) => void;
  setUser: (user: AuthUser) => void;
  logout: () => void;
}

export const AUTH_STORAGE_KEY = "aiagnet-auth";

/** Sync read from localStorage — used before zustand persist finishes rehydrating. */
export function readStoredAuth(): { token: string | null; user: AuthUser | null } {
  if (typeof window === "undefined") return { token: null, user: null };
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return { token: null, user: null };
    const parsed = JSON.parse(raw) as { state?: { token?: string | null; user?: AuthUser | null } };
    return {
      token: parsed.state?.token ?? null,
      user: parsed.state?.user ?? null,
    };
  } catch {
    return { token: null, user: null };
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: AUTH_STORAGE_KEY },
  ),
);

export function getAuthToken(): string | null {
  return useAuthStore.getState().token;
}
