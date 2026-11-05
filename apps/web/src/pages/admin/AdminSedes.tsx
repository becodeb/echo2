import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminOrgOut } from "../../api/types";
import { DotsMenu } from "../../components/DotsMenu";
import { PLAN_NAME } from "../../components/billing";
import { timeAgo } from "../../components/NotificationsPanel";
import { SegmentedToggle } from "../../components/Toggles";
import { Avatar, Badge, Button, Card, EmptyState, Input, Modal, Spinner } from "../../components/ui";
import { useAuth } from "../../state/auth";
import { OrgAIForm } from "./AdminAI";
import { OrgPlanControl } from "./AdminBilling";
import type { AdminPerson } from "./AdminUsers";

/** Las sedes de la instalación, de un vistazo; el detalle se abre en su ficha. */

const TILE_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"];

/** Siempre el mismo color para la misma sede. */
function orgColor(id: string): string {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return TILE_COLORS[hash % TILE_COLORS.length];
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function AiBadge({ org }: { org: AdminOrgOut }) {
  if (org.uses_own_key) return <Badge tone="green">IA con key propia</Badge>;
  if (org.llm_provider) return <Badge tone="gray">IA del servidor</Badge>;
  return <Badge tone="red">Sin IA</Badge>;
}

function enterOrg(switchOrg: (id: string) => void, orgId: string) {
  // Entra a la sede como la ve un admin: reuniones, niveles, personas.
  switchOrg(orgId);
  window.location.href = "/settings/access";
}

function Figure({ value, label }: { value: number; label: string }) {
  return (
    <span className="min-w-0">
      <span className="block text-sm font-semibold tabular-nums text-ink-900">{value.toLocaleString("es")}</span>
      <span className="block text-[11px] text-ink-400">{label}</span>
    </span>
  );
}

function OrgCard({
  org,
  onOpen,
  onViewUsers,
}: {
  org: AdminOrgOut;
  onOpen: () => void;
  onViewUsers: () => void;
}) {
  const { switchOrg } = useAuth();
  const rule = org.join_rules[0];
  return (
    <li className="relative rounded-3xl border border-ink-100 bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-shadow hover:shadow-[0_8px_24px_-12px_rgba(16,24,40,0.22)]">
      <button
        type="button"
        onClick={onOpen}
        className="block w-full rounded-3xl p-5 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
      >
        <span className="flex items-center gap-3 pr-9">
          <Avatar name={org.name} color={orgColor(org.id)} size={44} />
          <span className="min-w-0">
            <span className="block truncate text-[15px] font-semibold text-ink-900">{org.name}</span>
            <span className="block truncate text-xs text-ink-400">
              {PLAN_NAME[org.plan] ?? org.plan}
              {rule && ` · ${rule.includes("@") ? rule : `@${rule}`}`}
              {org.join_rules.length > 1 && ` +${org.join_rules.length - 1}`}
            </span>
          </span>
        </span>
        <span className="mt-4 grid grid-cols-[auto_auto_minmax(0,1fr)] gap-5 border-t border-ink-100 pt-4">
          <Figure value={org.members} label={org.members === 1 ? "persona" : "personas"} />
          <Figure value={org.meetings} label={org.meetings === 1 ? "reunión" : "reuniones"} />
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-ink-900">
              {org.last_meeting_at ? timeAgo(org.last_meeting_at) : "Nunca"}
            </span>
            <span className="block text-[11px] text-ink-400">última reunión</span>
          </span>
        </span>
        <span className="mt-3 flex">
          <AiBadge org={org} />
        </span>
      </button>
      <div className="absolute right-3 top-3">
        <DotsMenu
          label={`Opciones de ${org.name}`}
          items={[
            { label: "Configurar", onSelect: onOpen },
            { label: "Ver sus usuarios", onSelect: onViewUsers },
            { label: "Entrar a la sede", onSelect: () => enterOrg(switchOrg, org.id) },
          ]}
        />
      </div>
    </li>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-ink-100 pt-5">
      <h3 className="mb-3 text-sm font-semibold text-ink-900">{title}</h3>
      {children}
    </section>
  );
}

/** La ficha de una sede: nombre, plan, quién entra sola y su IA. */
function OrgDetail({ org, onViewUsers }: { org: AdminOrgOut; onViewUsers: () => void }) {
  const { switchOrg } = useAuth();
  return (
    <div className="space-y-5">
      <div>
        <OrgName org={org} />
        <p className="mt-0.5 text-sm text-ink-500">
          {plural(org.members, "persona", "personas")} · {plural(org.meetings, "reunión", "reuniones")}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => enterOrg(switchOrg, org.id)}>Entrar a la sede</Button>
        <Button variant="soft" onClick={onViewUsers}>Ver sus usuarios</Button>
      </div>
      <Section title="Plan">
        <OrgPlanControl org={org} />
      </Section>
      <Section title="Quién entra sin invitación">
        <JoinRules org={org} />
      </Section>
      <Section title="Inteligencia artificial">
        <OrgAIForm org={org} />
      </Section>
    </div>
  );
}

