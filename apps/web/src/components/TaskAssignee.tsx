import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { TaskOut } from "../api/types";
import { useAuth } from "../state/auth";
import { matchesSuggestion } from "../lib/assignee";
import { Select, type SelectOption } from "./Select";

interface Person {
  id: string;
  name: string;
  job_title: string | null;
  role: string;
}

const ROLE_LABEL: Record<string, string> = {
  owner: "Dueño",
  admin: "Administra",
  member: "Miembro",
  viewer: "Solo lectura",
};

/**
 * Quién se encarga de una tarea. Las que detecta Echo van a quien grabó la
 * reunión, que desde acá las reparte entre las personas de la sede, cada una
 * con su rol. Arriba van las que coinciden con quien se nombró en la reunión.
 */
export function TaskAssignee({
  task,
  onAssigned,
  className = "w-48",
}: {
  task: Pick<TaskOut, "id" | "assignee_name" | "assignee_user_id" | "suggested_assignee">;
  onAssigned: () => void;
  className?: string;
}) {
  const { activeOrg } = useAuth();
  const { data: people } = useQuery({
    queryKey: ["people", activeOrg?.id],
    queryFn: () => api<Person[]>("/api/people"),
    enabled: !!activeOrg,
    staleTime: 60_000,
  });
  const assign = useMutation({
    mutationFn: (userId: string) =>
      api(`/api/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ assignee_user_id: userId }) }),
    onSuccess: onAssigned,
  });

  const suggested = (people ?? []).filter((person) => matchesSuggestion(person, task.suggested_assignee));
  const rest = (people ?? []).filter((person) => !suggested.includes(person));
  const options: SelectOption[] = [...suggested, ...rest].map((person) => {
    const role = person.job_title || ROLE_LABEL[person.role] || person.role;
    return { value: person.id, label: person.name, hint: suggested.includes(person) ? `${role} · sugerida` : role };
  });

  return (
    <div className="min-w-0">
      <Select
        size="sm"
        ariaLabel="Responsable"
        value={task.assignee_user_id ?? ""}
        placeholder={task.assignee_name ?? "Sin asignar"}
        options={options}
        searchable
        searchPlaceholder="Buscar persona o rol"
        onChange={(userId) => assign.mutate(userId)}
        disabled={assign.isPending}
        className={className}
      />
      {task.suggested_assignee && (
        <p className="mt-1 truncate text-[11px] text-ink-400" title={task.suggested_assignee}>
          En la reunión: {task.suggested_assignee}
        </p>
      )}
      {assign.isError && <p className="mt-1 text-[11px] text-red-600">No se pudo asignar</p>}
    </div>
  );
}
