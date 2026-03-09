import { api } from "@/lib/api";

export type MembershipRow = {
  id: number | string;
  tenant: number | string;
  role: "owner" | "admin" | "member" | "viewer";
  created_at: string;
  user: { id: number | string; username: string; email: string };
};

export async function getMembers(): Promise<MembershipRow[]> {
  const { data } = await api.get("/memberships/");
  console.log("TENANT", localStorage.getItem("selectedTenantId"));
  return data;
}

export async function removeMember(membershipId: number | string) {
  await api.delete(`/memberships/${membershipId}/`);
}