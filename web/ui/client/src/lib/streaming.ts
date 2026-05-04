let loopbackWebRtcWarningShown = false;

function envFlag(raw: unknown, fallback: boolean): boolean {
  if (raw === undefined || raw === null || raw === "") {
    return fallback;
  }
  return String(raw).toLowerCase() === "true";
}

function getNavigatorPlatform(): string {
  if (typeof navigator === "undefined") {
    return "";
  }

  const nav = navigator as Navigator & {
    userAgentData?: { platform?: string };
  };
  return String(nav.userAgentData?.platform || nav.platform || nav.userAgent || "");
}

function isWindowsClient(): boolean {
  return /win/i.test(getNavigatorPlatform());
}

function isLoopbackHostname(hostname: string): boolean {
  const normalized = hostname.replace(/^\[/, "").replace(/\]$/, "").toLowerCase();
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1" || normalized === "0.0.0.0";
}

function resolveViewerUrl(base: string): URL | null {
  try {
    const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
    return new URL(base, origin);
  } catch {
    return null;
  }
}

export function getWebRtcViewerBaseUrl(): string {
  return String(import.meta.env.VITE_WEBRTC_VIEWER_BASE_URL ?? "").trim();
}

export function isLoopbackWebRtcBlocked(baseUrl: string = getWebRtcViewerBaseUrl()): boolean {
  if (!baseUrl || !isWindowsClient()) {
    return false;
  }

  if (envFlag(import.meta.env.VITE_ALLOW_LOOPBACK_WEBRTC_ON_WINDOWS, false)) {
    return false;
  }

  const parsed = resolveViewerUrl(baseUrl);
  return parsed ? isLoopbackHostname(parsed.hostname) : false;
}

export function isWebRtcEnabled(): boolean {
  if (!envFlag(import.meta.env.VITE_ENABLE_WEBRTC, false)) {
    return false;
  }

  const baseUrl = getWebRtcViewerBaseUrl();
  if (!baseUrl) {
    return false;
  }

  if (isLoopbackWebRtcBlocked(baseUrl)) {
    if (!loopbackWebRtcWarningShown && typeof console !== "undefined") {
      console.warn(
        "[streaming] Disabled loopback WebRTC on Windows because MediaMTX's local viewer can fail during adapter enumeration. Falling back to snapshots."
      );
      loopbackWebRtcWarningShown = true;
    }
    return false;
  }

  return true;
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

  const base = getWebRtcViewerBaseUrl();
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
