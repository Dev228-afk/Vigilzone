import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildWebRtcViewerUrl,
  getWebRtcViewerBaseUrl,
  isLoopbackWebRtcBlocked,
  isWebRtcEnabled,
} from "./streaming";

function setNavigatorPlatform(platform: string, userAgent: string) {
  Object.defineProperty(window.navigator, "platform", {
    value: platform,
    configurable: true,
  });
  Object.defineProperty(window.navigator, "userAgent", {
    value: userAgent,
    configurable: true,
  });
}

describe("streaming loopback safeguards", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("disables loopback WebRTC on Windows clients", () => {
    setNavigatorPlatform("Win32", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
    vi.stubEnv("VITE_ENABLE_WEBRTC", "true");
    vi.stubEnv("VITE_WEBRTC_VIEWER_BASE_URL", "http://localhost:8889");

    expect(getWebRtcViewerBaseUrl()).toBe("http://localhost:8889");
    expect(isLoopbackWebRtcBlocked()).toBe(true);
    expect(isWebRtcEnabled()).toBe(false);
    expect(buildWebRtcViewerUrl("main-door")).toBeUndefined();
  });

  it("keeps remote WebRTC enabled on Windows clients", () => {
    setNavigatorPlatform("Win32", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
    vi.stubEnv("VITE_ENABLE_WEBRTC", "true");
    vi.stubEnv("VITE_WEBRTC_VIEWER_BASE_URL", "https://streams.example.com");

    expect(isLoopbackWebRtcBlocked()).toBe(false);
    expect(isWebRtcEnabled()).toBe(true);
    expect(buildWebRtcViewerUrl("main-door")).toBe("https://streams.example.com/main-door/");
  });

  it("allows opt-in override for loopback WebRTC on Windows", () => {
    setNavigatorPlatform("Win32", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
    vi.stubEnv("VITE_ENABLE_WEBRTC", "true");
    vi.stubEnv("VITE_WEBRTC_VIEWER_BASE_URL", "http://127.0.0.1:8889");
    vi.stubEnv("VITE_ALLOW_LOOPBACK_WEBRTC_ON_WINDOWS", "true");

    expect(isLoopbackWebRtcBlocked()).toBe(false);
    expect(isWebRtcEnabled()).toBe(true);
    expect(buildWebRtcViewerUrl("main-door")).toBe("http://127.0.0.1:8889/main-door/");
  });
});
