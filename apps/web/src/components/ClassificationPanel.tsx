import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  Audience,
  ClassificationOut,
  FamilyOut,
  ProfessionalOut,
  ReasonOut,
  Severity,
} from "../api/types";
import { useAuth } from "../state/auth";
import { FamilySelect } from "./FamilySelect";
import { StudentPicker, onlyStudent } from "./StudentPicker";
import { Select } from "./Select";
import { Badge, Button, Input, Modal, Spinner } from "./ui";

/**
 * Clasificación de la reunión: familia, motivo, gravedad y quién vino.
 *
 * Se guarda todo junto porque en la práctica se completa de una sentada, al
 * terminar la reunión. El resumen vive en la cabecera de la reunión
 * (MeetingDetail); acá solo está el editor, que la cabecera abre y cierra.
 */

export const SEVERITIES: { value: Severity; label: string; dot: string }[] = [
  { value: "verde", label: "Verde", dot: "bg-emerald-500" },
  { value: "amarillo", label: "Amarillo", dot: "bg-amber-400" },
  { value: "rojo", label: "Rojo", dot: "bg-red-500" },
];

export const AUDIENCES: { value: Audience; label: string }[] = [
  { value: "familia", label: "Con la familia" },
  { value: "profesionales", label: "Con profesionales" },
  { value: "mixta", label: "Familia y profesionales" },
  { value: "docentes", label: "Con docentes" },
  { value: "interna", label: "Interna del equipo" },
];

export function useClassification(meetingId: string) {
  return useQuery({
    queryKey: ["classification", meetingId],
    queryFn: () => api<ClassificationOut>(`/api/meetings/${meetingId}/classification`),
  });
}

