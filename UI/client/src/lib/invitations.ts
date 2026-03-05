import { api } from "@/lib/api";

export type PendingInvite = {
  id: number | string;
  tenant: { id: number | string; name: string };
  role: string;
  invited_by?: string;
};

export async function getPendingInvites(): Promise<PendingInvite[]> {
  const { data } = await api.get("/invitations/pending/");
  return data;
}

export async function acceptInvite(inviteId: number | string) {
  const { data } = await api.post(`/invitations/${inviteId}/accept/`);
  return data;
}

export async function sendInvite(email: string, role: string) {
  const { data } = await api.post("/invitations/", { email, role });
  return data;
}