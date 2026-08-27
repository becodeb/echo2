import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { TaskOut } from "../api/types";
import { Badge, Card, EmptyState, Spinner, formatMs } from "../components/ui";
import { useAuth } from "../state/auth";

interface MyWork {
  tasks: TaskOut[];
  overdue_suggestions: { id: string; text: string; due_date: string; meeting_title: string | null }[];
  recent_meetings: { id: string; title: string; started_at: string | null }[];
  mentions: { id: string; text: string; meeting_id: string | null; created_at: string }[];
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Pendiente",
  in_progress: "En progreso",
  done: "Completada",
  cancelled: "Cancelada",
};

export default function Tasks() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [scope, setScope] = useState<"mine" | "all">("mine");

  const { data: myWork } = useQuery({
    queryKey: ["my-work", activeOrg?.id],
    queryFn: () => api<MyWork>("/api/tasks/my-work"),
    enabled: !!activeOrg && scope === "mine",
  });

  const { data: allTasks, isLoading } = useQuery({
    queryKey: ["tasks-all", activeOrg?.id],
    queryFn: () => api<TaskOut[]>("/api/tasks"),
    enabled: !!activeOrg && scope === "all",
  });

  const update = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: string }) =>
      api(`/api/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-work"] });
      queryClient.invalidateQueries({ queryKey: ["tasks-all"] });
    },
  });

  const tasks = scope === "mine" ? myWork?.tasks ?? [] : allTasks ?? [];

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Mi trabajo</h1>
        <div className="flex rounded-lg bg-ink-100 p-1">
          {(["mine", "all"] as const).map((option) => (
            <button
              key={option}
              onClick={() => setScope(option)}
              className={`rounded-md px-3 py-1 text-sm font-medium ${
                scope === option ? "bg-white text-ink-900 shadow-sm" : "text-ink-500"
              }`}
            >
              {option === "mine" ? "Mis tareas" : "Todas"}
            </button>
          ))}
        </div>
      </div>

      {myWork && myWork.overdue_suggestions.length > 0 && scope === "mine" && (
        <Card className="mb-5 border-amber-200 bg-amber-50/60">
          <h2 className="mb-2 text-sm font-semibold text-amber-800">Seguimiento sugerido</h2>
          <ul className="space-y-1 text-sm text-amber-800">
            {myWork.overdue_suggestions.map((task) => (
              <li key={task.id}>
                «{task.text}» aparentemente venció el{" "}
                {new Date(task.due_date).toLocaleDateString("es", { day: "numeric", month: "short" })}
                {task.meeting_title && ` (${task.meeting_title})`}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-amber-600">
            Echo no cambia el estado por su cuenta — marcá lo que corresponda.
          </p>
        </Card>
      )}

      {isLoading && scope === "all" && (
        <div className="flex justify-center py-16 text-ink-300"><Spinner className="h-6 w-6" /></div>
      )}

      {tasks.length === 0 && !isLoading ? (
        <Card>
          <EmptyState title="Sin tareas por ahora" mood="done">
            Las tareas detectadas en reuniones aparecen acá con responsable, fecha y origen.
          </EmptyState>
        </Card>
      ) : (
        <Card className="divide-y divide-ink-100 p-0">
          {tasks.map((task) => (
            <div key={task.id} className="flex items-start gap-3 px-5 py-3.5">
              <input
                type="checkbox"
                checked={task.status === "done"}
                onChange={(event) =>
                  update.mutate({ taskId: task.id, status: event.target.checked ? "done" : "pending" })
                }
                className="mt-1 rounded border-ink-300"
                aria-label="Completar tarea"
              />
              <div className="min-w-0 flex-1">
                <p className={`text-[15px] ${task.status === "done" ? "text-ink-400 line-through" : "text-ink-900"}`}>
                  {task.text}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-400">
                  {task.assignee_name && <span>{task.assignee_name}</span>}
                  {(task.due_date || task.due_text) && (
                    <span className={task.overdue ? "font-medium text-red-600" : ""}>
                      {task.due_date
                        ? new Date(task.due_date + "T00:00:00").toLocaleDateString("es", { day: "numeric", month: "short" })
                        : task.due_text}
                    </span>
                  )}
                  {task.meeting_id && (
                    <Link
                      to={`/meetings/${task.meeting_id}${task.evidence_start_ms != null ? `?t=${task.evidence_start_ms}` : ""}`}
                      className="text-accent-600 hover:underline"
                    >
                      {task.meeting_title ?? "Reunión"}
                      {task.evidence_start_ms != null && ` — ${formatMs(task.evidence_start_ms)}`}
                    </Link>
                  )}
                </div>
              </div>
              <select
                value={task.status}
                onChange={(event) => update.mutate({ taskId: task.id, status: event.target.value })}
                className="rounded-lg border border-ink-200 px-2 py-1 text-xs text-ink-600"
                aria-label="Estado"
              >
                {Object.entries(STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          ))}
        </Card>
      )}

      {myWork && myWork.mentions.length > 0 && scope === "mine" && (
        <>
          <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-ink-400">Menciones</h2>
          <Card className="divide-y divide-ink-100 p-0">
            {myWork.mentions.map((mention) => (
              <Link
                key={mention.id}
                to={mention.meeting_id ? `/meetings/${mention.meeting_id}` : "#"}
                className="block px-5 py-3 text-sm text-ink-700 hover:bg-ink-50"
              >
                {mention.text}
              </Link>
            ))}
          </Card>
        </>
      )}
    </div>
  );
}
