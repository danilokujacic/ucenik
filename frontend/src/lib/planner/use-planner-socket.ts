"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { requestWsTicket } from "@/lib/api/auth";
import { WS_BASE_URL } from "@/lib/api/client";
import { queryKeys } from "@/lib/query/keys";
import type { PlannerWsEvent } from "@/lib/types/api";

export type PlannerSocketStatus = "connecting" | "open" | "closed";

/**
 * One connection per plan (spec §3.6 point 3/§1) - every lecture in the
 * plan reports progress on this same socket, disambiguated by `lecture_id`.
 * Auth is `?ticket=` (query param, not a header - the native WebSocket API
 * can't set custom headers) - a short-lived, single-use ticket fetched via
 * a normal Authorization-header request (lib/api/auth.ts's requestWsTicket,
 * backend services/ws_tickets.py), not the real access token. Putting the
 * actual access token in a URL was the previous (and less safe) approach -
 * see docs/security-hardening.md item 8 for why that changed. A fresh
 * ticket is requested on every connect/reconnect since each one is single-
 * use and expires in seconds, not something to cache alongside the access
 * token. No replay on reconnect (plain Redis pub/sub - spec §1), so a
 * reconnect re-fetches lecture state via React Query invalidation instead
 * of trusting the socket alone for anything missed during the gap.
 */
export function usePlannerSocket(subjectId: string, planId: string) {
  const [status, setStatus] = useState<PlannerSocketStatus>("connecting");
  const socketRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef(new Set<(event: PlannerWsEvent) => void>());
  const queryClient = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    async function connect() {
      let ticket: string;
      try {
        ({ ticket } = await requestWsTicket());
      } catch {
        if (!cancelled) setStatus("closed");
        return;
      }
      if (cancelled) return;

      setStatus("connecting");
      const ws = new WebSocket(`${WS_BASE_URL}/ws/plans/${planId}?ticket=${encodeURIComponent(ticket)}`);
      socketRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setStatus("open");
      };

      ws.onmessage = (evt) => {
        let data: PlannerWsEvent;
        try {
          data = JSON.parse(evt.data);
        } catch {
          return;
        }
        listenersRef.current.forEach((fn) => fn(data));

        // Any event means this lecture's status field just changed -
        // refetch it and the plan's lecture list rather than hand-patching
        // the cache, so content (populated only on `lecture.ready`) comes
        // from a real GET rather than being partially reconstructed here.
        queryClient.invalidateQueries({ queryKey: queryKeys.lecture(subjectId, planId, data.lecture_id) });
        queryClient.invalidateQueries({ queryKey: queryKeys.lectures(subjectId, planId) });
        if (data.type === "lecture.ready") {
          queryClient.invalidateQueries({ queryKey: queryKeys.lectureVersions(subjectId, planId, data.lecture_id) });
        }
      };

      ws.onclose = () => {
        socketRef.current = null;
        if (cancelled) return;
        setStatus("closed");
        const delay = Math.min(1000 * 2 ** attempt, 15_000);
        attempt += 1;
        reconnectTimer = setTimeout(() => {
          // Missed events during the gap aren't replayed - re-sync from
          // the server's own idea of lecture status before reconnecting.
          queryClient.invalidateQueries({ queryKey: queryKeys.lectures(subjectId, planId) });
          connect();
        }, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [subjectId, planId, queryClient]);

  const subscribe = useCallback((fn: (event: PlannerWsEvent) => void) => {
    listenersRef.current.add(fn);
    return () => listenersRef.current.delete(fn);
  }, []);

  /** Await this before POSTing a generate/refine request - connecting
   * after the job starts means missing its events entirely (spec §3.6
   * point 3). Resolves immediately if already open; gives up after ~5s. */
  const waitUntilOpen = useCallback(async () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) return true;
    for (let i = 0; i < 50; i++) {
      await new Promise((r) => setTimeout(r, 100));
      if (socketRef.current?.readyState === WebSocket.OPEN) return true;
    }
    return false;
  }, []);

  return { status, subscribe, waitUntilOpen };
}
