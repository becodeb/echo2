import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { PublicPlan } from "../components/billing";
import { CompareTable, PlanCard, planSpecs } from "../components/PlanCatalog";
import { Reveal } from "./Reveal";

/**
 * Precios en la landing (docs/plan-correcciones.md §3.3): las mismas tarjetas
 * que la pantalla de Planes, con los precios y topes de la base, y la tabla
 * para comparar. Sin sesión: GET /api/billing/plans.
 */
export function Pricing() {
  const [plans, setPlans] = useState<PublicPlan[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/billing/plans")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => !cancelled && setPlans(data))
      .catch(() => !cancelled && setPlans(null));
    return () => {
      cancelled = true;
    };
  }, []);

  const specs = plans ? planSpecs(plans) : [];

  return (
    <Reveal id="precios" className="mx-auto max-w-6xl scroll-mt-20 px-6 py-24 md:px-12 md:py-32">
      <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">Precios</h2>
      <p className="mt-4 max-w-xl leading-relaxed text-ink-600 md:text-lg">
        Empezá gratis. Todas las reuniones se transcriben; los planes pagos suman reuniones largas, quién habló
        en más reuniones, preguntarle a Echo por todo el año y hablarle por voz.
      </p>
      <div className="mt-12 grid gap-4 md:grid-cols-3">
        {plans === null
          ? [0, 1, 2, 3].map((index) => <div key={index} className="h-[440px] animate-pulse rounded-3xl bg-ink-100/70" />)
          : specs.map((spec, index) => {
              const featured = spec.plan.code === "individual_voz";
              const sales = spec.plan.code === "institucion";
              return (
                <PlanCard key={spec.plan.code} spec={spec} featured={featured} delay={index * 60}>
                  <Link
                    to={sales ? "/contacto?tema=ventas" : "/register"}
                    className={`flex min-h-11 w-full items-center justify-center rounded-full text-sm font-semibold transition-colors ${
                      featured ? "bg-white text-ink-900 hover:bg-ink-100" : "bg-ink-900 text-white hover:bg-ink-700"
                    }`}
                  >
                    {sales ? "Contact sales" : spec.plan.price_usd === 0 ? "Empezar gratis" : "Empezar"}
                  </Link>
                </PlanCard>
              );
            })}
      </div>
      {plans && (
        <>
          <h3 className="mb-5 mt-16 text-2xl font-semibold tracking-tight text-ink-950">Comparar planes</h3>
          <CompareTable plans={plans} />
        </>
      )}
      <p className="mt-6 text-sm text-ink-500">
        Precios en dólares, por mes. Todavía no se cobra desde Echo: al elegir un plan pago te escribimos para darlo de
        alta.
      </p>
    </Reveal>
  );
}