function Stat({ value, label, warn = false }: { value: string; label: string; warn?: boolean }) {
  return (
    <div className="rounded-3xl border border-ink-100 bg-white px-5 py-4 shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
      <p className="text-2xl font-semibold tracking-tight tabular-nums text-ink-900">{value}</p>
      <p className={`mt-0.5 text-xs ${warn ? "font-medium text-amber-700" : "text-ink-400"}`}>{label}</p>
    </div>
  );
}

export function AdminSedes({ onViewUsers }: { onViewUsers: (orgId: string) => void }) {
  const { data: orgs, isLoading, isError, error } = useQuery({
    queryKey: ["admin-orgs"],
    queryFn: () => api<AdminOrgOut[]>("/api/admin/organizations", { skipOrg: true }),
  });
  const { data: people } = useQuery({
    queryKey: ["admin-people"],
    queryFn: () => api<AdminPerson[]>("/api/admin/people", { skipOrg: true }),
  });
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState<"sedes" | "individuales">("sedes");
  const [openId, setOpenId] = useState<string | null>(null);

  const campuses = useMemo(() => (orgs ?? []).filter((org) => !org.is_personal), [orgs]);
  const personal = useMemo(() => (orgs ?? []).filter((org) => org.is_personal), [orgs]);

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
        <EmptyState title="No se pudo cargar el panel" mood="error">
          <p>{error instanceof Error ? error.message : "Probá de nuevo en un momento."}</p>
        </EmptyState>
      </Card>
    );
  }

  const query = term.trim().toLowerCase();
  const shown = (kind === "sedes" ? campuses : personal).filter(
    (org) => !query || org.name.toLowerCase().includes(query) || org.join_rules.some((rule) => rule.includes(query)),
  );
  const open = (orgs ?? []).find((org) => org.id === openId) ?? null;
  const meetings = (orgs ?? []).reduce((sum, org) => sum + org.meetings, 0);
  const withoutAI = campuses.filter((org) => !org.llm_provider).length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat value={campuses.length.toLocaleString("es")} label={campuses.length === 1 ? "sede" : "sedes"} />
        <Stat value={people ? people.length.toLocaleString("es") : "—"} label="personas en Echo" />
        <Stat value={meetings.toLocaleString("es")} label="reuniones" />
        <Stat
          value={withoutAI.toLocaleString("es")}
          label={withoutAI ? "sin IA: sus actas no se generan" : "sedes sin IA"}
          warn={withoutAI > 0}
        />
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="flex-1">
          <Input
            placeholder="Buscar por nombre o dominio…"
            aria-label="Buscar sede"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
        </div>
        {personal.length > 0 && (
          <div className="lg:w-80">
            <SegmentedToggle
              ariaLabel="Qué mostrar"
              value={kind}
              onChange={setKind}
              options={[
                { value: "sedes", label: `Sedes (${campuses.length})` },
                { value: "individuales", label: `Individuales (${personal.length})` },
              ]}
            />
          </div>
        )}
        <NewCampus />
      </div>

      {shown.length === 0 ? (
        <Card>
          <EmptyState title={query ? "Ninguna coincide" : "Todavía no hay nada acá"} mood="idle">
            {!query && <p>Cuando se cree la primera, va a aparecer acá.</p>}
          </EmptyState>
        </Card>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((org) => (
            <OrgCard key={org.id} org={org} onOpen={() => setOpenId(org.id)} onViewUsers={() => onViewUsers(org.id)} />
          ))}
        </ul>
      )}

      <Modal open={!!open} onClose={() => setOpenId(null)} title={open?.is_personal ? "Cuenta individual" : "Sede"} wide>
        {open && (
          <OrgDetail
            key={open.id}
            org={open}
            onViewUsers={() => {
              setOpenId(null);
              onViewUsers(open.id);
            }}
          />
        )}
      </Modal>
    </div>
  );
}

