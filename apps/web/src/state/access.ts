import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "./auth";

export type Level = "inicial" | "primaria" | "secundaria";
export type LevelAccess = "direccion" | "total" | "limitado";

export const LEVELS: { value: Level; label: string }[] = [
  { value: "inicial", label: "Inicial" },
  { value: "primaria", label: "Primaria" },
  { value: "secundaria", label: "Secundaria" },
];

export const LEVEL_LABEL: Record<string, string> = Object.fromEntries(
  LEVELS.map((level) => [level.value, level.label]),
);

export interface MyAccess {
  /** Admin u owner de la sede, o superadmin: ve todos los niveles. */
  sees_everything: boolean;
  /** Superadmin mirando una sede de la que no es miembro. */
  superadmin_visit: boolean;
  access: Partial<Record<Level, LevelAccess>>;
  creatable_levels: Level[];
  managed_levels: Level[];
  needs_level: boolean;
}

/** Qué ve y qué puede hacer la persona en la sede activa (services/access.py). */
export function useMyAccess() {
  const { activeOrg } = useAuth();
  return useQuery({
    queryKey: ["my-access", activeOrg?.id],
    queryFn: () => api<MyAccess>("/api/org/access/me"),
    enabled: !!activeOrg,
    staleTime: 60_000,
  });
}
