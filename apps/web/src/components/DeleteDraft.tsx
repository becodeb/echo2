import { useState, type MouseEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { Spinner } from "./ui";

/**
 * Borrar un borrador desde la lista. Va dentro del link de la fila, así que
 * cada clic se queda acá. Primero pregunta (en la misma fila, sin ventana).
 */
export function DeleteDraft({ meetingId, title }: { meetingId: string; title: string }) {
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const remove = useMutation({
    mutationFn: () => api(`/api/meetings/${meetingId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const stop = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  if (remove.isError) {
    const forbidden = remove.error instanceof ApiError && remove.error.status === 403;
    return (
      <span onClick={stop} className="text-xs text-red-600" role="alert">
        {forbidden ? "Solo quien la creó puede borrarla" : "No se pudo borrar"}
      </span>
    );
  }

  if (asking) {
    return (
      <span onClick={stop} className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          className="inline-flex items-center gap-1.5 rounded-full bg-red-600 px-3 py-1 text-xs font-semibold text-white transition-colors hover:bg-red-700 disabled:opacity-60"
        >
          {remove.isPending ? <Spinner /> : "Borrar"}
        </button>
        <button
          type="button"
          onClick={() => setAsking(false)}
          className="rounded-full px-2.5 py-1 text-xs font-medium text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-800"
        >
          Cancelar
        </button>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={(event) => {
        stop(event);
        setAsking(true);
      }}
      aria-label={`Borrar el borrador «${title}»`}
      title="Borrar borrador"
      // En la compu aparece al pasar por la fila; en el celular está siempre.
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-ink-400 transition-all hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-accent-500 md:opacity-0 md:group-hover:opacity-100"
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M4.5 7h15M10 11v6M14 11v6M9 7l.6-2.1A1.3 1.3 0 0 1 10.9 4h2.2a1.3 1.3 0 0 1 1.3.9L15 7" />
        <path d="M6.5 7l.8 11.2A2 2 0 0 0 9.3 20h5.4a2 2 0 0 0 2-1.8L17.5 7" />
      </svg>
    </button>
  );
}
