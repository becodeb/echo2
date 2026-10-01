import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { SegmentedToggle } from "../components/Toggles";
import { AnimatedNumber, formatAudio, formatTokens, formatUSD, Shimmer } from "../components/billing";
import { currentMonth } from "../lib/months";

export { currentMonth };
import { useAuth } from "../state/auth";

export interface UsageLine {
  kind: string;
  provider: string;
  model: string | null;
  unit: string;
  quantity: number;
  cost_usd: number;
  credits: number;
  events: number;
  price_unknown: boolean;
}

export interface PersonUsage {
  user_id: string | null;
  name: string;
  email: string | null;
  plan: string | null;
  cost_usd: number;
  credits: number;
  audio_seconds: number;
  tokens: number;
  lines: UsageLine[];
}

interface UsageOut {
  month: string;
  scope: "me" | "org";
  total_cost_usd: number;
  total_credits: number;
  people: PersonUsage[];
}

const KIND_LABEL: Record<string, string> = {
  stt_live: "En vivo",
  stt_final: "Al terminar",
  llm: "IA",
  voice: "Voz",
  embeddings: "Índice del chat",
};

const PROVIDER_LABEL: Record<string, string> = {
  groq: "Groq",
  elevenlabs: "ElevenLabs",
  openai: "OpenAI",
  anthropic: "Anthropic",
  deepgram: "Deepgram",
};

export function lineTitle(line: UsageLine): string {
  const who = PROVIDER_LABEL[line.provider] ?? line.provider;
  if (line.kind === "stt_final" && line.provider === "elevenlabs") return "Quién habló · ElevenLabs";
  return `${KIND_LABEL[line.kind] ?? line.kind} · ${who}`;
}

export function lineAmount(line: UsageLine): string {
  if (line.unit === "tokens") return formatTokens(line.quantity);
  if (line.unit === "voice_seconds") return formatAudio(line.quantity);
  return formatAudio(line.quantity);
}

