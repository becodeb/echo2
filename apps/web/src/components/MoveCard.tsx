import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MoveOut } from "../api/types";
import { LEVEL_LABEL, type Level } from "../state/access";
import { Button, Spinner } from "./ui";

const ROLE_LABEL: Record<string, string> = {
  owner: "Dueño",
  admin: "Administra",
  member: "Miembro",
  viewer: "Solo lectura",
};

export function useMovePerson(onDone?: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (move: Pick<MoveOut, "user_id" | "from_id" | "to_id">) =>
      api<MoveOut>(`/api/admin/people/${move.user_id}/move`, {
        method: "POST",
        skipOrg: true,
        body: JSON.stringify({ from_organization_id: move.from_id, to_organization_id: move.to_id }),
      }),
    onSuccess: () => {
      for (const key of ["admin-people", "admin-orgs", "org-users"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
      onDone?.();
    },
  });
}

/** Con qué queda en la sede nueva y qué no se muda: lo que hay que saber antes de confirmar. */
export function MoveSummary({ move }: { move: MoveOut }) {
  const levels = (Object.keys(move.levels) as Level[]).map((level) => LEVEL_LABEL[level]);
  const what = [move.position ?? ROLE_LABEL[move.role] ?? move.role, ...levels].join(" · ");
  const left = [
    move.meetings_left > 0 && `${move.meetings_left} ${move.meetings_left === 1 ? "reunión" : "reuniones"}`,
    move.tasks_left > 0 && `${move.tasks_left} ${move.tasks_left === 1 ? "tarea abierta" : "tareas abiertas"}`,
  ].filter(Boolean);
  return (
    <ul className="space-y-1.5 text-sm text-ink-600">
      <li>
        {move.already_there ? "Conserva lo que ya tiene" : "Queda"} en {move.to_name}: <span className="font-medium text-ink-800">{what}</span>
      </li>
      <li>Deja de ver {move.from_name}.</li>
      {left.length > 0 && (
        <li className="text-amber-700">
          {left.join(" y ")} {move.meetings_left + move.tasks_left === 1 ? "queda" : "quedan"} en {move.from_name}: no se mudan.
        </li>
      )}
    </ul>
  );
}

/** La propuesta de Echo en el chat: no se mueve a nadie hasta tocar el botón. */
export function MoveCard({ move }: { move: MoveOut }) {
  const [state, setState] = useState<"asking" | "done" | "cancelled">("asking");
  const run = useMovePerson(() => setState("done"));

  if (state === "done") {
    return (
      <p className="mt-2 text-sm font-medium text-emerald-700">
        Listo: {move.name} ahora es de {move.to_name} y ya no de {move.from_name}.
      </p>
    );
  }
  if (state === "cancelled") return <p className="mt-2 text-sm text-ink-400">No moví a nadie.</p>;
  return (
    <div className="mt-3 rounded-2xl border border-ink-100 bg-white p-4">
      <p className="mb-2 truncate text-xs text-ink-400">{move.email}</p>
      <MoveSummary move={move} />
      {run.isError && (
        <p className="mt-2 text-sm text-red-600">{run.error instanceof Error ? run.error.message : "No se pudo mover"}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => run.mutate(move)} disabled={run.isPending}>
          {run.isPending ? <Spinner /> : "Sí, mover"}
        </Button>
        <Button variant="ghost" onClick={() => setState("cancelled")} disabled={run.isPending}>
          Cancelar
        </Button>
      </div>
    </div>
  );
}
