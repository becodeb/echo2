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
  type PublicPlan,
} from "../components/billing";
import { Spinner } from "../components/ui";

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
        <PlanGrid billing={billing} />
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
  // El plan que pagó la persona va primero: es el que ella eligió.
  const plan = billing.user_plan !== "base" ? billing.user_plan : effectivePlan(billing);
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

interface CardSpec {
  plan: PublicPlan;
  tagline: string;
  bullets: string[];
  cta: string;
  requestable: boolean;
}

function specs(billing: BillingInfo): CardSpec[] {
  const byCode = Object.fromEntries(billing.plans.map((plan) => [plan.code, plan]));
  const out: CardSpec[] = [];
  const base = byCode.base;
  if (base) {
    const credits = base.limits.credits_per_month ?? 4;
    out.push({
      plan: base,
      tagline: "Para empezar, sin pagar nada.",
      bullets: [
        "Reuniones sin límite, transcriptas en vivo",
        `${credits} reuniones por mes con quién habló`,
        "Acta, resumen y tareas con responsables",
        "Chat con la IA sobre cada reunión",
      ],
      cta: "Plan actual",
      requestable: false,
    });
  }
  const individual = byCode.individual;
  if (individual) {
    const hours = individual.limits.people_hours_per_month ?? 5;
    out.push({
      plan: individual,
      tagline: "Para quien graba sus propias reuniones.",
      bullets: ["Todo lo de Gratis", `${hours} h por mes con quién habló en cada reunión`, "Sin créditos que contar"],
      cta: "Suscribirme",
      requestable: true,
    });
  }
  const voice = byCode.individual_voz;
  if (voice) {
    const minutes = voice.limits.voice_minutes_per_month ?? 30;
    out.push({
      plan: voice,
      tagline: "Para hablarle a Echo como a una persona.",
      bullets: [
        "Todo lo de Individual",
        `${minutes} min por mes de conversación por voz con Echo`,
        "Preguntale por tus reuniones sin escribir",
      ],
      cta: "Suscribirme",
      requestable: true,
    });
  }
  const school = byCode.institucion;
  if (school) {
    out.push({
      plan: school,
      tagline: "Para todo el colegio, con sus sedes y niveles.",
      bullets: [
        "Quién habló en todas las reuniones",
        "Toda la institución: sedes, niveles, familias y equipos",
        "Te acompañamos a empezar",
      ],
      cta: "Contact sales",
      requestable: true,
    });
  }
  return out;
}

function PlanGrid({ billing }: { billing: BillingInfo }) {
  const current = currentPlans(billing);
  const cards = specs(billing);
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.map((card, index) => (
        <PlanCard
          key={card.plan.code}
          card={card}
          current={current.has(card.plan.code)}
          // Individual + voz ya trae todo lo de Individual.
          included={card.plan.code === "individual" && current.has("individual_voz")}
          featured={card.plan.code === "individual_voz"}
          // Solo un pedido abierto deja el botón en "te vamos a contactar":
          // uno ya resuelto (o cancelado) permite pedir de nuevo.
          pending={billing.requests.find(
            (request) => request.plan === card.plan.code && (request.status === "new" || request.status === "contacted"),
          )}
          delay={index * 60}
        />
      ))}
    </div>
  );
}

function PlanCard({
  card,
  current,
  included,
  featured,
  pending,
  delay,
}: {
  card: CardSpec;
  current: boolean;
  included: boolean;
  featured: boolean;
  pending?: { status: string };
  delay: number;
}) {
  const queryClient = useQueryClient();
  const [sent, setSent] = useState(false);
  const request = useMutation({
    mutationFn: () => api("/api/billing/requests", { method: "POST", body: JSON.stringify({ plan: card.plan.code }) }),
    onSuccess: () => {
      setSent(true);
      queryClient.invalidateQueries({ queryKey: ["billing"] });
    },
  });
  const asked = sent || !!pending;
  const price = card.plan.price_usd;

  return (
    <article
      className={`animate-fade-up relative flex flex-col rounded-3xl border p-6 transition-shadow duration-300 hover:shadow-[0_12px_32px_-12px_rgba(20,24,36,0.18)] ${
        featured ? "border-ink-900 bg-ink-950 text-white" : "border-ink-100 bg-white"
      }`}
      style={{ animationDelay: `${delay}ms`, animationFillMode: "backwards" }}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className={`text-lg font-semibold ${featured ? "text-white" : "text-ink-900"}`}>{card.plan.name}</h2>
        {current && (
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              featured ? "bg-white text-ink-900" : "bg-ink-100 text-ink-700"
            }`}
          >
            Tu plan
          </span>
        )}
      </div>
      <p className={`mt-1 text-sm ${featured ? "text-ink-300" : "text-ink-500"}`}>{card.tagline}</p>

      <div className="mt-6 flex items-baseline gap-1.5">
        {price == null ? (
          <span className={`text-[28px] font-semibold tracking-tight ${featured ? "text-white" : "text-ink-900"}`}>
            A medida
          </span>
        ) : (
          <>
            <span className={`text-[40px] font-semibold leading-none tracking-tight ${featured ? "text-white" : "text-ink-900"}`}>
              {price === 0 ? "US$ 0" : `US$ ${price.toLocaleString("es-AR")}`}
            </span>
            <span className={`text-sm ${featured ? "text-ink-400" : "text-ink-400"}`}>/ mes</span>
          </>
        )}
      </div>

      <ul className="mt-6 flex-1 space-y-3">
        {card.bullets.map((bullet) => (
          <li key={bullet} className="flex items-start gap-2.5 text-sm">
            <span
              aria-hidden
              className={`mt-[3px] flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
                featured ? "bg-white text-ink-900" : "bg-ink-900 text-white"
              }`}
            >
              <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
                <path d="M2.5 6.2 5 8.5l4.5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className={featured ? "text-ink-200" : "text-ink-600"}>{bullet}</span>
          </li>
        ))}
      </ul>

      <div className="mt-8">
        {current || included || !card.requestable ? (
          <div
            className={`rounded-full py-2.5 text-center text-sm font-medium ${
              featured ? "bg-white/10 text-ink-300" : "bg-ink-50 text-ink-400"
            }`}
          >
            {current ? "Plan actual" : included ? "Incluido en tu plan" : "Incluido para todos"}
          </div>
        ) : asked ? (
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
        ) : (
          <button
            type="button"
            onClick={() => request.mutate()}
            disabled={request.isPending}
            className={`flex w-full items-center justify-center gap-2 rounded-full py-2.5 text-sm font-semibold transition-all duration-200 active:scale-[0.98] disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ${
              featured ? "bg-white text-ink-900 hover:bg-ink-100" : "bg-ink-900 text-white hover:bg-ink-700"
            }`}
          >
            {request.isPending ? <Spinner /> : card.cta}
          </button>
        )}
        {request.isError && (
          <p className="mt-2 text-center text-xs text-red-500">No se pudo enviar el pedido. Probá de nuevo.</p>
        )}
      </div>
    </article>
  );
}
