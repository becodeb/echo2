import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  AnimatedNumber,
  CreditDots,
  effectivePlan,
  PLAN_NAME,
  renewsLabel,
  Shimmer,
  useBilling,
  type BillingInfo,
} from "../components/billing";
import { CompareTable, PlanCard, planSpecs, type PlanSpec } from "../components/PlanCatalog";
import { Spinner } from "../components/ui";
import { useAuth } from "../state/auth";

/**
 * Planes: Gratis, Individual, Individual + voz e Instituciones.
 * Todavía no hay cobro (docs/plan-transcripcion-y-planes.md, §5): "Suscribirme"
 * y "Contact sales" dejan el pedido y avisan a Becode, que contacta a la persona.
 */
export default function Plans() {
  const { data: billing, isLoading } = useBilling();

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-8 sm:py-10">
      <header className="mb-8 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-ink-400">Planes</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink-900 sm:text-[34px]">
            Elegí cuánto hace Echo por vos
          </h1>
          <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-ink-500">
            Todas las reuniones se transcriben. Lo que cambia es en cuántas Echo separa quién habló, y si podés
            conversar con Echo por voz.
          </p>
        </div>
        {isLoading || !billing ? <Shimmer className="h-[92px] w-full sm:w-80" /> : <CurrentPlan billing={billing} />}
      </header>

      {isLoading || !billing ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <Shimmer key={index} className="h-[420px]" />
          ))}
        </div>
      ) : (
        <>
          <PlanGrid billing={billing} />
          <h2 className="mb-4 mt-12 text-xl font-semibold tracking-tight text-ink-900">Comparar planes</h2>
          <CompareTable plans={billing.plans} />
        </>
      )}

      <p className="mt-8 text-center text-xs leading-relaxed text-ink-400">
        Las reuniones donde hablan menores de 18 se transcriben sin separar quién habló. Los créditos se renuevan cada
        mes y no se acumulan.{" "}
        <Link to="/usage" className="font-medium text-ink-600 hover:text-ink-900">
          Ver mi consumo
        </Link>
      </p>
    </div>
  );
}

/** Los planes que la persona tiene hoy: el suyo (si pagó uno) y el de su institución. */
function currentPlans(billing: BillingInfo): Set<string> {
  const plans = new Set<string>();
  if (billing.user_plan !== "base") plans.add(billing.user_plan);
  if (billing.org_plan !== "base") plans.add(billing.org_plan === "cortesia" ? "institucion" : billing.org_plan);
  if (plans.size === 0) plans.add("base");
  return plans;
}

