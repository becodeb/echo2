import { Link } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";

/** Lo que devuelve /api/billing/me (routers/billing.py). */
export interface BillingInfo {
  org_plan: string;
  user_plan: string;
  is_personal: boolean;
  people: {
    // always: cada reunión separa quién habló; credits: si lo pedís, gasta un
    // crédito; none: no quedan créditos este mes.
    mode: "always" | "credits" | "none";
    source: "organization" | "individual" | "credits";
    credits_per_month: number | null;
    credits_used: number;
    credits_left: number | null;
    people_hours_left: number | null;
    available: boolean;
  };
  features: { transcription: boolean; minutes: boolean; tasks: boolean; chat: boolean; paid: boolean };
  plans: PublicPlan[];
  requests: { id: string; plan: string; status: string; created_at: string }[];
  month_start: string;
  renews_at: string;
}

export interface PublicPlan {
  code: string;
  name: string;
  scope: string;
  price_usd: number | null;
  features: { people?: string; voice?: boolean };
  limits: Record<string, number>;
}

export function useBilling(enabled = true) {
  const { activeOrg } = useAuth();
  return useQuery({
    queryKey: ["billing", activeOrg?.id],
    queryFn: () => api<BillingInfo>("/api/billing/me"),
    enabled: enabled && !!activeOrg,
    staleTime: 30_000,
  });
}

export const PLAN_NAME: Record<string, string> = {
  base: "Gratis",
  individual: "Individual",
  individual_voz: "Individual + voz",
  institucion: "Instituciones",
  cortesia: "Cortesía",
  becode: "Cuenta Becode",
};

/** El plan que manda para esta persona en esta organización. */
export function effectivePlan(billing: BillingInfo): string {
  if (billing.org_plan !== "base") return billing.org_plan;
  if (billing.user_plan !== "base") return billing.user_plan;
  return "base";
}

/**
 * Los créditos del mes como puntos: cada punto es una reunión con quién habló.
 * Los gastados quedan huecos; al cambiar, el punto se vacía con una transición.
 */
export function CreditDots({
  total,
  left,
  size = "md",
  highlight = 0,
}: {
  total: number;
  left: number;
  size?: "sm" | "md" | "lg";
  // Cuántos de los disponibles se van a gastar (titilan, en "Nueva reunión").
  highlight?: number;
}) {
  const dot = { sm: "h-2 w-2", md: "h-2.5 w-2.5", lg: "h-3.5 w-3.5" }[size];
  const gap = { sm: "gap-1", md: "gap-1.5", lg: "gap-2" }[size];
  const shown = Math.min(total, 12);
  return (
    <span className={`inline-flex items-center ${gap}`} role="img" aria-label={`${left} de ${total} créditos disponibles`}>
      {Array.from({ length: shown }, (_, index) => {
        const available = index < left;
        const spending = available && index >= left - highlight;
        return (
          <span
            key={index}
            className={`${dot} rounded-full transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] ${
              spending
                ? "credit-spend bg-accent-500"
                : available
                  ? "bg-ink-900"
                  : "bg-transparent ring-[1.5px] ring-inset ring-ink-200"
            }`}
            style={{ transitionDelay: `${index * 40}ms` }}
          />
        );
      })}
    </span>
  );
}

/** Un número que llega contando a su valor (sin animación si se pidió menos movimiento). */
export function AnimatedNumber({
  value,
  format = (n) => Math.round(n).toLocaleString("es-AR"),
  duration = 700,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
}) {
  // Arranca de cero y cuenta hasta el valor (antes aparecía ya en el final).
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const start = from.current;
    if (reduce || start === value) {
      setShown(value);
      from.current = value;
      return;
    }
    let frame = 0;
    const began = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - began) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(start + (value - start) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return <span className="tabular-nums">{format(shown)}</span>;
}

export function formatUSD(value: number): string {
  if (value > 0 && value < 0.01) return "< US$ 0,01";
  return `US$ ${value.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatAudio(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toLocaleString("es-AR", { maximumFractionDigits: 1 })} M tokens`;
  if (tokens >= 1000) return `${Math.round(tokens / 1000).toLocaleString("es-AR")} mil tokens`;
  return `${Math.round(tokens)} tokens`;
}

export function renewsLabel(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleDateString("es-AR", { day: "numeric", month: "long" });
}

/** Skeleton redondeado para mientras carga. */
export function Shimmer({ className = "" }: { className?: string }) {
  return <span className={`block animate-pulse rounded-2xl bg-ink-100 ${className}`} />;
}

/** ¿La cuenta tiene un plan pago? undefined mientras carga (no se muestra el aviso). */
export function usePaid(): boolean | undefined {
  const { data } = useBilling();
  return data ? data.features.paid : undefined;
}

/** Lo que es de los planes pagos (Bauti, 1/10), con el camino a Planes. */
export function PaidOnly({ what, className = "" }: { what: string; className?: string }) {
  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl bg-accent-50 px-4 py-3 text-sm text-accent-700 ${className}`}>
      <span className="min-w-0 flex-1">{what} es parte de los planes pagos.</span>
      <Link to="/plans" className="inline-flex min-h-9 items-center rounded-full bg-ink-900 px-4 font-semibold text-white hover:bg-ink-700">
        Ver planes
      </Link>
    </div>
  );
}
