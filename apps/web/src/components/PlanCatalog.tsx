import type { ReactNode } from "react";
import type { PublicPlan } from "./billing";

/**
 * Lo que trae cada plan, en un solo lugar: lo usan la pantalla de Planes y la
 * landing (docs/plan-correcciones.md §3.3-3.4). Las diferencias las eligió
 * Bauti el 1/10 y la app las aplica (services/plans.py, is_paid): si se cambia
 * algo acá, se cambia también allá.
 */

export interface PlanSpec {
  plan: PublicPlan;
  tagline: string;
  bullets: string[];
}

function byCode(plans: PublicPlan[]): Record<string, PublicPlan> {
  return Object.fromEntries(plans.map((plan) => [plan.code, plan]));
}

export function planSpecs(plans: PublicPlan[]): PlanSpec[] {
  const code = byCode(plans);
  const out: PlanSpec[] = [];
  if (code.base) {
    const credits = code.base.limits.credits_per_month ?? 4;
    out.push({
      plan: code.base,
      tagline: "Para empezar, sin pagar nada.",
      bullets: [
        "Reuniones de hasta 1 hora, transcriptas en vivo",
        `${credits} reuniones por mes con quién habló`,
        "Acta, resumen y tareas con responsables",
        "Preguntale a Echo sobre cada reunión",
        "Exportar en PDF",
      ],
    });
  }
  if (code.individual) {
    const hours = code.individual.limits.people_hours_per_month ?? 5;
    out.push({
      plan: code.individual,
      tagline: "Para quien graba sus propias reuniones.",
      bullets: [
        "Todo lo de Gratis, sin límite de duración",
        `${hours} h por mes con quién habló`,
        "Preguntale a Echo sobre todas tus reuniones",
        "Word, Documento de Google y tu Drive",
        "Subí grabaciones de Zoom, Meet o el celular",
        "Soporte prioritario",
      ],
    });
  }
  if (code.institucion) {
    out.push({
      plan: code.institucion,
      tagline: "Para todo el colegio, con sus sedes y niveles.",
      bullets: [
        "Todo lo de Individual para cada docente",
        "Quién habló en todas las reuniones",
        "Membrete, formato y numeración de actas propios",
        "Sedes, niveles, familias y equipos",
        "Consumo por docente y Echo Devices para las salas",
        "Te acompañamos a empezar",
      ],
    });
  }
  return out;
}

type Cell = boolean | string;

/** La tabla "Comparar planes": Gratis, Individual, Instituciones. */
export function compareRows(plans: PublicPlan[]): { label: string; cells: Cell[] }[] {
  const code = byCode(plans);
  const credits = code.base?.limits.credits_per_month ?? 4;
  const hours = code.individual?.limits.people_hours_per_month ?? 5;
  return [
    { label: "Transcripción en vivo", cells: [true, true, true] },
    { label: "Duración de cada reunión", cells: ["Hasta 1 h", "Sin límite", "Sin límite"] },
    { label: "Quién habló", cells: [`${credits} reuniones / mes`, `${hours} h / mes`, "Todas"] },
    { label: "Acta, resumen y tareas", cells: [true, true, true] },
    { label: "Los nombres no le llegan a la IA", cells: [true, true, true] },
    { label: "Preguntale a Echo sobre cada reunión", cells: [true, true, true] },
    { label: "Preguntale a Echo sobre todas", cells: [false, true, true] },
    { label: "Exportar en PDF", cells: [true, true, true] },
    { label: "Word, Documento de Google y Drive", cells: [false, true, true] },
    { label: "Subir grabaciones (Zoom, Meet)", cells: [false, true, true] },
    { label: "Membrete y actas numeradas", cells: [true, true, true] },
    { label: "Sedes, niveles y consumo por docente", cells: [false, false, true] },
    { label: "Echo Devices", cells: [false, false, true] },
    { label: "Soporte", cells: ["Por mail", "Prioritario", "Acompañamiento"] },
  ];
}

