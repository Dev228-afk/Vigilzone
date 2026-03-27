export function isWebRtcEnabled(): boolean {
  return String(import.meta.env.VITE_ENABLE_WEBRTC ?? "false").toLowerCase() === "true";
}

function normalizePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

/**
 * Build a MediaMTX WebRTC viewer URL.
 * Returns undefined when WebRTC is not enabled/configured.
 */
export function buildWebRtcViewerUrl(streamPath?: string, aiCameraId?: string): string | undefined {
  if (!isWebRtcEnabled()) {
    return undefined;
  }

  const base = String(import.meta.env.VITE_WEBRTC_VIEWER_BASE_URL ?? "").trim();
  if (!base) {
    return undefined;
  }

  const rawPath = String(streamPath || aiCameraId || "").trim();
  if (!rawPath) {
    return undefined;
  }

  if (/^https?:\/\//i.test(rawPath)) {
    return rawPath;
  }

  const sanitizedBase = base.replace(/\/$/, "");
  const sanitizedPath = normalizePath(rawPath);
  return `${sanitizedBase}/${sanitizedPath}/`;
}
