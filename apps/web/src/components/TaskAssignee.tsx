import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { TaskOut } from "../api/types";
import { matchesSuggestion } from "../lib/assignee";
import { useSedePeople } from "./PeoplePicker";
import { Select, type SelectOption } from "./Select";
import { ChoiceCards } from "./SettingRows";
import { Button, Input, Modal, Spinner } from "./ui";

const ROLE_LABEL: Record<string, string> = {
  owner: "Dueño",
  admin: "Administra",
  member: "Miembro",
  viewer: "Solo lectura",
};

type Scope = "task" | "acta" | "meeting";

interface ExternalAccess {
  id: string;
  email: string;
  name: string | null;
  scope: Scope;
  mail_sent: boolean;
  last_seen_at: string | null;
  link: string | null;
}

const SCOPE_SHORT: Record<Scope, string> = { task: "solo la tarea", acta: "tarea y acta", meeting: "toda la reunión" };

/**
 * Quién se encarga de una tarea. Las que detecta Echo van a quien grabó la
 * reunión, que desde acá las reparte entre las personas de la sede: solo a
 * las de su mismo rol o de uno menor (un DOE no le asigna tareas a la
 * directora). También se le puede asignar a alguien de afuera de Echo, por
 * mail, eligiendo qué ve (routers/external.py).
 */
