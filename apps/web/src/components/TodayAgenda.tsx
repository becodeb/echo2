import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ScheduledMeetingOut } from "../api/types";
import { addDays, agendaTitle, isoDay } from "../lib/agenda";
import { NewMeetingModal } from "./NewMeetingModal";
import { useAuth } from "../state/auth";

/**
 * En Inicio: las reuniones agendadas para hoy que todavía no empezaron, con
 * "Empezar" a mano. Sin nada agendado no ocupa lugar.
 */
export function TodayAgenda() {
  const { activeOrg } = useAuth();
  const today = isoDay(new Date());
  const tomorrow = addDays(today, 1);
  const { data } = useQuery({
    queryKey: ["agenda", activeOrg?.id, today, tomorrow, "mine"],
    queryFn: () => api<ScheduledMeetingOut[]>(`/api/agenda?start=${today}&end=${tomorrow}&scope=mine`),
    enabled: !!activeOrg,
  });
  const [starting, setStarting] = useState<ScheduledMeetingOut | null>(null);

  const open = (data ?? []).filter((item) => item.status === "agendada" && !item.meeting_id);
  const todays = open.filter((item) => item.date === today);
  const tomorrows = open.filter((item) => item.date === tomorrow).length;
  if (!todays.length && !tomorrows) return null;

  return (
    <section aria-labelledby="hoy-agenda" className="mb-8 rounded-3xl border border-ink-100 bg-white p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 id="hoy-agenda" className="flex-1 font-semibold text-ink-900">
          {todays.length
            ? `Hoy tenés ${todays.length} ${todays.length === 1 ? "reunión agendada" : "reuniones agendadas"}`
            : "Hoy no tenés reuniones agendadas"}
        </h2>
        <Link to="/agenda" className="text-sm font-medium text-accent-600 hover:underline">
          Ver la agenda ›
        </Link>
      </div>
      {todays.length > 0 && (
        <ul className="space-y-2">
          {todays.map((item) => {
            const { title, detail } = agendaTitle(item);
            return (
              <li key={item.id} className="flex flex-wrap items-center gap-3 rounded-2xl bg-ink-50 px-4 py-3">
                <span className={`w-16 text-sm font-semibold ${item.time ? "text-ink-900" : "text-ink-400"}`}>
                  {item.time ?? "Sin hora"}
                </span>
                <span className="min-w-0 flex-1 text-sm font-semibold text-ink-900">
                  {title}
                  {(detail || item.reason_name) && (
                    <span className="font-medium text-ink-500"> · {[detail, item.reason_name].filter(Boolean).join(" · ")}</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => setStarting(item)}
                  className="inline-flex min-h-11 items-center rounded-full bg-accent-600 px-4 text-sm font-semibold text-white hover:bg-accent-700"
                >
                  Empezar
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {tomorrows > 0 && (
        <p className="mt-3 text-xs text-ink-500">
          Mañana: {tomorrows} {tomorrows === 1 ? "reunión" : "reuniones"}
        </p>
      )}
      {starting && <NewMeetingModal key={starting.id} open scheduled={starting} onClose={() => setStarting(null)} />}
    </section>
  );
}
