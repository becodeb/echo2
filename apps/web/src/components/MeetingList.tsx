import { Link } from "react-router-dom";
import type { MeetingListItem } from "../api/types";
import { LEVEL_LABEL } from "../state/access";
import { Badge, Card, formatDate, formatDuration } from "./ui";

export const MEETING_STATUS: Record<string, { label: string; tone: "gray" | "red" | "amber" | "green" | "sky" }> = {
  draft: { label: "Borrador", tone: "gray" },
  live: { label: "En vivo", tone: "red" },
  paused: { label: "Pausada", tone: "amber" },
  processing: { label: "Procesando", tone: "sky" },
  completed: { label: "Completada", tone: "green" },
  failed: { label: "Falló", tone: "red" },
};

/** Lista de reuniones: las terminadas van al detalle, las otras a grabar. */
export function MeetingList({ meetings }: { meetings: MeetingListItem[] }) {
  return (
    <Card className="divide-y divide-ink-100 p-0">
      {meetings.map((meeting) => {
        const status = MEETING_STATUS[meeting.status] ?? MEETING_STATUS.draft;
        const target =
          meeting.status === "completed" || meeting.status === "processing" || meeting.status === "failed"
            ? `/meetings/${meeting.id}`
            : `/meetings/${meeting.id}/live`;
        return (
          <Link
            key={meeting.id}
            to={target}
            className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-ink-50"
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
            <Badge tone={status.tone}>
              {meeting.status === "live" && <span className="recording-dot h-1.5 w-1.5 rounded-full bg-red-500" />}
              {status.label}
            </Badge>
          </Link>
        );
      })}
    </Card>
  );
}