export function monthLabel(month: string): string {
  const [year, number] = month.split("-").map(Number);
  const label = new Date(year, number - 1, 1).toLocaleDateString("es-AR", { month: "long", year: "numeric" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function shiftMonth(month: string, delta: number): string {
  const [year, number] = month.split("-").map(Number);
  const date = new Date(year, number - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

export function MonthPicker({ month, onChange }: { month: string; onChange: (month: string) => void }) {
  const isCurrent = month >= currentMonth();
  const arrow = "rounded-full p-2 text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900 disabled:opacity-30 disabled:hover:bg-transparent";
  return (
    <div className="inline-flex items-center gap-1 rounded-full border border-ink-100 bg-white p-1">
      <button type="button" className={arrow} onClick={() => onChange(shiftMonth(month, -1))} aria-label="Mes anterior">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M10 3 5 8l5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      <span className="min-w-[130px] text-center text-sm font-medium text-ink-800" aria-live="polite">{monthLabel(month)}</span>
      <button type="button" className={arrow} onClick={() => onChange(shiftMonth(month, 1))} disabled={isCurrent} aria-label="Mes siguiente">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="m6 3 5 5-5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
    </div>
  );
}

export function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-3xl border border-ink-100 bg-white p-4 sm:p-5">
      <p className="text-xs font-medium text-ink-400">{label}</p>
      {/* En el celular la cifra puede partirse en dos renglones antes que salirse de la tarjeta. */}
      <p className="mt-2 break-words text-[19px] font-semibold leading-tight tracking-tight text-ink-900 tabular-nums sm:whitespace-nowrap sm:text-[26px]">
        {children}
      </p>
    </div>
  );
}

/** Barras por proveedor y modelo, proporcionales al costo (o a la cantidad si no tiene precio). */
export function Breakdown({ lines }: { lines: UsageLine[] }) {
  const max = Math.max(...lines.map((line) => line.cost_usd), 0.000001);
  if (!lines.length) {
    return <p className="py-6 text-center text-sm text-ink-400">Sin consumo este mes.</p>;
  }
  return (
    <ul className="space-y-4">
      {lines.map((line) => (
        <li key={`${line.kind}-${line.provider}-${line.model}-${line.unit}`}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate font-medium text-ink-800">{lineTitle(line)}</span>
            <span className="shrink-0 tabular-nums text-ink-900">
              {line.price_unknown && line.cost_usd === 0 ? "sin precio" : formatUSD(line.cost_usd)}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-100">
            <div
              className="h-full origin-left rounded-full bg-ink-900 transition-transform duration-700 ease-[cubic-bezier(0.32,0.72,0,1)]"
              style={{ transform: `scaleX(${Math.max(line.cost_usd / max, 0.02)})` }}
            />
          </div>
          <p className="mt-1 text-xs text-ink-400">
            {lineAmount(line)}
            {line.model ? ` · ${line.model}` : ""}
            {line.credits ? ` · ${line.credits} ${line.credits === 1 ? "crédito" : "créditos"}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

function sum(lines: UsageLine[]) {
  const merged = new Map<string, UsageLine>();
  for (const line of lines) {
    const key = `${line.kind}|${line.provider}|${line.model}|${line.unit}`;
    const current = merged.get(key);
    if (!current) merged.set(key, { ...line });
    else {
      current.quantity += line.quantity;
      current.cost_usd += line.cost_usd;
      current.credits += line.credits;
      current.events += line.events;
      current.price_unknown ||= line.price_unknown;
    }
  }
  return [...merged.values()].sort((a, b) => b.cost_usd - a.cost_usd);
}

export default function Usage() {
  const { activeOrg } = useAuth();
  const isAdmin = activeOrg?.role === "owner" || activeOrg?.role === "admin";
  const [month, setMonth] = useState(currentMonth);
  const [scope, setScope] = useState<"me" | "org">("me");
  const effectiveScope = isAdmin && !activeOrg?.is_personal ? scope : "me";

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["usage", activeOrg?.id, effectiveScope, month],
    queryFn: () => api<UsageOut>(`/api/billing/usage?scope=${effectiveScope}&month=${month}`),
    placeholderData: keepPreviousData,
  });

  const lines = useMemo(() => sum((data?.people ?? []).flatMap((person) => person.lines)), [data]);
  const audio = (data?.people ?? []).reduce((total, person) => total + person.audio_seconds, 0);
  const tokens = (data?.people ?? []).reduce((total, person) => total + person.tokens, 0);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8 sm:py-10">
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-ink-400">Consumo</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink-900">
            {effectiveScope === "org" ? `Lo que usó ${activeOrg?.name}` : "Lo que usaste"}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {isAdmin && !activeOrg?.is_personal && (
            <div className="w-56">
              <SegmentedToggle
                ariaLabel="De quién"
                value={scope}
                onChange={setScope}
                options={[
                  { value: "me", label: "Yo" },
                  { value: "org", label: "Organización" },
                ]}
              />
            </div>
          )}
          <MonthPicker month={month} onChange={setMonth} />
        </div>
      </header>

      <div className={`transition-opacity duration-300 ${isFetching && !isLoading ? "opacity-60" : "opacity-100"}`}>
        {isLoading || !data ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((index) => <Shimmer key={index} className="h-[104px]" />)}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Costo estimado">
              <AnimatedNumber value={data.total_cost_usd} format={formatUSD} />
            </Stat>
            <Stat label="Audio transcripto">
              <AnimatedNumber value={audio} format={formatAudio} />
            </Stat>
            <Stat label="Créditos usados">
              <AnimatedNumber value={data.total_credits} />
            </Stat>
            <Stat label="IA (tokens)">
              <AnimatedNumber value={tokens} format={(n) => formatTokens(n).replace(/ tokens$/, "")} />
            </Stat>
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.2fr]">
          <section className="rounded-3xl border border-ink-100 bg-white p-6">
            <h2 className="mb-5 text-[15px] font-semibold text-ink-900">Por servicio</h2>
            {isLoading ? <Shimmer className="h-40" /> : <Breakdown lines={lines} />}
          </section>
          {effectiveScope === "org" && data && (
            <section className="rounded-3xl border border-ink-100 bg-white p-6">
              <h2 className="mb-5 text-[15px] font-semibold text-ink-900">Por persona</h2>
              <PeopleTable people={data.people} />
            </section>
          )}
          {effectiveScope === "me" && (
            <section className="rounded-3xl border border-ink-100 bg-ink-50/50 p-6 text-sm leading-relaxed text-ink-500">
              <h2 className="mb-3 text-[15px] font-semibold text-ink-900">Cómo se cuenta</h2>
              <p>
                Cada minuto de audio que Echo transcribe y cada pedido a la IA tiene un costo. Lo mostramos en dólares,
                al precio de cada servicio, para que sepas qué se usa y cuánto.
              </p>
              <p className="mt-3">
                Una reunión con quién habló gasta un crédito (dos si dura más de una hora). La IA de un modelo sin precio
                publicado se cuenta en tokens.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export function PeopleTable({ people }: { people: PersonUsage[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const max = Math.max(...people.map((person) => person.cost_usd), 0.000001);
  if (!people.length) return <p className="py-6 text-center text-sm text-ink-400">Nadie usó Echo este mes.</p>;
  return (
    <ul className="divide-y divide-ink-100">
      {people.map((person) => {
        const key = person.user_id ?? person.name;
        const expanded = open === key;
        return (
          <li key={key}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : key)}
              aria-expanded={expanded}
              className="flex w-full items-center gap-3 rounded-xl py-3 text-left transition-colors hover:bg-ink-50/70"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-800">{person.name}</p>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-ink-100">
                  <div
                    className="h-full origin-left rounded-full bg-ink-900 transition-transform duration-700"
                    style={{ transform: `scaleX(${person.cost_usd / max})` }}
                  />
                </div>
              </div>
              <span className="w-24 shrink-0 text-right text-sm tabular-nums text-ink-900">{formatUSD(person.cost_usd)}</span>
              <svg
                width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden
                className={`shrink-0 text-ink-400 transition-transform duration-300 ${expanded ? "rotate-180" : ""}`}
              >
                <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <div className="reveal-grid" data-open={expanded}>
              <div>
                <div className="pb-4 pl-1 pt-1">
                  <p className="mb-3 text-xs text-ink-400">
                    {formatAudio(person.audio_seconds)} de audio · {person.credits} créditos · {formatTokens(person.tokens)}
                  </p>
                  <Breakdown lines={person.lines} />
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
