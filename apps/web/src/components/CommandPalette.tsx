import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatMs } from "./ui";

interface SearchResults {
  meetings: { id: string; title: string; status: string }[];
  people: { id: string; name: string }[];
  decisions: { id: string; text: string; meeting_id: string; meeting_title: string; evidence_start_ms: number | null }[];
  tasks: { id: string; text: string; status: string }[];
  projects: { id: string; name: string }[];
  transcript: { meeting_id: string; meeting_title: string; start_ms: number; text: string }[];
}

interface Action {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const { data } = useQuery({
    queryKey: ["palette-search", query],
    queryFn: () => api<SearchResults>(`/api/search?q=${encodeURIComponent(query)}`),
    enabled: open && query.trim().length >= 2,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const go = (path: string) => {
    onClose();
    navigate(path);
  };

  const staticActions: Action[] = [
    { id: "new-meeting", label: "Nueva reunión", hint: "Crear y comenzar", run: () => go("/meetings?new=1") },
    { id: "ask", label: "Preguntale a Echo", hint: "Chat global", run: () => go("/ask") },
    { id: "tasks", label: "Mi trabajo", run: () => go("/tasks") },
    { id: "projects", label: "Proyectos", run: () => go("/projects") },
    { id: "settings", label: "Configuración", run: () => go("/settings") },
  ].filter((action) => !query || action.label.toLowerCase().includes(query.toLowerCase()));

  const results: Action[] = [
    ...staticActions,
    ...(data?.meetings ?? []).map((meeting) => ({
      id: `m-${meeting.id}`,
      label: meeting.title,
      hint: "Reunión",
      run: () => go(`/meetings/${meeting.id}`),
    })),
    ...(data?.projects ?? []).map((project) => ({
      id: `p-${project.id}`,
      label: project.name,
      hint: "Proyecto",
      run: () => go(`/projects/${project.id}`),
    })),
    ...(data?.people ?? []).map((person) => ({
      id: `u-${person.id}`,
      label: person.name,
      hint: "Persona",
      run: () => go(`/people/${person.id}`),
    })),
    ...(data?.decisions ?? []).slice(0, 4).map((decision) => ({
      id: `d-${decision.id}`,
      label: decision.text.slice(0, 80),
      hint: `Decisión · ${decision.meeting_title}`,
      run: () => go(`/meetings/${decision.meeting_id}?t=${decision.evidence_start_ms ?? 0}`),
    })),
    ...(data?.transcript ?? []).slice(0, 4).map((hit, index) => ({
      id: `t-${index}`,
      label: `“${hit.text.slice(0, 70)}…”`,
      hint: `${hit.meeting_title} · ${formatMs(hit.start_ms)}`,
      run: () => go(`/meetings/${hit.meeting_id}?t=${hit.start_ms}`),
    })),
  ];

  useEffect(() => {
    setSelected(0);
  }, [query, data]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink-950/40 p-4 pt-[12vh] backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="animate-fade-up w-full max-w-xl overflow-hidden rounded-2xl border border-ink-100 bg-white shadow-2xl">
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setSelected((current) => Math.min(current + 1, results.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setSelected((current) => Math.max(current - 1, 0));
            } else if (event.key === "Enter" && results[selected]) {
              results[selected].run();
            } else if (event.key === "Escape") {
              onClose();
            }
          }}
          placeholder="Buscar reuniones, decisiones, personas… o una acción"
          className="w-full border-b border-ink-100 px-5 py-4 text-[15px] outline-none placeholder:text-ink-400"
          aria-label="Buscar"
        />
        <ul className="max-h-[50vh] overflow-y-auto p-2" role="listbox">
          {results.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-ink-400">Sin resultados</li>
          )}
          {results.map((action, index) => (
            <li key={action.id} role="option" aria-selected={index === selected}>
              <button
                onClick={action.run}
                onMouseEnter={() => setSelected(index)}
                className={`flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm ${
                  index === selected ? "bg-ink-100 text-ink-900" : "text-ink-700"
                }`}
              >
                <span className="truncate">{action.label}</span>
                {action.hint && <span className="ml-3 shrink-0 text-xs text-ink-400">{action.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
