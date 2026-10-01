import type { ReactNode } from "react";

/**
 * Estados de reuniones y actas, sin pastillas de color ni puntitos: una
 * píldora de borde suave con texto tranquilo y un ícono fino que dice el
 * estado (el en vivo, con barritas que se mueven).
 */

type Tone = "neutral" | "muted" | "live" | "warn" | "busy" | "error" | "done";

const TONES: Record<Tone, string> = {
  neutral: "border-ink-200 bg-white text-ink-600",
  muted: "border-dashed border-ink-300 bg-transparent text-ink-500",
  live: "border-red-200 bg-white text-red-600",
  warn: "border-amber-200 bg-white text-amber-700",
  busy: "border-ink-200 bg-white text-ink-500",
  error: "border-red-200 bg-white text-red-600",
  done: "border-ink-200 bg-white text-ink-600",
};

export function StatusPill({ tone, icon, children }: { tone: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[3px] text-[12px] font-medium leading-none ${TONES[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 2.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

export const StatusIcons = {
  check: (
    <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden {...stroke}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  ),
  pause: (
    <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden {...stroke}>
      <path d="M9 6v12M15 6v12" />
    </svg>
  ),
  alert: (
    <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden {...stroke}>
      <path d="M12 7.5v5.5M12 16.5v.01" />
      <circle cx="12" cy="12" r="9" />
    </svg>
  ),
  pencil: (
    <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden {...stroke}>
      <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z" />
    </svg>
  ),
  busy: (
    <svg width="12" height="12" viewBox="0 0 24 24" className="animate-spin" aria-hidden {...stroke}>
      <path d="M21 12a9 9 0 1 1-9-9" />
    </svg>
  ),
  live: (
    // Tres barritas como un ecualizador, en lugar del punto que titila.
    <span className="flex h-2.5 items-end gap-[2px]" aria-hidden>
      <span className="live-bar w-[2px] rounded-full bg-current" style={{ animationDelay: "0ms" }} />
      <span className="live-bar w-[2px] rounded-full bg-current" style={{ animationDelay: "180ms" }} />
      <span className="live-bar w-[2px] rounded-full bg-current" style={{ animationDelay: "360ms" }} />
    </span>
  ),
};

const MEETING: Record<string, { label: string; tone: Tone; icon: ReactNode }> = {
  draft: { label: "Borrador", tone: "muted", icon: StatusIcons.pencil },
  live: { label: "En vivo", tone: "live", icon: StatusIcons.live },
  paused: { label: "Pausada", tone: "warn", icon: StatusIcons.pause },
  processing: { label: "Procesando", tone: "busy", icon: StatusIcons.busy },
  completed: { label: "Lista", tone: "done", icon: StatusIcons.check },
  failed: { label: "Falló", tone: "error", icon: StatusIcons.alert },
};

export function MeetingStatus({ status }: { status: string }) {
  const item = MEETING[status] ?? MEETING.draft;
  return (
    <StatusPill tone={item.tone} icon={item.icon}>
      {item.label}
    </StatusPill>
  );
}
