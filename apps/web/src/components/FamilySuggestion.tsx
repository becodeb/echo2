import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ClassificationOut, MeetingOut } from "../api/types";
import { Spinner } from "./ui";

/**
 * La reunión terminó sin familia: Echo sugiere una por el título (o crearla)
 * y se asigna con un toque. "Elegir otra" abre la clasificación de siempre.
 */
export function FamilySuggestion({ meeting, onPick }: { meeting: MeetingOut; onPick: () => void }) {
  const queryClient = useQueryClient();
  const suggestion = meeting.meta?.family_suggestion;
  const answer = useMutation({
    mutationFn: (action: "accept" | "dismiss") =>
      api<ClassificationOut>(`/api/meetings/${meeting.id}/family-suggestion`, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
    onSuccess: (classification) => {
      queryClient.setQueryData(["classification", meeting.id], classification);
      queryClient.invalidateQueries({ queryKey: ["meeting", meeting.id] });
      queryClient.invalidateQueries({ queryKey: ["classification", meeting.id] });
      queryClient.invalidateQueries({ queryKey: ["families"] });
    },
  });

  if (meeting.kind !== "familia" || suggestion?.status !== "pending" || answer.isSuccess) return null;
  const name = suggestion.family_name ?? suggestion.create_name;

  return (
    <section
      aria-label="Familia de la reunión"
      className="animate-fade-up mt-3 rounded-3xl border border-amber-200 bg-amber-50 px-4 py-3.5"
    >
      <p className="text-sm font-semibold text-amber-900">
        {suggestion.family_name
          ? `Esta reunión no tiene familia. ¿Es con la ${suggestion.family_name}?`
          : suggestion.create_name
            ? `Esta reunión no tiene familia y no hay ninguna cargada como «${suggestion.create_name}».`
            : "Esta reunión no tiene familia."}
      </p>
      <p className="mt-0.5 text-sm text-amber-800">
        Con la familia, la reunión queda en su historial y en su carpeta.
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {name && (
          <button
            type="button"
            disabled={answer.isPending}
            onClick={() => answer.mutate("accept")}
            className="inline-flex min-h-11 items-center gap-2 rounded-full bg-amber-900 px-4 text-sm font-semibold text-white hover:bg-amber-800 disabled:opacity-60"
          >
            {answer.isPending && answer.variables === "accept" && <Spinner />}
            {suggestion.family_name ? `Sí, asignar a ${suggestion.family_name}` : `Crear «${suggestion.create_name}» y asignarla`}
          </button>
        )}
        <button
          type="button"
          onClick={onPick}
          className="min-h-11 rounded-full bg-white px-4 text-sm font-semibold text-amber-900 hover:bg-amber-100"
        >
          {name ? "Elegir otra" : "Elegir familia"}
        </button>
        <button
          type="button"
          disabled={answer.isPending}
          onClick={() => answer.mutate("dismiss")}
          className="min-h-11 rounded-full px-3 text-sm font-semibold text-amber-900 hover:bg-amber-100"
        >
          No es con una familia
        </button>
      </div>
      {answer.isError && (
        <p className="mt-2 text-sm text-red-700">
          {answer.error instanceof Error ? answer.error.message : "No se pudo asignar"}
        </p>
      )}
    </section>
  );
}
