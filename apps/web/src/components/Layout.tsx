import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { Avatar } from "./ui";
import { EchoFace } from "./EchoFace";
import { CommandPalette } from "./CommandPalette";

const NAV = [
  { to: "/", label: "Inicio", icon: "M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5" },
  { to: "/meetings", label: "Reuniones", icon: "M4 5h16v12H8l-4 4V5z" },
  { to: "/tasks", label: "Mi trabajo", icon: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2" },
  { to: "/projects", label: "Proyectos", icon: "M3 7h6l2 2h10v10H3V7z" },
  { to: "/people", label: "Personas", icon: "M16 11a4 4 0 1 0-8 0M4 21c0-4 3.5-6 8-6s8 2 8 6" },
  { to: "/ask", label: "Preguntale a Echo", icon: "M12 3a9 9 0 1 0 4.5 16.8L21 21l-1.2-4.5A9 9 0 0 0 12 3z" },
];

function NavIcon({ d }: { d: string }) {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d={d} stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, activeOrg, organizations, switchOrg, logout } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const navigate = useNavigate();

  const { data: notifData } = useQuery({
    queryKey: ["notifications", activeOrg?.id],
    queryFn: () => api<{ unread_count: number }>("/api/notifications?unread_only=true"),
    refetchInterval: 60_000,
    enabled: !!activeOrg,
  });

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

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className={`${mobileNav ? "flex" : "hidden"} absolute inset-y-0 left-0 z-40 w-60 flex-col border-r border-ink-100 bg-white md:static md:flex`}
      >
        <div className="flex items-center gap-2.5 px-5 pb-2 pt-5">
          <span className="text-ink-900">
            <EchoFace mood="idle" size={26} />
          </span>
          <span className="text-[17px] font-semibold tracking-tight text-ink-900">Echo</span>
        </div>

        <div className="px-3 pb-1 pt-3">
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex w-full items-center justify-between rounded-lg border border-ink-150 border-ink-200 bg-ink-50 px-3 py-1.5 text-sm text-ink-400 hover:border-ink-300"
          >
            <span>Buscar…</span>
            <kbd className="rounded border border-ink-200 bg-white px-1.5 text-[10px] text-ink-400">Ctrl K</kbd>
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setMobileNav(false)}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive ? "bg-ink-100 text-ink-900" : "text-ink-500 hover:bg-ink-50 hover:text-ink-800"
                }`
              }
            >
              <NavIcon d={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-ink-100 p-3">
          <NavLink
            to="/settings"
            onClick={() => setMobileNav(false)}
            className={({ isActive }) =>
              `mb-1 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium ${
                isActive ? "bg-ink-100 text-ink-900" : "text-ink-500 hover:bg-ink-50"
              }`
            }
          >
            <NavIcon d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.5-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.5 2 1.5A7 7 0 0 0 5 12" />
            Ajustes
            {(notifData?.unread_count ?? 0) > 0 && (
              <span className="ml-auto rounded-full bg-accent-500 px-1.5 text-[10px] font-semibold text-white">
                {notifData!.unread_count}
              </span>
            )}
          </NavLink>

          {organizations.length > 1 && (
            <select
              value={activeOrg?.id ?? ""}
              onChange={(event) => {
                switchOrg(event.target.value);
                navigate("/");
                window.location.reload();
              }}
              className="mb-2 w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-700"
              aria-label="Organización activa"
            >
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          )}

          <div className="flex items-center gap-2.5 rounded-lg px-3 py-2">
            {user && <Avatar name={user.name} color={user.avatar_color} />}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink-800">{user?.name}</p>
              <p className="truncate text-xs text-ink-400">{activeOrg?.name}</p>
            </div>
            <button
              onClick={() => logout()}
              className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
              title="Cerrar sesión"
              aria-label="Cerrar sesión"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <path d="M15 12H4m0 0 3-3m-3 3 3 3M11 4h7a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-7" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      {/* click-out del nav móvil */}
      {mobileNav && (
        <div className="fixed inset-0 z-30 bg-ink-950/30 md:hidden" onClick={() => setMobileNav(false)} />
      )}

      {/* Contenido */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-ink-100 bg-white px-4 py-2.5 md:hidden">
          <button onClick={() => setMobileNav(true)} className="rounded-lg p-1.5 text-ink-600" aria-label="Menú">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
          <span className="text-ink-900"><EchoFace mood="idle" size={22} /></span>
          <span className="font-semibold text-ink-900">Echo</span>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
