import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, useEffect, useState } from "react";
import { EchoFace, type EchoMood } from "./EchoFace";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" | "soft" }) {
  const base =
    "inline-flex min-h-10 items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500";
  const variants = {
    primary: "bg-ink-900 text-white hover:bg-ink-700",
    soft: "bg-ink-100 text-ink-800 hover:bg-ink-200",
    ghost: "text-ink-600 hover:bg-ink-100 hover:text-ink-900",
    danger: "bg-red-600 text-white hover:bg-red-500",
  };
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function Input({
  label,
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return (
    <label className="block">
      {label && <span className="mb-1.5 block text-sm font-medium text-ink-700">{label}</span>}
      <input
        className={`w-full rounded-full border border-ink-200 bg-white px-4 py-2.5 text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20 ${className}`}
        {...props}
      />
    </label>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-3xl border border-ink-100/80 bg-white p-6 shadow-[0_1px_2px_rgba(16,24,40,0.03)] ${className}`}>
      {children}
    </div>
  );
}

export function Badge({
  children,
  tone = "gray",
}: {
  children: ReactNode;
  tone?: "gray" | "green" | "red" | "amber" | "indigo" | "sky";
}) {
  const tones = {
    gray: "bg-ink-100 text-ink-600",
    green: "bg-emerald-50 text-emerald-700",
    red: "bg-red-50 text-red-700",
    amber: "bg-amber-50 text-amber-700",
    indigo: "bg-indigo-50 text-indigo-700",
    sky: "bg-sky-50 text-sky-700",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg className={`h-4 w-4 animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-label="Cargando">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function EmptyState({
  mood = "idle",
  title,
  children,
}: {
  mood?: EchoMood;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-ink-500">
      <div className="text-ink-300">
        <EchoFace mood={mood} size={56} />
      </div>
      <p className="font-medium text-ink-700">{title}</p>
      {children && <div className="max-w-sm text-sm">{children}</div>}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // La página de atrás no se mueve mientras la ventana está abierta.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      // El fondo scrollea: si la ventana es más alta que la pantalla (celular,
      // teclado abierto), el botón de abajo tiene que poder alcanzarse.
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto overscroll-contain bg-ink-950/40 p-3 pt-4 backdrop-blur-[2px] sm:p-4 sm:pt-[8vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className={`animate-fade-up mb-4 w-full ${wide ? "max-w-3xl" : "max-w-lg"} rounded-3xl border border-ink-100 bg-white p-5 shadow-xl sm:p-7`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink-900">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-full p-2 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
            aria-label="Cerrar"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** La foto de la cuenta de Google si hay; si no (o si no carga), las iniciales. */
export function Avatar({
  name,
  color,
  size = 28,
  src,
}: {
  name: string;
  color: string;
  size?: number;
  src?: string | null;
}) {
  const [broken, setBroken] = useState(false);
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  if (src && !broken) {
    return (
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        // Google no sirve la foto si le llega el referer de otro sitio.
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className="inline-block shrink-0 rounded-full bg-ink-100 object-cover"
        style={{ width: size, height: size }}
        aria-hidden
      />
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{ backgroundColor: color, width: size, height: size, fontSize: size * 0.4 }}
      aria-hidden
    >
      {initials}
    </span>
  );
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "--:--";
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

export function formatDuration(seconds: number): string {
  if (!seconds) return "0 min";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a: Date, b: Date) =>
    a.getDate() === b.getDate() && a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear();
  if (sameDay(date, today)) return "Hoy";
  if (sameDay(date, yesterday)) return "Ayer";
  return date.toLocaleDateString("es", { day: "numeric", month: "short" });
}
