import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { Shimmer } from "./billing";
import { Icon, type IconName } from "./icons";

interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  read: boolean;
  created_at: string;
}

/** "hace 3 horas", "hace 4 meses". */
export function timeAgo(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const format = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "recién";
}

// El dibujo de cada tipo, en un círculo de color (como las imágenes de las novedades de ElevenLabs).
const KIND_ART: { match: (kind: string) => boolean; icon: IconName; tone: string }[] = [
  { match: (k) => k.startsWith("announcement:"), icon: "megaphone", tone: "from-accent-400 to-accent-600 text-white" },
  { match: (k) => k === "plan_request", icon: "sparkle", tone: "from-amber-300 to-orange-500 text-white" },
  { match: (k) => k.startsWith("minutes"), icon: "doc", tone: "from-sky-300 to-sky-600 text-white" },
  { match: (k) => k.startsWith("task"), icon: "check", tone: "from-emerald-300 to-emerald-600 text-white" },
  { match: (k) => k.startsWith("comment"), icon: "comment", tone: "from-fuchsia-300 to-fuchsia-600 text-white" },
];

function art(kind: string) {
  return KIND_ART.find((item) => item.match(kind)) ?? { icon: "bell" as IconName, tone: "from-ink-200 to-ink-400 text-white" };
}

/**
 * Notificaciones en un panel que se despliega desde la campanita, con las
 * tarjetas de las novedades de ElevenLabs: título, texto, cuándo fue y un
 * dibujo redondo a la derecha.
 * Tocar una lleva adonde corresponde y la marca leída.
 */
export function NotificationsPanel({ onClose, className = "" }: { onClose: () => void; className?: string }) {
  const { activeOrg } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["notifications-list", activeOrg?.id],
    queryFn: () => api<{ unread_count: number; notifications: NotificationItem[] }>("/api/notifications"),
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
    queryClient.invalidateQueries({ queryKey: ["notifications-list"] });
    queryClient.invalidateQueries({ queryKey: ["notifications-full"] });
  };
  const markAll = useMutation({
    mutationFn: () => api("/api/notifications/read-all", { method: "POST" }),
    onSuccess: refresh,
  });

  // Se cierra al tocar afuera o con Escape, como el panel de novedades de ElevenLabs.
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target)) return;
      // El botón de la campanita abre y cierra él mismo.
      if ((target as HTMLElement).closest?.("[data-notifications-toggle]")) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [onClose]);

  const open = (item: NotificationItem) => {
    if (!item.read) void api(`/api/notifications/${item.id}/read`, { method: "POST" }).then(refresh).catch(() => {});
    onClose();
    if (item.link) navigate(item.link);
  };

  const items = data?.notifications ?? [];
  return (
    <div
      ref={panel}
      role="dialog"
      aria-label="Notificaciones"
      // Se abre ahí mismo, colgando de la campanita (en el celular, de lado a lado).
      className={`notif-pop fixed inset-x-2 top-14 z-50 flex max-h-[80dvh] flex-col overflow-hidden rounded-3xl border border-ink-100 bg-white shadow-[0_20px_56px_-16px_rgba(20,24,36,0.32)] md:inset-x-auto md:top-[52px] md:max-h-[72vh] md:w-[420px] ${className}`}
    >
      <div className="flex min-h-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-ink-100 px-5 py-4">
          <h2 className="flex-1 text-[15px] font-semibold text-ink-900">Notificaciones</h2>
          {(data?.unread_count ?? 0) > 0 && (
            <button
              type="button"
              onClick={() => markAll.mutate()}
              className="rounded-full px-2.5 py-1 text-xs font-medium text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900"
            >
              Marcar todo como leído
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink-800"
            aria-label="Cerrar"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2].map((index) => <Shimmer key={index} className="h-20" />)}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-ink-50 text-ink-400">
                <Icon name="bell" size={22} />
              </span>
              <p className="text-sm font-medium text-ink-700">Estás al día</p>
              <p className="max-w-xs text-xs text-ink-400">Acá vas a ver cuando un acta esté lista, te asignen una tarea o te comenten algo.</p>
            </div>
          ) : (
            <ul className="divide-y divide-ink-100">
              {items.map((item, index) => {
                const { icon, tone } = art(item.kind);
                return (
                  <li key={item.id} className="animate-fade-up" style={{ animationDelay: `${Math.min(index, 8) * 30}ms`, animationFillMode: "backwards" }}>
                    <button
                      type="button"
                      onClick={() => open(item)}
                      className="flex w-full gap-4 px-5 py-4 text-left transition-colors hover:bg-ink-50/70"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="flex items-start gap-2 text-sm font-semibold leading-snug text-ink-900">
                          {!item.read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent-500" aria-label="Sin leer" />}
                          <span>{item.title}</span>
                        </p>
                        {item.body && <p className="mt-1 line-clamp-3 text-[13px] leading-relaxed text-ink-500">{item.body}</p>}
                        <p className="mt-2 text-xs text-ink-400">{timeAgo(item.created_at)}</p>
                      </div>
                      <span
                        aria-hidden
                        className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br shadow-inner ${tone}`}
                      >
                        <Icon name={icon} size={22} />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
