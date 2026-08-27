import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, Card, EmptyState, formatDate, formatDuration } from "../components/ui";
import { useAuth } from "../state/auth";

interface DashboardData {
  greeting_name: string;
  pending_task_count: number;
  recent_meetings: {
    id: string;
    title: string;
    status: string;
    started_at: string | null;
    created_at: string;
    duration_seconds: number;
  }[];
  recent_decisions: { id: string; text: string; meeting_id: string; meeting_title: string }[];
  active_projects: { id: string; name: string; color: string }[];
  my_tasks: { id: string; text: string; due_date: string | null; overdue: boolean }[];
}

const STATUS_LABEL: Record<string, { label: string; tone: "gray" | "red" | "amber" | "green" | "sky" }> = {
  draft: { label: "Borrador", tone: "gray" },
  live: { label: "En vivo", tone: "red" },
  paused: { label: "Pausada", tone: "amber" },
  processing: { label: "Procesando", tone: "sky" },
  completed: { label: "Completada", tone: "green" },
  failed: { label: "Falló", tone: "red" },
};

export default function Dashboard() {
  const { activeOrg } = useAuth();
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["dashboard", activeOrg?.id],
    queryFn: () => api<DashboardData>("/api/dashboard"),
    enabled: !!activeOrg,
  });

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Buenos días" : hour < 20 ? "Buenas tardes" : "Buenas noches";

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            {greeting}{data ? `, ${data.greeting_name}` : ""}.
          </h1>
          {data && data.pending_task_count > 0 && (
            <p className="mt-1 text-sm text-ink-500">
              {data.pending_task_count}{" "}
              {data.pending_task_count === 1 ? "tarea necesita" : "tareas necesitan"} seguimiento
            </p>
          )}
        </div>
        <button
          onClick={() => navigate("/meetings?new=1")}
          className="inline-flex items-center gap-2 rounded-xl bg-ink-900 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-ink-700"
        >
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          Nueva reunión
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-400">
            Reuniones recientes
          </h2>
          <Card className="divide-y divide-ink-100 p-0">
            {data?.recent_meetings.length === 0 && (
              <EmptyState title="Todavía no hay reuniones">
                Creá tu primera reunión y Echo empezará a recordar por vos.
              </EmptyState>
            )}
            {data?.recent_meetings.map((meeting) => {
              const status = STATUS_LABEL[meeting.status] ?? STATUS_LABEL.draft;
              return (
                <Link
                  key={meeting.id}
                  to={
                    meeting.status === "live" || meeting.status === "paused" || meeting.status === "draft"
                      ? `/meetings/${meeting.id}/live`
                      : `/meetings/${meeting.id}`
                  }
                  className="flex items-center justify-between gap-4 px-5 py-3.5 transition-colors hover:bg-ink-50"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink-900">{meeting.title}</p>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {formatDate(meeting.started_at ?? meeting.created_at)}
                      {meeting.duration_seconds > 0 && ` · ${formatDuration(meeting.duration_seconds)}`}
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

          {data && data.recent_decisions.length > 0 && (
            <>
              <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-ink-400">
                Decisiones recientes
              </h2>
              <Card className="divide-y divide-ink-100 p-0">
                {data.recent_decisions.map((decision) => (
                  <Link
                    key={decision.id}
                    to={`/meetings/${decision.meeting_id}`}
                    className="block px-5 py-3 transition-colors hover:bg-ink-50"
                  >
                    <p className="text-sm text-ink-800">{decision.text}</p>
                    <p className="mt-0.5 text-xs text-ink-400">{decision.meeting_title}</p>
                  </Link>
                ))}
              </Card>
            </>
          )}
        </div>

        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-400">Mis tareas</h2>
          <Card className="p-0">
            {(!data || data.my_tasks.length === 0) && (
              <p className="px-5 py-6 text-center text-sm text-ink-400">Sin tareas pendientes</p>
            )}
            <ul className="divide-y divide-ink-100">
              {data?.my_tasks.map((task) => (
                <li key={task.id} className="px-5 py-3">
                  <p className="text-sm text-ink-800">{task.text}</p>
                  {task.due_date && (
                    <p className={`mt-0.5 text-xs ${task.overdue ? "font-medium text-red-600" : "text-ink-400"}`}>
                      {task.overdue ? "Venció " : "Vence "}
                      {new Date(task.due_date).toLocaleDateString("es", { day: "numeric", month: "short" })}
                    </p>
                  )}
                </li>
              ))}
            </ul>
            {data && data.my_tasks.length > 0 && (
              <Link to="/tasks" className="block border-t border-ink-100 px-5 py-2.5 text-center text-xs font-medium text-accent-600 hover:bg-ink-50">
                Ver todo mi trabajo
              </Link>
            )}
          </Card>

          {data && data.active_projects.length > 0 && (
            <>
              <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-ink-400">
                Proyectos activos
              </h2>
              <div className="flex flex-wrap gap-2">
                {data.active_projects.map((project) => (
                  <Link
                    key={project.id}
                    to={`/projects/${project.id}`}
                    className="inline-flex items-center gap-2 rounded-lg border border-ink-150 border-ink-200 bg-white px-3 py-1.5 text-sm font-medium text-ink-700 hover:border-ink-300"
                  >
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: project.color }} />
                    {project.name}
                  </Link>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
