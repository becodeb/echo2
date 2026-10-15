import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { MeetingListItem } from "../api/types";
import { LEVEL_LABEL } from "../state/access";
import { DeleteDraft } from "./DeleteDraft";
import { MeetingStatus } from "./MeetingStatus";
import { Button, Card, Spinner, formatDate, formatDuration } from "./ui";
import { prefetchMeeting } from "../lib/prefetch";

/**
 * Lista de reuniones: las terminadas van al detalle, las otras a grabar.
 * Al pasar el mouse (o apoyar el dedo) se baja la reunión, así abre sin espera.
 * Con `onMore`, al llegar al final se piden las anteriores.
 */
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
  const queryClient = useQueryClient();
  return (
    <>
      <Card className="divide-y divide-ink-100 p-0">
        {meetings.map((meeting) => {
          const detail = meeting.status === "completed" || meeting.status === "processing" || meeting.status === "failed";
          const target = detail ? `/meetings/${meeting.id}` : `/meetings/${meeting.id}/live`;
          const warm = detail ? () => prefetchMeeting(queryClient, meeting.id) : undefined;
          return (
            <Link
              key={meeting.id}
              to={target}
              onMouseEnter={warm}
              onFocus={warm}
              onTouchStart={warm}
              className="group flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-ink-50"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-ink-900">{meeting.title}</p>
                <p className="mt-0.5 text-xs text-ink-400">
                  {formatDate(meeting.started_at ?? meeting.created_at)}
                  {meeting.duration_seconds > 0 && ` · ${formatDuration(meeting.duration_seconds)}`}
                  {meeting.participant_count > 0 && ` · ${meeting.participant_count} participantes`}
                  {meeting.project_name && ` · ${meeting.project_name}`}
                  {meeting.group_name && ` · ${meeting.group_name}`}
                  {meeting.level && ` · ${LEVEL_LABEL[meeting.level] ?? meeting.level}`}
                  {meeting.recorded && " · con grabación"}
                </p>
              </div>
              <span className="flex shrink-0 items-center gap-2">
                {meeting.status === "draft" && <DeleteDraft meetingId={meeting.id} title={meeting.title} />}
                <MeetingStatus status={meeting.status} />
              </span>
            </Link>
          );
        })}
      </Card>
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