export function ClassificationPanel({
  meetingId,
  editing,
  onClose,
}: {
  meetingId: string;
  editing: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const canManageReasons = activeOrg?.role === "owner" || activeOrg?.role === "admin";
  const [newReason, setNewReason] = useState<string | null>(null);
  const [familyId, setFamilyId] = useState("");
  const [reasonId, setReasonId] = useState("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [attended, setAttended] = useState<Set<string>>(new Set());
  const [audience, setAudience] = useState<Audience | "">("");
  const [attendedPros, setAttendedPros] = useState<Set<string>>(new Set());
  const [students, setStudents] = useState<string[]>([]);

  const { data: classification, isLoading } = useClassification(meetingId);
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
  const { data: professionals } = useQuery({
    queryKey: ["professionals"],
    queryFn: () => api<ProfessionalOut[]>("/api/professionals"),
    enabled: editing,
  });

  // Al abrir el editor se parte de lo que ya está guardado.
  useEffect(() => {
    if (!editing || !classification) return;
    setFamilyId(classification.family_id ?? "");
    setReasonId(classification.reason_id ?? "");
    setSeverity(classification.severity ?? "");
    setAudience(classification.audience ?? "");
    setStudents(classification.student_ids ?? []);
    setAttended(
      new Set(classification.attendance.filter((row) => row.attended).map((row) => row.member_id)),
    );
    setAttendedPros(
      new Set(
        classification.professionals
          .filter((row) => row.attended)
          .map((row) => row.professional_id),
      ),
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
          audience: audience || null,
          attended_member_ids: [...attended],
          attended_professional_ids: [...attendedPros],
          student_ids: familyId === classification?.family_id || students.length ? students : onlyStudent(selectedFamily),
        }),
      }),
    onSuccess: () => {
      onClose();
      queryClient.invalidateQueries({ queryKey: ["classification", meetingId] });
      queryClient.invalidateQueries({ queryKey: ["families"] });
    },
  });

  const createReason = useMutation({
    mutationFn: (name: string) =>
      api<ReasonOut>("/api/org/meeting-reasons", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), is_active: true, position: (reasons?.length ?? 0) + 1 }),
      }),
    onSuccess: (reason) => {
      queryClient.setQueryData<ReasonOut[]>(["reasons"], (current) => [...(current ?? []), reason]);
      queryClient.invalidateQueries({ queryKey: ["reasons"] });
      setReasonId(reason.id);
      setNewReason(null);
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

  // Los profesionales que acompañan a la familia elegida se muestran primero.
  const linkedProIds = new Set(
    selectedFamily && selectedFamily.id !== classification?.family_id
      ? selectedFamily.professionals.map((pro) => pro.id)
      : (classification?.professionals ?? []).filter((row) => row.linked).map((row) => row.professional_id),
  );

  if (!editing) return null;

  return (
    <div className="mt-4 space-y-4 rounded-xl border border-ink-100 bg-white px-4 py-4">
      <Select
        label="¿Con quién fue?"
        value={audience}
        onChange={(next) => setAudience(next as Audience | "")}
        options={[{ value: "", label: "Sin definir" }, ...AUDIENCES]}
        className="sm:max-w-xs"
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <FamilySelect
          value={familyId}
          onChange={(next) => {
            setFamilyId(next);
            setAttended(new Set());
          }}
        />

        <div>
          <Select
            label="Motivo"
            value={reasonId}
            onChange={setReasonId}
            options={[
              { value: "", label: "Sin motivo" },
              ...(reasons ?? []).map((reason) => ({ value: reason.id, label: reason.name })),
            ]}
            searchPlaceholder="Buscar motivo…"
            action={
              canManageReasons
                ? { label: "Nuevo motivo", onClick: (query) => setNewReason(query) }
                : undefined
            }
          />
          {reasons?.length === 0 && !canManageReasons && (
            <span className="mt-1 block text-xs text-ink-400">
              No hay motivos definidos: los carga un administrador en{" "}
              <Link to="/settings" className="text-accent-600 hover:underline">
                Ajustes
              </Link>
              .
            </span>
          )}
        </div>
      </div>

      <div>
        <span className="mb-1.5 block text-sm font-medium text-ink-700">Gravedad</span>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSeverity("")}
            className={`rounded-xl border px-3 py-1.5 text-sm ${
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
              className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 text-sm ${
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

      <StudentPicker family={selectedFamily} value={students} onChange={setStudents} />

      {familyId && (
        <div>
          <span className="mb-1.5 block text-sm font-medium text-ink-700">¿Quiénes vinieron?</span>
          {membersToShow.length === 0 ? (
            <p className="text-sm text-ink-500">
              Esta familia no tiene integrantes cargados.{" "}
              <Link to={`/families/${familyId}`} className="text-accent-600 hover:underline">
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

      {(professionals ?? []).length > 0 && (
        <div>
          <span className="mb-1.5 block text-sm font-medium text-ink-700">
            Profesionales presentes
          </span>
          <div className="space-y-1.5">
            {[...(professionals ?? [])]
              .sort((a, b) => {
                // Primero los que acompañan a esta familia: son los esperables.
                const aLinked = linkedProIds.has(a.id) ? 0 : 1;
                const bLinked = linkedProIds.has(b.id) ? 0 : 1;
                return aLinked - bLinked || a.name.localeCompare(b.name);
              })
              .map((pro) => (
                <label key={pro.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={attendedPros.has(pro.id)}
                    onChange={(event) => {
                      const next = new Set(attendedPros);
                      if (event.target.checked) next.add(pro.id);
                      else next.delete(pro.id);
                      setAttendedPros(next);
                    }}
                    className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                  />
                  <span className="text-ink-800">{pro.name}</span>
                  {pro.role_label && <Badge tone="gray">{pro.role_label}</Badge>}
                  {linkedProIds.has(pro.id) && <Badge tone="indigo">acompaña</Badge>}
                </label>
              ))}
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        {save.isError && (
          <span className="text-sm text-red-600">
            {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
          </span>
        )}
      </div>

      <Modal open={newReason !== null} onClose={() => setNewReason(null)} title="Nuevo motivo">
        {newReason !== null && (
          <form
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (newReason.trim()) createReason.mutate(newReason);
            }}
            className="space-y-4"
          >
            <Input
              label="Nombre"
              placeholder="Conducta, aprendizaje, convivencia…"
              required
              autoFocus
              value={newReason}
              onChange={(event) => setNewReason(event.target.value)}
            />
            {createReason.isError && (
              <p className="text-sm text-red-600">
                {createReason.error instanceof Error ? createReason.error.message : "No se pudo crear"}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setNewReason(null)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={createReason.isPending}>
                {createReason.isPending ? <Spinner /> : "Crear y elegir"}
              </Button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
