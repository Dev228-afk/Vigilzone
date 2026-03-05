export type TenantRole = "owner" | "admin" | "member" | "viewer";

const ROLE_RANK: Record<TenantRole, number> = {
  owner: 4,
  admin: 3,
  member: 2,
  viewer: 1,
};

export function roleAtLeast(role: TenantRole | null | undefined, min: TenantRole) {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[min];
}