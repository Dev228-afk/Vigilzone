export function hasToken() {
  return !!localStorage.getItem("accessToken") || !!sessionStorage.getItem("accessToken");
}

export function getTenantId() {
  return localStorage.getItem("selectedTenantId");
}