import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { InterviewFields, LetterheadOut, MinutesOut } from "../api/types";
import { InterviewSheet } from "./InterviewSheet";
import { Button, Card, Input, Spinner } from "./ui";

/**
 * Revisión y confirmación del acta de entrevista.
 *
 * Mientras no está confirmada, el acta se muestra como formulario editable:
 * quien grabó la reunión la corrige y la confirma. Recién confirmada aparece
 * "Imprimir", con la hoja tal como sale en papel.
 */
export function InterviewReview({ meetingId, minutes, fields }: {
  meetingId: string;
  minutes: MinutesOut;
  fields: InterviewFields;
}) {
  const queryClient = useQueryClient();
  const confirmed = minutes.status === "approved";
  const [editing, setEditing] = useState(!confirmed);
  const [form, setForm] = useState<InterviewFields>(fields);
  const dirty = JSON.stringify(form) !== JSON.stringify(fields);

  const { data: letterhead } = useQuery({
    queryKey: ["letterhead"],
    queryFn: () => api<LetterheadOut>("/api/org/letterhead"),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["minutes", meetingId] });

  const save = useMutation({
    mutationFn: () =>
      api<MinutesOut>(`/api/meetings/${meetingId}/minutes/versions`, {
        method: "POST",
        body: JSON.stringify({ fields: form }),
      }),
    onSuccess: refresh,
  });

  const confirm = useMutation({
    mutationFn: async () => {
      if (dirty) await save.mutateAsync();
      return api<MinutesOut>(`/api/meetings/${meetingId}/minutes/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: "approved" }),
      });
    },
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });

  const set = (key: keyof InterviewFields) => (value: string) => setForm((current) => ({ ...current, [key]: value }));
  const error = confirm.error ?? save.error;

  if (!editing) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 rounded-xl bg-emerald-50 px-4 py-3">
          <span className="text-sm font-medium text-emerald-800">
            {minutes.number != null ? `Acta N.º ${minutes.number} confirmada` : "Acta confirmada"}
            {minutes.approved_at ? ` el ${new Date(minutes.approved_at).toLocaleString("es")}` : ""}.
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={() => setEditing(true)}>Corregir</Button>
            <Link to={`/meetings/${meetingId}/acta?print=1`} target="_blank" rel="noopener">
              <Button>Imprimir acta</Button>
            </Link>
          </div>
        </div>
        {letterhead && (
          <div className="overflow-x-auto rounded-xl bg-ink-100 p-4">
            <InterviewSheet fields={fields} letterhead={letterhead} number={minutes.number} />
          </div>
        )}
      </div>
    );
  }

  return (
    <Card className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-ink-900">Revisá el acta y confirmala</h3>
        <p className="text-sm text-ink-500">
          Echo completó el formulario con lo que se dijo en la reunión. Corregí lo que haga falta; al confirmar
          queda lista para imprimir.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
        <Input label="Nombre del alumno" value={form.alumno} onChange={(e) => set("alumno")(e.target.value)} />
        <Input label="Curso" value={form.curso} onChange={(e) => set("curso")(e.target.value)} />
      </div>

      <fieldset>
        <legend className="mb-1.5 text-sm font-medium text-ink-700">Solicitada por</legend>
        <div className="flex gap-5">
          {(["familia", "colegio"] as const).map((option) => (
            <label key={option} className="flex items-center gap-2 text-sm text-ink-800">
              <input
                type="radio"
                name="solicitada_por"
                checked={form.solicitada_por === option}
                onChange={() => set("solicitada_por")(option)}
              />
              {option === "familia" ? "Familia" : "Colegio"}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
        <Input label="Motivo general" value={form.motivo} onChange={(e) => set("motivo")(e.target.value)} />
        <Input label="Fecha" type="date" value={form.fecha} onChange={(e) => set("fecha")(e.target.value)} />
      </div>
      <Input label="Se reúnen (por el colegio)" value={form.reunen} onChange={(e) => set("reunen")(e.target.value)} />
      <Input label="Con (familia u otros)" value={form.con} onChange={(e) => set("con")(e.target.value)} />

      <label className="block">
        <span className="mb-1.5 block text-sm font-medium text-ink-700">Desarrollo</span>
        <textarea
          value={form.desarrollo}
          onChange={(e) => set("desarrollo")(e.target.value)}
          rows={14}
          className="w-full rounded-lg border border-ink-200 p-3 text-sm leading-relaxed text-ink-900 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20"
        />
      </label>

      {error && (
        <p className="text-sm text-red-600">{error instanceof Error ? error.message : "No se pudo guardar"}</p>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2">
        {confirmed && (
          <Button variant="ghost" onClick={() => { setForm(fields); setEditing(false); }}>Cancelar</Button>
        )}
        {dirty && (
          <Button variant="soft" onClick={() => save.mutate()} disabled={save.isPending || confirm.isPending}>
            {save.isPending && !confirm.isPending ? <Spinner /> : "Guardar sin confirmar"}
          </Button>
        )}
        {minutes.can_confirm ? (
          <Button onClick={() => confirm.mutate()} disabled={confirm.isPending}>
            {confirm.isPending ? <Spinner /> : "Confirmar acta"}
          </Button>
        ) : (
          <span className="text-sm text-ink-500">La confirma quien grabó la reunión.</span>
        )}
      </div>
    </Card>
  );
}
