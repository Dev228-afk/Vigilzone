export function hasToken() {
  return !!localStorage.getItem("accessToken") || !!sessionStorage.getItem("accessToken");
}

export function getTenantId() {
  try {
    return localStorage.getItem("selectedTenantId") || sessionStorage.getItem("selectedTenantId");
  } catch {
    return null;
  }
}