import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MeetingOut } from "../api/types";
import { useAuth } from "../state/auth";
import { useMyAccess } from "../state/access";
import { useSeesInternal } from "../state/internalGroups";
import { Avatar } from "./ui";
import { EchoFace } from "./EchoFace";
import { AnnouncementPopup } from "./AnnouncementPopup";
import { AskPanel } from "./AskPanel";
import { CommandPalette } from "./CommandPalette";
import { Icon, type IconName } from "./icons";
import { NotificationsPanel } from "./NotificationsPanel";
import { VoicePrompt } from "./VoicePrompt";
import { CreditDots, effectivePlan, PLAN_NAME, useBilling } from "./billing";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
}

// Como la barra de ElevenLabs: lo de todos los días arriba, y debajo de un
// título chico lo del colegio.
const NAV_MAIN: NavItem[] = [
  { to: "/", label: "Inicio", icon: "home" },
  { to: "/meetings", label: "Reuniones", icon: "meetings" },
  { to: "/internal", label: "Reuniones internas", icon: "internal" },
  { to: "/tasks", label: "Mi trabajo", icon: "tasks" },
];
const NAV_SCHOOL: NavItem[] = [
  { to: "/people", label: "Personas", icon: "people" },
  { to: "/families", label: "Familias", icon: "families" },
  { to: "/projects", label: "Proyectos", icon: "projects" },
  { to: "/reports", label: "Reportes", icon: "reports" },
];

