import { useState, useEffect } from "react";

interface UseMediamtxHealthResult {
  reachable: boolean;
  checked: boolean;
  activePaths: Set<string>;
}

/**
 * Check if MediaMTX is reachable by hitting its configured base URL.
 * Also retrieves the list of active paths via proxy to ensure we don't load 
 * an iframe for a stream that is not publishing (prevents "stream not found" error).
 */
export function useMediamtxHealth(): UseMediamtxHealthResult {
  const [reachable, setReachable] = useState(false);
  const [checked, setChecked] = useState(false);
  const [activePaths, setActivePaths] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;

    const webrtcEnabled = String(import.meta.env.VITE_ENABLE_WEBRTC ?? "false").toLowerCase() === "true";
    const apiHealthcheckEnabled = String(import.meta.env.VITE_ENABLE_MEDIAMTX_API_HEALTHCHECK ?? "true").toLowerCase() === "true";
    const baseUrl = String(import.meta.env.VITE_WEBRTC_VIEWER_BASE_URL ?? "").trim();

    if (!webrtcEnabled || !baseUrl) {
      if (!cancelled) {
        setReachable(false);
        setChecked(true);
      }
      return;
    }

    (async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);

      try {
        let pathsReady = false;

        // Optionally fetch active paths via Vite proxy to MediaMTX API
        if (apiHealthcheckEnabled) {
          try {
            const pathsRes = await fetch("/mediamtx_api/v3/paths/list", {
              signal: controller.signal,
            });

            if (!cancelled && pathsRes.ok) {
              const data = await pathsRes.json();
              const paths = new Set<string>();
              if (data && data.items) {
                data.items.forEach((item: any) => {
                  if (item.name && item.ready === true) {
                    paths.add(item.name);
                  }
                });
              }
              setActivePaths(paths);
              setReachable(true);
              pathsReady = true;
            }
          } catch (apiErr) {
            console.debug("MediaMTX API health check failed, falling back to reachability", apiErr);
          }
        }

        if (cancelled) return;

        // Fallback or lightweight check if API check is disabled or failed
        if (!pathsReady) {
          const fallbackRes = await fetch(`${baseUrl.replace(/\/$/, "")}/`, {
            method: "HEAD",
            mode: "no-cors",
            signal: controller.signal,
          });
          setReachable(true);
        }
      } catch (err) {
        if (!cancelled) {
          // Even if both fail, don't crash; just mark as unreachable
          setReachable(false);
          setActivePaths(new Set());
        }
      } finally {
        clearTimeout(timeoutId);
        if (!cancelled) {
          setChecked(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return { reachable, checked, activePaths };
}
