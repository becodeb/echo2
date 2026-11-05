import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminOrgOut, MoveOut } from "../../api/types";
import { DotsMenu } from "../../components/DotsMenu";
import { MoveSummary, useMovePerson } from "../../components/MoveCard";
import { PLAN_NAME } from "../../components/billing";
import { timeAgo } from "../../components/NotificationsPanel";
import { Select } from "../../components/Select";
import { Avatar, Badge, Button, Card, EmptyState, Input, Modal, Spinner } from "../../components/ui";
import { LEVEL_LABEL, type Level } from "../../state/access";
import { useAuth } from "../../state/auth";
import { Chip } from "../settings/Positions";
import { UserEditor, type OrgUsers } from "../settings/UsersSection";

/**
 * Todas las personas de la instalación. Lo que se edita acá pasa por la misma API
 * de cada sede (`/api/org/...` con esa sede en el header), así valen las mismas
 * reglas que en Ajustes y queda en el historial de la sede.
 */

export interface AdminMembership {
  member_id: string;
  organization_id: string;
  organization: string;
  is_personal: boolean;
  role: string;
  position: string | null;
  guessed: boolean;
  levels: Partial<Record<Level, string>>;
}

export interface AdminPerson {
  id: string;
  name: string;
  email: string;
  avatar_color: string;
  avatar_url: string | null;
  plan: string;
  is_superadmin: boolean;
  is_active: boolean;
  last_seen_at: string | null;
  has_voice: boolean;
  memberships: AdminMembership[];
}

const ROLE_LABEL: Record<string, string> = {
  owner: "Dueño",
  admin: "Administra",
  member: "Miembro",
  viewer: "Solo lectura",
};
const ROLE_OPTIONS = ["member", "admin", "viewer"].map((value) => ({ value, label: ROLE_LABEL[value] }));
const USER_PLANS = ["base", "individual", "individual_voz"];

const WITHOUT_CAMPUS = "sin-sede";

/** Pedido a la API de una sede que no es la activa. */
function inOrg(orgId: string): { skipOrg: true; headers: Record<string, string> } {
  return { skipOrg: true, headers: { "X-Organization-Id": orgId } };
}

function campuses(person: AdminPerson): AdminMembership[] {
  return person.memberships.filter((membership) => !membership.is_personal);
}

function refreshPeople(queryClient: ReturnType<typeof useQueryClient>, orgId?: string) {
  queryClient.invalidateQueries({ queryKey: ["admin-people"] });
  queryClient.invalidateQueries({ queryKey: ["admin-orgs"] });
  if (orgId) queryClient.invalidateQueries({ queryKey: ["org-users", orgId] });
}

