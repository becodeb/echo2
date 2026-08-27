import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge, Card, EmptyState, Spinner, formatMs } from "../components/ui";

interface SearchResults {
  meetings: { id: string; title: string; status: string; started_at: string | null }[];
  people: { id: string; name: string; avatar_color: string }[];
  decisions: { id: string; text: string; meeting_id: string; meeting_title: string; evidence_start_ms: number | null }[];
  tasks: { id: string; text: string; status: string; assignee_name: string | null; meeting_title: string | null }[];
  projects: { id: string; name: string; color: string }[];
  transcript: { meeting_id: string; meeting_title: string; start_ms: number; text: string; speaker: string | null; semantic: boolean }[];
  semantic_enabled: boolean;
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const activeQuery = params.get("q") ?? "";

  const { data, isFetching } = useQuery({
    queryKey: ["search", activeQuery],
    queryFn: () => api<SearchResults>(`/api/search?q=${encodeURIComponent(activeQuery)}`),
    enabled: activeQuery.trim().length >= 2,
  });

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setParams({ q: query });
        }}
        className="mb-8"
      >
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar en todas las reuniones…"
          autoFocus
          className="w-full rounded-2xl border border-ink-200 bg-white px-5 py-3.5 text-lg shadow-sm focus:border-accent-500 focus:outline-none"
        />
        {data && !data.semantic_enabled && (
          <p className="mt-2 text-xs text-ink-400">
            Búsqueda semántica desactivada (configurá embeddings en Ajustes → IA). Usando búsqueda por texto.
          </p>
        )}
      </form>

      {isFetching && <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-6 w-6" /></div>}

      {data && (
        <div className="space-y-6">
          {data.transcript.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">En las conversaciones</h2>
              <Card className="divide-y divide-ink-100 p-0">
                {data.transcript.map((hit, index) => (
                  <Link
                    key={index}
                    to={`/meetings/${hit.meeting_id}?t=${hit.start_ms}`}
                    className="block px-5 py-3 hover:bg-ink-50"
                  >
                    <p className="text-sm text-ink-800">“{hit.text}”</p>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {hit.meeting_title} · {formatMs(hit.start_ms)}
                      {hit.speaker && ` · ${hit.speaker}`}
                    </p>
                  </Link>
                ))}
              </Card>
            </section>
          )}

          {data.meetings.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">Reuniones</h2>
              <Card className="divide-y divide-ink-100 p-0">
                {data.meetings.map((meeting) => (
                  <Link key={meeting.id} to={`/meetings/${meeting.id}`} className="flex items-center justify-between px-5 py-3 hover:bg-ink-50">
                    <span className="text-sm font-medium text-ink-900">{meeting.title}</span>
                    <Badge tone={meeting.status === "completed" ? "green" : "gray"}>{meeting.status}</Badge>
                  </Link>
                ))}
              </Card>
            </section>
          )}

          {data.decisions.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">Decisiones</h2>
              <Card className="divide-y divide-ink-100 p-0">
                {data.decisions.map((decision) => (
                  <Link
                    key={decision.id}
                    to={`/meetings/${decision.meeting_id}${decision.evidence_start_ms != null ? `?t=${decision.evidence_start_ms}` : ""}`}
                    className="block px-5 py-3 hover:bg-ink-50"
                  >
                    <p className="text-sm text-ink-800">{decision.text}</p>
                    <p className="mt-0.5 text-xs text-ink-400">{decision.meeting_title}</p>
                  </Link>
                ))}
              </Card>
            </section>
          )}

          {data.tasks.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">Tareas</h2>
              <Card className="divide-y divide-ink-100 p-0">
                {data.tasks.map((task) => (
                  <div key={task.id} className="px-5 py-3">
                    <p className="text-sm text-ink-800">{task.text}</p>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {task.assignee_name} {task.meeting_title && `· ${task.meeting_title}`}
                    </p>
                  </div>
                ))}
              </Card>
            </section>
          )}

          {(data.people.length > 0 || data.projects.length > 0) && (
            <section className="flex flex-wrap gap-2">
              {data.people.map((person) => (
                <Link key={person.id} to={`/people/${person.id}`} className="rounded-full border border-ink-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:border-ink-300">
                  {person.name}
                </Link>
              ))}
              {data.projects.map((project) => (
                <Link key={project.id} to={`/projects/${project.id}`} className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:border-ink-300">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: project.color }} />
                  {project.name}
                </Link>
              ))}
            </section>
          )}

          {activeQuery &&
            data.meetings.length === 0 &&
            data.transcript.length === 0 &&
            data.decisions.length === 0 &&
            data.tasks.length === 0 && <EmptyState title="Sin resultados" mood="idle" />}
        </div>
      )}
    </div>
  );
}
