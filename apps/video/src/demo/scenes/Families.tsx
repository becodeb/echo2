import { Badge, Button, Card } from "../../../../web/src/components/ui";
import { mix, pressScale, settle } from "../anim";
import { APP_W, FAM_REUNIONES, MAIN_X, PANEL_X } from "../layout";
import { CLICK } from "../timeline";

const FAMILIES = [
  { name: "Familia Romero", meta: "Legajo 1482 · 2 responsables · 4 reuniones · 1 prof." },
  { name: "Familia Acosta", meta: "Legajo 1377 · 2 responsables · 2 reuniones" },
  { name: "Familia Benítez", meta: "Legajo 1519 · 1 responsable · 3 reuniones · 2 prof." },
  { name: "Familia Gómez", meta: "Legajo 1290 · 2 responsables · 1 reunión" },
];

const HISTORY: { title: string; date: string; severity: "amarillo" | "verde"; reason: string; acta: string; attendance: string; ok: boolean }[] = [
  { title: "Familia Romero · 28 sept", date: "lun, 28 sept · 24 min", severity: "amarillo", reason: "Seguimiento de convivencia", acta: "Acta aprobada · Nº 14", attendance: "Faltó algún responsable (vino Laura Romero)", ok: false },
  { title: "Familia Romero · 2 sept", date: "mié, 2 sept · 31 min", severity: "verde", reason: "Rendimiento académico", acta: "Acta aprobada · Nº 9", attendance: "Vinieron todos los responsables", ok: true },
  { title: "Familia Romero · 14 sept", date: "lun, 14 sept · 22 min", severity: "amarillo", reason: "Seguimiento de convivencia", acta: "Acta aprobada · Nº 6", attendance: "Vinieron todos los responsables", ok: true },
];
const BAR = { verde: "bg-emerald-500", amarillo: "bg-amber-400", rojo: "bg-red-500" };

function Stat({ value, label, children }: { value: string; label: string; children?: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl border border-ink-100 bg-ink-50/60 px-3 py-2.5">
      <p className="truncate text-lg font-semibold text-ink-900">{value}</p>
      <p className="truncate text-xs text-ink-500">{label}</p>
      {children}
    </div>
  );
}

/** pages/Families.tsx + el panel "Reuniones de la familia". */
export function Families({ frame }: { frame: number }) {
  const open = settle(frame, CLICK.reuniones + 2, 160);
  return (
    <div className="absolute inset-y-0 right-0 bg-[#fafbfc]" style={{ left: MAIN_X }}>
      <div className="absolute inset-0" style={{ left: -MAIN_X }}>
        <div className="absolute space-y-5" style={{ left: 336, width: 848, top: 40 }}>
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Familias</h1>
            <Button>Nueva familia</Button>
          </div>
          <div className="flex gap-1 border-b border-ink-100">
            <span className="-mb-px border-b-2 border-ink-900 px-3 py-2 text-sm font-medium text-ink-900">Familias</span>
            <span className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-ink-400">Profesionales</span>
          </div>
          <div className="space-y-2">
            {FAMILIES.map((family, index) => (
              <Card key={family.name} className="flex items-center gap-3 !py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-medium text-ink-900">{family.name}</p>
                  <p className="text-sm text-ink-500">{family.meta}</p>
                </div>
                <span className="text-sm font-medium text-accent-600">Drive ↗</span>
                <Button
                  variant="soft"
                  style={index === 0 ? { transform: `scale(${pressScale(frame, CLICK.reuniones)})` } : undefined}
                >
                  Reuniones
                </Button>
                <Button variant="ghost">Detalle</Button>
              </Card>
            ))}
          </div>
        </div>

        {open > 0.001 && (
          <>
            <div className="absolute inset-0 bg-ink-950/40" style={{ opacity: open }} />
            <aside
              className="absolute inset-y-0 flex flex-col bg-white shadow-2xl"
              style={{ left: PANEL_X, width: APP_W - PANEL_X, transform: `translateX(${mix(64, 0, open)}px)`, opacity: Math.min(1, open * 1.4) }}
            >
              <header className="border-b border-ink-100 px-6 py-4">
                <p className="text-xs font-medium uppercase tracking-wide text-ink-400">Reuniones de la familia</p>
                <h2 className="text-xl font-semibold text-ink-900">Familia Romero</h2>
                <p className="mt-0.5 text-sm text-ink-500">Legajo 1482 · Laura Romero, Martín Romero</p>
              </header>
              <div className="space-y-5 px-6 py-4">
                <div className="grid grid-cols-4 gap-2">
                  <Stat value="4" label="reuniones" />
                  <Stat value="hoy" label="última reunión" />
                  <Stat value="3 de 4" label="asistencia completa" />
                  <Stat value="0" label="en rojo">
                    <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-ink-100">
                      <div className="bg-emerald-500" style={{ flexGrow: 2 }} />
                      <div className="bg-amber-400" style={{ flexGrow: 2 }} />
                      <div className="bg-red-500" style={{ flexGrow: 0 }} />
                    </div>
                  </Stat>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {[
                    { label: "Verde", dot: "bg-emerald-500" },
                    { label: "Amarillo", dot: "bg-amber-400" },
                    { label: "Rojo", dot: "bg-red-500" },
                    { label: "Sin gravedad", dot: "bg-ink-300" },
                  ].map((chip) => (
                    <span key={chip.label} className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 px-3 py-1 text-xs font-medium text-ink-600">
                      <span className={`h-2 w-2 rounded-full ${chip.dot}`} />
                      {chip.label}
                    </span>
                  ))}
                </div>
                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-400">Septiembre de 2026</h3>
                  {HISTORY.map((meeting) => (
                    <div key={meeting.title} className="flex gap-3 rounded-xl border border-ink-100 bg-white p-3.5">
                      <div className={`w-1 shrink-0 rounded-full ${BAR[meeting.severity]}`} />
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <div className="flex items-baseline justify-between gap-3">
                          <p className="text-[15px] font-medium text-ink-900">{meeting.title}</p>
                          <p className="shrink-0 text-xs text-ink-500">{meeting.date}</p>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge>{meeting.reason}</Badge>
                          <Badge tone="green">{meeting.acta}</Badge>
                          <Badge tone="sky">Familia y profesionales</Badge>
                        </div>
                        <p className={`text-xs ${meeting.ok ? "text-emerald-700" : "text-amber-700"}`}>{meeting.attendance}</p>
                      </div>
                    </div>
                  ))}
                </section>
              </div>
            </aside>
          </>
        )}
      </div>
    </div>
  );
}

export const FAMILIES_REUNIONES = FAM_REUNIONES;
