import { NAV_ITEMS, NAV_STEP, NAV_TOP, SIDEBAR_W } from "../layout";
import { Face } from "./Face";

// Los mismos íconos (paths) que apps/web/src/components/Layout.tsx.
const ICONS: Record<(typeof NAV_ITEMS)[number], string> = {
  Inicio: "M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5",
  Reuniones: "M4 5h16v12H8l-4 4V5z",
  "Mi trabajo": "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  Proyectos: "M3 7h6l2 2h10v10H3V7z",
  Personas: "M16 11a4 4 0 1 0-8 0M4 21c0-4 3.5-6 8-6s8 2 8 6",
  Familias:
    "M7 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm10 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20c0-3 2.2-5 5-5s5 2 5 5m0 0c0-3 2.2-5 5-5s5 2 5 5",
  Reportes: "M4 20V10m5 10V4m5 16v-7m5 7V8",
  "Preguntale a Echo": "M12 3a9 9 0 1 0 4.5 16.8L21 21l-1.2-4.5A9 9 0 0 0 12 3z",
};

export function Sidebar({ active, frame }: { active: (typeof NAV_ITEMS)[number]; frame: number }) {
  return (
    <aside
      className="absolute inset-y-0 left-0 flex flex-col border-r border-ink-100 bg-white"
      style={{ width: SIDEBAR_W }}
    >
      <div className="flex items-center gap-2.5 px-5 pb-2 pt-5">
        <span className="text-ink-900">
          <Face size={26} frame={frame} blinkAt={[240, 880, 1420]} />
        </span>
        <span className="text-[17px] font-semibold tracking-tight text-ink-900">Echo</span>
      </div>
      <div className="px-3 pb-1 pt-3">
        <div className="flex w-full items-center justify-between rounded-lg border border-ink-200 bg-ink-50 px-3 py-1.5 text-sm text-ink-400">
          <span>Buscar…</span>
          <kbd className="rounded border border-ink-200 bg-white px-1.5 text-[10px] text-ink-400">Ctrl K</kbd>
        </div>
      </div>
      {NAV_ITEMS.map((label, index) => (
        <div
          key={label}
          className={`absolute left-3 right-3 flex items-center gap-2.5 rounded-lg px-3 text-sm font-medium ${
            label === active ? "bg-ink-100 text-ink-900" : "text-ink-500"
          }`}
          style={{ top: NAV_TOP + index * NAV_STEP, height: 36 }}
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d={ICONS[label]} stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {label}
        </div>
      ))}
      <div className="absolute inset-x-0 bottom-0 flex items-center gap-2.5 border-t border-ink-100 p-3">
        <span
          className="inline-flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold text-white"
          style={{ backgroundColor: "#0ea5e9" }}
        >
          LS
        </span>
        <div className="min-w-0 leading-tight">
          <p className="truncate text-sm font-medium text-ink-800">Lucía Sosa</p>
          <p className="truncate text-xs text-ink-400">Colegio San Martín</p>
        </div>
      </div>
    </aside>
  );
}
