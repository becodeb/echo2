import { Link } from "react-router-dom";
import type { MeetingListItem } from "../api/types";
import { LEVEL_LABEL } from "../state/access";
import { DeleteDraft } from "./DeleteDraft";
import { MeetingStatus } from "./MeetingStatus";
import { Card, formatDate, formatDuration } from "./ui";

/** Lista de reuniones: las terminadas van al detalle, las otras a grabar. */
export function MeetingList({ meetings }: { meetings: MeetingListItem[] }) {
  return (
    <Card className="divide-y divide-ink-100 p-0">
      {meetings.map((meeting) => {
        const target =
          meeting.status === "completed" || meeting.status === "processing" || meeting.status === "failed"
            ? `/meetings/${meeting.id}`
            : `/meetings/${meeting.id}/live`;
        return (
          <Link
            key={meeting.id}
            to={target}
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
  );
}
