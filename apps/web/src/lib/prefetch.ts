import { infiniteQueryOptions, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { InsightsOut, MeetingOut, SegmentOut } from "../api/types";

/**
 * Lo que abre una reunión, con las mismas claves que usa la pantalla: así se
 * puede bajar antes (al pasar el mouse o tocar la fila) y la reunión se abre
 * con todo ya en caché, sin esperar la ida y vuelta al servidor.
 */
export const meetingQuery = (id: string) => ({
  queryKey: ["meeting", id] as const,
  queryFn: () => api<MeetingOut>(`/api/meetings/${id}`),
});

export const summaryQuery = (id: string) => ({
  queryKey: ["summary", id] as const,
  queryFn: () =>
    api<
      Record<
        string,
        { content: { points?: string[]; markdown?: string; people?: { name: string; points: string[] }[] } }
      >
    >(`/api/meetings/${id}/summary`),
});

export const insightsQuery = (id: string) => ({
  queryKey: ["insights", id] as const,
  queryFn: () => api<InsightsOut>(`/api/meetings/${id}/insights`),
});

export interface TranscriptPage {
  segments: SegmentOut[];
  total: number;
  next_after: number | null;
}

/** El transcript en páginas de 300; `term` filtra (vacío = todo). */
export const transcriptQuery = (id: string, term = "") =>
  infiniteQueryOptions({
    queryKey: ["transcript", id, term] as const,
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams({ after_seq: String(pageParam), limit: "300" });
      if (term) query.set("search", term);
      return api<TranscriptPage>(`/api/meetings/${id}/transcript?${query}`);
    },
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_after ?? undefined,
    staleTime: 30_000,
  });

// Una vez por reunión y por un rato: pasar el mouse varias veces no repite pedidos.
const PREFETCH_STALE = 30_000;

export function prefetchMeeting(queryClient: QueryClient, id: string, withTranscript = false): void {
  queryClient.prefetchQuery({ ...meetingQuery(id), staleTime: PREFETCH_STALE });
  queryClient.prefetchQuery({ ...summaryQuery(id), staleTime: PREFETCH_STALE });
  queryClient.prefetchQuery({ ...insightsQuery(id), staleTime: PREFETCH_STALE });
  if (withTranscript) queryClient.prefetchInfiniteQuery(transcriptQuery(id));
}