function CurrentPlan({ billing }: { billing: BillingInfo }) {
  const { user } = useAuth();
  // El plan que pagó la persona va primero: es el que ella eligió. La gente de
  // Becode tiene todo incluido, como dice Inicio.
  const plan = user?.is_superadmin
    ? "becode"
    : billing.user_plan !== "base"
      ? billing.user_plan
      : effectivePlan(billing);
  const people = billing.people;
  return (
    <div className="animate-fade-up rounded-3xl border border-ink-100 bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] sm:w-80">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-ink-400">Tu plan</span>
        <span className="rounded-full bg-ink-900 px-2.5 py-0.5 text-xs font-semibold text-white">
          {PLAN_NAME[plan] ?? plan}
        </span>
      </div>
      {people.mode === "always" ? (
        <p className="mt-3 text-sm text-ink-700">
          {people.source === "individual" && people.people_hours_left != null ? (
            <>
              <span className="text-2xl font-semibold text-ink-900">
                <AnimatedNumber
                  value={people.people_hours_left}
                  format={(n) => n.toLocaleString("es-AR", { maximumFractionDigits: 1 })}
                />{" "}
                h
              </span>{" "}
              con quién habló este mes
            </>
          ) : (
            "Quién habló en todas las reuniones."
          )}
        </p>
      ) : (
        <div className="mt-3">
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-ink-900">
              <AnimatedNumber value={people.credits_left ?? 0} />
            </span>
            <span className="text-sm text-ink-500">de {people.credits_per_month} créditos este mes</span>
          </div>
          <div className="mt-2 flex items-center justify-between gap-3">
            <CreditDots total={people.credits_per_month ?? 0} left={people.credits_left ?? 0} size="lg" />
            <span className="text-xs text-ink-400">Se renuevan el {renewsLabel(billing.renews_at)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

const REQUESTABLE = new Set(["individual", "individual_voz", "institucion"]);

function PlanGrid({ billing }: { billing: BillingInfo }) {
  const { user } = useAuth();
  const becode = !!user?.is_superadmin;
  const current = becode ? new Set<string>() : currentPlans(billing);
  const specs = planSpecs(billing.plans);
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {specs.map((spec, index) => {
        const isCurrent = current.has(spec.plan.code);
        // Individual + voz ya trae todo lo de Individual.
        const included = spec.plan.code === "individual" && current.has("individual_voz");
        // Solo un pedido abierto deja el botón en "te vamos a contactar": uno
        // ya resuelto (o cancelado) permite pedir de nuevo.
        const pending = billing.requests.find(
          (request) => request.plan === spec.plan.code && (request.status === "new" || request.status === "contacted"),
        );
        return (
          <PlanCard
            key={spec.plan.code}
            spec={spec}
            featured={spec.plan.code === "individual_voz"}
            badge={isCurrent ? "Tu plan" : undefined}
            delay={index * 60}
          >
            <PlanAction
              spec={spec}
              featured={spec.plan.code === "individual_voz"}
              state={
                becode
                  ? "Incluido en tu cuenta"
                  : isCurrent
                    ? "Plan actual"
                    : included
                      ? "Incluido en tu plan"
                      : !REQUESTABLE.has(spec.plan.code)
                        ? "Incluido para todos"
                        : null
              }
              pending={pending}
            />
          </PlanCard>
        );
      })}
    </div>
  );
}

/**
 * Suscribirme / Contact sales, con un paso de confirmación (§4.7): todavía no
 * hay cobro, así que lo que hace es avisarle a Becode, y eso se dice antes.
 */
function PlanAction({
  spec,
  featured,
  state,
  pending,
}: {
  spec: PlanSpec;
  featured: boolean;
  state: string | null;
  pending?: { status: string };
}) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [sent, setSent] = useState(false);
  const request = useMutation({
    mutationFn: () => api("/api/billing/requests", { method: "POST", body: JSON.stringify({ plan: spec.plan.code }) }),
    onSuccess: () => {
      setSent(true);
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: ["billing"] });
    },
  });
  const sales = spec.plan.code === "institucion";
  const solid = featured ? "bg-white text-ink-900 hover:bg-ink-100" : "bg-ink-900 text-white hover:bg-ink-700";
  const muted = featured ? "bg-white/10 text-ink-300" : "bg-ink-50 text-ink-400";

  if (state) {
    return <div className={`rounded-full py-2.5 text-center text-sm font-medium ${muted}`}>{state}</div>;
  }
  if (sent || pending) {
    return (
      <div
        className={`animate-fade-up flex items-center justify-center gap-2 rounded-full py-2.5 text-sm font-medium ${
          featured ? "bg-white/10 text-white" : "bg-emerald-50 text-emerald-700"
        }`}
        role="status"
      >
        <svg width="14" height="14" viewBox="0 0 12 12" fill="none" aria-hidden>
          <path d="M2.5 6.2 5 8.5l4.5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {pending?.status === "contacted" ? "Ya te contactamos" : "Listo, te vamos a contactar"}
      </div>
    );
  }
  if (confirming) {
    return (
      <div className={`animate-fade-up rounded-2xl p-3 text-sm ${featured ? "bg-white/10 text-ink-200" : "bg-ink-50 text-ink-600"}`}>
        <p>
          {sales
            ? "Le avisamos a Becode y te escribimos para armar el plan de tu institución."
            : `Le avisamos a Becode que querés el plan ${spec.plan.name}. Te escribimos por mail para darlo de alta; todavía no se cobra desde Echo.`}
        </p>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => request.mutate()}
            disabled={request.isPending}
            className={`flex min-h-10 flex-1 items-center justify-center rounded-full px-3 font-semibold disabled:opacity-60 ${solid}`}
          >
            {request.isPending ? <Spinner /> : "Sí, avisar"}
          </button>
          <button type="button" onClick={() => setConfirming(false)} className="min-h-10 rounded-full px-3 font-medium">
            Cancelar
          </button>
        </div>
        {request.isError && <p className="mt-2 text-xs text-red-500">No se pudo enviar el pedido. Probá de nuevo.</p>}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      className={`flex w-full items-center justify-center gap-2 rounded-full py-2.5 text-sm font-semibold transition-all duration-200 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ${solid}`}
    >
      {sales ? "Contact sales" : "Suscribirme"}
    </button>
  );
}
