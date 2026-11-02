import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ScheduledMeetingOut } from "../api/types";
import { NewMeetingModal } from "../components/NewMeetingModal";
import { ScheduleModal } from "../components/ScheduleModal";
import { Select } from "../components/Select";
import { Button, Spinner } from "../components/ui";
import {
  addDays,
  agendaTitle,
  dayLabel,
  isoDay,
  monthGrid,
  monthLabel,
  parseDay,
  shiftMonth,
  shortWeekday,
  weekStart,
} from "../lib/agenda";
import { useAuth } from "../state/auth";
import { useMyAccess } from "../state/access";

/**
 * Agenda: las reuniones de cada día, cargadas de antemano. El día llega, se
 * toca "Empezar" y la reunión arranca con familia, alumno, motivo y quiénes
 * van. La hora es opcional: alcanza con el día.
 */
export default function Agenda() {
  const { activeOrg } = useAuth();
  const { data: myAccess } = useMyAccess();
  const queryClient = useQueryClient();
  const today = isoDay(new Date());
  const [params, setParams] = useSearchParams();
  const day = /^\d{4}-\d{2}-\d{2}$/.test(params.get("dia") ?? "") ? params.get("dia")! : today;
  const setDay = (next: string) => {
    const query = new URLSearchParams(params);
    if (next === today) query.delete("dia");
    else query.set("dia", next);
    setParams(query, { replace: true });
  };
  // "Todo mi nivel": para quien ve todo un nivel o administra la sede.
  const seesLevel = !!myAccess && (myAccess.sees_everything || Object.values(myAccess.access).includes("total"));
  const [scope, setScope] = useState<"mine" | "nivel">("mine");

  const [scheduling, setScheduling] = useState(false);
  const [editing, setEditing] = useState<ScheduledMeetingOut | null>(null);
  const [starting, setStarting] = useState<ScheduledMeetingOut | null>(null);

  // Una sola consulta por mes: la grilla del calendario contiene la semana elegida.
  const grid = monthGrid(day);
  const start = grid[0][0].iso;
  const end = grid.at(-1)!.at(-1)!.iso;
  const { data: items, isLoading } = useQuery({
    queryKey: ["agenda", activeOrg?.id, start, end, scope],
    queryFn: () => api<ScheduledMeetingOut[]>(`/api/agenda?start=${start}&end=${end}&scope=${scope}`),
    enabled: !!activeOrg,
  });
  const { data: pending } = useQuery({
    queryKey: ["agenda", activeOrg?.id, "pending", today],
    queryFn: () => api<ScheduledMeetingOut[]>(`/api/agenda/pending?today=${today}`),
    enabled: !!activeOrg,
  });

  const byDay = new Map<string, ScheduledMeetingOut[]>();
  for (const item of items ?? []) {
    if (item.status === "no_se_hizo") continue;
    byDay.set(item.date, [...(byDay.get(item.date) ?? []), item]);
  }
  const dayItems = (items ?? []).filter((item) => item.date === day);
  const monday = weekStart(day);
  // Lunes a viernes; sábado y domingo solo si tienen algo o están elegidos.
  const week = Array.from({ length: 7 }, (_, index) => addDays(monday, index)).filter(
    (iso, index) => index < 5 || byDay.has(iso) || iso === day,
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Agenda</h1>
          <p className="mt-1 text-sm text-ink-500">
            Las reuniones que vienen, ya cargadas. El día llegás, tocás «Empezar» y grabás.
          </p>
        </div>
        <Button onClick={() => setScheduling(true)}>+ Agendar reunión</Button>
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-2">
        {/* En el teléfono los días van en una fila de columnas iguales, como el calendario. */}
        <div role="group" aria-label="Semana" className="flex w-full items-center gap-1.5 sm:w-auto sm:gap-2">
          <button
            type="button"
            aria-label="Semana anterior"
            onClick={() => setDay(addDays(monday, -7))}
            className="flex h-11 w-9 shrink-0 items-center justify-center rounded-full bg-ink-100 text-ink-700 hover:bg-ink-200 sm:w-11"
          >
            ‹
          </button>
          <div className="grid min-w-0 flex-1 gap-1.5 sm:flex sm:gap-2" style={{ gridTemplateColumns: `repeat(${week.length}, minmax(0, 1fr))` }}>
            {week.map((iso) => {
              const count = byDay.get(iso)?.length ?? 0;
              const selected = iso === day;
              return (
                <button
                  key={iso}
                  type="button"
                  aria-pressed={selected}
                  aria-label={`${dayLabel(iso)}${count ? `, ${count} ${count === 1 ? "reunión" : "reuniones"}` : ", libre"}`}
                  onClick={() => setDay(iso)}
                  className={`flex min-h-16 flex-col items-center rounded-2xl px-1 py-2 transition-colors sm:min-w-[5.5rem] sm:items-start sm:px-3.5 sm:text-left ${
                    selected ? "bg-ink-900 text-white" : "border border-ink-200 bg-white text-ink-900 hover:border-ink-300"
                  }`}
                >
                  <span className={`text-xs ${selected ? "text-white/80" : "text-ink-500"}`}>
                    {iso === today ? (
                      <>
                        Hoy<span className="hidden sm:inline"> · {shortWeekday(iso)}</span>
                      </>
                    ) : (
                      shortWeekday(iso)
                    )}
                  </span>
                  <span className="text-lg font-bold leading-tight">{parseDay(iso).getDate()}</span>
                  <span className={`text-xs ${selected ? "text-white/85" : count ? "text-ink-600" : "text-ink-400"}`}>
                    <span className="sm:hidden">{count ? count : "–"}</span>
                    <span className="hidden sm:inline">
                      {count ? `${count} ${count === 1 ? "reunión" : "reuniones"}` : "Libre"}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            aria-label="Semana siguiente"
            onClick={() => setDay(addDays(monday, 7))}
            className="flex h-11 w-9 shrink-0 items-center justify-center rounded-full bg-ink-100 text-ink-700 hover:bg-ink-200 sm:w-11"
          >
            ›
          </button>
        </div>
        {day !== today && (
          <Button variant="ghost" onClick={() => setDay(today)}>
            Hoy
          </Button>
        )}
        {seesLevel && (
          <Select
            ariaLabel="Qué reuniones ver"
            size="sm"
            className="ml-auto w-44"
            value={scope}
            onChange={(value) => setScope(value as "mine" | "nivel")}
            options={[
              { value: "mine", label: "Mis reuniones" },
              { value: "nivel", label: "Todo mi nivel" },
            ]}
          />
        )}
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <section aria-labelledby="agenda-dia" className="min-w-0 flex-[999_1_32rem] space-y-3">
          <h2 id="agenda-dia" className="text-lg font-semibold text-ink-900">
            {dayLabel(day)}{" "}
            <span className="font-normal text-ink-500">
              · {dayItems.length ? `${dayItems.length} ${dayItems.length === 1 ? "reunión" : "reuniones"}` : "sin reuniones"}
            </span>
          </h2>
          {isLoading && (
            <div className="flex justify-center py-12 text-ink-400">
              <Spinner className="h-6 w-6" />
            </div>
          )}
          {items && dayItems.length === 0 && (
            <div className="rounded-3xl border border-dashed border-ink-200 px-6 py-10 text-center">
              <p className="text-sm text-ink-500">No hay reuniones agendadas para este día.</p>
              <Button variant="soft" className="mt-3" onClick={() => setScheduling(true)}>
                Agendar una
              </Button>
            </div>
          )}
          {dayItems.map((item) => (
            <AgendaItem key={item.id} item={item} onStart={() => setStarting(item)} onEdit={() => setEditing(item)} />
          ))}
        </section>

        <aside className="w-full max-w-sm flex-[1_1_17rem] space-y-4">
          <MonthCalendar day={day} today={today} counts={byDay} onPick={setDay} />
          {pending && pending.length > 0 && (
            <PendingBox
              items={pending}
              onChanged={() => queryClient.invalidateQueries({ queryKey: ["agenda"] })}
            />
          )}
        </aside>
      </div>

      {scheduling && (
        <ScheduleModal
          open
          draft={{ date: day < today ? today : day }}
          onClose={() => setScheduling(false)}
          onSaved={(item) => setDay(item.date)}
        />
      )}
      {editing && (
        <ScheduleModal key={editing.id} open editing={editing} onClose={() => setEditing(null)} onSaved={(item) => setDay(item.date)} />
      )}
      {starting && <NewMeetingModal key={starting.id} open scheduled={starting} onClose={() => setStarting(null)} />}
    </div>
  );
}

function AgendaItem({
  item,
  onStart,
  onEdit,
}: {
  item: ScheduledMeetingOut;
  onStart: () => void;
  onEdit: () => void;
}) {
  const { title, detail } = agendaTitle(item);
  const live = item.meeting_status === "live" || item.meeting_status === "paused";
  const processing = item.meeting_status === "processing";
  const done = !!item.meeting_id && !live && !processing && item.meeting_status !== "draft";
  const skipped = item.status === "no_se_hizo";
  const people = item.staff.map((person) => person.name).join(", ");
  const sub = [item.reason_name, people ? `Con ${people}` : "", item.kind === "interna" ? "Solo lo ve el grupo" : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <article
      className={`flex flex-wrap items-center gap-x-4 gap-y-3 rounded-3xl border bg-white px-4 py-4 sm:px-5 ${
        live ? "border-red-200" : "border-ink-100"
      } ${skipped ? "opacity-60" : ""}`}
    >
      <div className="w-16 shrink-0">
        {item.time ? (
          <p className="text-base font-bold text-ink-900">{item.time}</p>
        ) : (
          <p className="text-sm font-semibold text-ink-400">Sin hora</p>
        )}
      </div>
      <div className="min-w-0 flex-[1_1_15rem]">
        <p className="font-semibold text-ink-900">
          {title} {detail && <span className="font-medium text-ink-500">· {detail}</span>}
        </p>
        {sub && <p className="mt-0.5 text-sm text-ink-500">{sub}</p>}
        {item.note && <p className="mt-1 text-sm text-ink-500">Nota: {item.note}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {skipped ? (
          <StatusPill tone="gray">No se hizo</StatusPill>
        ) : live ? (
          <StatusPill tone="red">En curso</StatusPill>
        ) : processing ? (
          <StatusPill tone="indigo">Armando el acta</StatusPill>
        ) : done ? (
          <StatusPill tone="green">Hecha</StatusPill>
        ) : (
          <StatusPill tone="indigo">Agendada</StatusPill>
        )}
        {item.meeting_id ? (
          <Link
            to={live ? `/meetings/${item.meeting_id}/live` : `/meetings/${item.meeting_id}${done ? "?tab=minutes" : ""}`}
            className="inline-flex min-h-11 items-center rounded-full bg-ink-100 px-4 text-sm font-semibold text-ink-900 hover:bg-ink-200"
          >
            {live ? "Volver" : done ? "Ver acta" : "Abrir"}
          </Link>
        ) : (
          !skipped && (
            <>
              {item.can_edit && (
                <Button variant="ghost" onClick={onEdit} aria-label={`Cambiar la reunión con ${title}`}>
                  Cambiar
                </Button>
              )}
              <button
                type="button"
                onClick={onStart}
                className="inline-flex min-h-11 items-center gap-2 rounded-full bg-accent-600 px-5 text-sm font-semibold text-white hover:bg-accent-700"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
                </svg>
                Empezar
              </button>
            </>
          )
        )}
      </div>
    </article>
  );
}

function StatusPill({ tone, children }: { tone: "green" | "red" | "indigo" | "gray"; children: string }) {
  const tones = {
    green: "bg-emerald-50 text-emerald-700",
    red: "bg-red-50 text-red-700",
    indigo: "bg-accent-50 text-accent-700",
    gray: "bg-ink-100 text-ink-600",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tones[tone]}`}>
      {tone === "red" && <span aria-hidden className="h-2 w-2 rounded-full bg-red-500" />}
      {children}
    </span>
  );
}

function MonthCalendar({
  day,
  today,
  counts,
  onPick,
}: {
  day: string;
  today: string;
  counts: Map<string, ScheduledMeetingOut[]>;
  onPick: (iso: string) => void;
}) {
  const grid = monthGrid(day);
  return (
    <section aria-labelledby="agenda-mes" className="rounded-3xl border border-ink-100 bg-white p-4">
      <div className="mb-3 flex items-center gap-1">
        <h2 id="agenda-mes" className="flex-1 font-semibold text-ink-900">
          {monthLabel(day)}
        </h2>
        <button
          type="button"
          aria-label="Mes anterior"
          onClick={() => onPick(shiftMonth(day, -1))}
          className="flex h-9 w-9 items-center justify-center rounded-full text-ink-600 hover:bg-ink-100"
        >
          ‹
        </button>
        <button
          type="button"
          aria-label="Mes siguiente"
          onClick={() => onPick(shiftMonth(day, 1))}
          className="flex h-9 w-9 items-center justify-center rounded-full text-ink-600 hover:bg-ink-100"
        >
          ›
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-sm">
        {["L", "M", "M", "J", "V", "S", "D"].map((letter, index) => (
          <span key={index} aria-hidden className="pb-1 text-xs font-semibold text-ink-400">
            {letter}
          </span>
        ))}
        {grid.flat().map(({ iso, inMonth }) => {
          const count = counts.get(iso)?.length ?? 0;
          const selected = iso === day;
          return (
            <button
              key={iso}
              type="button"
              onClick={() => onPick(iso)}
              aria-label={`${dayLabel(iso)}${count ? `, ${count} ${count === 1 ? "reunión" : "reuniones"}` : ""}`}
              aria-pressed={selected}
              className={`relative flex h-9 items-center justify-center rounded-xl ${
                selected
                  ? "bg-ink-900 font-bold text-white"
                  : count
                    ? "font-bold text-accent-700 hover:bg-accent-50"
                    : inMonth
                      ? "text-ink-700 hover:bg-ink-100"
                      : "text-ink-300 hover:bg-ink-50"
              } ${iso === today && !selected ? "ring-1 ring-ink-300" : ""}`}
            >
              {parseDay(iso).getDate()}
              {count > 0 && !selected && <span aria-hidden className="absolute bottom-1 h-1 w-1 rounded-full bg-accent-500" />}
            </button>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-ink-500">Los días con reuniones agendadas, en azul.</p>
    </section>
  );
}

/** Las que quedaron sin hacer en días anteriores: pasarlas a otro día o descartarlas. */
function PendingBox({ items, onChanged }: { items: ScheduledMeetingOut[]; onChanged: () => void }) {
  const [moving, setMoving] = useState<string | null>(null);
  const [date, setDate] = useState(isoDay(new Date()));
  const change = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) =>
      api(`/api/agenda/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      setMoving(null);
      onChanged();
    },
  });
  return (
    <section aria-labelledby="agenda-pendientes" className="rounded-3xl border border-amber-200 bg-amber-50 p-4">
      <h2 id="agenda-pendientes" className="font-semibold text-amber-900">
        Quedaron sin hacer
      </h2>
      <ul className="mt-2 space-y-3">
        {items.map((item) => {
          const { title, detail } = agendaTitle(item);
          return (
            <li key={item.id} className="text-sm text-amber-900">
              <p>
                <span className="font-medium">{dayLabel(item.date)}</span> · {title}
                {detail ? ` (${detail})` : ""}
              </p>
              {item.can_edit && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {moving === item.id ? (
                    <>
                      <input
                        type="date"
                        aria-label="Nuevo día"
                        value={date}
                        onChange={(event) => setDate(event.target.value)}
                        className="min-h-10 rounded-full border border-amber-300 bg-white px-3 text-sm text-ink-900"
                      />
                      <button
                        type="button"
                        disabled={!date || change.isPending}
                        onClick={() => change.mutate({ id: item.id, body: { date } })}
                        className="min-h-10 rounded-full bg-amber-900 px-4 font-semibold text-white disabled:opacity-50"
                      >
                        Pasar
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setMoving(item.id)}
                      className="min-h-10 rounded-full bg-white px-4 font-semibold text-amber-900 hover:bg-amber-100"
                    >
                      Pasar a otro día
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={change.isPending}
                    onClick={() => change.mutate({ id: item.id, body: { status: "no_se_hizo" } })}
                    className="min-h-10 rounded-full px-3 font-semibold text-amber-900 hover:bg-amber-100"
                  >
                    No se hizo
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