export function TaskAssignee({
  task,
  onAssigned,
  className = "w-48",
  inMeeting,
}: {
  task: Pick<TaskOut, "id" | "assignee_name" | "assignee_user_id" | "suggested_assignee" | "assignee_email"> & {
    meeting_id?: string | null;
  };
  onAssigned: () => void;
  className?: string;
  /** La tarea es de una reunión: se puede compartir el acta o la reunión. */
  inMeeting?: boolean;
}) {
  const { data: people } = useSedePeople();
  const [external, setExternal] = useState<string | null>(null);
  const assign = useMutation({
    mutationFn: (userId: string) =>
      api(`/api/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify({ assignee_user_id: userId }) }),
    onSuccess: onAssigned,
  });

  const assignable = (people ?? []).filter((person) => person.assignable);
  const suggested = assignable.filter((person) => matchesSuggestion(person, task.suggested_assignee));
  const rest = assignable.filter((person) => !suggested.includes(person));
  const options: SelectOption[] = [...suggested, ...rest].map((person) => {
    const role = person.job_title || person.rank_label || ROLE_LABEL[person.role] || person.role;
    return { value: person.id, label: person.name, hint: suggested.includes(person) ? `${role} · sugerida` : role };
  });

  return (
    <div className="min-w-0">
      <Select
        size="sm"
        ariaLabel="Responsable"
        value={task.assignee_user_id ?? ""}
        placeholder={task.assignee_name ?? task.assignee_email ?? "Sin asignar"}
        options={options}
        searchable
        searchPlaceholder="Buscar persona o rol"
        onChange={(userId) => assign.mutate(userId)}
        action={{ label: "Alguien de afuera, por mail", onClick: (query) => setExternal(query) }}
        disabled={assign.isPending}
        className={className}
      />
      {task.suggested_assignee && (
        <p className="mt-1 truncate text-[11px] text-ink-400" title={task.suggested_assignee}>
          En la reunión: {task.suggested_assignee}
        </p>
      )}
      {task.assignee_email && <ExternalAccessLine taskId={task.id} />}
      {assign.isError && (
        <p className="mt-1 text-[11px] text-red-600">
          {assign.error instanceof Error ? assign.error.message : "No se pudo asignar"}
        </p>
      )}
      <ExternalAssignModal
        open={external !== null}
        initial={external ?? ""}
        taskId={task.id}
        inMeeting={inMeeting ?? !!task.meeting_id}
        onClose={() => setExternal(null)}
        onAssigned={onAssigned}
      />
    </div>
  );
}

/** "Por mail a x · ve: tarea y acta · Quitar acceso". */
function ExternalAccessLine({ taskId }: { taskId: string }) {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["task-external", taskId],
    queryFn: () => api<ExternalAccess[]>(`/api/tasks/${taskId}/external`),
    staleTime: 30_000,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api/external-access/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task-external", taskId] }),
  });
  if (!data?.length) return null;
  return (
    <>
      {data.map((access) => (
        <p key={access.id} className="mt-1 text-[11px] text-ink-400">
          Por mail · ve {SCOPE_SHORT[access.scope]}
          {access.last_seen_at ? " · ya lo abrió" : ""} ·{" "}
          <button
            type="button"
            onClick={() => revoke.mutate(access.id)}
            disabled={revoke.isPending}
            className="font-medium text-ink-600 underline-offset-2 hover:underline"
          >
            Quitar acceso
          </button>
        </p>
      ))}
    </>
  );
}

function ExternalAssignModal({
  open,
  initial,
  taskId,
  inMeeting,
  onClose,
  onAssigned,
}: {
  open: boolean;
  initial: string;
  taskId: string;
  inMeeting: boolean;
  onClose: () => void;
  onAssigned: () => void;
}) {
  const queryClient = useQueryClient();
  const looksLikeMail = initial.includes("@");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [scope, setScope] = useState<Scope>("task");
  const [done, setDone] = useState<ExternalAccess | null>(null);
  const [copied, setCopied] = useState(false);
  const [lastInitial, setLastInitial] = useState("");
  // Lo que se venía buscando en el desplegable arranca escrito.
  if (open && initial !== lastInitial) {
    setLastInitial(initial);
    setEmail(looksLikeMail ? initial : "");
    setName(looksLikeMail ? "" : initial);
  }

  const send = useMutation({
    mutationFn: () =>
      api<ExternalAccess>(`/api/tasks/${taskId}/external`, {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), name: name.trim() || null, scope }),
      }),
    onSuccess: (access) => {
      setDone(access);
      queryClient.invalidateQueries({ queryKey: ["task-external", taskId] });
      onAssigned();
    },
  });

  const close = () => {
    setDone(null);
    setCopied(false);
    setScope("task");
    setLastInitial("");
    send.reset();
    onClose();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (email.trim()) send.mutate();
  };

  return (
    <Modal open={open} onClose={close} title="Asignar a alguien de afuera">
      {done ? (
        <div className="space-y-4">
          {done.mail_sent ? (
            <p className="text-sm text-ink-700">
              Listo: le mandamos un mail a <strong className="font-medium">{done.email}</strong> con la tarea y su link
              personal. Cuando la marque como hecha, te llega el aviso.
            </p>
          ) : (
            <p className="text-sm text-ink-700">
              La tarea quedó asignada a <strong className="font-medium">{done.email}</strong>, pero el mail no salió.
              Mandale vos este link (es personal, no se puede volver a ver):
            </p>
          )}
          {!done.mail_sent && done.link && (
            <div className="flex flex-wrap items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-xl bg-ink-50 px-3 py-2 text-xs text-ink-700">{done.link}</code>
              <Button
                variant="soft"
                onClick={() => {
                  navigator.clipboard?.writeText(done.link ?? "").then(() => setCopied(true));
                }}
              >
                {copied ? "Copiado" : "Copiar"}
              </Button>
            </div>
          )}
          <div className="flex justify-end">
            <Button onClick={close}>Cerrar</Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <p className="text-sm text-ink-500">
            Para alguien que no usa Echo (una terapeuta, un docente de otra institución). Le llega un mail con la tarea y
            un link para verla y marcarla como hecha.
          </p>
          <Input
            label="Mail"
            type="email"
            required
            autoFocus
            placeholder="nombre@ejemplo.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Input label="Nombre (opcional)" placeholder="Laura Gómez" value={name} onChange={(event) => setName(event.target.value)} />
          <div>
            <span className="mb-1.5 block text-sm font-medium text-ink-700">¿Qué puede ver?</span>
            <ChoiceCards<Scope>
              ariaLabel="Qué puede ver"
              value={scope}
              onChange={setScope}
              options={[
                { value: "task", title: "Solo la tarea", hint: "Lo que tiene que hacer y para cuándo." },
                {
                  value: "acta",
                  title: "La tarea y el acta",
                  hint: inMeeting ? "Además, el acta de la reunión." : "Esta tarea no es de una reunión.",
                  disabled: !inMeeting,
                },
                {
                  value: "meeting",
                  title: "Toda la reunión",
                  hint: inMeeting ? "Resumen, acta y transcripción. Nunca el audio." : "Esta tarea no es de una reunión.",
                  disabled: !inMeeting,
                },
              ]}
            />
          </div>
          {send.isError && (
            <p className="text-sm text-red-600">{send.error instanceof Error ? send.error.message : "No se pudo asignar"}</p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={close}>
              Cancelar
            </Button>
            <Button type="submit" disabled={send.isPending || !email.trim()}>
              {send.isPending ? <Spinner /> : "Asignar y mandar mail"}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
