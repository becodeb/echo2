import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { effectivePlan, PLAN_NAME, useBilling } from "../components/billing";
import { api } from "../api/client";
import { DeleteDraft } from "../components/DeleteDraft";
import { MeetingStatus } from "../components/MeetingStatus";
import { Card, EmptyState, formatDate, formatDuration } from "../components/ui";
import { EchoFace } from "../components/EchoFace";
import { useAuth } from "../state/auth";
import { useVoice } from "../state/voice";

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

export default function Dashboard() {
  const { activeOrg } = useAuth();
  const navigate = useNavigate();
  const voice = useVoice();
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
          <PlanLine />
        </div>
        <button
          onClick={() => navigate("/meetings?new=1")}
          className="inline-flex items-center gap-2 rounded-2xl bg-ink-900 px-5 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-ink-700"
        >
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          Nueva reunión
        </button>
      </div>

      {data && <FirstSteps hasMeetings={data.recent_meetings.length > 0} />}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="min-w-0 lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-400">
            Reuniones recientes
          </h2>
          <Card className="divide-y divide-ink-100 overflow-hidden p-0">
            {!data && [0, 1, 2].map((index) => (
              <div key={index} className="flex items-center justify-between gap-4 px-5 py-4" aria-hidden>
                <div className="space-y-2">
                  <div className="h-4 w-56 animate-pulse rounded-full bg-ink-100" />
                  <div className="h-3 w-24 animate-pulse rounded-full bg-ink-100" />
                </div>
                <div className="h-6 w-16 animate-pulse rounded-full bg-ink-100" />
              </div>
            ))}
            {data?.recent_meetings.length === 0 && (
              <EmptyState title="Todavía no hay reuniones">
                Creá tu primera reunión y Echo empezará a recordar por vos.
                <div className="mt-4">
                  <button
                    onClick={() => navigate("/meetings?new=1")}
                    className="inline-flex min-h-11 items-center rounded-full bg-ink-900 px-5 text-sm font-semibold text-white hover:bg-ink-700"
                  >
                    Crear la primera
                  </button>
                </div>
              </EmptyState>
            )}
            {data?.recent_meetings.map((meeting) => {
              return (
                <Link
                  key={meeting.id}
                  to={
                    meeting.status === "live" || meeting.status === "paused" || meeting.status === "draft"
                      ? `/meetings/${meeting.id}/live`
                      : `/meetings/${meeting.id}`
                  }
                  className="group flex items-center justify-between gap-4 px-5 py-3.5 transition-colors hover:bg-ink-50"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink-900">{meeting.title}</p>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {formatDate(meeting.started_at ?? meeting.created_at)}
                      {meeting.duration_seconds > 0 && ` · ${formatDuration(meeting.duration_seconds)}`}
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
          <button
            type="button"
            onClick={voice.open}
            className="group mb-8 flex w-full items-center gap-4 rounded-3xl bg-ink-900 p-5 text-left text-white shadow-[0_12px_32px_-14px_rgba(20,24,36,0.6)] transition-transform duration-200 hover:-translate-y-0.5"
          >
            <span className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/10">
              <span aria-hidden className="voice-bubble-wave absolute inset-0 rounded-full border-2 border-accent-400/50" />
              <EchoFace mood="idle" size={26} />
            </span>
            <span className="min-w-0">
              <span className="block font-semibold">Hablá con Echo</span>
              <span className="mt-0.5 block text-sm text-white/70">Preguntale por tus reuniones, en voz alta.</span>
            </span>
          </button>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-400">Mis tareas</h2>
          <Card className="overflow-hidden p-0">
            {!data && (
              <div className="space-y-3 px-5 py-5" aria-hidden>
                <div className="h-4 w-full animate-pulse rounded-full bg-ink-100" />
                <div className="h-4 w-2/3 animate-pulse rounded-full bg-ink-100" />
              </div>
            )}
            {data && data.my_tasks.length === 0 && (
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
                    className="inline-flex items-center gap-2 rounded-full border border-ink-200 bg-white px-3 py-1.5 text-sm font-medium text-ink-700 hover:border-ink-300"
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

/** El plan y lo que queda del mes, en una línea (lleva a Planes). */
function PlanLine() {
  const { data: billing } = useBilling();
  const { user } = useAuth();
  if (!billing) return <div className="mt-2 h-4 w-60 animate-pulse rounded-full bg-ink-100" aria-hidden />;
  const plan = user?.is_superadmin ? "becode" : effectivePlan(billing);
  const people = billing.people;
  const detail =
    people.mode === "always"
      ? people.people_hours_left != null
        ? `te quedan ${people.people_hours_left.toLocaleString("es-AR", { maximumFractionDigits: 1 })} h con quién habló`
        : "quién habló en todas las reuniones"
      : `te quedan ${people.credits_left ?? 0} de ${people.credits_per_month ?? 0} reuniones con quién habló`;
  return (
    <Link to="/plans" className="mt-2 inline-flex flex-wrap items-center gap-x-2 text-sm text-ink-500 hover:text-ink-900">
      <span className="rounded-full bg-ink-100 px-2.5 py-0.5 text-xs font-semibold text-ink-700">{PLAN_NAME[plan] ?? plan}</span>
      <span>{detail}</span>
    </Link>
  );
}

const STEPS_KEY = "echo_primeros_pasos_ocultos";

/** Primeros pasos para quien recién empieza; se van solos al completarlos (o al cerrarlos). */
function FirstSteps({ hasMeetings }: { hasMeetings: boolean }) {
  const voice = useVoice();
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(STEPS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const { data: myVoice } = useQuery({
    queryKey: ["my-voice"],
    queryFn: () => api<{ has_sample: boolean }>("/api/me/voice", { skipOrg: true }),
    enabled: !hidden,
  });
  if (hidden || !myVoice) return null;
  const steps = [
    { done: hasMeetings, label: "Grabá tu primera reunión", to: "/meetings?new=1" },
    { done: myVoice.has_sample, label: "Grabá tu voz para aparecer con tu nombre", to: "/settings/my-voice" },
    { done: false, label: "Preguntale a Echo por una reunión", action: voice.open, optional: true },
  ];
  if (steps.filter((step) => !step.optional).every((step) => step.done)) return null;
  const close = () => {
    setHidden(true);
    try {
      localStorage.setItem(STEPS_KEY, "1");
    } catch {
      // Sin almacenamiento: vuelve a aparecer al recargar.
    }
  };
  return (
    <section className="mb-8 rounded-3xl border border-ink-100 bg-white p-5" aria-label="Primeros pasos">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold text-ink-900">Primeros pasos</h2>
        <button onClick={close} className="min-h-9 rounded-full px-3 text-xs font-medium text-ink-500 hover:bg-ink-50">
          Ocultar
        </button>
      </div>
      <ol className="grid gap-2 sm:grid-cols-3">
        {steps.map((step, index) => {
          const inner = (
            <>
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  step.done ? "bg-emerald-500 text-white" : "bg-ink-100 text-ink-600"
                }`}
              >
                {step.done ? "✓" : index + 1}
              </span>
              <span className={step.done ? "text-ink-400 line-through" : "text-ink-800"}>{step.label}</span>
            </>
          );
          const className = "flex min-h-12 w-full items-center gap-3 rounded-2xl bg-ink-50/70 px-3.5 py-2.5 text-left text-sm hover:bg-ink-100";
          return (
            <li key={step.label}>
              {step.action ? (
                <button type="button" onClick={step.action} className={className}>{inner}</button>
              ) : (
                <Link to={step.to!} className={className}>{inner}</Link>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
