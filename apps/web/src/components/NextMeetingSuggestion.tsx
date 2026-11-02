import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ClassificationOut, MeetingOut, MinutesOut } from "../api/types";
import { dayLabel, isoDay, nextMeetingIn } from "../lib/agenda";
import { ScheduleModal } from "./ScheduleModal";

const storageKey = (meetingId: string) => `echo_proxima_${meetingId}`;

function remembered(meetingId: string): string | null {
  try {
    return localStorage.getItem(storageKey(meetingId));
  } catch {
    return null;
  }
}

function remember(meetingId: string, value: string) {
  try {
    localStorage.setItem(storageKey(meetingId), value);
  } catch {
    // Sin almacenamiento la sugerencia vuelve a aparecer: no es grave.
  }
}

/**
 * Debajo del acta: si en la reunión se acordó volver a reunirse, ofrece
 * agendarla con la misma familia, alumno, motivo y personas del colegio.
 */
export function NextMeetingSuggestion({ meeting }: { meeting: MeetingOut }) {
  const [state, setState] = useState(() => remembered(meeting.id));
  const [date, setDate] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const { data: minutes } = useQuery({
    queryKey: ["minutes", meeting.id],
    queryFn: () => api<MinutesOut | null>(`/api/meetings/${meeting.id}/minutes`),
    enabled: meeting.kind === "familia",
  });
  const { data: classification } = useQuery({
    queryKey: ["classification", meeting.id],
    queryFn: () => api<ClassificationOut>(`/api/meetings/${meeting.id}/classification`),
    enabled: meeting.kind === "familia",
  });

  if (meeting.kind !== "familia" || !minutes?.version || state === "no") return null;
  const today = isoDay(new Date());
  const from = isoDay(new Date(meeting.started_at ?? meeting.created_at));
  const found = nextMeetingIn(minutes.version.body_markdown, from);
  // Un acuerdo de hace rato ya no sirve de sugerencia.
  if (!found || found.date < today) return null;
  const chosen = date ?? found.date;

  if (state && state !== "no") {
    return (
      <p className="rounded-2xl bg-accent-50 px-4 py-3 text-sm text-accent-800">
        Próxima reunión agendada para el {dayLabel(state).toLowerCase()}.{" "}
        <Link to={`/agenda?dia=${state}`} className="font-semibold underline-offset-2 hover:underline">
          Ver en la agenda
        </Link>
      </p>
    );
  }

  return (
    <section aria-labelledby="proxima-reunion" className="space-y-3 rounded-3xl border border-accent-100 bg-accent-50 p-5">
      <h3 id="proxima-reunion" className="font-semibold text-accent-900">
        En la reunión se acordó volver a reunirse
      </h3>
      <p className="text-sm text-accent-800">«{found.sentence}»</p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm font-medium text-accent-900">
          Día
          <input
            type="date"
            value={chosen}
            min={today}
            onChange={(event) => setDate(event.target.value)}
            className="min-h-11 rounded-full border border-accent-300 bg-white px-4 text-sm text-ink-900"
          />
        </label>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex min-h-11 items-center rounded-full bg-accent-600 px-5 text-sm font-semibold text-white hover:bg-accent-700"
        >
          Agendar
        </button>
        <button
          type="button"
          onClick={() => {
            remember(meeting.id, "no");
            setState("no");
          }}
          className="min-h-11 rounded-full px-3 text-sm font-semibold text-accent-700 hover:bg-accent-100"
        >
          Ahora no
        </button>
      </div>
      <p className="text-xs text-accent-700">Misma familia, alumno y quienes estuvieron. Se puede cambiar antes de agendar.</p>
      {open && (
        <ScheduleModal
          open
          onClose={() => setOpen(false)}
          draft={{
            date: chosen,
            kind: "familia",
            family_id: classification?.family_id ?? null,
            student_ids: classification?.student_ids ?? [],
            reason_id: classification?.reason_id ?? null,
            level: meeting.level,
            staff_ids: meeting.participants.map((person) => person.user_id).filter((id): id is string => !!id),
          }}
          onSaved={(item) => {
            remember(meeting.id, item.date);
            setState(item.date);
          }}
        />
      )}
    </section>
  );
}
