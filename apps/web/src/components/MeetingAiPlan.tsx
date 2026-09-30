import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CreditDots,
  renewsLabel,
  Shimmer,
  useBilling,
  type BillingInfo,
} from "./billing";

/**
 * "Lo que va a hacer Echo" en una reunión nueva, según el plan y los créditos
 * (services/plans.py): transcripción, quién habló (y si gasta un crédito),
 * acta, tareas con responsables, chat, voz. Y el interruptor de menores: con
 * alumnos hablando, la reunión no se manda a separar voces.
 */
export function MeetingAiPlan({
  people,
  onPeople,
  minors,
  onMinors,
  minutes,
  enabled,
}: {
  people: boolean;
  onPeople: (value: boolean) => void;
  minors: boolean;
  onMinors: (value: boolean) => void;
  // Si esta reunión va a tener acta (las internas solo si se pidió).
  minutes: boolean;
  enabled: boolean;
}) {
  const { data: billing, isLoading } = useBilling(enabled);

  if (isLoading || !billing) {
    return (
      <div
        className="space-y-2 rounded-2xl border border-ink-100 p-4"
        aria-busy="true"
      >
        <Shimmer className="h-4 w-40" />
        <Shimmer className="h-10 w-full" />
        <Shimmer className="h-4 w-2/3" />
      </div>
    );
  }

  const { features } = billing;
  return (
    <section
      className="overflow-hidden rounded-2xl border border-ink-100 bg-white"
      aria-label="Lo que va a hacer Echo"
    >
      <header className="flex items-center justify-between gap-3 border-b border-ink-100 bg-ink-50/60 px-4 py-2.5">
        <h3 className="text-[13px] font-semibold text-ink-800">
          Lo que va a hacer Echo
        </h3>
        <Link
          to="/plans"
          className="text-xs font-medium text-ink-500 transition-colors hover:text-ink-900"
        >
          Ver planes
        </Link>
      </header>
      <ul className="divide-y divide-ink-100">
        <Row
          on
          label="Transcripción"
          hint="En vivo mientras hablan, y completa al terminar."
        />
        <PeopleRow
          billing={billing}
          people={people}
          onPeople={onPeople}
          minors={minors}
        />
        <Row
          on={features.minutes && minutes}
          label="Acta y resumen"
          hint={
            !minutes
              ? "Sin acta en esta reunión."
              : !features.minutes
                ? NO_AI
                : undefined
          }
        />
        <Row
          on={features.tasks}
          label="Tareas con responsables"
          hint={features.tasks ? undefined : NO_AI}
        />
        <Row
          on={features.chat}
          label="Chat con la IA sobre la reunión"
          hint={features.chat ? undefined : NO_AI}
        />
        {features.voice && (
          <Row
            on={false}
            label="Conversación por voz"
            hint="Muy pronto en tu plan."
          />
        )}
      </ul>
      <div className="border-t border-ink-100 px-4 py-3">
        <Toggle
          checked={minors}
          onChange={onMinors}
          label="Hablan alumnos (menores de 18)"
          hint={
            minors
              ? "Se transcribe sin separar quién habló: el servicio que separa las voces no admite voces de menores."
              : "Activalo si en la reunión habla algún alumno o alumna."
          }
        />
      </div>
    </section>
  );
}

const NO_AI =
  "Falta configurar la IA de la organización (Ajustes → IA y transcripción).";

function PeopleRow({
  billing,
  people,
  onPeople,
  minors,
}: {
  billing: BillingInfo;
  people: boolean;
  onPeople: (value: boolean) => void;
  minors: boolean;
}) {
  const access = billing.people;
  if (minors) {
    return (
      <Row
        on={false}
        label="Quién habló"
        hint="No se separa: hablan menores de 18."
      />
    );
  }
  if (!access.available) {
    return (
      <Row
        on={false}
        label="Quién habló"
        hint="No está disponible por ahora."
      />
    );
  }
  if (access.mode === "always") {
    const hint =
      access.source === "individual" && access.people_hours_left != null
        ? `Incluido en tu plan · te quedan ${formatHours(access.people_hours_left)} este mes.`
        : "Incluido en el plan de tu institución.";
    return <Row on label="Quién habló" hint={hint} />;
  }
  const total = access.credits_per_month ?? 0;
  const left = access.credits_left ?? 0;
  if (access.mode === "none") {
    return (
      <Row
        on={false}
        label="Quién habló"
        hint={
          <>
            Ya usaste tus {total} créditos del mes. Se renuevan el{" "}
            {renewsLabel(billing.renews_at)}.{" "}
            <Link
              to="/plans"
              className="font-medium text-ink-800 underline-offset-2 hover:underline"
            >
              Ver planes
            </Link>
          </>
        }
        aside={<CreditDots total={total} left={0} size="sm" />}
      />
    );
  }
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <Mark on={people} />
      <div className="min-w-0 flex-1">
        <Toggle
          checked={people}
          onChange={onPeople}
          label="Quién habló"
          hint={
            people
              ? `Al terminar, Echo separa a cada persona. Gasta 1 crédito (2 si dura más de una hora).`
              : `Te quedan ${left} de ${total} créditos este mes. Activalo solo si lo necesitás.`
          }
          extra={
            <CreditDots
              total={total}
              left={left}
              size="sm"
              highlight={people ? 1 : 0}
            />
          }
        />
      </div>
    </li>
  );
}

function formatHours(hours: number): string {
  if (hours >= 1)
    return `${hours.toLocaleString("es-AR", { maximumFractionDigits: 1 })} h`;
  return `${Math.round(hours * 60)} min`;
}

function Mark({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors duration-300 ${
        on ? "bg-ink-900 text-white" : "bg-ink-100 text-ink-400"
      }`}
    >
      {on ? (
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
          <path
            d="M2.5 6.2 5 8.5l4.5-5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : (
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
          <path
            d="M3 6h6"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      )}
    </span>
  );
}

function Row({
  on,
  label,
  hint,
  aside,
}: {
  on: boolean;
  label: string;
  hint?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <Mark on={on} />
      <div className="min-w-0 flex-1">
        <p
          className={`text-sm font-medium ${on ? "text-ink-800" : "text-ink-500"}`}
        >
          {label}
          <span className="sr-only">{on ? " (sí)" : " (no)"}</span>
        </p>
        {hint && (
          <p className="mt-0.5 text-xs leading-relaxed text-ink-400">{hint}</p>
        )}
      </div>
      {aside && <span className="mt-1 shrink-0">{aside}</span>}
    </li>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  hint,
  extra,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
  extra?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink-800">
          {label}
          {extra}
        </p>
        {hint && (
          <p
            key={hint}
            className="animate-fade-up mt-0.5 text-xs leading-relaxed text-ink-400"
          >
            {hint}
          </p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-[26px] w-[44px] shrink-0 rounded-full transition-colors duration-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ${
          checked ? "bg-ink-900" : "bg-ink-200"
        }`}
      >
        <span
          aria-hidden
          className="absolute left-[3px] top-[3px] h-5 w-5 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.25)] transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
          style={{ transform: checked ? "translateX(18px)" : "translateX(0)" }}
        />
      </button>
    </div>
  );
}
