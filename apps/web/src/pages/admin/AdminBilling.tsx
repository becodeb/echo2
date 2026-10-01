import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminOrgOut } from "../../api/types";
import { Select } from "../../components/Select";
import { AnimatedNumber, formatAudio, formatUSD, PLAN_NAME, Shimmer } from "../../components/billing";
import { Button, Input, Spinner } from "../../components/ui";
import { currentMonth, MonthPicker, monthLabel, PeopleTable, shiftMonth, Stat, versus, type PersonUsage } from "../Usage";

/**
 * Panel de superadmin: planes y topes (sin números fijos en el código: se
 * ajustan acá), plan de cada organización y de cada persona, pedidos de
 * "Suscribirme" / "Contact sales" y el consumo de toda la instalación.
 */

const LIMIT_LABEL: Record<string, string> = {
  credits_per_month: "Créditos por mes",
  people_hours_per_month: "Horas con quién habló por mes",
  voice_minutes_per_month: "Minutos de voz por mes",
  meetings_per_day: "Reuniones por día",
  audio_hours_per_month: "Horas de audio por mes",
};
const ORG_PLANS = ["base", "institucion", "cortesia"];
const USER_PLANS = ["base", "individual", "individual_voz"];

interface AdminPlan {
  code: string;
  name: string;
  scope: string;
  price_usd: number | null;
  features: Record<string, unknown>;
  limits: Record<string, number>;
}

/** Plan de una organización y su tope de créditos propio (va dentro de cada tarjeta). */
export function OrgPlanControl({ org }: { org: AdminOrgOut }) {
  const queryClient = useQueryClient();
  const [credits, setCredits] = useState(org.limits?.credits_per_month?.toString() ?? "");
  const save = useMutation({
    mutationFn: (body: { plan?: string; limits?: Record<string, number | null> }) =>
      api(`/api/admin/organizations/${org.id}/plan`, { method: "PUT", skipOrg: true, body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-orgs"] }),
  });
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-2xl bg-ink-50/70 p-3">
      <div className="w-48">
        <Select
          label="Plan"
          value={org.plan}
          onChange={(plan) => save.mutate({ plan })}
          options={ORG_PLANS.map((plan) => ({ value: plan, label: PLAN_NAME[plan] ?? plan }))}
        />
      </div>
      <div className="w-44">
        <Input
          label="Créditos por persona"
          type="number"
          min={0}
          placeholder="Los del plan"
          value={credits}
          onChange={(event) => setCredits(event.target.value)}
          onBlur={() => {
            const next = credits === "" ? null : Number(credits);
            if (next === (org.limits?.credits_per_month ?? null)) return;
            save.mutate({ limits: { ...(org.limits ?? {}), credits_per_month: next } as Record<string, number | null> });
          }}
        />
      </div>
      {org.is_personal && <span className="pb-2 text-xs text-ink-400">Cuenta individual</span>}
      {save.isPending && <Spinner className="mb-2.5 text-ink-400" />}
      {save.isError && <span className="pb-2 text-xs text-red-600">No se pudo guardar</span>}
    </div>
  );
}

export function PlansEditor() {
  const { data: plans, isLoading } = useQuery({
    queryKey: ["admin-plans"],
    queryFn: () => api<AdminPlan[]>("/api/admin/plans", { skipOrg: true }),
  });
  if (isLoading || !plans) return <Shimmer className="h-64" />;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {plans.map((plan) => (
        <PlanLimits key={plan.code} plan={plan} />
      ))}
    </div>
  );
}

