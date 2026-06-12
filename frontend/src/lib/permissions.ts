import type { AuthUser } from "./authStore";

export function hasPermission(user: AuthUser | null | undefined, perm: string): boolean {
  if (!user) return false;
  if (user.is_admin) return true;
  return (user.permissions ?? []).includes(perm);
}

export function canViewDashboard(user: AuthUser | null | undefined): boolean {
  return hasPermission(user, "dashboard:view");
}

export function canManageOrg(user: AuthUser | null | undefined): boolean {
  return hasPermission(user, "org:manage");
}

export function canDelegateDept(user: AuthUser | null | undefined): boolean {
  return hasPermission(user, "users:delegate:dept") || hasPermission(user, "users:manage");
}

export function canDelegateExec(user: AuthUser | null | undefined): boolean {
  return hasPermission(user, "users:delegate:exec") || hasPermission(user, "users:manage");
}

export function canReadEmployees(user: AuthUser | null | undefined): boolean {
  return hasPermission(user, "employees:read");
}

export function mergeUserProfile(existing: AuthUser | null, profile: AuthUser): AuthUser {
  return { ...existing, ...profile };
}
