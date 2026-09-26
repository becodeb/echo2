import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { InternalGroupsOut } from "../api/types";
import { useAuth } from "./auth";

/** Grupos internos de la sede activa y si la persona puede administrarlos. */
export function useInternalGroups() {
  const { activeOrg } = useAuth();
  return useQuery({
    queryKey: ["internal-groups", activeOrg?.id],
    queryFn: () => api<InternalGroupsOut>("/api/internal-groups"),
    enabled: !!activeOrg,
    staleTime: 60_000,
  });
}

/** La sección existe para quien es de algún grupo o los administra. */
export function useSeesInternal(): boolean {
  const { data } = useInternalGroups();
  return !!data && (data.can_manage || data.groups.some((group) => group.is_member));
}
