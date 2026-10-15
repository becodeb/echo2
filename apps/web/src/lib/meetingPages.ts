import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MeetingListItem } from "../api/types";

const PAGE = 30;

/**
 * Lista de reuniones de a 30, de la más nueva a la más vieja. Antes se pedían
 * las últimas 30 y nada más: las anteriores no aparecían en la lista.
 */
export function useMeetingPages(queryKey: readonly unknown[], path: string, enabled: boolean) {
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) =>
      api<MeetingListItem[]>(`${path}${path.includes("?") ? "&" : "?"}limit=${PAGE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
    enabled,
  });
  return { ...query, meetings: query.data?.pages.flat() };
}
