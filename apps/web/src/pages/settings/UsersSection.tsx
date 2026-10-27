import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { timeAgo } from "../../components/NotificationsPanel";
import { Select } from "../../components/Select";
import { Avatar, Badge, Input } from "../../components/ui";
import { useAuth } from "../../state/auth";
import { LEVEL_LABEL, type Level } from "../../state/access";
import { Block, ErrorText, Loading } from "./parts";

interface Position {
  id: string;
  label: string;
  description: string;
  /** Dirección de la sede ve todo: los niveles no le cambian nada. */
  needs_levels: boolean;
}

interface OrgUser {
  member_id: string;
  user_id: string;
  name: string;
  email: string;
  avatar_color: string;
  avatar_url: string | null;
  role: string;
  /** El que se eligió; null si nadie lo eligió todavía. */
  position: string | null;
  /** Lo que parece por sus permisos, mientras no se elija. */
  guessed_position: string | null;
  levels: Partial<Record<Level, string>>;
  groups: { id: string; name: string }[];
  last_seen_at: string | null;
  has_voice: boolean;
  is_owner: boolean;
}

interface OrgUsers {
  positions: Position[];
  levels: Level[];
  users: OrgUser[];
}

const NO_POSITION = "sin";

function Chip({
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

/** Puesto y niveles de una persona: cada clic se guarda solo, en cuanto queda completo. */
function UserEditor({
  user,
  positions,
  levels,
  isMe,
}: {
  user: OrgUser;
  positions: Position[];
  levels: Level[];
  isMe: boolean;
}) {
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const [position, setPosition] = useState(user.position ?? user.guessed_position);
  const [chosen, setChosen] = useState<Level[]>(levels.filter((level) => user.levels[level]));
  const current = positions.find((item) => item.id === position);

  const save = useMutation({
    mutationFn: (change: { position: string; levels: Level[] }) =>
      api<OrgUser>(`/api/org/users/${user.user_id}`, { method: "PUT", body: JSON.stringify(change) }),
    onSuccess: (saved) => {
      queryClient.setQueryData<OrgUsers>(["org-users", activeOrg?.id], (data) =>
        data ? { ...data, users: data.users.map((item) => (item.user_id === saved.user_id ? saved : item)) } : data,
      );
      // Lo que se arma con los mismos permisos en otras pantallas.
      for (const key of ["level-access", "members", "people", "my-access", "internal-groups"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: () => {
      setPosition(user.position ?? user.guessed_position);
      setChosen(levels.filter((level) => user.levels[level]));
    },
  });

  const apply = (nextPosition: string | null, nextLevels: Level[]) => {
    setPosition(nextPosition);
    setChosen(nextLevels);
    const meta = positions.find((item) => item.id === nextPosition);
    if (!meta || (meta.needs_levels && nextLevels.length === 0)) return;
    save.mutate({ position: meta.id, levels: nextLevels });
  };

  const missingLevel = current?.needs_levels && chosen.length === 0;

  return (
    <div className="mt-3 space-y-4 rounded-2xl bg-ink-50 p-3 sm:p-4">
      <div>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-400">Puesto</p>
        <div role="group" aria-label={`Puesto de ${user.name}`} className="flex flex-wrap gap-1.5">
          {positions.map((item) => (
            <Chip
              key={item.id}
              active={position === item.id}
              disabled={save.isPending || (user.is_owner && item.needs_levels)}
              title={user.is_owner && item.needs_levels ? "Creó la sede: sigue siendo Dirección de la sede" : item.description}
              onClick={() => position !== item.id && apply(item.id, chosen)}
            >
              {item.label}
            </Chip>
          ))}
        </div>
        {current && <p className="mt-2 text-xs text-ink-500">{current.description}</p>}
      </div>

      {current && !current.needs_levels ? (
        <p className="text-xs text-ink-500">Ve todos los niveles.</p>
      ) : (
        <div>
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-400">Niveles</p>
          <div role="group" aria-label={`Niveles de ${user.name}`} className="flex flex-wrap gap-1.5">
            {levels.map((level) => {
              const on = chosen.includes(level);
              return (
                <Chip
                  key={level}
                  active={on}
                  disabled={save.isPending}
                  onClick={() =>
                    apply(position, on ? chosen.filter((item) => item !== level) : levels.filter((item) => item === level || chosen.includes(item)))
                  }
                >
                  {LEVEL_LABEL[level]}
                </Chip>
              );
            })}
          </div>
          {missingLevel && <p className="mt-2 text-xs text-amber-700">Elegí al menos un nivel.</p>}
          {!current && <p className="mt-2 text-xs text-amber-700">Elegí el puesto.</p>}
        </div>
      )}

      {isMe && <p className="text-xs text-ink-400">Tus propios permisos podés bajarlos, no subirlos: eso lo hace otra persona que administre la sede.</p>}
      {save.isError && <ErrorText error={save.error} fallback="No se pudo guardar" />}
    </div>
  );
}

function UserRow({
  user,
  positions,
  levels,
  isMe,
  open,
  onToggle,
}: {
  user: OrgUser;
  positions: Position[];
  levels: Level[];
  isMe: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const label = (id: string | null) => positions.find((item) => item.id === id)?.label;
  const position = label(user.position);
  const guessed = !position ? label(user.guessed_position) : undefined;
  const levelNames = levels.filter((level) => user.levels[level]).map((level) => LEVEL_LABEL[level]);
  const admin = user.role === "owner" || user.role === "admin";

  return (
    <li className="py-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-3 rounded-xl text-left focus-visible:outline-2 focus-visible:outline-ink-900"
      >
        <Avatar name={user.name} color={user.avatar_color} src={user.avatar_url} size={36} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="truncate text-sm font-medium text-ink-900">
              {user.name}
              {isMe && <span className="font-normal text-ink-400"> (vos)</span>}
            </p>
            {position ? (
              <Badge tone={admin ? "indigo" : "gray"}>{position}</Badge>
            ) : (
              <span
                className="rounded-full border border-dashed border-amber-300 px-2 py-0.5 text-xs font-medium text-amber-700"
                title="Nadie le eligió el puesto todavía"
              >
                {guessed ? `¿${guessed}?` : "Sin puesto"}
              </span>
            )}
          </div>
          <p className="truncate text-xs text-ink-400">{user.email}</p>
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-500">
            <span>{admin ? "Todos los niveles" : levelNames.length ? levelNames.join(", ") : "Sin nivel"}</span>
            {user.groups.length > 0 && <span>Grupos: {user.groups.map((group) => group.name).join(", ")}</span>}
            <span>{user.last_seen_at ? `Entró ${timeAgo(user.last_seen_at)}` : "Nunca entró"}</span>
            <span className={user.has_voice ? "text-emerald-700" : "text-ink-400"}>
              {user.has_voice ? "Con Mi voz" : "Sin Mi voz"}
            </span>
          </p>
        </div>
        <span className="mt-1 shrink-0 text-xs font-medium text-ink-500">{open ? "Cerrar" : "Cambiar"}</span>
      </button>
      {open && <UserEditor user={user} positions={positions} levels={levels} isMe={isMe} />}
    </li>
  );
}

/** Todos los usuarios de la sede, con su puesto y sus niveles. Solo para quien la administra. */
export function UsersSection() {
  const { activeOrg, user: me } = useAuth();
  const [term, setTerm] = useState("");
  const [positionFilter, setPositionFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState<Level | "">("");
  const [open, setOpen] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["org-users", activeOrg?.id],
    queryFn: () => api<OrgUsers>("/api/org/users"),
  });

  if (isLoading) return <Loading />;
  if (isError || !data) {
    return <p className="text-sm text-ink-500">{error instanceof Error ? error.message : "No se pudieron cargar los usuarios."}</p>;
  }

  const query = term.trim().toLowerCase();
  const users = data.users.filter((user) => {
    if (query && !user.name.toLowerCase().includes(query) && !user.email.toLowerCase().includes(query)) return false;
    if (positionFilter === NO_POSITION && user.position) return false;
    if (positionFilter && positionFilter !== NO_POSITION && (user.position ?? user.guessed_position) !== positionFilter) {
      return false;
    }
    const admin = user.role === "owner" || user.role === "admin";
    if (levelFilter && !admin && !user.levels[levelFilter]) return false;
    return true;
  });
  const unset = data.users.filter((user) => !user.position).length;

  return (
    <Block
      id="users-list"
      hint={
        <>
          Elegí el puesto y los niveles de cada persona: de eso sale qué reuniones ve y a quién le puede asignar tareas.
          {unset > 0 && (
            <>
              {" "}
              <span className="font-medium text-amber-700">
                {unset === 1 ? "A 1 persona" : `A ${unset} personas`} todavía no se le eligió el puesto.
              </span>
            </>
          )}
        </>
      }
    >
      <div className="mb-3 flex flex-col gap-2 sm:flex-row">
        <div className="flex-1">
          <Input placeholder="Buscar por nombre o mail…" value={term} onChange={(event) => setTerm(event.target.value)} />
        </div>
        <Select
          ariaLabel="Filtrar por puesto"
          value={positionFilter}
          onChange={setPositionFilter}
          options={[
            { value: "", label: "Todos los puestos" },
            ...data.positions.map((item) => ({ value: item.id, label: item.label })),
            { value: NO_POSITION, label: "Sin puesto elegido" },
          ]}
          className="sm:w-56"
        />
      </div>
      <div role="group" aria-label="Filtrar por nivel" className="mb-2 flex flex-wrap gap-1.5">
        <Chip active={!levelFilter} onClick={() => setLevelFilter("")}>
          Todos
        </Chip>
        {data.levels.map((level) => (
          <Chip key={level} active={levelFilter === level} onClick={() => setLevelFilter(levelFilter === level ? "" : level)}>
            {LEVEL_LABEL[level]}
          </Chip>
        ))}
      </div>
      <p className="mb-1 text-xs text-ink-400">
        {users.length === data.users.length ? `${users.length} personas` : `${users.length} de ${data.users.length} personas`}
      </p>

      <ul className="divide-y divide-ink-100">
        {users.map((user) => (
          <UserRow
            key={user.user_id}
            user={user}
            positions={data.positions}
            levels={data.levels}
            isMe={user.user_id === me?.id}
            open={open === user.user_id}
            onToggle={() => setOpen(open === user.user_id ? null : user.user_id)}
          />
        ))}
        {users.length === 0 && <li className="py-6 text-center text-sm text-ink-400">Nadie coincide.</li>}
      </ul>
    </Block>
  );
}
