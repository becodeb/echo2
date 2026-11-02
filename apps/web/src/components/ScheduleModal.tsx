import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FamilyOut, ReasonOut, ScheduledMeetingOut } from "../api/types";
import { isoDay } from "../lib/agenda";
import { FamilySelect } from "./FamilySelect";
import { PeoplePicker } from "./PeoplePicker";
import { Select } from "./Select";
import { StudentPicker, onlyStudent } from "./StudentPicker";
import { SegmentedToggle } from "./Toggles";
import { Button, Input, Modal, Spinner } from "./ui";
import { LEVEL_LABEL, useMyAccess, type Level } from "../state/access";
import { useAuth } from "../state/auth";
import { useInternalGroups } from "../state/internalGroups";

type Kind = "familia" | "interna";

/** Lo que llega precargado: desde el acta (la próxima reunión con la misma familia) o un día elegido. */
export interface ScheduleDraft {
  date?: string;
  kind?: Kind;
  family_id?: string | null;
  student_ids?: string[];
  reason_id?: string | null;
  level?: string | null;
  group_id?: string | null;
  staff_ids?: string[];
}

/**
 * Agendar (o cambiar) una reunión de la Agenda. Lo que se carga acá ya queda
 * puesto al tocar "Empezar" ese día. El día es lo único obligatorio.
 */