/** El nombre, que es lo que ve quien elige sede al registrarse ("Northfield Puertos"). */
function OrgName({ org }: { org: AdminOrgOut }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const rename = useMutation({
    mutationFn: (name: string) =>
      api(`/api/admin/organizations/${org.id}`, { method: "PATCH", skipOrg: true, body: JSON.stringify({ name }) }),
    onSuccess: () => {
      setDraft(null);
      queryClient.invalidateQueries({ queryKey: ["admin-orgs"] });
    },
  });
  if (draft == null) {
    return (
      <h3 className="text-[15px] font-semibold text-ink-900">
        {org.name}{" "}
        <button onClick={() => setDraft(org.name)} className="text-xs font-medium text-accent-600 hover:underline">
          Renombrar
        </button>
      </h3>
    );
  }
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (draft.trim().length >= 2) rename.mutate(draft.trim());
      }}
    >
      <Input value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Nombre" autoFocus />
      <Button type="submit" disabled={rename.isPending}>{rename.isPending ? <Spinner /> : "Guardar"}</Button>
      <Button type="button" variant="ghost" onClick={() => setDraft(null)}>Cancelar</Button>
    </form>
  );
}

/**
 * Una sede nueva sin miembros (ej. "Northfield Nordelta"). Con el mismo
 * dominio que otra sede, a quien se registra se le pregunta de cuál es.
 */
function NewCampus() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [rules, setRules] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api("/api/admin/organizations", {
        method: "POST",
        skipOrg: true,
        body: JSON.stringify({
          name: name.trim(),
          join_rules: rules.split(/[\n,]/).map((rule) => rule.trim()).filter(Boolean),
        }),
      }),
    onSuccess: () => {
      setOpen(false);
      setName("");
      setRules("");
      queryClient.invalidateQueries({ queryKey: ["admin-orgs"] });
    },
  });
  return (
    <>
      <Button onClick={() => setOpen(true)}>+ Nueva sede</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Nueva sede">
        <div className="space-y-3">
          <Input label="Nombre" value={name} onChange={(event) => setName(event.target.value)} placeholder="Northfield Nordelta" />
          <Input
            label="Se unen solos (dominio o emails, separados por coma)"
            value={rules}
            onChange={(event) => setRules(event.target.value)}
            placeholder="northfield.edu.ar"
          />
          <p className="text-xs text-ink-400">
            Si otra sede ya tiene el mismo dominio, a quien se registre con ese mail se le pregunta de cuál es. Quienes ya
            están en una sede no cambian.
          </p>
          {create.isError && (
            <p className="text-sm text-red-600">{create.error instanceof Error ? create.error.message : "No se pudo crear"}</p>
          )}
          <div className="flex gap-2">
            <Button onClick={() => create.mutate()} disabled={create.isPending || name.trim().length < 2}>
              {create.isPending ? <Spinner /> : "Crear sede"}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancelar</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}

/**
 * Quién entra a esta organización sin invitación: dominios del colegio o
 * emails puntuales. Si dos organizaciones comparten dominio (dos sedes), a
 * quien entra se le pregunta de cuál es.
 */
function JoinRules({ org }: { org: AdminOrgOut }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const save = useMutation({
    mutationFn: (rules: string[]) =>
      api<string[]>(`/api/admin/organizations/${org.id}/join-rules`, {
        method: "PUT",
        skipOrg: true,
        body: JSON.stringify({ rules }),
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["admin-orgs"] });
    },
  });

  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-500">Se unen solos:</span>
        {org.join_rules.length === 0 ? (
          <span className="text-ink-400">nadie (solo por invitación)</span>
        ) : (
          org.join_rules.map((rule) => (
            <Badge key={rule} tone={rule.includes("@") ? "sky" : "indigo"}>
              {rule.includes("@") ? rule : `@${rule}`}
            </Badge>
          ))
        )}
        <button
          onClick={() => {
            setDraft(org.join_rules.join("\n"));
            save.reset();
            setEditing(true);
          }}
          className="text-sm font-medium text-accent-600 hover:underline"
        >
          Editar
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-xl border border-ink-100 bg-ink-50 p-3">
      <label className="block">
        <span className="mb-1.5 block text-sm font-medium text-ink-700">Quién se une sin invitación</span>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          placeholder={"northfield.edu.ar\nmariana.gibson@gmail.com"}
          className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 font-mono text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20"
        />
      </label>
      <p className="text-xs text-ink-400">
        Uno por renglón. Un dominio suma a todo el que entre con Google con un mail de ese dominio;
        si otra organización tiene el mismo dominio (otra sede), se le pregunta de cuál es. Un email
        exacto suma a esa persona directo. Correos públicos como gmail.com no se aceptan como
        dominio.
      </p>
      {save.isError && (
        <p className="text-sm text-red-600">
          {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          onClick={() => save.mutate(draft.split(/[\n,]/).map((rule) => rule.trim()).filter(Boolean))}
          disabled={save.isPending}
        >
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        <Button variant="ghost" onClick={() => setEditing(false)}>
          Cancelar
        </Button>
      </div>
    </div>
  );
}
