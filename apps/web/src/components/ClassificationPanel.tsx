import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ClassificationOut, FamilyOut, ReasonOut, Severity } from "../api/types";
import { Badge, Button, Spinner } from "./ui";

/**
 * Clasificación de la reunión: familia, motivo, gravedad y quién vino.
 *
 * Se guarda todo junto porque en la práctica se completa de una sentada, al
 * terminar la reunión. Colapsado muestra el resumen; se abre para editar.
 */

const SEVERITIES: { value: Severity; label: string; dot: string }[] = [
  { value: "verde", label: "Verde", dot: "bg-emerald-500" },
  { value: "amarillo", label: "Amarillo", dot: "bg-amber-400" },
  { value: "rojo", label: "Rojo", dot: "bg-red-500" },
];

const SEVERITY_TONE: Record<Severity, "green" | "amber" | "red"> = {
  verde: "green",
  amarillo: "amber",
  rojo: "red",
};

export function ClassificationPanel({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [familyId, setFamilyId] = useState("");
  const [reasonId, setReasonId] = useState("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [attended, setAttended] = useState<Set<string>>(new Set());

  const { data: classification, isLoading } = useQuery({
    queryKey: ["classification", meetingId],
    queryFn: () => api<ClassificationOut>(`/api/meetings/${meetingId}/classification`),
  });
  const { data: families } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
    enabled: editing,
  });
  const { data: reasons } = useQuery({
    queryKey: ["reasons"],
    queryFn: () => api<ReasonOut[]>("/api/org/meeting-reasons"),
    enabled: editing,
  });

  // Al abrir el editor se parte de lo que ya está guardado.
  useEffect(() => {
    if (!editing || !classification) return;
    setFamilyId(classification.family_id ?? "");
    setReasonId(classification.reason_id ?? "");
    setSeverity(classification.severity ?? "");
    setAttended(
      new Set(classification.attendance.filter((row) => row.attended).map((row) => row.member_id)),
    );
  }, [editing, classification]);

  const save = useMutation({
    mutationFn: () =>
      api<ClassificationOut>(`/api/meetings/${meetingId}/classification`, {
        method: "PUT",
        body: JSON.stringify({
          family_id: familyId || null,
          reason_id: reasonId || null,
          severity: severity || null,
          attended_member_ids: [...attended],
        }),
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["classification", meetingId] });
      queryClient.invalidateQueries({ queryKey: ["families"] });
    },
  });

  if (isLoading) return null;

  // Al cambiar de familia en el editor, los integrantes que se listan son los
  // de la familia elegida, no los de la anterior.
  const selectedFamily = families?.find((family) => family.id === familyId);
  const membersToShow =
    editing && selectedFamily && selectedFamily.id !== classification?.family_id
      ? selectedFamily.members.map((member) => ({
          member_id: member.id,
          name: member.name,
          relationship_type: member.relationship_type,
          is_guardian: member.is_guardian,
          attended: false,
          recorded: false,
        }))
      : classification?.attendance ?? [];

  if (!editing) {
    const nothingSet =
      !classification?.family_id && !classification?.reason_id && !classification?.severity;
    return (
      <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-ink-100 bg-white px-4 py-3">
        {nothingSet ? (
          <span className="text-sm text-ink-500">Esta reunión no está clasificada.</span>
        ) : (
          <>
            {classification?.family_name && (
              <Badge tone="indigo">{classification.family_name}</Badge>
            )}
            {classification?.reason_name && <Badge>{classification.reason_name}</Badge>}
            {classification?.severity && (
              <Badge tone={SEVERITY_TONE[classification.severity]}>
                {SEVERITIES.find((s) => s.value === classification.severity)?.label}
              </Badge>
            )}
            {classification?.all_guardians_present === true && (
              <Badge tone="green">Vinieron todos</Badge>
            )}
            {classification?.all_guardians_present === false && (
              <Badge tone="amber">Faltó alguno</Badge>
            )}
            {classification?.family_id && classification.all_guardians_present === null && (
              <Badge tone="gray">Asistencia sin registrar</Badge>
            )}
          </>
        )}
        <button
          onClick={() => setEditing(true)}
          className="ml-auto text-sm font-medium text-accent-600 hover:underline"
        >
          {nothingSet ? "Clasificar" : "Editar"}
        </button>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-4 rounded-lg border border-ink-100 bg-white px-4 py-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700">Familia</span>
          <select
            value={familyId}
            onChange={(event) => {
              setFamilyId(event.target.value);
              setAttended(new Set());
            }}
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
          >
            <option value="">— sin familia —</option>
            {(families ?? []).map((family) => (
              <option key={family.id} value={family.id}>
                {family.name}
              </option>
            ))}
          </select>
          {families?.length === 0 && (
            <span className="mt-1 block text-xs text-ink-400">
              Todavía no hay familias cargadas.{" "}
              <Link to="/families" className="text-accent-600 hover:underline">
                Crear una
              </Link>
            </span>
          )}
        </label>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700">Motivo</span>
          <select
            value={reasonId}
            onChange={(event) => setReasonId(event.target.value)}
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
          >
            <option value="">— sin motivo —</option>
            {(reasons ?? []).map((reason) => (
              <option key={reason.id} value={reason.id}>
                {reason.name}
              </option>
            ))}
          </select>
          {reasons?.length === 0 && (
            <span className="mt-1 block text-xs text-ink-400">
              No hay motivos definidos.{" "}
              <Link to="/settings" className="text-accent-600 hover:underline">
                Cargarlos en Ajustes
              </Link>
            </span>
          )}
        </label>
      </div>

      <div>
        <span className="mb-1.5 block text-sm font-medium text-ink-700">Gravedad</span>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSeverity("")}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              severity === "" ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 text-ink-600"
            }`}
          >
            Sin definir
          </button>
          {SEVERITIES.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setSeverity(item.value)}
              className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm ${
                severity === item.value
                  ? "border-ink-900 bg-ink-900 text-white"
                  : "border-ink-200 text-ink-600"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${item.dot}`} />
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {familyId && (
        <div>
          <span className="mb-1.5 block text-sm font-medium text-ink-700">¿Quiénes vinieron?</span>
          {membersToShow.length === 0 ? (
            <p className="text-sm text-ink-500">
              Esta familia no tiene integrantes cargados.{" "}
              <Link to="/families" className="text-accent-600 hover:underline">
                Cargarlos
              </Link>
            </p>
          ) : (
            <div className="space-y-1.5">
              {membersToShow.map((row) => (
                <label key={row.member_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={attended.has(row.member_id)}
                    onChange={(event) => {
                      const next = new Set(attended);
                      if (event.target.checked) next.add(row.member_id);
                      else next.delete(row.member_id);
                      setAttended(next);
                    }}
                    className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                  />
                  <span className="text-ink-800">{row.name}</span>
                  <Badge tone={row.is_guardian ? "indigo" : "gray"}>{row.relationship_type}</Badge>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        <Button variant="ghost" onClick={() => setEditing(false)}>
          Cancelar
        </Button>
        {save.isError && (
          <span className="text-sm text-red-600">
            {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
          </span>
        )}
      </div>
    </div>
  );
}