export function ScheduleModal({
  open,
  onClose,
  editing,
  draft,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** Cambiar una ya agendada. */
  editing?: ScheduledMeetingOut;
  draft?: ScheduleDraft;
  onSaved?: (item: ScheduledMeetingOut) => void;
}) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { data: myAccess } = useMyAccess();
  const { data: groupsData } = useInternalGroups();
  const myGroups = (groupsData?.groups ?? []).filter((group) => group.is_member);

  const [date, setDate] = useState(editing?.date ?? draft?.date ?? isoDay(new Date()));
  const [time, setTime] = useState(editing?.time ?? "");
  const [kind, setKind] = useState<Kind>(editing?.kind ?? draft?.kind ?? "familia");
  const [familyId, setFamilyId] = useState(editing?.family_id ?? draft?.family_id ?? "");
  const [students, setStudents] = useState<string[]>(editing?.students.map((s) => s.id) ?? draft?.student_ids ?? []);
  const [reasonId, setReasonId] = useState(editing?.reason_id ?? draft?.reason_id ?? "");
  const [levelChoice, setLevelChoice] = useState(editing?.level ?? draft?.level ?? "");
  const [groupChoice, setGroupChoice] = useState(editing?.group_id ?? draft?.group_id ?? "");
  const [staff, setStaff] = useState<string[]>(
    (editing?.staff.map((person) => person.id) ?? draft?.staff_ids ?? []).filter((id) => id !== user?.id),
  );
  const [note, setNote] = useState(editing?.note ?? "");
  const groupId = groupChoice || myGroups[0]?.id || "";

  const { data: families } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
    enabled: open && kind === "familia",
  });
  const { data: reasons } = useQuery({
    queryKey: ["reasons"],
    queryFn: () => api<ReasonOut[]>("/api/org/meeting-reasons"),
    enabled: open && kind === "familia",
  });
  const family = families?.find((item) => item.id === familyId);
  // El nivel por defecto es el del alumno, como al crear una reunión.
  const creatable = myAccess?.creatable_levels ?? [];
  const kids = students.length ? students : onlyStudent(family);
  const childLevel = family?.members.find((member) => kids.includes(member.id) && member.level)?.level;
  const level = levelChoice || (childLevel && creatable.includes(childLevel as Level) ? childLevel : (creatable[0] ?? ""));

  const save = useMutation({
    mutationFn: () => {
      const body = {
        date,
        time: time || null,
        kind,
        family_id: kind === "familia" ? familyId || null : null,
        student_ids: kind === "familia" && familyId ? kids : [],
        reason_id: kind === "familia" ? reasonId || null : null,
        level: kind === "familia" ? level || null : null,
        group_id: kind === "interna" ? groupId || null : null,
        staff_ids: staff,
        note,
        ...(editing ? { status: "agendada" } : {}),
      };
      return editing
        ? api<ScheduledMeetingOut>(`/api/agenda/${editing.id}`, { method: "PUT", body: JSON.stringify(body) })
        : api<ScheduledMeetingOut>("/api/agenda", { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: (item) => {
      queryClient.invalidateQueries({ queryKey: ["agenda"] });
      onSaved?.(item);
      onClose();
    },
  });

  const remove = useMutation({
    mutationFn: () => api(`/api/agenda/${editing!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agenda"] });
      onClose();
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!date || (kind === "interna" && !groupId)) return;
    save.mutate();
  };
  const error = save.error ?? remove.error;

  return (
    <Modal open={open} onClose={onClose} title={editing ? "Cambiar reunión agendada" : "Agendar reunión"}>
      <form onSubmit={submit} className="space-y-4">
        <p className="-mt-2 text-sm text-ink-500">Lo que cargues ahora ya queda puesto al empezar a grabar.</p>

        <div className="grid grid-cols-2 gap-3">
          <Input label="Día" type="date" required value={date} onChange={(event) => setDate(event.target.value)} />
          <Input label="Hora (opcional)" type="time" value={time} onChange={(event) => setTime(event.target.value)} />
        </div>

        {myGroups.length > 0 && (
          <SegmentedToggle
            ariaLabel="Con quién"
            value={kind}
            onChange={setKind}
            options={[
              { value: "familia", label: "Con una familia" },
              { value: "interna", label: "Interna" },
            ]}
          />
        )}

        {kind === "familia" ? (
          <div className="grid gap-4 rounded-2xl bg-ink-50 p-4 sm:grid-cols-2">
            <FamilySelect
              value={familyId}
              onChange={(next) => {
                setFamilyId(next);
                setStudents([]);
              }}
              enabled={open}
            />
            <Select
              label="Motivo"
              value={reasonId}
              onChange={setReasonId}
              options={[{ value: "", label: "Sin definir" }, ...(reasons ?? []).map((reason) => ({ value: reason.id, label: reason.name }))]}
            />
            <StudentPicker family={family} value={students} onChange={setStudents} />
            {creatable.length > 1 && (
              <Select
                label="Nivel"
                value={level}
                onChange={setLevelChoice}
                options={creatable.map((value) => ({ value, label: LEVEL_LABEL[value] }))}
              />
            )}
          </div>
        ) : (
          <div className="rounded-2xl bg-ink-50 p-4">
            <Select
              label="Grupo"
              value={groupId}
              onChange={setGroupChoice}
              options={myGroups.map((item) => ({ value: item.id, label: item.name }))}
            />
          </div>
        )}

        <PeoplePicker
          label="Por el colegio"
          hint="A quienes sumes les aparece en su agenda."
          value={staff}
          onChange={setStaff}
          exclude={user ? [user.id] : []}
          enabled={open}
        />

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700">
            Nota para ese día <span className="font-normal text-ink-400">· no va al acta</span>
          </span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            maxLength={1000}
            placeholder="Traer el informe de la psicopedagoga"
            className="w-full resize-none rounded-2xl border border-ink-200 bg-white px-4 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20"
          />
        </label>

        {error && (
          <p className="text-sm text-red-600">{error instanceof Error ? error.message : "No se pudo guardar"}</p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          {editing?.can_edit && (
            <Button
              type="button"
              variant="ghost"
              className="mr-auto text-red-600 hover:bg-red-50 hover:text-red-700"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending ? <Spinner /> : "Borrar"}
            </Button>
          )}
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={save.isPending || !date || (kind === "interna" && !groupId)}>
            {save.isPending ? <Spinner /> : editing ? "Guardar" : "Agendar"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