/** Lo que tiene alguien en una sede: rol, puesto y niveles, y sacarlo de ahí. */
function MembershipEditor({ person, membership }: { person: AdminPerson; membership: AdminMembership }) {
  const queryClient = useQueryClient();
  const { user: me } = useAuth();
  const orgId = membership.organization_id;
  const [confirming, setConfirming] = useState(false);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["org-users", orgId],
    queryFn: () => api<OrgUsers>("/api/org/users", inOrg(orgId)),
  });
  const orgUser = data?.users.find((item) => item.user_id === person.id);

  const setRole = useMutation({
    mutationFn: (role: string) =>
      api(`/api/org/members/${membership.member_id}`, {
        ...inOrg(orgId),
        method: "PATCH",
        body: JSON.stringify({ role }),
      }),
    onSuccess: () => refreshPeople(queryClient, orgId),
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/org/members/${membership.member_id}`, { ...inOrg(orgId), method: "DELETE" }),
    onSuccess: () => refreshPeople(queryClient, orgId),
  });

  return (
    <section className="rounded-3xl border border-ink-100 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-[15px] font-semibold text-ink-900">{membership.organization}</h3>
        {membership.role === "owner" ? (
          <Badge tone="indigo">Dueño: creó la sede</Badge>
        ) : (
          <div className="w-44">
            <Select
              ariaLabel={`Rol en ${membership.organization}`}
              value={membership.role}
              onChange={(role) => role !== membership.role && setRole.mutate(role)}
              options={ROLE_OPTIONS}
              disabled={setRole.isPending}
            />
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-6 text-ink-300">
          <Spinner />
        </div>
      )}
      {isError && <p className="mt-3 text-sm text-red-600">{error instanceof Error ? error.message : "No se pudo cargar"}</p>}
      {data && orgUser && (
        <UserEditor
          key={`${orgUser.user_id}-${orgUser.role}`}
          user={orgUser}
          positions={data.positions}
          levels={data.levels}
          groups={data.groups}
          isMe={person.id === me?.id}
          orgId={orgId}
        />
      )}

      {setRole.isError && (
        <p className="mt-2 text-sm text-red-600">{setRole.error instanceof Error ? setRole.error.message : "No se pudo cambiar el rol"}</p>
      )}
      {remove.isError && (
        <p className="mt-2 text-sm text-red-600">{remove.error instanceof Error ? remove.error.message : "No se pudo sacar"}</p>
      )}

      {membership.role !== "owner" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {confirming ? (
            <>
              <span className="text-sm text-ink-600">¿Sacar a {person.name} de {membership.organization}?</span>
              <Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
                {remove.isPending ? <Spinner /> : "Sí, sacar"}
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>Cancelar</Button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="text-sm font-medium text-red-600 hover:underline"
            >
              Sacar de esta sede
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function AddToCampus({ person, orgs }: { person: AdminPerson; orgs: AdminOrgOut[] }) {
  const queryClient = useQueryClient();
  const [orgId, setOrgId] = useState("");
  const taken = new Set(person.memberships.map((membership) => membership.organization_id));
  const options = orgs
    .filter((org) => !org.is_personal && !taken.has(org.id))
    .map((org) => ({ value: org.id, label: org.name }));
  const add = useMutation({
    mutationFn: () =>
      api(`/api/admin/people/${person.id}/memberships`, {
        method: "POST",
        skipOrg: true,
        body: JSON.stringify({ organization_id: orgId }),
      }),
    onSuccess: () => {
      refreshPeople(queryClient, orgId);
      setOrgId("");
    },
  });
  if (options.length === 0) return null;
  return (
    <section className="rounded-3xl bg-ink-50/70 p-4 sm:p-5">
      <h3 className="text-sm font-semibold text-ink-900">Sumar a una sede</h3>
      <p className="mt-0.5 text-xs text-ink-500">Entra como miembro, sin invitación. Después le elegís el puesto y los niveles.</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <div className="flex-1">
          <Select
            ariaLabel="Sede"
            value={orgId}
            onChange={setOrgId}
            options={options}
            placeholder="Elegir sede…"
            searchable={options.length > 6}
          />
        </div>
        <Button onClick={() => add.mutate()} disabled={!orgId || add.isPending}>
          {add.isPending ? <Spinner /> : "Sumar"}
        </Button>
      </div>
      {add.isError && <p className="mt-2 text-sm text-red-600">{add.error instanceof Error ? add.error.message : "No se pudo sumar"}</p>}
    </section>
  );
}

/** Sale de una sede y queda en otra en un solo paso; antes de confirmar se ve con qué queda. */
function MovePerson({ person, orgs, onDone }: { person: AdminPerson; orgs: AdminOrgOut[]; onDone: () => void }) {
  const movable = campuses(person).filter((membership) => membership.role !== "owner");
  const [fromId, setFromId] = useState(movable.length === 1 ? movable[0].organization_id : "");
  const [toId, setToId] = useState("");
  const destinations = orgs
    .filter((org) => !org.is_personal && org.id !== fromId)
    .map((org) => ({ value: org.id, label: org.name }));
  const preview = useQuery({
    queryKey: ["admin-move", person.id, fromId, toId],
    queryFn: () =>
      api<MoveOut>(
        `/api/admin/people/${person.id}/move?from_organization_id=${fromId}&to_organization_id=${toId}`,
        { skipOrg: true },
      ),
    enabled: !!fromId && !!toId,
    retry: false,
  });
  const run = useMovePerson(onDone);

  if (movable.length === 0) {
    return <p className="text-sm text-ink-500">{person.name} no tiene una sede de la que se pueda mover.</p>;
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-600">
        <span className="font-semibold text-ink-900">{person.name}</span> · {person.email}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Select
          label="De"
          value={fromId}
          onChange={(value) => {
            setFromId(value);
            if (value === toId) setToId("");
          }}
          options={movable.map((membership) => ({ value: membership.organization_id, label: membership.organization }))}
          placeholder="Elegir sede…"
        />
        <Select
          label="A"
          value={toId}
          onChange={setToId}
          options={destinations}
          placeholder="Elegir sede…"
          searchable={destinations.length > 6}
        />
      </div>
      {preview.isFetching && (
        <div className="flex justify-center py-2 text-ink-300">
          <Spinner />
        </div>
      )}
      {preview.isError && (
        <p className="text-sm text-red-600">{preview.error instanceof Error ? preview.error.message : "No se puede mover"}</p>
      )}
      {preview.data && !preview.isFetching && (
        <div className="rounded-2xl bg-ink-50/70 p-4">
          <MoveSummary move={preview.data} />
        </div>
      )}
      {run.isError && <p className="text-sm text-red-600">{run.error instanceof Error ? run.error.message : "No se pudo mover"}</p>}
      <div className="flex justify-end">
        <Button
          onClick={() => preview.data && run.mutate(preview.data)}
          disabled={!preview.data || preview.isFetching || preview.isError || run.isPending}
        >
          {run.isPending ? <Spinner /> : "Mover"}
        </Button>
      </div>
    </div>
  );
}

function PersonEditor({ person, orgs }: { person: AdminPerson; orgs: AdminOrgOut[] }) {
  const queryClient = useQueryClient();
  const setPlan = useMutation({
    mutationFn: (plan: string) =>
      api(`/api/admin/users/${person.id}/plan`, { method: "PUT", skipOrg: true, body: JSON.stringify({ plan }) }),
    onSuccess: () => refreshPeople(queryClient),
  });
  const own = campuses(person);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Avatar name={person.name} color={person.avatar_color} src={person.avatar_url} size={44} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold text-ink-900">{person.name}</p>
          <p className="truncate text-sm text-ink-500">{person.email}</p>
        </div>
      </div>

      {person.is_superadmin && (
        <p className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Es de Becode: ve todas las sedes. Ese permiso no se da desde acá, sale de la variable SUPERADMIN_EMAILS del servidor.
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl bg-ink-50/70 p-4 sm:px-5">
        <div>
          <p className="text-sm font-semibold text-ink-900">Plan individual</p>
          <p className="text-xs text-ink-500">Lo que paga esta persona, aparte de su sede.</p>
        </div>
        <div className="w-52">
          <Select
            ariaLabel="Plan individual"
            value={person.plan}
            onChange={(plan) => plan !== person.plan && setPlan.mutate(plan)}
            options={USER_PLANS.map((plan) => ({ value: plan, label: PLAN_NAME[plan] ?? plan }))}
            disabled={setPlan.isPending}
          />
        </div>
        {setPlan.isError && <p className="w-full text-sm text-red-600">No se pudo cambiar el plan</p>}
      </div>

      {own.map((membership) => (
        <MembershipEditor key={membership.member_id} person={person} membership={membership} />
      ))}
      {own.length === 0 && <p className="px-1 text-sm text-ink-500">No es de ninguna sede: solo tiene su cuenta individual.</p>}
      <AddToCampus person={person} orgs={orgs} />
    </div>
  );
}

function CampusTag({ membership }: { membership: AdminMembership }) {
  const levels = (Object.keys(membership.levels) as Level[]).map((level) => LEVEL_LABEL[level]);
  const admin = membership.role === "owner" || membership.role === "admin";
  const position = membership.position ? (membership.guessed ? `¿${membership.position}?` : membership.position) : "Sin puesto";
  return (
    // En el celular no entra en una línea: se parte en vez de cortar las palabras.
    <span className="inline-flex max-w-full flex-wrap items-center gap-x-1.5 rounded-2xl bg-ink-50 px-2.5 py-1 text-xs text-ink-600">
      <span className="font-medium text-ink-800">{membership.organization}</span>
      <span aria-hidden className="text-ink-300">·</span>
      <span className={membership.guessed || !membership.position ? "text-amber-700" : ""}>{position}</span>
      {!admin && levels.length > 0 && (
        <>
          <span aria-hidden className="text-ink-300">·</span>
          <span>{levels.join(", ")}</span>
        </>
      )}
    </span>
  );
}

function PersonRow({ person, onEdit, onMove }: { person: AdminPerson; onEdit: () => void; onMove: () => void }) {
  const own = campuses(person);
  return (
    <li className="flex items-start gap-3 px-4 py-3.5 sm:px-5">
      <button
        type="button"
        onClick={onEdit}
        className="flex min-w-0 flex-1 items-start gap-3 rounded-2xl text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
      >
        <Avatar name={person.name} color={person.avatar_color} src={person.avatar_url} size={38} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="truncate text-sm font-semibold text-ink-900">{person.name}</span>
            {person.is_superadmin && <Badge tone="amber">Becode</Badge>}
            {person.plan !== "base" && <Badge tone="indigo">{PLAN_NAME[person.plan] ?? person.plan}</Badge>}
            {!person.is_active && <Badge tone="red">Desactivada</Badge>}
          </span>
          <span className="block truncate text-xs text-ink-400">{person.email}</span>
          <span className="mt-1.5 flex flex-wrap gap-1.5">
            {own.map((membership) => (
              <CampusTag key={membership.member_id} membership={membership} />
            ))}
            {own.length === 0 && <span className="py-1 text-xs text-ink-400">Sin sede</span>}
          </span>
        </span>
        <span className="hidden shrink-0 pt-0.5 text-right text-xs text-ink-400 sm:block">
          {person.last_seen_at ? `Entró ${timeAgo(person.last_seen_at)}` : "Nunca entró"}
          <span className={`block ${person.has_voice ? "text-emerald-700" : ""}`}>
            {person.has_voice ? "Con Mi voz" : "Sin Mi voz"}
          </span>
        </span>
      </button>
      <DotsMenu
        label={`Opciones de ${person.name}`}
        items={[
          { label: "Editar permisos y roles", onSelect: onEdit },
          ...(own.length > 0 ? [{ label: "Mover a otra sede", onSelect: onMove }] : []),
          { label: "Copiar el mail", onSelect: () => void navigator.clipboard?.writeText(person.email) },
        ]}
      />
    </li>
  );
}

export function AdminUsers({ initialOrg }: { initialOrg: string | null }) {
  const { data: people, isLoading, isError, error } = useQuery({
    queryKey: ["admin-people"],
    queryFn: () => api<AdminPerson[]>("/api/admin/people", { skipOrg: true }),
  });
  const { data: orgs } = useQuery({
    queryKey: ["admin-orgs"],
    queryFn: () => api<AdminOrgOut[]>("/api/admin/organizations", { skipOrg: true }),
  });
  const [term, setTerm] = useState("");
  const [orgFilter, setOrgFilter] = useState(initialOrg ?? "");
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [movingId, setMovingId] = useState<string | null>(null);
  useEffect(() => setOrgFilter(initialOrg ?? ""), [initialOrg]);

  const shown = useMemo(() => {
    const query = term.trim().toLowerCase();
    return (people ?? []).filter((person) => {
      if (query && !person.name.toLowerCase().includes(query) && !person.email.toLowerCase().includes(query)) return false;
      const own = campuses(person);
      if (orgFilter === WITHOUT_CAMPUS) {
        if (own.length > 0) return false;
      } else if (orgFilter && !person.memberships.some((item) => item.organization_id === orgFilter)) {
        return false;
      }
      if (onlyMissing && !own.some((item) => item.guessed || !item.position)) return false;
      return true;
    });
  }, [people, term, orgFilter, onlyMissing]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (isError) {
    return (
      <Card>
        <EmptyState title="No se pudieron cargar los usuarios" mood="error">
          <p>{error instanceof Error ? error.message : "Probá de nuevo en un momento."}</p>
        </EmptyState>
      </Card>
    );
  }

  const campusOptions = (orgs ?? [])
    .filter((org) => !org.is_personal)
    .map((org) => ({ value: org.id, label: `${org.name} (${org.members})` }));
  const editing = (people ?? []).find((person) => person.id === editingId) ?? null;
  const moving = (people ?? []).find((person) => person.id === movingId) ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="flex-1">
          <Input
            placeholder="Buscar por nombre o mail…"
            aria-label="Buscar persona"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
        </div>
        <Select
          ariaLabel="Filtrar por sede"
          value={orgFilter}
          onChange={setOrgFilter}
          options={[
            { value: "", label: "Todas las sedes" },
            ...campusOptions,
            { value: WITHOUT_CAMPUS, label: "Sin sede" },
          ]}
          searchable={campusOptions.length > 6}
          className="sm:w-72"
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-400">
          {shown.length === (people ?? []).length
            ? `${shown.length} personas`
            : `${shown.length} de ${(people ?? []).length} personas`}
        </p>
        <Chip active={onlyMissing} onClick={() => setOnlyMissing((value) => !value)}>
          Falta elegirles el puesto
        </Chip>
      </div>

      {shown.length === 0 ? (
        <Card>
          <EmptyState title="Nadie coincide" mood="idle" />
        </Card>
      ) : (
        <ul className="divide-y divide-ink-100 rounded-3xl border border-ink-100 bg-white shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
          {shown.map((person) => (
            <PersonRow
              key={person.id}
              person={person}
              onEdit={() => setEditingId(person.id)}
              onMove={() => setMovingId(person.id)}
            />
          ))}
        </ul>
      )}

      <p className="px-1 text-xs text-ink-400">
        También podés pedírselo a Echo con el botón de arriba: «mové a Ana Gómez de Nordelta a Puertos». Te muestra lo que
        va a hacer y lo confirmás.
      </p>

      <Modal open={!!moving} onClose={() => setMovingId(null)} title="Mover a otra sede">
        {moving && <MovePerson key={moving.id} person={moving} orgs={orgs ?? []} onDone={() => setMovingId(null)} />}
      </Modal>

      <Modal open={!!editing} onClose={() => setEditingId(null)} title="Permisos y roles" wide>
        {editing && <PersonEditor key={editing.id} person={editing} orgs={orgs ?? []} />}
      </Modal>
    </div>
  );
}
