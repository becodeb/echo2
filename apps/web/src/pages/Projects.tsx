import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Button, Card, EmptyState, Input, Modal, Spinner, formatDate } from "../components/ui";
import { useAuth } from "../state/auth";

interface ProjectOut {
  id: string;
  name: string;
  description: string | null;
  status: string;
  color: string;
  meeting_count: number;
  decision_count: number;
  open_task_count: number;
  last_meeting_at: string | null;
}

const COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"];

export default function Projects() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState(COLORS[0]);

  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects", activeOrg?.id],
    queryFn: () => api<ProjectOut[]>("/api/projects"),
    enabled: !!activeOrg,
  });

  const create = useMutation({
    mutationFn: () =>
      api("/api/projects", { method: "POST", body: JSON.stringify({ name, color }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowNew(false);
      setName("");
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Proyectos</h1>
        <Button onClick={() => setShowNew(true)}>+ Nuevo proyecto</Button>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16 text-ink-300"><Spinner className="h-6 w-6" /></div>
      )}

      {projects && projects.length === 0 && (
        <Card>
          <EmptyState title="Sin proyectos" mood="idle">
            Asociá reuniones a proyectos para seguir su evolución: decisiones, tareas y línea de tiempo.
          </EmptyState>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {projects?.map((project) => (
          <Link key={project.id} to={`/projects/${project.id}`}>
            <Card className="h-full transition-shadow hover:shadow-md">
              <div className="mb-3 flex items-center gap-2.5">
                <span className="h-3 w-3 rounded-full" style={{ backgroundColor: project.color }} />
                <h2 className="font-semibold text-ink-900">{project.name}</h2>
              </div>
              <dl className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <dt className="text-xs text-ink-400">Reuniones</dt>
                  <dd className="text-lg font-semibold text-ink-800">{project.meeting_count}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-400">Decisiones</dt>
                  <dd className="text-lg font-semibold text-ink-800">{project.decision_count}</dd>
                </div>
                <div>
                  <dt className="text-xs text-ink-400">Tareas abiertas</dt>
                  <dd className="text-lg font-semibold text-ink-800">{project.open_task_count}</dd>
                </div>
              </dl>
              {project.last_meeting_at && (
                <p className="mt-3 text-xs text-ink-400">
                  Última reunión: {formatDate(project.last_meeting_at)}
                </p>
              )}
            </Card>
          </Link>
        ))}
      </div>

      <Modal open={showNew} onClose={() => setShowNew(false)} title="Nuevo proyecto">
        <form onSubmit={submit} className="space-y-4">
          <Input label="Nombre" value={name} onChange={(event) => setName(event.target.value)} autoFocus required />
          <div>
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Color</span>
            <div className="flex gap-2">
              {COLORS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setColor(option)}
                  className={`h-7 w-7 rounded-full transition-transform ${color === option ? "scale-110 ring-2 ring-ink-900 ring-offset-2" : ""}`}
                  style={{ backgroundColor: option }}
                  aria-label={`Color ${option}`}
                />
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setShowNew(false)}>Cancelar</Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <Spinner /> : "Crear"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
