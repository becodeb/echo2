import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Avatar, Badge, Card, EmptyState, Spinner, formatDate, formatMs } from "../components/ui";

interface PersonDetailData {
  id: string;
  name: string;
  email: string;
  avatar_color: string;
  job_title: string | null;
  role: string;
  meetings: { id: string; title: string; status: string; started_at: string | null }[];
  tasks: { id: string; text: string; status: string; due_date: string | null; meeting_title: string | null }[];
  interventions: { meeting_id: string; meeting_title: string; start_ms: number; text: string }[];
}

export default function PersonDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: person } = useQuery({
    queryKey: ["person", id],
    queryFn: () => api<PersonDetailData>(`/api/people/${id}`),
    enabled: !!id,
  });

  if (!person) {
    return <div className="flex h-full items-center justify-center text-ink-300"><Spinner className="h-6 w-6" /></div>;
  }

  const openTasks = person.tasks.filter((task) => task.status === "pending" || task.status === "in_progress");

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-8 flex items-center gap-4">
        <Avatar name={person.name} color={person.avatar_color} size={56} />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">{person.name}</h1>
          <p className="text-sm text-ink-500">
            {person.job_title ?? person.email} · {person.meetings.length} reuniones · {openTasks.length} tareas abiertas
          </p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-400">Tareas</h2>
          <Card className="divide-y divide-ink-100 p-0">
            {person.tasks.length === 0 && <EmptyState title="Sin tareas" mood="done" />}
            {person.tasks.map((task) => (
              <div key={task.id} className="px-5 py-3">
                <p className={`text-sm ${task.status === "done" ? "text-ink-400 line-through" : "text-ink-800"}`}>
                  {task.text}
                </p>
                <p className="mt-0.5 text-xs text-ink-400">
                  {task.meeting_title}
                  {task.due_date && ` · vence ${new Date(task.due_date + "T00:00:00").toLocaleDateString("es")}`}
                </p>
              </div>
            ))}
          </Card>
        </div>

        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-400">Reuniones</h2>
          <Card className="divide-y divide-ink-100 p-0">
            {person.meetings.length === 0 && <EmptyState title="Sin reuniones" mood="idle" />}
            {person.meetings.map((meeting) => (
              <Link key={meeting.id} to={`/meetings/${meeting.id}`} className="flex items-center justify-between px-5 py-3 hover:bg-ink-50">
                <div>
                  <p className="text-sm font-medium text-ink-900">{meeting.title}</p>
                  <p className="text-xs text-ink-400">{formatDate(meeting.started_at)}</p>
                </div>
                <Badge tone={meeting.status === "completed" ? "green" : "gray"}>{meeting.status}</Badge>
              </Link>
            ))}
          </Card>

          {person.interventions.length > 0 && (
            <>
              <h2 className="mb-3 mt-6 text-sm font-semibold uppercase tracking-wide text-ink-400">
                Últimas intervenciones
              </h2>
              <Card className="divide-y divide-ink-100 p-0">
                {person.interventions.map((intervention, index) => (
                  <Link
                    key={index}
                    to={`/meetings/${intervention.meeting_id}?t=${intervention.start_ms}`}
                    className="block px-5 py-3 hover:bg-ink-50"
                  >
                    <p className="text-sm text-ink-700">“{intervention.text}”</p>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {intervention.meeting_title} · {formatMs(intervention.start_ms)}
                    </p>
                  </Link>
                ))}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