function PlanLimits({ plan }: { plan: AdminPlan }) {
  const queryClient = useQueryClient();
  const relevant = Object.keys(LIMIT_LABEL);
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(relevant.map((key) => [key, plan.limits[key]?.toString() ?? ""])),
  );
  const save = useMutation({
    mutationFn: () =>
      api(`/api/admin/plans/${plan.code}`, {
        method: "PUT",
        skipOrg: true,
        body: JSON.stringify({
          limits: Object.fromEntries(relevant.map((key) => [key, values[key] === "" ? null : Number(values[key])])),
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-plans"] }),
  });
  return (
    <section className="rounded-3xl border border-ink-100 bg-white p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-[15px] font-semibold text-ink-900">{plan.name}</h3>
        <span className="text-sm text-ink-400">
          {plan.price_usd == null ? "A medida" : `US$ ${plan.price_usd} / mes`}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-ink-400">
        {plan.features.people === "always" ? "Quién habló en todas las reuniones" : "Quién habló con créditos"}
        {plan.features.voice ? " · voz" : ""}
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        {relevant.map((key) => (
          <Input
            key={key}
            label={LIMIT_LABEL[key]}
            type="number"
            min={0}
            placeholder="Sin tope"
            value={values[key]}
            onChange={(event) => setValues({ ...values, [key]: event.target.value })}
          />
        ))}
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={() => save.mutate()} disabled={save.isPending} className="rounded-full">
          {save.isPending ? <Spinner /> : "Guardar topes"}
        </Button>
        {save.isSuccess && <span className="text-sm text-emerald-600">Guardado</span>}
        {save.isError && <span className="text-sm text-red-600">Revisá los números</span>}
      </div>
    </section>
  );
}

interface UserPlanRow {
  id: string;
  name: string;
  email: string;
  plan: string;
  limits: Record<string, number>;
}

export function UserPlans() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const { data: users, isFetching } = useQuery({
    queryKey: ["admin-users", query],
    queryFn: () => api<UserPlanRow[]>(`/api/admin/users?q=${encodeURIComponent(query)}`, { skipOrg: true }),
    enabled: query.trim().length >= 2,
    placeholderData: keepPreviousData,
  });
  const save = useMutation({
    mutationFn: ({ id, plan }: { id: string; plan: string }) =>
      api(`/api/admin/users/${id}/plan`, { method: "PUT", skipOrg: true, body: JSON.stringify({ plan }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  return (
    <section className="rounded-3xl border border-ink-100 bg-white p-5">
      <h3 className="text-[15px] font-semibold text-ink-900">Planes individuales</h3>
      <p className="mt-0.5 text-xs text-ink-400">
        Una persona puede pagar su plan aunque esté dentro de un colegio. Cuando se cobre, se asigna acá.
      </p>
      <div className="mt-4">
        <Input placeholder="Buscar por nombre o email…" value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      <ul className="mt-3 divide-y divide-ink-100">
        {query.trim().length >= 2 && isFetching && !users && <li className="py-3"><Shimmer className="h-8" /></li>}
        {(users ?? []).map((user) => (
          <li key={user.id} className="flex items-center gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink-800">{user.name}</p>
              <p className="truncate text-xs text-ink-400">{user.email}</p>
            </div>
            <div className="w-44">
              <Select
                size="sm"
                ariaLabel={`Plan de ${user.name}`}
                value={user.plan}
                onChange={(plan) => save.mutate({ id: user.id, plan })}
                options={USER_PLANS.map((plan) => ({ value: plan, label: PLAN_NAME[plan] ?? plan }))}
              />
            </div>
          </li>
        ))}
        {users && users.length === 0 && <li className="py-3 text-sm text-ink-400">Nadie con ese nombre o email.</li>}
      </ul>
    </section>
  );
}

interface PlanRequestRow {
  id: string;
  plan: string;
  status: "new" | "contacted" | "done" | "cancelled";
  message: string | null;
  created_at: string;
  user_name: string;
  user_email: string;
  organization_name: string | null;
}

const STATUS_LABEL = { new: "Nuevo", contacted: "Contactado", done: "Dado de alta", cancelled: "Cancelado" };

export function PlanRequests() {
  const queryClient = useQueryClient();
  const { data: requests, isLoading } = useQuery({
    queryKey: ["admin-plan-requests"],
    queryFn: () => api<PlanRequestRow[]>("/api/admin/plan-requests", { skipOrg: true }),
  });
  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api(`/api/admin/plan-requests/${id}`, { method: "PUT", skipOrg: true, body: JSON.stringify({ status }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-plan-requests"] }),
  });
  if (isLoading) return <Shimmer className="h-40" />;
  if (!requests?.length) {
    return (
      <p className="rounded-3xl border border-dashed border-ink-200 p-10 text-center text-sm text-ink-400">
        Todavía nadie pidió un plan. Cuando alguien toque "Suscribirme" o "Contact sales", aparece acá y te llega un mail.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {requests.map((request) => (
        <li key={request.id} className="flex flex-wrap items-center gap-3 rounded-2xl border border-ink-100 bg-white px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-ink-800">
              {request.user_name} · <span className="text-ink-500">{PLAN_NAME[request.plan] ?? request.plan}</span>
            </p>
            <p className="truncate text-xs text-ink-400">
              {request.user_email}
              {request.organization_name ? ` · ${request.organization_name}` : ""} ·{" "}
              {new Date(request.created_at).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" })}
            </p>
            {request.message && <p className="mt-1 text-xs text-ink-600">"{request.message}"</p>}
          </div>
          <div className="w-40">
            <Select
              size="sm"
              ariaLabel="Estado del pedido"
              value={request.status}
              onChange={(status) => update.mutate({ id: request.id, status })}
              options={Object.entries(STATUS_LABEL).map(([value, label]) => ({ value, label }))}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

interface AdminUsage {
  month: string;
  total_cost_usd: number;
  total_credits: number;
  organizations: {
    id: string | null;
    name: string;
    plan: string | null;
    is_personal: boolean;
    cost_usd: number;
    credits: number;
    audio_seconds: number;
    tokens: number;
    people: PersonUsage[];
  }[];
  individuals: PersonUsage[];
}

export function GlobalUsage() {
  const [month, setMonth] = useState(currentMonth);
  const [open, setOpen] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["admin-usage", month],
    queryFn: () => api<AdminUsage>(`/api/admin/usage?month=${month}`, { skipOrg: true }),
    placeholderData: keepPreviousData,
  });
  const previousMonth = shiftMonth(month, -1);
  const { data: before } = useQuery({
    queryKey: ["admin-usage", previousMonth],
    queryFn: () => api<AdminUsage>(`/api/admin/usage?month=${previousMonth}`, { skipOrg: true }),
  });
  const audioOf = (usage?: AdminUsage) => (usage?.organizations ?? []).reduce((total, org) => total + org.audio_seconds, 0);
  const audio = audioOf(data);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight text-ink-900">
          Consumo de {monthLabel(month).toLowerCase()}
        </h2>
        <MonthPicker month={month} onChange={setMonth} />
      </div>
      {isLoading || !data ? (
        <Shimmer className="h-[104px]" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Costo estimado total" hint={versus(data.total_cost_usd, before?.total_cost_usd, previousMonth)}>
            <AnimatedNumber value={data.total_cost_usd} format={formatUSD} />
          </Stat>
          <Stat label="Audio transcripto" hint={versus(audio, before ? audioOf(before) : undefined, previousMonth)}>
            <AnimatedNumber value={audio} format={formatAudio} />
          </Stat>
          <Stat label="Créditos usados" hint={versus(data.total_credits, before?.total_credits, previousMonth)}>
            <AnimatedNumber value={data.total_credits} />
          </Stat>
        </div>
      )}
      <section className="rounded-3xl border border-ink-100 bg-white p-5">
        <h3 className="mb-3 text-[15px] font-semibold text-ink-900">Por organización</h3>
        <ul className="divide-y divide-ink-100">
          {(data?.organizations ?? []).map((org) => {
            const key = org.id ?? org.name;
            const expanded = open === key;
            return (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => setOpen(expanded ? null : key)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-3 py-3 text-left"
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-800">
                    {org.name}
                    <span className="ml-2 text-xs font-normal text-ink-400">
                      {org.is_personal ? "Individual" : PLAN_NAME[org.plan ?? "base"]}
                    </span>
                  </span>
                  <span className="text-xs text-ink-400">{formatAudio(org.audio_seconds)}</span>
                  <span className="w-24 text-right text-sm tabular-nums text-ink-900">{formatUSD(org.cost_usd)}</span>
                </button>
                <div className="reveal-grid" data-open={expanded}>
                  <div><div className="pb-4 pl-3"><PeopleTable people={org.people} /></div></div>
                </div>
              </li>
            );
          })}
          {data && data.organizations.length === 0 && <li className="py-6 text-center text-sm text-ink-400">Sin consumo este mes.</li>}
        </ul>
      </section>
      <section className="rounded-3xl border border-ink-100 bg-white p-5">
        <h3 className="mb-1 text-[15px] font-semibold text-ink-900">Planes individuales</h3>
        <p className="mb-3 text-xs text-ink-400">Quienes pagan su propio plan, estén o no dentro de un colegio.</p>
        <PeopleTable people={data?.individuals ?? []} />
      </section>
    </div>
  );
}

/** Crea (o actualiza) el agente de la conversación por voz en ElevenLabs, con la key de la instalación. */
export function VoiceAgentCard() {
  const setup = useMutation({
    mutationFn: () =>
      api<{ agent_id: string; voice_id: string; llm: string }>("/api/admin/voice-agent", { method: "POST", skipOrg: true }),
  });
  return (
    <section className="rounded-3xl border border-ink-100 bg-white p-5">
      <h3 className="text-[15px] font-semibold text-ink-900">Agente de voz</h3>
      <p className="mt-0.5 text-xs leading-relaxed text-ink-400">
        La conversación por voz del plan Individual + voz. Tocalo una vez para crearlo, y de nuevo cuando cambie la voz
        (ELEVENLABS_AGENT_VOICE_ID) o el prompt: actualiza el mismo agente.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button onClick={() => setup.mutate()} disabled={setup.isPending} className="rounded-full">
          {setup.isPending ? <Spinner /> : "Crear o actualizar el agente"}
        </Button>
        {setup.isSuccess && (
          <span className="text-sm text-emerald-600">
            Listo · {setup.data.agent_id} · {setup.data.llm}
          </span>
        )}
        {setup.isError && (
          <span className="text-sm text-red-600">
            {setup.error instanceof Error ? setup.error.message : "No se pudo crear"}
          </span>
        )}
      </div>
    </section>
  );
}
