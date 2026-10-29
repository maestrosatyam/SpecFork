import { useCallback, useEffect, useRef, useState } from "react";
import { ACTIVE_STATUSES, ApiError, type Api } from "../api";
import type { Run } from "../types";

/**
 * Loads a run and keeps it live: SSE (with polling fallback inside the API client) while the run is in an
 * active status. Call `follow(run)` after POSTing answers / converge to resume streaming.
 */
export function useRun(api: Api, id: string) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [streamKey, setStreamKey] = useState(0);
  const latest = useRef<Run | null>(null);

  const accept = useCallback((r: Run) => {
    // Ignore out-of-order snapshots.
    if (latest.current && latest.current.id === r.id && r.updated_at < latest.current.updated_at) return;
    latest.current = r;
    setRun(r);
  }, []);

  useEffect(() => {
    setRun(null);
    setError(null);
    latest.current = null;
  }, [id]);

  useEffect(() => {
    let unsub: (() => void) | null = null;
    let cancelled = false;
    (async () => {
      try {
        const r = await api.getRun(id);
        if (cancelled) return;
        accept(r);
        if (!ACTIVE_STATUSES.has(r.status)) return;
        unsub = api.subscribe(
          id,
          (snap) => !cancelled && accept(snap),
          () => undefined,
          () => undefined,
        );
      } catch (e) {
        if (!cancelled) setError(e as Error);
      }
    })();
    return () => {
      cancelled = true;
      unsub?.();
    };
  }, [api, id, streamKey, accept]);

  const follow = useCallback(
    (r: Run) => {
      accept(r);
      setStreamKey((k) => k + 1);
    },
    [accept],
  );

  return { run, error, follow };
}
