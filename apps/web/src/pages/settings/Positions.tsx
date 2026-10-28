import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Select } from "../../components/Select";
import { Badge, Button, Input, Modal } from "../../components/ui";
import { ErrorText } from "./parts";

export interface Position {
  id: string;
  label: string;
  description: string;
  /** Dirección de la sede ve todo: los niveles no le cambian nada. */
  needs_levels: boolean;
  /** Los propios de la sede: se editan y se borran; los fijos no. */
  custom: boolean;
  is_admin: boolean;
  access: string;
  group: string | null;
  watch_group_ids: string[];
  holders: number;
}

export interface Group {
  id: string;
  name: string;
}

export function Chip({
  active,
  disabled,
  title,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      title={title}
      onClick={onClick}
      className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "border-ink-900 bg-ink-900 text-white"
          : "border-ink-200 bg-white text-ink-600 hover:border-ink-300 hover:text-ink-900"
      }`}
    >
      {children}
    </button>
  );
}

/** Lo que pasa a ver alguien con este puesto, en una línea por permiso. */
export function permissionLines(position: Position, groups: Group[]): string[] {
  if (position.is_admin) return ["Ve todo y administra la sede, sus usuarios y ajustes."];
  const lines = [
    position.access === "total"
      ? "Ve todas las reuniones de sus niveles."
      : "Ve lo suyo, sus familias y donde estuvo.",
  ];
  const watched = groups.filter((group) => position.watch_group_ids.includes(group.id)).map((group) => group.name);
  if (watched.length) lines.push(`Ve también las reuniones de: ${watched.join(", ")}.`);
  if (position.group) lines.push(`Está en el grupo ${position.group}: ve sus reuniones internas.`);
  return lines;
}

interface Draft {
  name: string;
  description: string;
  is_admin: boolean;
  access: "total" | "limitado";
  group_id: string;
  watch_group_ids: string[];
}

const EMPTY: Draft = { name: "", description: "", is_admin: false, access: "limitado", group_id: "", watch_group_ids: [] };

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["org-users", "level-access", "members", "people", "my-access", "internal-groups"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

function Field({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-sm font-medium text-ink-700">{title}</p>
      {children}
      {hint && <p className="mt-1.5 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

function PositionForm({
  editing,
  groups,
  onClose,
}: {
  editing: Position | null;
  groups: Group[];
  onClose: () => void;
}) {
  const refresh = useRefresh();
  const [draft, setDraft] = useState<Draft>(
    editing
      ? {
          name: editing.label,
          description: editing.description,
          is_admin: editing.is_admin,
          access: editing.access === "total" ? "total" : "limitado",
          group_id: groups.find((group) => group.name === editing.group)?.id ?? "",
          watch_group_ids: editing.watch_group_ids,
        }
      : EMPTY,
  );
  const set = (change: Partial<Draft>) => setDraft((current) => ({ ...current, ...change }));

  const save = useMutation({
    mutationFn: () =>
      api<Position>(editing ? `/api/org/positions/${editing.id}` : "/api/org/positions", {
        method: editing ? "PUT" : "POST",
        body: JSON.stringify({ ...draft, group_id: draft.group_id || null }),
      }),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Input label="Nombre" placeholder="Adviser, Tutora…" value={draft.name} maxLength={60} onChange={(e) => set({ name: e.target.value })} autoFocus />
      <Input
        label="Descripción corta (opcional)"
        placeholder="Jefa de las coordinadoras del DOE"
        value={draft.description}
        maxLength={200}
        onChange={(e) => set({ description: e.target.value })}
      />

      <Field
        title="¿Administra la sede?"
        hint={draft.is_admin ? "Ve todo y administra la sede, sus usuarios y ajustes." : "No toca usuarios ni ajustes de la sede."}
      >
        <div className="flex flex-wrap gap-1.5">
          <Chip active={!draft.is_admin} onClick={() => set({ is_admin: false })}>
            No
          </Chip>
          <Chip active={draft.is_admin} onClick={() => set({ is_admin: true })}>
            Sí
          </Chip>
        </div>
      </Field>

      {!draft.is_admin && (
        <>
          <Field
            title="En sus niveles ve"
            hint={
              draft.access === "total"
                ? "Ve todas las reuniones (no privadas) de los niveles que se le elijan."
                : "Ve lo suyo, sus familias y donde estuvo."
            }
          >
            <div className="flex flex-wrap gap-1.5">
              <Chip active={draft.access === "limitado"} onClick={() => set({ access: "limitado" })}>
                Lo suyo
              </Chip>
              <Chip active={draft.access === "total"} onClick={() => set({ access: "total" })}>
                Todo el nivel
              </Chip>
            </div>
          </Field>

          <Field
            title="Ve también las reuniones de estos grupos"
            hint={
              groups.length
                ? "Las no privadas que creó, o donde estuvo, alguien de esos grupos."
                : "La sede todavía no tiene grupos: se arman en Reuniones internas."
            }
          >
            <div className="flex flex-wrap gap-1.5">
              {groups.map((group) => {
                const on = draft.watch_group_ids.includes(group.id);
                return (
                  <Chip
                    key={group.id}
                    active={on}
                    onClick={() =>
                      set({
                        watch_group_ids: on
                          ? draft.watch_group_ids.filter((id) => id !== group.id)
                          : [...draft.watch_group_ids, group.id],
                      })
                    }
                  >
                    {group.name}
                  </Chip>
                );
              })}
            </div>
          </Field>
        </>
      )}

      <Field title="Grupo interno (opcional)" hint="Lo suma a ese grupo: ve sus reuniones internas.">
        <Select
          ariaLabel="Grupo interno"
          value={draft.group_id}
          onChange={(value) => set({ group_id: value })}
          options={[{ value: "", label: "Ninguno" }, ...groups.map((group) => ({ value: group.id, label: group.name }))]}
        />
      </Field>

      {editing && editing.holders > 0 && (
        <p className="text-xs text-amber-700">
          {editing.holders === 1 ? "Lo tiene 1 persona" : `Lo tienen ${editing.holders} personas`}: los cambios se les aplican al guardar.
        </p>
      )}
      {save.isError && <ErrorText error={save.error} fallback="No se pudo guardar" />}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        <Button type="submit" disabled={!draft.name.trim() || save.isPending}>
          {editing ? "Guardar" : "Crear puesto"}
        </Button>
      </div>
    </form>
  );
}

function DeletePosition({ position, positions, onClose }: { position: Position; positions: Position[]; onClose: () => void }) {
  const refresh = useRefresh();
  const [moveTo, setMoveTo] = useState("");
  const remove = useMutation({
    mutationFn: () =>
      api<void>(
        `/api/org/positions/${position.id}${position.holders ? `?move_to=${encodeURIComponent(moveTo)}` : ""}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  return (
    <div className="space-y-4">
      {position.holders > 0 ? (
        <Field
          title={`${position.holders === 1 ? "Lo tiene 1 persona" : `Lo tienen ${position.holders} personas`}: ¿a qué puesto pasan?`}
          hint="Mantienen sus niveles y pasan a tener los permisos del puesto nuevo."
        >
          <Select
            ariaLabel="Puesto nuevo"
            value={moveTo}
            onChange={setMoveTo}
            placeholder="Elegir puesto…"
            options={positions.filter((item) => item.id !== position.id).map((item) => ({ value: item.id, label: item.label }))}
          />
        </Field>
      ) : (
        <p className="text-sm text-ink-600">Nadie lo tiene: se borra y listo.</p>
      )}
      {remove.isError && <ErrorText error={remove.error} fallback="No se pudo borrar" />}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancelar
        </Button>
        <Button variant="danger" disabled={remove.isPending || (position.holders > 0 && !moveTo)} onClick={() => remove.mutate()}>
          Borrar puesto
        </Button>
      </div>
    </div>
  );
}

