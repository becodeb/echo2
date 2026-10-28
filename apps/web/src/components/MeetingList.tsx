import { useEffect, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { MeetingListItem } from "../api/types";
import { LEVEL_LABEL } from "../state/access";
import { DeleteDraft } from "./DeleteDraft";
import { MeetingStatus, StatusIcons, StatusPill } from "./MeetingStatus";
import { Button, Card, Spinner, formatDuration } from "./ui";
import { prefetchMeeting } from "../lib/prefetch";

/**
 * Lista de reuniones, agrupada por fecha: las terminadas van al detalle, las
 * otras a grabar. Al pasar el mouse (o apoyar el dedo) se baja la reunión, así
 * abre sin espera. Con `onMore`, al llegar al final se piden las anteriores.
 */

const DAY = 24 * 60 * 60 * 1000;

const meetingDate = (meeting: MeetingListItem) => new Date(meeting.started_at ?? meeting.created_at);

const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** "Hoy", "Esta semana", "Este mes" y después un grupo por mes. */
function groupOf(date: Date, now: Date): { key: string; label: string } {
  const today = startOfDay(now);
  const day = startOfDay(date);
  if (day >= today) return { key: "hoy", label: "Hoy" };
  const monday = today - ((now.getDay() + 6) % 7) * DAY;
  if (day >= monday) return { key: "semana", label: "Esta semana" };
  if (date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth()) {
    return { key: "mes", label: "Este mes" };
  }
  const month = date.toLocaleDateString("es", { month: "long", year: "numeric" });
  return { key: `${date.getFullYear()}-${date.getMonth()}`, label: month[0].toUpperCase() + month.slice(1) };
}

/** Qué pasó con la reunión y su acta, en una palabra útil. */
function StateChip({ meeting }: { meeting: MeetingListItem }) {
  if (meeting.status !== "completed" || meeting.kind !== "familia") {
    return <MeetingStatus status={meeting.status} />;
  }
  if (meeting.minutes_generation === "generating") {
    return <StatusPill tone="busy" icon={StatusIcons.busy}>Armando el acta</StatusPill>;
  }
  if (meeting.minutes_status === "approved") {
    return (
      <StatusPill tone="done" icon={StatusIcons.check}>
        {meeting.minutes_number != null ? `Acta N.º ${meeting.minutes_number}` : "Acta aprobada"}
      </StatusPill>
    );
  }
  if (meeting.minutes_status) return <StatusPill tone="warn">Acta por confirmar</StatusPill>;
  return <StatusPill tone="muted">Sin acta</StatusPill>;
}

function Row({ meeting, today }: { meeting: MeetingListItem; today: boolean }) {
  const queryClient = useQueryClient();
  const detail = meeting.status === "completed" || meeting.status === "processing" || meeting.status === "failed";
  const target = detail ? `/meetings/${meeting.id}` : `/meetings/${meeting.id}/live`;
  const warm = detail ? () => prefetchMeeting(queryClient, meeting.id) : undefined;
  const date = meetingDate(meeting);
  const when = today
    ? date.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" });
  const about = [meeting.family_name, meeting.student_initials.join(" · "), meeting.reason_name].filter(Boolean);
  const chip = (
    <span className="flex shrink-0 items-center gap-2">
      {meeting.status === "draft" && <DeleteDraft meetingId={meeting.id} title={meeting.title} />}
      <StateChip meeting={meeting} />
    </span>
  );
  return (
    <Link
      to={target}
      onMouseEnter={warm}
      onFocus={warm}
      onTouchStart={warm}
      className="group block px-4 py-3.5 transition-colors hover:bg-ink-50 sm:px-5 sm:py-4"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="min-w-0 truncate font-medium text-ink-900">{meeting.title}</p>
        {chip}
      </div>
      {about.length > 0 && <p className="mt-0.5 truncate text-sm text-ink-600">{about.join(" · ")}</p>}
      <p className="mt-1 text-xs text-ink-400">
        {when}
        {meeting.duration_seconds > 0 && ` · ${formatDuration(meeting.duration_seconds)}`}
        {meeting.participant_count > 0 && ` · ${meeting.participant_count} participantes`}
        {meeting.project_name && ` · ${meeting.project_name}`}
        {meeting.group_name && ` · ${meeting.group_name}`}
        {meeting.level && ` · ${LEVEL_LABEL[meeting.level] ?? meeting.level}`}
        {meeting.recorded && " · con grabación"}
      </p>
    </Link>
  );
}

export function MeetingList({
  meetings,
  hasMore = false,
  loadingMore = false,
  onMore,
}: {
  meetings: MeetingListItem[];
  hasMore?: boolean;
  loadingMore?: boolean;
  onMore?: () => void;
}) {
  const groups = useMemo(() => {
    const now = new Date();
    const out: { key: string; label: string; items: MeetingListItem[] }[] = [];
    for (const meeting of meetings) {
      const group = groupOf(meetingDate(meeting), now);
      const last = out[out.length - 1];
      if (last && last.key === group.key) last.items.push(meeting);
      else out.push({ ...group, items: [meeting] });
    }
    return out;
  }, [meetings]);

  return (
    <>
      <div className="space-y-5">
        {groups.map((group) => (
          <section key={group.key}>
            <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-ink-400">{group.label}</h2>
            <Card className="divide-y divide-ink-100 p-0">
              {group.items.map((meeting) => (
                <Row key={meeting.id} meeting={meeting} today={group.key === "hoy"} />
              ))}
            </Card>
          </section>
        ))}
      </div>
      {hasMore && onMore && <MoreSentinel loading={loadingMore} onMore={onMore} />}
    </>
  );
}

/** Pide la página siguiente cuando el final de la lista entra en pantalla. */
function MoreSentinel({ loading, onMore }: { loading: boolean; onMore: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || loading) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onMore();
    }, { rootMargin: "400px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [loading, onMore]);
  return (
    <div ref={ref} className="flex justify-center py-4">
      <Button variant="soft" onClick={onMore} disabled={loading}>
        {loading ? <Spinner /> : "Ver reuniones anteriores"}
      </Button>
    </div>
  );
}
