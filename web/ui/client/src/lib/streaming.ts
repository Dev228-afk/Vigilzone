export function isWebRtcEnabled(): boolean {
  return String(import.meta.env.VITE_ENABLE_WEBRTC ?? "false").toLowerCase() === "true";
}

export function isHlsEnabled(): boolean {
  return String(import.meta.env.VITE_HLS_ENABLED ?? "true").toLowerCase() === "true";
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

/**
 * Build a MediaMTX HLS stream URL for fallback when WebRTC unavailable.
 * HLS provides lower-latency (~5-10s) alternative with broader browser support.
 */
export function buildHlsStreamUrl(streamPath?: string, aiCameraId?: string): string | undefined {
  if (!isHlsEnabled()) {
    return undefined;
  }

  const base = String(import.meta.env.VITE_HLS_VIEWER_BASE_URL ?? "").trim();
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
  return `${sanitizedBase}/${sanitizedPath}/index.m3u8`;
}
