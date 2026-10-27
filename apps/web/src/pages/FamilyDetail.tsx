import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  FamilyDetailOut,
  FamilyMemberOut,
  FamilySummaryOut,
  FamilyTaskOut,
  ProfessionalOut,
} from "../api/types";
import { FamilyMeetings } from "../components/FamilyMeetingsPanel";
import { LevelBadge, LevelPicker } from "../components/FamilyLevel";
import { NewMeetingModal } from "../components/NewMeetingModal";
import { PeoplePicker } from "../components/PeoplePicker";
import { Select } from "../components/Select";
import { Badge, Button, Card, EmptyState, Input, Spinner } from "../components/ui";
import { LEVEL_LABEL, useMyAccess, type Level } from "../state/access";
import { useAuth } from "../state/auth";

/**
 * La página de una familia: hijos con su curso y nivel, responsables,
 * resumen de IA, tareas abiertas, todas sus reuniones, quiénes la siguen,
 * profesionales, carpeta de Drive e historial de cambios.
 *
 * Lo que sale de reuniones (resumen, tareas, reuniones) es solo lo que quien
 * mira puede ver: eso lo resuelve el servidor.
 */

type Relationship = FamilyMemberOut["relationship_type"];

const GUARDIAN_RELATIONSHIPS: { value: Relationship; label: string }[] = [
  { value: "madre", label: "Madre" },
  { value: "padre", label: "Padre" },
  { value: "tutor", label: "Tutor/a" },
  { value: "otro", label: "Otro" },
];

const RELATIONSHIP_LABEL: Record<string, string> = {
  madre: "Madre",
  padre: "Padre",
  tutor: "Tutor/a",
  estudiante: "Hijo/a",
  otro: "Otro",
};

const textareaClass =
  "w-full rounded-2xl border border-ink-200 bg-white px-4 py-2.5 text-base text-ink-900 placeholder:text-ink-400 sm:text-sm focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20";

const DAY = 24 * 60 * 60 * 1000;

function ago(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / DAY);
  if (days <= 0) return "hoy";
  if (days === 1) return "ayer";
  if (days < 30) return `hace ${days} días`;
  return new Date(iso).toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" });
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("es", { day: "numeric", month: "short" });
}

function memberBody(member: FamilyMemberOut, changes: Partial<FamilyMemberOut> = {}) {
  const next = { ...member, ...changes };
  return JSON.stringify({
    name: next.name,
    relationship_type: next.relationship_type,
    is_guardian: next.is_guardian,
    email: next.email,
    phone: next.phone,
    curso: next.curso ?? null,
    level: next.level ?? null,
  });
}

