import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { Button, Input, Modal, Spinner } from "./ui";

/**
 * El número de acta lo pone quien la hace (Bauti, 6/10): hay actas que se
 * hacen fuera de Echo (presenciales, en papel) y el contador no puede saber
 * cuál sigue. Echo sugiere el siguiente al más alto que conoce.
 */
export function useNextActaNumber(enabled = true) {
  const { activeOrg } = useAuth();
  return useQuery({
    queryKey: ["minutes-numbering", activeOrg?.id],
    queryFn: () => api<{ next_number: number; last_assigned: number | null }>("/api/org/minutes-numbering"),
    enabled: enabled && !!activeOrg,
    staleTime: 0,
  }).data?.next_number;
}

export function parseActaNumber(text: string): number | null {
  const value = Number(text.trim());
  return Number.isInteger(value) && value >= 1 ? value : null;
}

/** "¿Qué número de acta es?": aparece mientras el acta no tenga número (o al tocar "Cambiar"). */
export function ActaNumberCard({
  meetingId,
  current,
  onDone,
}: {
  meetingId: string;
  current: number | null;
  onDone?: () => void;
}) {
  const queryClient = useQueryClient();
  const suggested = useNextActaNumber(current == null);
  const [text, setText] = useState<string | null>(null);
  const value = text ?? String(current ?? suggested ?? "");
  const save = useMutation({
    mutationFn: (number: number) =>
      api(`/api/meetings/${meetingId}/minutes/number`, { method: "PUT", body: JSON.stringify({ number }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["minutes", meetingId] });
      queryClient.invalidateQueries({ queryKey: ["minutes-numbering"] });
      setText(null);
      onDone?.();
    },
  });
  const number = parseActaNumber(value);

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-2xl border border-accent-200 bg-accent-50/60 px-4 py-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (number != null) save.mutate(number);
      }}
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink-900">
          {current == null ? "¿Qué número de acta es?" : "Cambiar el número de acta"}
        </p>
        <p className="text-xs text-ink-500">
          {suggested != null && current == null
            ? `Echo sugiere el ${suggested} (el siguiente al último que conoce). Si hiciste actas fuera de Echo, poné el que corresponda.`
            : "El número que va en el acta impresa."}
        </p>
      </div>
      <div className="w-28">
        <Input
          label="N.º de acta"
          inputMode="numeric"
          value={value}
          onChange={(event) => setText(event.target.value)}
        />
      </div>
      <Button type="submit" disabled={number == null || save.isPending}>
        {save.isPending ? <Spinner /> : "Guardar"}
      </Button>
      {current != null && onDone && (
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancelar
        </Button>
      )}
      {save.isError && (
        <p className="w-full text-sm text-red-600">
          {save.error instanceof Error ? save.error.message : "No se pudo guardar el número"}
        </p>
      )}
    </form>
  );
}

/**
 * Antes de hacer (o rehacer) el acta: el número y, si se quiere, qué tiene que
 * estar y qué no. Las indicaciones son opcionales y van plegadas: el acta
 * normal sale bien sin tocar nada.
 */
export function GenerateActaModal({
  meetingId,
  currentNumber,
  regenerating,
  onClose,
}: {
  meetingId: string;
  currentNumber: number | null;
  regenerating: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const suggested = useNextActaNumber(currentNumber == null);
  const [text, setText] = useState<string | null>(null);
  const [instructions, setInstructions] = useState("");
  const [showInstructions, setShowInstructions] = useState(false);
  const value = text ?? String(currentNumber ?? suggested ?? "");
  const number = parseActaNumber(value);

  const generate = useMutation({
    mutationFn: () =>
      api(`/api/meetings/${meetingId}/minutes/generate`, {
        method: "POST",
        body: JSON.stringify({ number, instructions: instructions.trim() || null }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["minutes", meetingId] });
      queryClient.invalidateQueries({ queryKey: ["minutes-numbering"] });
      onClose();
    },
  });

  return (
    <Modal open onClose={onClose} title={regenerating ? "Regenerar el acta" : "Hacer el acta"}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          generate.mutate();
        }}
      >
        <div>
          <Input
            label="Número de acta"
            inputMode="numeric"
            value={value}
            onChange={(event) => setText(event.target.value)}
            autoFocus
          />
          <p className="mt-1 text-xs text-ink-500">
            {currentNumber != null
              ? "Es el que ya tenía; cambialo si no corresponde."
              : suggested != null
                ? `Echo sugiere el ${suggested}. Si hiciste actas fuera de Echo, poné el que corresponda.`
                : "El número que va en el acta impresa."}
          </p>
        </div>

        {showInstructions ? (
          <div>
            <label className="mb-1 block text-sm font-medium text-ink-700" htmlFor="acta-instructions">
              Qué tiene que estar y qué no (opcional)
            </label>
            <textarea
              id="acta-instructions"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value.slice(0, 1000))}
              rows={4}
              placeholder="Ej.: no incluir lo que se habló del hermano. Que figure que la familia pidió una reunión con la psicopedagoga."
              className="w-full rounded-2xl border border-ink-200 bg-white px-3.5 py-2.5 text-[15px] text-ink-900 placeholder:text-ink-400 focus:border-ink-400 focus:outline-none"
            />
            <p className="mt-1 text-xs text-ink-500">Echo lo tiene en cuenta, sin agregar nada que no se haya dicho.</p>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowInstructions(true)}
            className="text-sm font-medium text-accent-700 hover:underline"
          >
            + Indicar qué tiene que estar y qué no (opcional)
          </button>
        )}

        {regenerating && (
          <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Echo redacta una versión nueva: las correcciones hechas a mano quedan en la versión anterior.
          </p>
        )}
        {generate.isError && (
          <p className="text-sm text-red-600">
            {generate.error instanceof Error ? generate.error.message : "No se pudo empezar"}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={generate.isPending || (value.trim() !== "" && number == null)}>
            {generate.isPending ? <Spinner /> : regenerating ? "Regenerar" : "Hacer el acta"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
