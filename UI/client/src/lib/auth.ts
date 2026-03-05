import { api, setAccessToken } from "./api";
import { queryClient } from "./queryClient";

type TokenResponse = { access: string; refresh: string };

export async function login(usernameOrEmail: string, password: string) {
  // Adjust endpoint + payload to your backend:
  // common simplejwt: POST /api/auth/token/ { username, password }
  const { data } = await api.post("/auth/token/", {
    // if your backend uses email, send email instead of username
    username: usernameOrEmail,
    password,
  });

  // Expecting: { access, refresh }
  setAccessToken(data.access);
  if (data.refresh) localStorage.setItem("refreshToken", data.refresh);

  return data;
}

export function logout() {
  setAccessToken(null);
  localStorage.removeItem("refreshToken");

  // clear refresh token (support local/session if you later add remember-me)
  localStorage.removeItem("refreshToken");
  sessionStorage.removeItem("refreshToken");

  // optional: clear any tenant/community selection you store later
  localStorage.removeItem("selectedTenantId");
  sessionStorage.removeItem("selectedTenantId");

  // optional but recommended: wipe cached user data
  queryClient.clear();
}
export async function register(username:string,email:string,password:string){
  await api.post("/auth/register/", { username, email, password });
}

export async function refresh() {
  const rt = localStorage.getItem("refreshToken");
  if (!rt) throw new Error("No refresh token");
  const { data } = await api.post<TokenResponse>("/auth/refresh/", { refresh: rt });
  setAccessToken(data.access);
}
