import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Select } from "../../components/Select";
import { Badge, Input } from "../../components/ui";
import { useAuth } from "../../state/auth";
import { LEVEL_LABEL, type Level, type LevelAccess } from "../../state/access";
import { Block, ErrorText, Loading } from "./parts";

interface AccessMember {
  user_id: string;
  name: string;
  email: string;
  role: string;
  access: Partial<Record<Level, LevelAccess>>;
}

interface AccessList {
  managed_levels: Level[];
  can_assign_direction: boolean;
  /** Los accesos que quien mira puede dar (un directivo no da los que muestran más de lo que ve él). */
  assignable: string[];
  members: AccessMember[];
}

/** Cada acceso: cómo se llama en pantalla y qué ve (services/access.py). */
const ACCESS: { value: string; label: string; sees: string }[] = [
  { value: "total", label: "Ve todo (dirección)", sees: "Todas las reuniones del nivel." },
  { value: "adviser", label: "Adviser", sees: "Lo suyo y lo que crean el DOE y los tutores del nivel." },
  { value: "direccion", label: "Directivo", sees: "Solo lo suyo: lo que creó, donde estuvo, lo compartido y sus familias." },
  { value: "limitado", label: "DOE", sees: "Solo lo suyo: lo que creó, donde estuvo, lo compartido y sus familias." },
  { value: "tutor", label: "Tutor/a", sees: "Lo mismo que el DOE." },
  { value: "nulo", label: "Sin acceso", sees: "Nada del nivel." },
];
const ACCESS_LABEL: Record<string, string> = Object.fromEntries(ACCESS.map((item) => [item.value, item.label]));

export function AccessSection() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [filter, setFilter] = useState("");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["level-access"],
    queryFn: () => api<AccessList>("/api/org/access"),
  });

  const setAccess = useMutation({
    mutationFn: (change: { user_id: string; level: Level; access: string }) =>
      api<AccessMember>("/api/org/access", { method: "PUT", body: JSON.stringify(change) }),
    onSuccess: (member) => {
      queryClient.setQueryData<AccessList>(["level-access"], (current) =>
        current
          ? { ...current, members: current.members.map((m) => (m.user_id === member.user_id ? member : m)) }
          : current,
      );
    },
  });

  if (isLoading) return <Loading />;
  if (isError || !data) {
    return <p className="text-sm text-ink-500">{error instanceof Error ? error.message : "No se pudieron cargar los accesos."}</p>;
  }

  const options = ACCESS.filter((item) => data.assignable.includes(item.value)).map((item) => ({
    value: item.value,
    label: item.label,
    description: item.sees,
  }));
  const term = filter.trim().toLowerCase();
  const members = data.members.filter(
    (member) => !term || member.name.toLowerCase().includes(term) || member.email.toLowerCase().includes(term),
  );

  return (
    <Block
      id="access-members"
      hint={
        <>
          Niveles que dirigís: {data.managed_levels.map((level) => LEVEL_LABEL[level]).join(", ")}. Qué ve cada uno en el nivel:
        </>
      }
    >
      <dl className="mb-5 grid gap-x-4 gap-y-0 text-sm sm:gap-y-1.5 sm:grid-cols-[max-content_1fr]">
        {ACCESS.filter((item) => data.assignable.includes(item.value)).map((item) => (
          <div key={item.value} className="contents">
            <dt className="font-medium text-ink-700">{item.label}</dt>
            <dd className="mb-2.5 text-ink-500 sm:mb-0">{item.sees}</dd>
          </div>
        ))}
      </dl>

      {data.members.length > 6 && (
        <Input placeholder="Buscar persona…" value={filter} onChange={(event) => setFilter(event.target.value)} />
      )}

      <ul className="divide-y divide-ink-100">
        {members.map((member) => {
          const admin = member.role === "admin" || member.role === "owner";
          return (
            <li key={member.user_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
              <div className="min-w-0 flex-1 basis-48">
                <p className="truncate text-sm font-medium text-ink-900">
                  {member.name}
                  {member.user_id === user?.id && <span className="font-normal text-ink-400"> (vos)</span>}
                </p>
                <p className="truncate text-xs text-ink-400">{member.email}</p>
              </div>
              {admin ? (
                <Badge tone="indigo">Admin de la sede: ve todo</Badge>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {data.managed_levels.map((level) => {
                    const current = member.access[level] ?? "nulo";
                    // Quien dirige no se toca a sí misma ni cambia accesos que ella no puede dar: eso es de un admin.
                    const locked =
                      !data.can_assign_direction &&
                      (!data.assignable.includes(current) || member.user_id === user?.id);
                    return (
                      <div key={level} className="w-44">
                        <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-ink-400">
                          {LEVEL_LABEL[level]}
                        </span>
                        {locked ? (
                          <p className="py-1 text-xs font-medium text-ink-700">{ACCESS_LABEL[current]}</p>
                        ) : (
                          <Select
                            size="sm"
                            ariaLabel={`Acceso de ${member.name} a ${LEVEL_LABEL[level]}`}
                            value={current}
                            onChange={(access) =>
                              access !== current && setAccess.mutate({ user_id: member.user_id, level, access })
                            }
                            options={options}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
        {members.length === 0 && <li className="py-6 text-center text-sm text-ink-400">Nadie coincide.</li>}
      </ul>
      {setAccess.isError && <ErrorText error={setAccess.error} fallback="No se pudo cambiar el acceso" />}
    </Block>
  );
}
