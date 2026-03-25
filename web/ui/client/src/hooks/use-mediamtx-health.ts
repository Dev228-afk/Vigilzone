import { useState, useEffect } from "react";

interface UseMediamtxHealthResult {
  reachable: boolean;
  checked: boolean;
}

/**
 * Hook to check if MediaMTX is reachable.
 * Returns whether the MediaMTX server can be reached.
 */
export function useMediamtxHealth(): UseMediamtxHealthResult {
  const [reachable, setReachable] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        // Try to reach the MediaMTX API (typically on port 8889)
        // or check for a known stream endpoint
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);

        const response = await fetch("/streams/", {
          method: "HEAD",
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (cancelled) return;

        // If we get any response (even 404), the server is reachable
        // MediaMTX returns 404 for /streams/ but that means it's up
        setReachable(response.ok || response.status === 404);
      } catch {
        if (!cancelled) {
          // If fetch fails, MediaMTX might not be reachable
          setReachable(false);
        }
      } finally {
        if (!cancelled) {
          setChecked(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return { reachable, checked };
}
