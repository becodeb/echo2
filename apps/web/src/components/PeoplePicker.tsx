import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MeetingOut } from "../api/types";
import { useAuth } from "../state/auth";
import { Select } from "./Select";
import { Button, Spinner } from "./ui";

/** Una persona de la sede, como la devuelve /api/people. */
export interface SedePerson {
  id: string;
  name: string;
  email: string;
  job_title: string | null;
  role: string;
  /** 3 dirección de la sede, 2 directivo, 1 equipo (DOE, docentes). */
  rank: number;
  rank_label: string | null;
  /** Si quien mira le puede asignar tareas (igual o menor rango). */
  assignable: boolean;
}

export function useSedePeople(enabled = true) {
  const { activeOrg } = useAuth();
  return useQuery({
    queryKey: ["people", activeOrg?.id],
    queryFn: () => api<SedePerson[]>("/api/people"),
    enabled: enabled && !!activeOrg,
    staleTime: 60_000,
  });
}

/**
 * Elegir varias personas de la sede: las elegidas como fichas con una cruz, y
 * un desplegable con buscador para sumar más.
 */
export function PeoplePicker({
  value,
  onChange,
  exclude = [],
  label,
  hint,
  enabled = true,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  /** Personas que no se ofrecen (por ejemplo, quien está creando la reunión). */
  exclude?: string[];
  label?: string;
  hint?: string;
  enabled?: boolean;
}) {
  const { data: people } = useSedePeople(enabled);
  const byId = new Map((people ?? []).map((person) => [person.id, person]));
  const options = (people ?? [])
    .filter((person) => !value.includes(person.id) && !exclude.includes(person.id))
    .map((person) => ({ value: person.id, label: person.name, hint: person.job_title || person.rank_label || undefined }));

  return (
    <div>
      {label && <span className="mb-1.5 block text-sm font-medium text-ink-700">{label}</span>}
      {value.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {value.map((id) => (
            <span
              key={id}
              className="inline-flex min-h-8 items-center gap-1 rounded-full bg-ink-100 py-1 pl-3 pr-1 text-sm text-ink-800"
            >
              {byId.get(id)?.name ?? "…"}
              <button
                type="button"
                aria-label={`Sacar a ${byId.get(id)?.name ?? "esta persona"}`}
                onClick={() => onChange(value.filter((item) => item !== id))}
                className="flex h-6 w-6 items-center justify-center rounded-full text-ink-400 hover:bg-ink-200 hover:text-ink-900"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}
      <Select
        value=""
        placeholder={options.length ? "Sumar persona…" : "No hay más personas"}
        options={options}
        searchable
        searchPlaceholder="Buscar persona"
        onChange={(id) => id && onChange([...value, id])}
        disabled={!options.length}
        ariaLabel={label ?? "Sumar persona"}
      />
      {hint && <p className="mt-1.5 text-xs text-ink-400">{hint}</p>}
    </div>
  );
}

/**
 * Quiénes de la sede estuvieron en la reunión. Es lo que decide quién la ve
 * (además de quien la grabó, sus familias y los directivos), así que se puede
 * corregir después.
 */
export function MeetingStaff({ meeting }: { meeting: MeetingOut }) {
  const queryClient = useQueryClient();
  const staff = meeting.participants.filter((participant) => participant.user_id).map((p) => p.user_id as string);
  const [editing, setEditing] = useState<string[] | null>(null);
  const save = useMutation({
    mutationFn: (ids: string[]) =>
      api<MeetingOut>(`/api/meetings/${meeting.id}/staff`, { method: "PUT", body: JSON.stringify({ user_ids: ids }) }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["meeting", meeting.id], updated);
      setEditing(null);
    },
  });

  if (editing) {
    return (
      <div className="mt-3 rounded-3xl bg-ink-50 p-4">
        <PeoplePicker
          label="¿Quiénes del colegio estuvieron?"
          hint="Las personas que sumes ven esta reunión y les llega un aviso."
          value={editing}
          onChange={setEditing}
          exclude={[meeting.created_by]}
        />
        {save.isError && <p className="mt-2 text-sm text-red-600">{(save.error as Error).message}</p>}
        <div className="mt-3 flex gap-2">
          <Button onClick={() => save.mutate(editing)} disabled={save.isPending}>
            {save.isPending ? <Spinner /> : "Guardar"}
          </Button>
          <Button variant="ghost" onClick={() => setEditing(null)}>
            Cancelar
          </Button>
        </div>
      </div>
    );
  }

  const names = meeting.participants.filter((participant) => participant.user_id).map((p) => p.name);
  return (
    <p className="mt-1 text-sm text-ink-500">
      {names.length ? <>Del colegio estuvieron: {names.join(", ")}. </> : <>Nadie más del colegio figura en esta reunión. </>}
      <button
        type="button"
        onClick={() => setEditing(staff)}
        className="font-medium text-ink-700 underline-offset-2 hover:underline"
      >
        {names.length ? "Cambiar" : "Sumar a quienes estuvieron"}
      </button>
    </p>
  );
}