/** Los puestos propios de la sede: se crean, se editan y se borran acá. */
export function CustomPositions({ positions, groups }: { positions: Position[]; groups: Group[] }) {
  const [editing, setEditing] = useState<Position | "new" | null>(null);
  const [deleting, setDeleting] = useState<Position | null>(null);
  const custom = positions.filter((item) => item.custom);

  return (
    <div className="mb-5 rounded-2xl border border-ink-100 p-3 sm:p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-ink-900">Puestos propios</p>
          <p className="text-xs text-ink-500">Además de los de siempre, armá los de tu sede con sus permisos.</p>
        </div>
        <Button variant="soft" className="shrink-0" onClick={() => setEditing("new")}>
          Nuevo puesto
        </Button>
      </div>
      {custom.length > 0 && (
        <ul className="mt-3 divide-y divide-ink-100">
          {custom.map((item) => (
            <li key={item.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink-900">
                  {item.label}
                  <Badge tone={item.is_admin ? "indigo" : "gray"}>
                    {item.holders === 1 ? "1 persona" : `${item.holders} personas`}
                  </Badge>
                </p>
                {item.description && <p className="text-xs text-ink-500">{item.description}</p>}
                <ul className="mt-1 space-y-0.5 text-xs text-ink-600">
                  {permissionLines(item, groups).map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                </ul>
              </div>
              <div className="flex shrink-0 gap-1">
                <Button variant="ghost" className="min-h-8 px-3" onClick={() => setEditing(item)}>
                  Editar
                </Button>
                <Button variant="ghost" className="min-h-8 px-3 text-red-600" onClick={() => setDeleting(item)}>
                  Borrar
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Nuevo puesto" : "Editar puesto"}>
        {editing !== null && (
          <PositionForm
            key={editing === "new" ? "new" : editing.id}
            editing={editing === "new" ? null : editing}
            groups={groups}
            onClose={() => setEditing(null)}
          />
        )}
      </Modal>
      <Modal open={deleting !== null} onClose={() => setDeleting(null)} title={`Borrar "${deleting?.label ?? ""}"`}>
        {deleting && <DeletePosition position={deleting} positions={positions} onClose={() => setDeleting(null)} />}
      </Modal>
    </div>
  );
}
