import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useMyAccess } from "../state/access";
import { Button, Modal, Spinner } from "./ui";

interface ImportResult {
  families_created: number;
  families_completed: number;
  students: number;
  guardians: number;
  skipped_rows: number;
  columns: Record<string, string>;
  sample: { name: string; students: string[]; guardians: string[] }[];
}

/**
 * Cargar alumnos y familias desde la planilla del colegio (CSV de Excel o de
 * Google Sheets). Primero muestra qué va a crear; recién al confirmar guarda.
 * Lo ven los directivos (routers/families.py, import_families).
 */
export function FamilyImportButton() {
  const queryClient = useQueryClient();
  const { data: access } = useMyAccess();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);

  const send = (chosen: File, preview: boolean) => {
    const form = new FormData();
    form.append("file", chosen, chosen.name);
    return api<ImportResult>(`/api/families/import?preview=${preview}`, { method: "POST", body: form });
  };
  const preview = useMutation({ mutationFn: (chosen: File) => send(chosen, true) });
  const save = useMutation({
    mutationFn: (chosen: File) => send(chosen, false),
    onSuccess: (result) => {
      setDone(result);
      queryClient.invalidateQueries({ queryKey: ["families"] });
    },
  });

  if ((access?.rank ?? 1) < 2) return null;

  const close = () => {
    setFile(null);
    setDone(null);
    preview.reset();
    save.reset();
  };
  const result = done ?? preview.data;
  const error = (preview.error ?? save.error) as Error | null;

  return (
    <>
      <Button variant="soft" onClick={() => input.current?.click()}>
        Importar planilla
      </Button>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(event) => {
          const chosen = event.target.files?.[0] ?? null;
          event.target.value = "";
          if (!chosen) return;
          setFile(chosen);
          setDone(null);
          save.reset();
          preview.reset();
          // Se calcula en cuanto se elige el archivo.
          preview.mutate(chosen);
        }}
      />
      <Modal open={!!file} onClose={close} title="Importar alumnos y familias">
        <div className="space-y-4">
          <p className="text-sm text-ink-500">
            Subí la planilla en CSV (en Excel: Guardar como → CSV). La primera fila tiene que tener títulos como
            «Alumno» (o «Apellido» y «Nombre»), «Curso», «Nivel», «Madre», «Padre», «Email». Los hermanos con el
            mismo apellido y responsable quedan en la misma familia.
          </p>
          {file && <p className="truncate text-sm text-ink-700">Archivo: {file.name}</p>}
          {(preview.isPending || save.isPending) && (
            <p className="flex items-center gap-2 text-sm text-ink-500">
              <Spinner className="h-4 w-4" /> {save.isPending ? "Cargando…" : "Leyendo la planilla…"}
            </p>
          )}
          {error && <p className="text-sm text-red-600">{error.message}</p>}
          {result && (
            <div className="space-y-3 rounded-2xl bg-ink-50 p-4 text-sm text-ink-700">
              <p>
                {done ? "Listo: se crearon" : "Se van a crear"} <strong>{result.families_created}</strong>{" "}
                {result.families_created === 1 ? "familia" : "familias"}
                {result.families_completed > 0 && <> y se completan {result.families_completed} que ya estaban</>}, con{" "}
                <strong>{result.students}</strong> {result.students === 1 ? "alumno" : "alumnos"} y {result.guardians}{" "}
                {result.guardians === 1 ? "responsable" : "responsables"}.
                {result.skipped_rows > 0 && ` ${result.skipped_rows} filas sin nombre de alumno se saltean.`}
              </p>
              {!done && result.sample.length > 0 && (
                <ul className="space-y-1 text-xs text-ink-500">
                  {result.sample.map((family) => (
                    <li key={family.name}>
                      <span className="font-medium text-ink-700">{family.name}</span>: {family.students.join(", ")}
                      {family.guardians.length > 0 && ` — ${family.guardians.join(", ")}`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={close}>
              {done ? "Cerrar" : "Cancelar"}
            </Button>
            {!done && (
              <Button
                onClick={() => file && save.mutate(file)}
                disabled={!preview.data || save.isPending || (preview.data.students === 0 && preview.data.guardians === 0)}
              >
                Importar
              </Button>
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
