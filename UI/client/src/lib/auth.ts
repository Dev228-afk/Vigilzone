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

  // Expecting: { access, refresh, user?: { username } } or similar
  setAccessToken(data.access);
  if (data.refresh) localStorage.setItem("refreshToken", data.refresh);

  // Store username for immediate use in UI
  if (data.user?.username) {
    localStorage.setItem("username", data.user.username);
  } else if (!usernameOrEmail.includes("@")) {
    // If login was with username (not email), store it
    localStorage.setItem("username", usernameOrEmail);
  }

  return data;
}

export function logout() {
  setAccessToken(null);
  localStorage.removeItem("refreshToken");

  // clear refresh token (support local/session if you later add remember-me)
  localStorage.removeItem("refreshToken");
  sessionStorage.removeItem("refreshToken");

  // clear username
  localStorage.removeItem("username");
  sessionStorage.removeItem("username");

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
