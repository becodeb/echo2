import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, Card, EmptyState, Spinner, formatDate, formatDuration, formatMs } from "../components/ui";

interface ProjectDetailData {
  id: string;
  name: string;
  description: string | null;
  color: string;
  meetings: {
    id: string;
    title: string;
    status: string;
    started_at: string | null;
    duration_seconds: number;
    participant_count: number;
  }[];
  timeline: {
    at: string;
    kind: string;
    label: string;
    meeting_id?: string;
    meeting_title?: string;
    evidence_start_ms?: number | null;
  }[];
}

interface Changes {
  has_comparison: boolean;
  message?: string;
  before?: Snapshot;
  after?: Snapshot;
}

interface Snapshot {
  meeting_id: string;
  title: string;
  date: string | null;
  decisions: { text: string; evidence_start_ms: number | null }[];
  tasks: { text: string; assignee: string | null; status: string }[];
  open_questions: string[];
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<"timeline" | "meetings" | "changes">("timeline");

  const { data: project } = useQuery({
    queryKey: ["project", id],
    queryFn: () => api<ProjectDetailData>(`/api/projects/${id}`),
    enabled: !!id,
  });

  const { data: changes } = useQuery({
    queryKey: ["project-changes", id],
    queryFn: () => api<Changes>(`/api/projects/${id}/changes`),
    enabled: !!id && tab === "changes",
  });

  if (!project) {
    return <div className="flex h-full items-center justify-center text-ink-300"><Spinner className="h-6 w-6" /></div>;
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-6 flex items-center gap-3">
        <span className="h-4 w-4 rounded-full" style={{ backgroundColor: project.color }} />
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">{project.name}</h1>
      </header>

      <nav className="mb-6 flex gap-1 border-b border-ink-100">
        {(
          [
            ["timeline", "Línea de tiempo"],
            ["meetings", `Reuniones (${project.meetings.length})`],
            ["changes", "¿Qué cambió?"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setTab(value)}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium ${
              tab === value ? "border-ink-900 text-ink-900" : "border-transparent text-ink-400 hover:text-ink-700"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "timeline" && (
        <Card>
          {project.timeline.length === 0 ? (
            <EmptyState title="Sin actividad todavía" mood="idle" />
          ) : (
            <ol className="relative ml-2 space-y-5 border-l border-ink-200 pl-6">
              {project.timeline.map((item, index) => (
                <li key={index} className="relative">
                  <span
                    className={`absolute -left-[31px] top-1 h-2.5 w-2.5 rounded-full ${
                      item.kind === "decision" ? "bg-accent-500" : item.kind === "meeting" ? "bg-ink-400" : "bg-emerald-500"
                    }`}
                  />
                  <p className="text-xs text-ink-400">{formatDate(item.at)}</p>
                  {item.meeting_id ? (
                    <Link
                      to={`/meetings/${item.meeting_id}${item.evidence_start_ms != null ? `?t=${item.evidence_start_ms}` : ""}`}
                      className="text-[15px] text-ink-800 hover:text-accent-600"
                    >
                      {item.label}
                      {item.kind === "decision" && item.meeting_title && (
                        <span className="ml-2 text-xs text-ink-400">({item.meeting_title})</span>
                      )}
                    </Link>
                  ) : (
                    <p className="text-[15px] text-ink-800">{item.label}</p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}

      {tab === "meetings" && (
        <Card className="divide-y divide-ink-100 p-0">
          {project.meetings.length === 0 && <EmptyState title="Sin reuniones asociadas" mood="idle" />}
          {project.meetings.map((meeting) => (
            <Link
              key={meeting.id}
              to={`/meetings/${meeting.id}`}
              className="flex items-center justify-between px-5 py-3.5 hover:bg-ink-50"
            >
              <div>
                <p className="font-medium text-ink-900">{meeting.title}</p>
                <p className="text-xs text-ink-400">
                  {formatDate(meeting.started_at)} · {formatDuration(meeting.duration_seconds)} ·{" "}
                  {meeting.participant_count} participantes
                </p>
              </div>
              <Badge tone={meeting.status === "completed" ? "green" : "gray"}>{meeting.status}</Badge>
            </Link>
          ))}
        </Card>
      )}

      {tab === "changes" && (
        <>
          {!changes && <div className="flex justify-center py-10 text-ink-300"><Spinner /></div>}
          {changes && !changes.has_comparison && (
            <Card>
              <EmptyState title="Sin comparación disponible" mood="idle">
                {changes.message}
              </EmptyState>
            </Card>
          )}
          {changes?.has_comparison && changes.before && changes.after && (
            <div className="grid gap-4 md:grid-cols-2">
              {[
                { label: "ANTES", snapshot: changes.before },
                { label: "AHORA", snapshot: changes.after },
              ].map(({ label, snapshot }) => (
                <Card key={label}>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">{label}</p>
                  <Link to={`/meetings/${snapshot.meeting_id}`} className="font-medium text-ink-900 hover:text-accent-600">
                    {snapshot.title}
                  </Link>
                  <p className="mb-3 text-xs text-ink-400">{snapshot.date ? formatDate(snapshot.date) : ""}</p>
                  {snapshot.decisions.length > 0 && (
                    <>
                      <p className="mb-1 text-xs font-medium text-ink-500">Decisiones</p>
                      <ul className="mb-3 space-y-1 text-sm text-ink-800">
                        {snapshot.decisions.map((decision, index) => (
                          <li key={index} className="flex gap-1.5">
                            <span className="text-ink-300">•</span>
                            <span>
                              {decision.text}
                              {decision.evidence_start_ms != null && (
                                <span className="ml-1 font-mono text-xs text-ink-400">
                                  {formatMs(decision.evidence_start_ms)}
                                </span>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {snapshot.open_questions.length > 0 && (
                    <>
                      <p className="mb-1 text-xs font-medium text-ink-500">Preguntas abiertas</p>
                      <ul className="space-y-1 text-sm text-ink-800">
                        {snapshot.open_questions.map((question, index) => (
                          <li key={index}>? {question}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
