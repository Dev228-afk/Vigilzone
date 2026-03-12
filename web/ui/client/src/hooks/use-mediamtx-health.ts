import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface MediamtxHealthResult {
  reachable: boolean;
  checked: boolean;
}

let cachedResult: MediamtxHealthResult | null = null;
let cacheTs = 0;
const CACHE_TTL_MS = 30_000; // re-check every 30 s

/**
 * Returns { reachable, checked } — `checked` is false until the first
 * health probe completes.  While checked is false, callers should
 * NOT render WebRTC iframes (avoids ECONNREFUSED spam).
 */
export function useMediamtxHealth(): MediamtxHealthResult {
  const [result, setResult] = useState<MediamtxHealthResult>(
    cachedResult && Date.now() - cacheTs < CACHE_TTL_MS
      ? cachedResult
      : { reachable: false, checked: false },
  );

  useEffect(() => {
    if (cachedResult && Date.now() - cacheTs < CACHE_TTL_MS) {
      setResult(cachedResult);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get("/debug/mediamtx/health/");
        const r: MediamtxHealthResult = { reachable: !!data?.reachable, checked: true };
        if (!cancelled) {
          cachedResult = r;
          cacheTs = Date.now();
          setResult(r);
        }
      } catch {
        const r: MediamtxHealthResult = { reachable: false, checked: true };
        if (!cancelled) {
          cachedResult = r;
          cacheTs = Date.now();
          setResult(r);
        }
      }
    })();

    return () => { cancelled = true; };
  }, []);

  return result;
}