function Section({
  title,
  action,
  children,
  className = "",
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={`space-y-4 p-4 sm:p-6 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">{title}</h2>
        {action}
      </div>
      {children}
    </Card>
  );
}

function useFamilyInvalidate(familyId: string) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ["family", familyId] });
    queryClient.invalidateQueries({ queryKey: ["families"] });
  };
}

function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-sm text-red-600">{error instanceof Error ? error.message : "No se pudo guardar"}</p>;
}

/** "¿Sacar a X?" con Sí/No en el lugar, sin ventana. */
function ConfirmRemove({ label, onConfirm, busy }: { label: string; onConfirm: () => void; busy?: boolean }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className="text-xs text-ink-400 hover:text-red-600">
        Sacar
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 text-xs">
      <span className="text-ink-600">¿Sacar a {label}?</span>
      <button type="button" onClick={onConfirm} disabled={busy} className="font-medium text-red-600 hover:underline">
        Sí
      </button>
      <button type="button" onClick={() => setAsking(false)} className="text-ink-500 hover:underline">
        No
      </button>
    </span>
  );
}

// ── Resumen de IA ────────────────────────────────────────────────

function SummaryList({ title, items, tone = "text-ink-300" }: { title: string; items: string[]; tone?: string }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">{title}</h3>
      <ul className="space-y-1 text-sm text-ink-700">
        {items.map((item, index) => (
          <li key={index} className="flex gap-2">
            <span aria-hidden className={tone}>
              •
            </span>
            <span className="min-w-0 break-words">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FamilySummary({ familyId, canGenerate }: { familyId: string; canGenerate: boolean }) {
  const queryClient = useQueryClient();
  const { data: state, isLoading } = useQuery({
    queryKey: ["family-summary", familyId],
    queryFn: () => api<FamilySummaryOut>(`/api/families/${familyId}/summary`),
  });
  const generate = useMutation({
    mutationFn: () => api<FamilySummaryOut>(`/api/families/${familyId}/summary`, { method: "POST" }),
    onSuccess: (next) => queryClient.setQueryData(["family-summary", familyId], next),
  });

  // Sin resumen, o con reuniones nuevas: se arma solo, una vez por visita.
  const tried = useRef<string | null>(null);
  useEffect(() => {
    if (!state || !canGenerate || !state.ai_configured) return;
    if (state.status !== "none" && state.status !== "stale") return;
    const key = `${familyId}:${state.meetings_available}`;
    if (tried.current === key) return;
    tried.current = key;
    generate.mutate();
  }, [state, canGenerate, familyId, generate]);

  const summary = state?.summary;
  const busy = generate.isPending;

  let note: ReactNode = null;
  if (state && summary) {
    note = (
      <>
        Con {state.meetings_used} {state.meetings_used === 1 ? "reunión" : "reuniones"}
        {state.generated_at && ` · ${ago(state.generated_at)}`}
        {state.status === "stale" &&
          ` · hay ${state.new_meetings} ${state.new_meetings === 1 ? "reunión nueva" : "reuniones nuevas"}`}
        {state.status === "outdated" && " · cambió un acta o una tarea desde entonces"}
      </>
    );
  }

  return (
    <Section
      title="Resumen de Echo"
      action={
        state && state.status !== "empty" && state.ai_configured && canGenerate ? (
          <Button variant="soft" className="min-h-8 px-3 py-1 text-xs" onClick={() => generate.mutate()} disabled={busy}>
            {busy ? <Spinner /> : summary ? "Actualizar" : "Generar"}
          </Button>
        ) : null
      }
    >
      {isLoading ? (
        <div className="flex justify-center py-6 text-ink-300">
          <Spinner className="h-5 w-5" />
        </div>
      ) : !state || state.status === "empty" ? (
        <p className="text-sm text-ink-500">
          Cuando haya reuniones de la familia con resumen o acta, Echo arma acá qué se viene trabajando, los
          acuerdos y lo que quedó pendiente.
        </p>
      ) : !summary ? (
        busy ? (
          <p className="flex items-center gap-2 text-sm text-ink-500">
            <Spinner /> Leyendo {state.meetings_available}{" "}
            {state.meetings_available === 1 ? "reunión" : "reuniones"} para armar el resumen…
          </p>
        ) : !state.ai_configured ? (
          <p className="text-sm text-ink-500">Para el resumen hace falta un modelo de IA (Ajustes → IA).</p>
        ) : (
          <p className="text-sm text-ink-500">
            Todavía no hay resumen de esta familia.
            {!canGenerate && " Lo puede generar cualquiera del equipo con permiso de edición."}
          </p>
        )
      ) : (
        <div className={`space-y-4 transition-opacity ${busy ? "opacity-60" : ""}`}>
          {summary.overview && <p className="text-[15px] leading-relaxed text-ink-800">{summary.overview}</p>}
          <div className="grid gap-4 md:grid-cols-2">
            <SummaryList title="Qué se viene trabajando" items={summary.working_on} />
            <SummaryList title="Acuerdos" items={summary.agreements} tone="text-emerald-500" />
            <SummaryList title="Pendientes" items={summary.pending} tone="text-amber-500" />
            <SummaryList title="Para tener en cuenta" items={summary.alerts} tone="text-red-500" />
          </div>
          <p className="text-xs text-ink-400">
            {busy ? "Actualizando…" : note} · Armado con las reuniones que ves vos.
          </p>
        </div>
      )}
      <ErrorText error={generate.error} />
    </Section>
  );
}

// ── Hijos ────────────────────────────────────────────────────────

function ChildRow({ familyId, child }: { familyId: string; child: FamilyMemberOut }) {
  const invalidate = useFamilyInvalidate(familyId);
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(child.name);
  const [curso, setCurso] = useState(child.curso ?? "");

  const save = useMutation({
    mutationFn: (changes: Partial<FamilyMemberOut>) =>
      api<FamilyMemberOut>(`/api/families/members/${child.id}`, { method: "PATCH", body: memberBody(child, changes) }),
    onMutate: (changes) => {
      // El nivel cambia al toque; si falla, vuelve.
      queryClient.setQueryData<FamilyDetailOut>(["family", familyId], (current) =>
        current && {
          ...current,
          members: current.members.map((member) => (member.id === child.id ? { ...member, ...changes } : member)),
        },
      );
    },
    onSuccess: () => setEditing(false),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/families/members/${child.id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  if (editing) {
    return (
      <li className="rounded-2xl border border-ink-100 p-3">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (name.trim()) save.mutate({ name: name.trim(), curso: curso.trim() || null });
          }}
        >
          <div className="min-w-[180px] flex-1">
            <Input label="Nombre y apellido" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="w-28">
            <Input label="Curso" placeholder="3N EP" value={curso} onChange={(event) => setCurso(event.target.value)} />
          </div>
          <Button type="submit" variant="soft" disabled={save.isPending}>
            {save.isPending ? <Spinner /> : "Guardar"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
            Cancelar
          </Button>
        </form>
        <ErrorText error={save.error} />
      </li>
    );
  }

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-ink-100 p-3">
      <div className="min-w-[11rem] flex-1">
        <p className="break-words text-[15px] font-medium text-ink-900">{child.name}</p>
        <p className="text-xs text-ink-500">{child.curso ? `Curso ${child.curso}` : "Sin curso"}</p>
      </div>
      <LevelPicker
        label={`Nivel de ${child.name}`}
        value={child.level}
        onChange={(level) => save.mutate({ level })}
        disabled={save.isPending}
      />
      <div className="ml-auto flex items-center gap-3">
        <button
          type="button"
          onClick={() => {
            setName(child.name);
            setCurso(child.curso ?? "");
            setEditing(true);
          }}
          className="text-xs text-ink-500 hover:text-ink-900"
        >
          Editar
        </button>
        <ConfirmRemove label={child.name.split(" ")[0]} onConfirm={() => remove.mutate()} busy={remove.isPending} />
      </div>
      {save.isError && (
        <div className="w-full">
          <ErrorText error={save.error} />
        </div>
      )}
    </li>
  );
}

function ChildrenSection({ family }: { family: FamilyDetailOut }) {
  const invalidate = useFamilyInvalidate(family.id);
  const children = family.members.filter((member) => member.relationship_type === "estudiante");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [curso, setCurso] = useState("");
  const [level, setLevel] = useState<Level | null>(null);

  const add = useMutation({
    mutationFn: () =>
      api<FamilyMemberOut>(`/api/families/${family.id}/members`, {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          relationship_type: "estudiante",
          is_guardian: false,
          curso: curso.trim() || null,
          level,
        }),
      }),
    onSuccess: () => {
      setName("");
      setCurso("");
      setAdding(false);
      invalidate();
    },
  });

  return (
    <Section
      title={`Hijos${children.length ? ` (${children.length})` : ""}`}
      action={
        !adding && (
          <Button variant="soft" className="min-h-8 px-3 py-1 text-xs" onClick={() => setAdding(true)}>
            Agregar hijo
          </Button>
        )
      }
    >
      {children.length === 0 && !adding && (
        <p className="text-sm text-ink-500">
          Sin hijos cargados. Agregalos con su curso y nivel: cada reunión dice de qué hijo es, y eso va al acta.
        </p>
      )}
      {children.length > 0 && (
        <ul className="space-y-2">
          {children.map((child) => (
            <ChildRow key={child.id} familyId={family.id} child={child} />
          ))}
        </ul>
      )}
      {adding && (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (name.trim()) add.mutate();
          }}
          className="space-y-3 rounded-2xl bg-ink-50/70 p-3"
        >
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[180px] flex-1">
              <Input
                label="Nombre y apellido"
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="w-28">
              <Input label="Curso" placeholder="3N EP" value={curso} onChange={(event) => setCurso(event.target.value)} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink-700">Nivel</span>
            <LevelPicker value={level} onChange={setLevel} />
          </div>
          <ErrorText error={add.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setAdding(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={add.isPending || !name.trim()}>
              {add.isPending ? <Spinner /> : "Agregar"}
            </Button>
          </div>
        </form>
      )}
    </Section>
  );
}

// ── Responsables ─────────────────────────────────────────────────

interface GuardianForm {
  name: string;
  relationship_type: Relationship;
  email: string;
  phone: string;
  is_guardian: boolean;
}

const EMPTY_GUARDIAN: GuardianForm = { name: "", relationship_type: "madre", email: "", phone: "", is_guardian: true };

function GuardianFields({ form, onChange }: { form: GuardianForm; onChange: (next: GuardianForm) => void }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[180px] flex-1">
          <Input
            label="Nombre y apellido"
            value={form.name}
            onChange={(event) => onChange({ ...form, name: event.target.value })}
          />
        </div>
        <Select
          label="Vínculo"
          value={form.relationship_type}
          onChange={(next) => onChange({ ...form, relationship_type: next as Relationship })}
          options={GUARDIAN_RELATIONSHIPS}
          className="w-36"
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Input
          label="Email"
          type="email"
          value={form.email}
          onChange={(event) => onChange({ ...form, email: event.target.value })}
        />
        <Input
          label="Teléfono"
          type="tel"
          value={form.phone}
          onChange={(event) => onChange({ ...form, phone: event.target.value })}
        />
      </div>
      <label className="flex items-start gap-2 text-sm text-ink-700">
        <input
          type="checkbox"
          checked={form.is_guardian}
          onChange={(event) => onChange({ ...form, is_guardian: event.target.checked })}
          className="mt-0.5 h-4 w-4 rounded border-ink-300"
        />
        <span>
          Es responsable
          <span className="block text-xs text-ink-400">Cuenta para «¿vinieron todos los responsables?»</span>
        </span>
      </label>
    </div>
  );
}

function GuardianRow({ familyId, member }: { familyId: string; member: FamilyMemberOut }) {
  const invalidate = useFamilyInvalidate(familyId);
  const [form, setForm] = useState<GuardianForm | null>(null);
  const save = useMutation({
    mutationFn: (next: GuardianForm) =>
      api(`/api/families/members/${member.id}`, {
        method: "PATCH",
        body: memberBody(member, { ...next, email: next.email || null, phone: next.phone || null }),
      }),
    onSuccess: () => {
      setForm(null);
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/families/members/${member.id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  if (form) {
    return (
      <li className="rounded-2xl border border-ink-100 p-3">
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (form.name.trim()) save.mutate(form);
          }}
          className="space-y-3"
        >
          <GuardianFields form={form} onChange={setForm} />
          <ErrorText error={save.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button type="submit" variant="soft" disabled={save.isPending}>
              {save.isPending ? <Spinner /> : "Guardar"}
            </Button>
          </div>
        </form>
      </li>
    );
  }

  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-2xl border border-ink-100 p-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="break-words text-[15px] font-medium text-ink-900">{member.name}</span>
          <Badge tone={member.is_guardian ? "indigo" : "gray"}>
            {RELATIONSHIP_LABEL[member.relationship_type] ?? member.relationship_type}
          </Badge>
          {!member.is_guardian && <span className="text-xs text-ink-400">no cuenta para la asistencia</span>}
        </div>
        {(member.email || member.phone) && (
          <p className="flex flex-wrap gap-x-3 text-sm">
            {member.email && (
              <a href={`mailto:${member.email}`} className="break-all text-accent-600 hover:underline">
                {member.email}
              </a>
            )}
            {member.phone && (
              <a href={`tel:${member.phone.replace(/[^\d+]/g, "")}`} className="text-accent-600 hover:underline">
                {member.phone}
              </a>
            )}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() =>
            setForm({
              name: member.name,
              relationship_type: member.relationship_type,
              email: member.email ?? "",
              phone: member.phone ?? "",
              is_guardian: member.is_guardian,
            })
          }
          className="text-xs text-ink-500 hover:text-ink-900"
        >
          Editar
        </button>
        <ConfirmRemove label={member.name.split(" ")[0]} onConfirm={() => remove.mutate()} busy={remove.isPending} />
      </div>
    </li>
  );
}

function GuardiansSection({ family }: { family: FamilyDetailOut }) {
  const invalidate = useFamilyInvalidate(family.id);
  const adults = family.members.filter((member) => member.relationship_type !== "estudiante");
  const [form, setForm] = useState<GuardianForm | null>(null);
  const add = useMutation({
    mutationFn: (next: GuardianForm) =>
      api(`/api/families/${family.id}/members`, {
        method: "POST",
        body: JSON.stringify({ ...next, name: next.name.trim(), email: next.email || null, phone: next.phone || null }),
      }),
    onSuccess: () => {
      setForm(null);
      invalidate();
    },
  });

  return (
    <Section
      title="Responsables"
      action={
        !form && (
          <Button variant="soft" className="min-h-8 px-3 py-1 text-xs" onClick={() => setForm(EMPTY_GUARDIAN)}>
            Agregar
          </Button>
        )
      }
    >
      {adults.length === 0 && !form && (
        <p className="text-sm text-ink-500">
          Cargá al menos a los responsables: son contra quienes se mide si vinieron todos.
        </p>
      )}
      {adults.length > 0 && (
        <ul className="space-y-2">
          {adults.map((member) => (
            <GuardianRow key={member.id} familyId={family.id} member={member} />
          ))}
        </ul>
      )}
      {form && (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (form.name.trim()) add.mutate(form);
          }}
          className="space-y-3 rounded-2xl bg-ink-50/70 p-3"
        >
          <GuardianFields form={form} onChange={setForm} />
          <ErrorText error={add.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={add.isPending || !form.name.trim()}>
              {add.isPending ? <Spinner /> : "Agregar"}
            </Button>
          </div>
        </form>
      )}
    </Section>
  );
}

// ── Tareas abiertas ──────────────────────────────────────────────

const TASK_STATUS: Record<FamilyTaskOut["status"], { label: string; tone: "amber" | "gray" | "sky" }> = {
  suggested: { label: "A confirmar", tone: "amber" },
  pending: { label: "Pendiente", tone: "gray" },
  in_progress: { label: "En curso", tone: "sky" },
};

function TasksSection({ tasks }: { tasks: FamilyTaskOut[] }) {
  return (
    <Section
      title={`Tareas abiertas${tasks.length ? ` (${tasks.length})` : ""}`}
      action={
        tasks.length > 0 && (
          <Link to="/tasks" className="text-xs font-medium text-accent-600 hover:underline">
            Ver todas las tareas
          </Link>
        )
      }
    >
      {tasks.length === 0 ? (
        <p className="text-sm text-ink-500">No quedó nada abierto en las reuniones de la familia.</p>
      ) : (
        <ul className="divide-y divide-ink-100">
          {tasks.map((task) => (
            <li key={task.id} className="py-2.5 first:pt-0 last:pb-0">
              <p className="break-words text-sm text-ink-800">{task.text}</p>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-500">
                <Badge tone={TASK_STATUS[task.status].tone}>{TASK_STATUS[task.status].label}</Badge>
                {task.assignee && <span>{task.assignee}</span>}
                {(task.due_date || task.due_text) && (
                  <span className={task.overdue ? "font-medium text-red-600" : ""}>
                    {task.overdue ? "Venció " : "Vence "}
                    {task.due_date ? shortDate(`${task.due_date}T00:00:00`) : task.due_text}
                  </span>
                )}
                <Link to={`/meetings/${task.meeting_id}`} className="text-accent-600 hover:underline">
                  {task.meeting_title} · {shortDate(task.meeting_date)}
                </Link>
              </p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ── Datos, asignadas, profesionales, historial ───────────────────

function DataSection({ family }: { family: FamilyDetailOut }) {
  const invalidate = useFamilyInvalidate(family.id);
  const [form, setForm] = useState<{ name: string; reference: string; notes: string; drive_url: string } | null>(null);
  const save = useMutation({
    mutationFn: (next: NonNullable<typeof form>) =>
      api(`/api/families/${family.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: next.name.trim(),
          reference: next.reference.trim() || null,
          notes: next.notes.trim() || null,
          drive_url: next.drive_url.trim() || null,
        }),
      }),
    onSuccess: () => {
      setForm(null);
      invalidate();
    },
  });

  if (form) {
    return (
      <Section title="Datos de la familia">
        <form
          className="space-y-3"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (form.name.trim()) save.mutate(form);
          }}
        >
          <Input label="Nombre" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          <Input
            label="Legajo o matrícula"
            value={form.reference}
            onChange={(event) => setForm({ ...form, reference: event.target.value })}
          />
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Notas</span>
            <textarea
              rows={4}
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
              placeholder="Hermanos en otras sedes, acuerdos de comunicación, lo que conviene saber antes de una reunión…"
              className={textareaClass}
            />
          </label>
          <Input
            label="Carpeta de Drive"
            placeholder="https://drive.google.com/drive/folders/…"
            value={form.drive_url}
            onChange={(event) => setForm({ ...form, drive_url: event.target.value })}
          />
          <p className="text-xs text-ink-400">
            Echo guarda el enlace, no el contenido: los informes siguen viviendo en tu Drive. El enlace aparece en
            cada reunión de esta familia.
          </p>
          <ErrorText error={save.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setForm(null)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <Spinner /> : "Guardar"}
            </Button>
          </div>
        </form>
      </Section>
    );
  }

  return (
    <Section
      title="Datos de la familia"
      action={
        <button
          type="button"
          onClick={() =>
            setForm({
              name: family.name,
              reference: family.reference ?? "",
              notes: family.notes ?? "",
              drive_url: family.drive_url ?? "",
            })
          }
          className="text-xs font-medium text-accent-600 hover:underline"
        >
          Editar
        </button>
      }
    >
      <dl className="space-y-3 text-sm">
        <div>
          <dt className="text-xs text-ink-400">Legajo</dt>
          <dd className="text-ink-800">{family.reference || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-400">Carpeta de Drive</dt>
          <dd>
            {family.drive_url ? (
              <a
                href={family.drive_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-accent-600 hover:underline"
              >
                Abrir carpeta ↗
              </a>
            ) : (
              <span className="text-ink-500">Sin carpeta</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-400">Notas</dt>
          <dd className="whitespace-pre-wrap break-words text-ink-800">{family.notes || "—"}</dd>
        </div>
      </dl>
    </Section>
  );
}

/**
 * Personas de la sede asignadas a la familia: ven todas sus reuniones (menos
 * las privadas). Las asignan los directivos; el resto solo ve quiénes son.
 */
function AssigneesSection({ family }: { family: FamilyDetailOut }) {
  const invalidate = useFamilyInvalidate(family.id);
  const { data: access } = useMyAccess();
  const canAssign = (access?.rank ?? 1) >= 2;
  const save = useMutation({
    mutationFn: (ids: string[]) =>
      api(`/api/families/${family.id}/assignees`, { method: "PUT", body: JSON.stringify({ user_ids: ids }) }),
    onSuccess: invalidate,
  });

  return (
    <Section title="La siguen">
      {canAssign ? (
        <div>
          <PeoplePicker
            label="Asignadas a la familia"
            hint="Ven todas las reuniones de la familia, aunque no hayan estado (menos las privadas)."
            value={family.assignees.map((assignee) => assignee.user_id)}
            onChange={(next) => save.mutate(next)}
          />
          {save.isPending && <p className="mt-1 text-xs text-ink-400">Guardando…</p>}
          <ErrorText error={save.error} />
        </div>
      ) : (
        <p className="text-sm text-ink-600">
          {family.assignees.length
            ? family.assignees.map((assignee) => assignee.name).join(", ")
            : "Nadie todavía. Las asigna un directivo."}
        </p>
      )}
    </Section>
  );
}

function ProfessionalsSection({ family }: { family: FamilyDetailOut }) {
  const invalidate = useFamilyInvalidate(family.id);
  const [linking, setLinking] = useState("");
  const { data: professionals } = useQuery({
    queryKey: ["professionals"],
    queryFn: () => api<ProfessionalOut[]>("/api/professionals"),
  });
  const link = useMutation({
    mutationFn: (professionalId: string) =>
      api(`/api/families/${family.id}/professionals/${professionalId}`, { method: "PUT" }),
    onSuccess: () => {
      setLinking("");
      invalidate();
    },
  });
  const unlink = useMutation({
    mutationFn: (professionalId: string) =>
      api(`/api/families/${family.id}/professionals/${professionalId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
  const linked = new Set(family.professionals.map((pro) => pro.id));
  const available = (professionals ?? []).filter((pro) => !linked.has(pro.id));

  return (
    <Section title="Profesionales">
      {family.professionals.length === 0 ? (
        <p className="text-sm text-ink-500">Ninguno asociado todavía.</p>
      ) : (
        <ul className="space-y-2">
          {family.professionals.map((pro) => (
            <li key={pro.id} className="text-sm">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="break-words font-medium text-ink-900">{pro.name}</p>
                  <p className="text-xs text-ink-500">
                    {[pro.role_label, pro.affiliation].filter(Boolean).join(" · ") || "Sin rol cargado"}
                  </p>
                  {(pro.email || pro.phone) && (
                    <p className="flex flex-wrap gap-x-2 text-xs">
                      {pro.email && (
                        <a href={`mailto:${pro.email}`} className="break-all text-accent-600 hover:underline">
                          {pro.email}
                        </a>
                      )}
                      {pro.phone && <span className="text-ink-500">{pro.phone}</span>}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => unlink.mutate(pro.id)}
                  className="shrink-0 text-xs text-ink-400 hover:text-red-600"
                >
                  Desasociar
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {available.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            ariaLabel="Profesional"
            size="sm"
            value={linking}
            onChange={setLinking}
            options={available.map((pro) => ({ value: pro.id, label: pro.name, hint: pro.role_label ?? undefined }))}
            placeholder="Asociar profesional…"
            searchPlaceholder="Buscar profesional…"
            className="min-w-0 flex-1"
          />
          <Button
            variant="soft"
            className="min-h-8 px-3 py-1 text-xs"
            onClick={() => linking && link.mutate(linking)}
            disabled={!linking || link.isPending}
          >
            Asociar
          </Button>
        </div>
      )}
      <p className="text-xs text-ink-400">
        Los profesionales se cargan en <Link to="/families?tab=profesionales" className="text-accent-600 hover:underline">Familias → Profesionales</Link>.
      </p>
    </Section>
  );
}

const FIELD_LABEL: Record<string, string> = {
  name: "nombre",
  reference: "legajo",
  notes: "notas",
  drive_url: "carpeta de Drive",
  relationship_type: "vínculo",
  is_guardian: "responsable",
  email: "email",
  phone: "teléfono",
  curso: "curso",
  level: "nivel",
};

function historyText(entry: FamilyDetailOut["history"][number]): string {
  const detail = (entry.detail ?? {}) as { name?: string; fields?: string[]; level?: string | null };
  const fields = (detail.fields ?? []).map((field) => FIELD_LABEL[field] ?? field).join(", ");
  switch (entry.action) {
    case "family.create":
      return "Creó la familia";
    case "family.update":
      return fields ? `Editó ${fields}` : "Editó los datos";
    case "family.member_add":
      return `Agregó a ${detail.name ?? "un integrante"}`;
    case "family.member_update":
      if (detail.fields?.length === 1 && detail.fields[0] === "level") {
        return detail.level
          ? `Pasó a ${detail.name} a ${LEVEL_LABEL[detail.level] ?? detail.level}`
          : `Sacó el nivel de ${detail.name}`;
      }
      return `Editó a ${detail.name ?? "un integrante"}${fields ? ` (${fields})` : ""}`;
    case "family.member_remove":
      return `Sacó a ${detail.name ?? "un integrante"}`;
    case "family.assignees":
      return "Cambió quiénes la siguen";
    case "family.professional_link":
      return `Asoció a ${detail.name ?? "un profesional"}`;
    case "family.professional_unlink":
      return `Desasoció a ${detail.name ?? "un profesional"}`;
    default:
      return entry.action;
  }
}

function HistorySection({ family }: { family: FamilyDetailOut }) {
  const [all, setAll] = useState(false);
  const shown = all ? family.history : family.history.slice(0, 6);
  return (
    <Section title="Historial">
      {family.history.length === 0 ? (
        <p className="text-sm text-ink-500">Sin cambios registrados.</p>
      ) : (
        <ol className="space-y-2.5">
          {shown.map((entry, index) => (
            <li key={index} className="flex gap-2.5 text-sm">
              <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-300" />
              <div className="min-w-0">
                <p className="break-words text-ink-800">{historyText(entry)}</p>
                <p className="text-xs text-ink-400">
                  {entry.actor ?? "Echo"} · {ago(entry.at)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
      {family.history.length > 6 && (
        <button type="button" onClick={() => setAll(!all)} className="text-xs font-medium text-accent-600 hover:underline">
          {all ? "Ver menos" : `Ver los ${family.history.length} cambios`}
        </button>
      )}
    </Section>
  );
}

function RemoveFamily({ family }: { family: FamilyDetailOut }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const remove = useMutation({
    mutationFn: () => api(`/api/families/${family.id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["families"] });
      navigate("/families", { replace: true });
    },
  });
  return (
    <div className="px-1 text-xs text-ink-400">
      {asking ? (
        <span className="flex flex-wrap items-center gap-2">
          ¿Dar de baja a {family.name}? Sus reuniones quedan como están.
          <button type="button" onClick={() => remove.mutate()} className="font-medium text-red-600 hover:underline">
            Dar de baja
          </button>
          <button type="button" onClick={() => setAsking(false)} className="hover:underline">
            Cancelar
          </button>
        </span>
      ) : (
        <button type="button" onClick={() => setAsking(true)} className="hover:text-red-600">
          Dar de baja la familia
        </button>
      )}
      <ErrorText error={remove.error} />
    </div>
  );
}

// ── Página ───────────────────────────────────────────────────────

export default function FamilyDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const location = useLocation();
  const { activeOrg } = useAuth();
  const [creating, setCreating] = useState(false);
  const { data: family, isLoading, isError, error } = useQuery({
    queryKey: ["family", id],
    queryFn: () => api<FamilyDetailOut>(`/api/families/${id}`),
    enabled: !!id,
  });

  // Volver a la lista con el filtro y la búsqueda con los que se entró.
  const back = `/families${(location.state as { search?: string } | null)?.search ?? ""}`;
  const role = activeOrg?.role ?? "";
  const canEdit = role !== "viewer";
  const isAdmin = role === "owner" || role === "admin";

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center py-20 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (isError || !family) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <Card>
          <EmptyState title="No encontramos esta familia" mood="idle">
            <p className="mb-4">{error instanceof Error ? error.message : "Puede que la hayan dado de baja."}</p>
            <Link to="/families" className="font-medium text-accent-600 hover:underline">
              Volver a Familias
            </Link>
          </EmptyState>
        </Card>
      </div>
    );
  }

  const children = family.members.filter((member) => member.relationship_type === "estudiante");
  const levels = [...new Set(children.map((child) => child.level).filter(Boolean))] as Level[];
  const guardians = family.members.filter((member) => member.is_guardian);

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6 sm:py-10">
      <header className="space-y-3">
        <Link to={back} className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-ink-900">
          <span aria-hidden>←</span> Familias
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-semibold tracking-tight text-ink-900">{family.name}</h1>
            <p className="mt-1 text-sm text-ink-500">
              {family.reference && <>Legajo {family.reference} · </>}
              {children.length} {children.length === 1 ? "hijo" : "hijos"} · {guardians.length}{" "}
              {guardians.length === 1 ? "responsable" : "responsables"} · {family.meetings}{" "}
              {family.meetings === 1 ? "reunión" : "reuniones"}
            </p>
            {levels.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {levels.map((level) => (
                  <LevelBadge key={level} level={level} />
                ))}
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {family.drive_url && (
              <a
                href={family.drive_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-10 items-center rounded-full bg-ink-100 px-4 text-sm font-medium text-ink-800 hover:bg-ink-200"
              >
                Carpeta de Drive ↗
              </a>
            )}
            {canEdit && <Button onClick={() => setCreating(true)}>Nueva reunión</Button>}
          </div>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <FamilySummary familyId={family.id} canGenerate={canEdit} />
          <ChildrenSection family={family} />
          <GuardiansSection family={family} />
          <TasksSection tasks={family.open_tasks} />
          <Section title={`Reuniones${family.meetings ? ` (${family.meetings})` : ""}`}>
            <FamilyMeetings familyId={family.id} students={children} />
          </Section>
        </div>
        <aside className="min-w-0 space-y-5">
          <DataSection family={family} />
          <AssigneesSection family={family} />
          <ProfessionalsSection family={family} />
          <HistorySection family={family} />
          {isAdmin && <RemoveFamily family={family} />}
        </aside>
      </div>

      <NewMeetingModal open={creating} onClose={() => setCreating(false)} initialFamily={family.id} />
    </div>
  );
}