export function priceLabel(plan: PublicPlan): { amount: string; per: string | null } {
  if (plan.price_usd == null) return { amount: "A medida", per: null };
  return { amount: plan.price_usd === 0 ? "US$ 0" : `US$ ${plan.price_usd.toLocaleString("es-AR")}`, per: "/ mes" };
}

function Check({ inverse = false }: { inverse?: boolean }) {
  return (
    <span
      aria-hidden
      className={`mt-[3px] flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
        inverse ? "bg-white text-ink-900" : "bg-ink-900 text-white"
      }`}
    >
      <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
        <path d="M2.5 6.2 5 8.5l4.5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/** Una tarjeta de plan; el botón (o lo que va abajo) lo pone quien la usa. */
export function PlanCard({
  spec,
  featured = false,
  badge,
  delay = 0,
  children,
}: {
  spec: PlanSpec;
  featured?: boolean;
  badge?: string;
  delay?: number;
  children: ReactNode;
}) {
  const price = priceLabel(spec.plan);
  return (
    <article
      className={`animate-fade-up relative flex flex-col rounded-3xl border p-6 transition-shadow duration-300 hover:shadow-[0_12px_32px_-12px_rgba(20,24,36,0.18)] ${
        featured ? "border-ink-900 bg-ink-950 text-white" : "border-ink-100 bg-white"
      }`}
      style={{ animationDelay: `${delay}ms`, animationFillMode: "backwards" }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className={`text-lg font-semibold ${featured ? "text-white" : "text-ink-900"}`}>{spec.plan.name}</h3>
        {badge && (
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              featured ? "bg-white text-ink-900" : "bg-ink-100 text-ink-700"
            }`}
          >
            {badge}
          </span>
        )}
      </div>
      <p className={`mt-1 text-sm ${featured ? "text-ink-300" : "text-ink-500"}`}>{spec.tagline}</p>
      <div className="mt-6 flex items-baseline gap-1.5">
        <span
          className={`${price.per ? "text-[40px] leading-none" : "text-[28px]"} font-semibold tracking-tight ${
            featured ? "text-white" : "text-ink-900"
          }`}
        >
          {price.amount}
        </span>
        {price.per && <span className={`text-sm ${featured ? "text-ink-300" : "text-ink-400"}`}>{price.per}</span>}
      </div>
      <ul className="mt-6 flex-1 space-y-3">
        {spec.bullets.map((bullet) => (
          <li key={bullet} className="flex items-start gap-2.5 text-sm">
            <Check inverse={featured} />
            <span className={featured ? "text-ink-200" : "text-ink-600"}>{bullet}</span>
          </li>
        ))}
      </ul>
      <div className="mt-8">{children}</div>
    </article>
  );
}

/** "Comparar planes", tipo ElevenLabs: una fila por cosa que cambia. */
export function CompareTable({ plans }: { plans: PublicPlan[] }) {
  const specs = planSpecs(plans);
  const rows = compareRows(plans);
  return (
    <div className="relative overflow-x-auto rounded-3xl border border-ink-100 bg-white">
      <table className="w-full min-w-[640px] text-left text-sm">
        <caption className="sr-only">Comparar planes</caption>
        <thead>
          <tr className="border-b border-ink-100">
            <th scope="col" className="px-5 py-4 font-medium text-ink-500">
              Qué incluye
            </th>
            {specs.map((spec) => (
              <th key={spec.plan.code} scope="col" className="px-4 py-4 text-center font-semibold text-ink-900">
                {spec.plan.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-ink-50 last:border-0">
              <th scope="row" className="px-5 py-3 font-normal text-ink-700">
                {row.label}
              </th>
              {row.cells.slice(0, specs.length).map((cell, index) => (
                <td key={index} className="px-4 py-3 text-center text-ink-700">
                  {cell === true ? (
                    <span className="inline-flex justify-center" aria-label="Sí">
                      <Check />
                    </span>
                  ) : cell === false ? (
                    <span className="text-ink-300" aria-label="No">
                      —
                    </span>
                  ) : (
                    cell
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