/** Título de la barra de arriba según la ruta (como el de cada página de ElevenLabs). */
function pageTitle(pathname: string): string {
  const exact: Record<string, string> = {
    "/": "Inicio",
    "/meetings": "Reuniones",
    "/internal": "Reuniones internas",
    "/tasks": "Mi trabajo",
    "/projects": "Proyectos",
    "/people": "Personas",
    "/families": "Familias",
    "/reports": "Reportes",
    "/ask": "Preguntale a Echo",
    "/search": "Buscar",
    "/plans": "Planes",
    "/usage": "Consumo",
    "/admin": "Panel de Becode",
  };
  if (exact[pathname]) return exact[pathname];
  if (pathname.startsWith("/settings")) return "Ajustes";
  if (pathname.startsWith("/meetings/")) return "Reunión";
  if (pathname.startsWith("/projects/")) return "Proyecto";
  if (pathname.startsWith("/people/")) return "Persona";
  return "Echo";
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, activeOrg } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const { data: myAccess } = useMyAccess();
  const seesInternal = useSeesInternal();
  const location = useLocation();
  // Dentro de una reunión interna se marca su sección y no "Reuniones". Lee la
  // reunión que la página ya cargó: no la vuelve a pedir.
  const openMeetingId = /^\/meetings\/([^/]+)/.exec(location.pathname)?.[1];
  const { data: openMeeting } = useQuery<MeetingOut>({
    queryKey: ["meeting", openMeetingId],
    // La misma consulta que la página de la reunión; apagada: solo lee el caché.
    queryFn: () => api<MeetingOut>(`/api/meetings/${openMeetingId}`),
    enabled: false,
  });
  const inInternal = openMeeting?.kind === "interna";
  const live = /^\/meetings\/[^/]+\/live/.test(location.pathname);

  const { data: notifData } = useQuery({
    queryKey: ["notifications", activeOrg?.id],
    queryFn: () => api<{ unread_count: number }>("/api/notifications?unread_only=true"),
    refetchInterval: 60_000,
    enabled: !!activeOrg,
  });
  const unread = notifData?.unread_count ?? 0;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // En la página de Preguntale a Echo el panel sobra: es lo mismo en grande.
  useEffect(() => {
    if (location.pathname === "/ask") setAskOpen(false);
  }, [location.pathname]);

  // Con el panel de preguntas abierto (en la computadora) la barra queda en íconos.
  const collapsed = askOpen;
  const navLink = (item: NavItem) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === "/"}
      onClick={() => setMobileNav(false)}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) => {
        const active =
          item.to === "/internal" ? isActive || inInternal : item.to === "/meetings" ? isActive && !inInternal : isActive;
        return `flex items-center gap-2.5 rounded-xl px-2.5 py-[7px] text-[14px] font-medium transition-colors duration-150 ${
          collapsed ? "md:justify-center md:px-0" : ""
        } ${active ? "bg-ink-100 text-ink-900" : "text-ink-600 hover:bg-ink-50 hover:text-ink-900"}`;
      }}
    >
      <Icon name={item.icon} />
      <span className={collapsed ? "md:hidden" : ""}>{item.label}</span>
    </NavLink>
  );

  return (
    // h-dvh y no h-screen: en el celular 100vh incluye la barra del navegador y
    // el final de la página queda tapado.
    <div
      className={`flex h-dvh overflow-hidden transition-colors duration-300 ${askOpen ? "md:bg-[#f1f2f5]" : ""}`}
    >
      {/* Barra lateral */}
      <aside
        className={`${mobileNav ? "flex" : "hidden"} absolute inset-y-0 left-0 z-40 w-60 flex-col border-r border-ink-100 bg-white transition-[width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] md:static md:flex ${
          collapsed ? "md:w-16 md:border-r-0 md:bg-transparent" : ""
        }`}
      >
        <div className={`flex items-center gap-2.5 px-5 pb-3 pt-5 ${collapsed ? "md:justify-center md:px-0" : ""}`}>
          <span className="text-ink-900">
            <EchoFace mood="idle" size={26} />
          </span>
          <span className={`text-[17px] font-semibold tracking-tight text-ink-900 ${collapsed ? "md:hidden" : ""}`}>Echo</span>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-1" aria-label="Secciones">
          {NAV_MAIN.filter((item) => item.to !== "/internal" || seesInternal).map(navLink)}
          <p className={`px-2.5 pb-1.5 pt-5 text-[12px] font-medium text-ink-400 ${collapsed ? "md:hidden" : ""}`}>Colegio</p>
          {collapsed && <div className="hidden pt-4 md:block" />}
          {NAV_SCHOOL.map(navLink)}
        </nav>

        <div className="space-y-1 p-3">
          {!collapsed && <PlanCard onNavigate={() => setMobileNav(false)} />}
          {user?.is_superadmin &&
            navLink({ to: "/admin", label: "Panel de Becode", icon: "admin" })}
        </div>
      </aside>

      {/* click-out del nav móvil */}
      {mobileNav && <div className="fixed inset-0 z-30 bg-ink-950/30 md:hidden" onClick={() => setMobileNav(false)} />}

      {/* Contenido: con el panel de preguntas abierto se vuelve una tarjeta, como en ElevenLabs. */}
      <div
        className={`flex min-w-0 flex-1 flex-col bg-[#fafbfc] transition-[margin,border-radius,box-shadow] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${
          askOpen ? "md:my-2 md:overflow-hidden md:rounded-2xl md:border md:border-ink-200/70 md:shadow-[0_1px_3px_rgba(16,24,40,0.06),0_12px_32px_-16px_rgba(16,24,40,0.18)]" : ""
        }`}
      >
        <header className="flex items-center gap-1 border-b border-ink-100 bg-white px-3 py-2 md:hidden">
          <button onClick={() => setMobileNav(true)} className="rounded-full p-2 text-ink-600 hover:bg-ink-100" aria-label="Menú">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <span className="flex min-w-0 flex-1 items-center gap-2 px-1">
            <span className="truncate font-semibold text-ink-900">{pageTitle(location.pathname)}</span>
            {myAccess?.superadmin_visit && <SuperadminTag org={activeOrg?.name ?? "esta sede"} compact />}
          </span>
          <RoundButton label="Buscar" onClick={() => setPaletteOpen(true)}>
            <Icon name="search" />
          </RoundButton>
          <RoundButton label="Preguntale a Echo" onClick={() => setAskOpen(true)}>
            <Icon name="ask" />
          </RoundButton>
          <RoundButton label="Notificaciones" onClick={() => setNotificationsOpen((open) => !open)} badge={unread} toggle="notifications" active={notificationsOpen}>
            <Icon name="bell" />
          </RoundButton>
          <ProfileMenu />
        </header>
        {!live && (
          <TopBar
            title={pageTitle(location.pathname)}
            superadminVisit={myAccess?.superadmin_visit ? activeOrg?.name ?? "esta sede" : null}
            onSearch={() => setPaletteOpen(true)}
            askOpen={askOpen}
            onAsk={() => setAskOpen((open) => !open)}
            onNotifications={() => setNotificationsOpen((open) => !open)}
            notificationsOpen={notificationsOpen}
            unread={unread}
          />
        )}

        <main className="min-h-0 flex-1 overflow-y-auto">
          {/* Cada sección entra con un fundido corto en vez de aparecer de golpe. */}
          <div key={location.pathname} className="page-in h-full">
            {children}
          </div>
        </main>
      </div>

      {/* Panel de preguntas: al costado en la computadora, pantalla completa en el celular. */}
      {askOpen && (
        <>
          <div className="animate-slide-in hidden w-[380px] shrink-0 md:flex">
            <AskPanel onClose={() => setAskOpen(false)} />
          </div>
          <div className="animate-fade-up fixed inset-0 z-50 flex bg-[#f6f7f9] md:hidden">
            <AskPanel onClose={() => setAskOpen(false)} />
          </div>
        </>
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      {notificationsOpen && (
        <NotificationsPanel
          onClose={() => setNotificationsOpen(false)}
          // Colgando de la campanita: corre a la izquierda si el panel de preguntas está abierto.
          className={askOpen ? "md:right-[396px]" : "md:right-4"}
        />
      )}
      <AnnouncementPopup />
      <VoicePrompt />
    </div>
  );
}

function RoundButton({
  label,
  onClick,
  badge = 0,
  active = false,
  toggle,
  children,
}: {
  label: string;
  onClick: () => void;
  badge?: number;
  active?: boolean;
  // Para que el panel que abre no se cierre al tocar el mismo botón.
  toggle?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-notifications-toggle={toggle === "notifications" ? "" : undefined}
      aria-expanded={toggle ? active : undefined}
      aria-label={label}
      title={label}
      className={`relative flex h-9 w-9 items-center justify-center rounded-full transition-colors ${
        active ? "bg-ink-100 text-ink-900" : "text-ink-600 hover:bg-ink-100 hover:text-ink-900"
      }`}
    >
      {children}
      {badge > 0 && (
        <span className="absolute -right-0.5 -top-0.5 min-w-[17px] rounded-full bg-accent-500 px-1 text-center text-[10px] font-semibold leading-[17px] text-white ring-2 ring-white">
          {badge > 9 ? "9+" : badge}
        </span>
      )}
    </button>
  );
}

/**
 * Barra de arriba en la computadora, como la de ElevenLabs: el título de la
 * página, la búsqueda al centro y a la derecha los accesos en píldoras, las
 * notificaciones y el perfil.
 */
function TopBar({
  title,
  superadminVisit,
  onSearch,
  askOpen,
  onAsk,
  onNotifications,
  notificationsOpen,
  unread,
}: {
  title: string;
  // Nombre de la sede que un superadmin está viendo sin ser miembro.
  superadminVisit: string | null;
  onSearch: () => void;
  askOpen: boolean;
  onAsk: () => void;
  onNotifications: () => void;
  notificationsOpen: boolean;
  unread: number;
}) {
  return (
    <div className="hidden h-14 shrink-0 items-center gap-3 border-b border-ink-100 bg-white px-5 md:flex">
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <h1 className="truncate text-[15px] font-semibold text-ink-900">{title}</h1>
        {superadminVisit && <SuperadminTag org={superadminVisit} />}
      </div>
      {askOpen ? (
        // Con el panel de preguntas abierto no hay lugar: la búsqueda queda en un ícono.
        <RoundButton label="Buscar" onClick={onSearch}>
          <Icon name="search" />
        </RoundButton>
      ) : (
        <button
          type="button"
          onClick={onSearch}
          className="flex w-56 items-center gap-2 rounded-full border border-ink-200 bg-white px-3 py-1.5 text-[13px] text-ink-400 transition-colors hover:border-ink-300 lg:w-64"
        >
          <Icon name="search" size={16} />
          <span className="flex-1 text-left">Buscar…</span>
          <kbd className="rounded-md border border-ink-200 px-1.5 text-[10px] text-ink-400">Ctrl K</kbd>
        </button>
      )}
      <button
        type="button"
        onClick={onAsk}
        aria-pressed={askOpen}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors ${
          askOpen
            ? "border-ink-900 bg-ink-900 text-white"
            : "border-ink-200 bg-white text-ink-700 hover:border-ink-300 hover:bg-ink-50"
        }`}
      >
        <Icon name="ask" size={16} />
        Preguntar
      </button>
      <RoundButton label="Notificaciones" onClick={onNotifications} badge={unread} toggle="notifications" active={notificationsOpen}>
        <Icon name="bell" />
      </RoundButton>
      <ProfileMenu />
    </div>
  );
}

/** El perfil arriba a la derecha: quién sos, en qué organización, y tu cuenta. */
function ProfileMenu() {
  const { user, activeOrg, organizations, switchOrg, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };
  const item =
    "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm text-ink-700 transition-colors hover:bg-ink-50 hover:text-ink-900";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Tu cuenta"
        className="flex h-9 w-9 items-center justify-center rounded-full ring-1 ring-ink-200 transition-shadow hover:ring-ink-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
      >
        <Avatar name={user.name} color={user.avatar_color} size={30} />
      </button>
      {open && (
        <div
          role="menu"
          className="animate-fade-up absolute right-0 top-11 z-50 w-72 overflow-hidden rounded-2xl border border-ink-100 bg-white p-1.5 shadow-[0_16px_48px_-12px_rgba(20,24,36,0.25)]"
        >
          <div className="flex items-center gap-3 px-2.5 pb-3 pt-2">
            <Avatar name={user.name} color={user.avatar_color} size={36} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink-900">{user.name}</p>
              <p className="truncate text-xs text-ink-400">{user.email}</p>
            </div>
          </div>
          {organizations.length > 1 && (
            <div className="border-t border-ink-100 py-1.5">
              <p className="px-2.5 pb-1 pt-1 text-[11px] font-medium text-ink-400">Organización</p>
              <div className="max-h-48 overflow-y-auto">
                {organizations.map((org) => (
                  <button
                    key={org.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={org.id === activeOrg?.id}
                    onClick={() => {
                      setOpen(false);
                      if (org.id === activeOrg?.id) return;
                      switchOrg(org.id);
                      navigate("/");
                      window.location.reload();
                    }}
                    className={item}
                  >
                    <span className="min-w-0 flex-1 truncate">{org.is_personal ? "Mi cuenta individual" : org.name}</span>
                    {org.id === activeOrg?.id && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                        <path d="m5 12.5 4.5 4.5L19 7.5" />
                      </svg>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="border-t border-ink-100 py-1.5">
            <button type="button" role="menuitem" onClick={() => go("/plans")} className={item}>
              <Icon name="plans" size={17} /> Mi plan
            </button>
            <button type="button" role="menuitem" onClick={() => go("/usage")} className={item}>
              <Icon name="usage" size={17} /> Consumo
            </button>
            <button type="button" role="menuitem" onClick={() => go("/settings")} className={item}>
              <Icon name="settings" size={17} /> Ajustes
            </button>
            {user.is_superadmin && (
              <button type="button" role="menuitem" onClick={() => go("/admin")} className={item}>
                <Icon name="admin" size={17} /> Panel de Becode
              </button>
            )}
          </div>
          <div className="border-t border-ink-100 pt-1.5">
            <button type="button" role="menuitem" onClick={() => logout()} className={item}>
              <Icon name="logout" size={17} /> Cerrar sesión
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * El plan y los créditos del mes, siempre a mano: cada punto es una reunión
 * con quién habló. Lleva a Planes.
 */
function PlanCard({ onNavigate }: { onNavigate: () => void }) {
  const { data: billing } = useBilling();
  const { user } = useAuth();
  const navigate = useNavigate();
  if (!billing) return <div className="mb-2 h-[62px] animate-pulse rounded-2xl bg-ink-50" />;
  // Las cuentas de Becode tienen todo habilitado: no es "Gratis" ni hay que mejorar nada.
  const plan = user?.is_superadmin ? "becode" : effectivePlan(billing);
  const people = billing.people;
  const credits = people.mode !== "always" && people.credits_per_month != null;
  return (
    <button
      type="button"
      onClick={() => {
        onNavigate();
        navigate("/plans");
      }}
      className="mb-2 block w-full rounded-2xl border border-ink-100 bg-white p-3 text-left shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-shadow hover:shadow-[0_4px_16px_-8px_rgba(16,24,40,0.2)]"
    >
      <span className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-semibold text-ink-800">{PLAN_NAME[plan] ?? plan}</span>
        {credits ? (
          <CreditDots total={people.credits_per_month ?? 0} left={people.credits_left ?? 0} size="sm" />
        ) : (
          <span className="whitespace-nowrap text-[11px] font-medium text-ink-400">Todo incluido</span>
        )}
      </span>
      <span className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-ink-400">
        <span className="truncate">
          {credits ? `${people.credits_left} de ${people.credits_per_month} este mes` : "Quién habló en todas las reuniones"}
        </span>
        {plan === "base" && <span className="shrink-0 font-semibold text-ink-700">Mejorar</span>}
      </span>
    </button>
  );
}

/** Una etiqueta chica en vez de la franja: estás en una sede ajena como superadmin. */
function SuperadminTag({ org, compact = false }: { org: string; compact?: boolean }) {
  return (
    <span
      title={`Estás viendo ${org} como superadmin. Queda registrado en su historial.`}
      className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800"
    >
      {compact ? "Superadmin" : `Superadmin · ${org}`}
    </span>
  );
}
