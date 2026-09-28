import { Badge, Button, Card } from "../../../../web/src/components/ui";
import { mix, pressScale, presence, ramp, settle } from "../anim";
import { detailScroll } from "../camera";
import {
  ACTA_ROW2_Y,
  CLASS_COLLAPSED_H,
  CLASS_OPEN_H,
  CLASS_Y,
  CONTENT_Y,
  DETAIL_R,
  DETAIL_W,
  DETAIL_X,
  GUARDAR,
  MAIN_X,
  MEMBER_Y,
  SEVERITY_BUTTONS,
  SEVERITY_Y,
  TABS,
  VERIFY_Y,
  actaButtons,
  tabsY,
} from "../layout";
import { B, CLAIMS_AT, CLICK } from "../timeline";

export type DetailTab = "transcript" | "minutes" | "tasks";

const SPEAKERS = {
  directora: { name: "Directora", color: "#6366f1" },
  mama: { name: "Mamá de Pedro", color: "#0ea5e9" },
  doe: { name: "Orientadora (DOE)", color: "#10b981" },
};
const SEGMENTS: { ms: string; who: keyof typeof SPEAKERS; text: string }[] = [
  { ms: "00:02", who: "directora", text: "Gracias por venir. Queríamos hablar de cómo está Pedro en los recreos." },
  { ms: "00:07", who: "mama", text: "En casa lo notamos más callado. No quiere venir al colegio." },
  { ms: "00:13", who: "doe", text: "Acordamos una reunión con la psicopedagoga el viernes." },
  { ms: "00:16", who: "directora", text: "Yo coordino con ella y les confirmo el horario." },
  { ms: "00:21", who: "mama", text: "Perfecto. Gracias por escucharnos." },
];
export const HIGHLIGHT_INDEX = 2;

const CLAIMS: { status: "verified" | "weak"; text: string; ms?: string }[] = [
  { status: "verified", text: "La familia notó a Pedro más callado y sin ganas de venir al colegio.", ms: "00:07" },
  { status: "verified", text: "Se acordó una reunión con la psicopedagoga el viernes.", ms: "00:13" },
  { status: "weak", text: "Se hará un nuevo seguimiento en tres semanas." },
];

/** Ubicación de los fragmentos del transcript (para la cámara y el resaltado). */
export const SEGMENT_TOP = CONTENT_Y + 88;
export const SEGMENT_STEP = 76;

function Header({ frame }: { frame: number }) {
  return (
    <>
      <div className="absolute flex items-center gap-3" style={{ left: DETAIL_X, width: DETAIL_W, top: 32 }}>
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Familia Romero · 28 sept</h1>
        <div className="ml-auto">
          <Button variant="soft">Compartir</Button>
        </div>
      </div>
      <div className="absolute" style={{ left: DETAIL_X, top: 76 }}>
        <Badge tone="indigo">Primaria</Badge>
      </div>
      <p className="absolute text-sm text-ink-500" style={{ left: DETAIL_X, top: 100 }}>
        Hoy · 24 min · Directora, Orientadora (DOE), Mamá de Pedro
      </p>
      <Classification frame={frame} />
    </>
  );
}

/** Alto del panel de clasificación en cada frame (se despliega y se pliega). */
export const classHeight = (frame: number) => {
  const open = settle(frame, CLICK.clasificar + 2, 150);
  const close = settle(frame, CLICK.guardar + 2, 150);
  return mix(mix(CLASS_COLLAPSED_H, CLASS_OPEN_H, open), CLASS_COLLAPSED_H, close);
};

function Classification({ frame }: { frame: number }) {
  const height = classHeight(frame);
  const editing = frame >= CLICK.clasificar && frame < CLICK.guardar + 6;
  const saved = frame >= CLICK.guardar;
  const empty = presence(frame, -20, CLICK.clasificar, 1, 8);
  const form = presence(frame, CLICK.clasificar + 6, CLICK.guardar, 10, 8);
  const chips = presence(frame, CLICK.guardar + 8, Infinity, 12);
  const amarillo = frame >= CLICK.amarillo;
  const madre = frame >= CLICK.madre;
  const check = (on: boolean) => (
    <span
      className={`flex h-4 w-4 items-center justify-center rounded border ${on ? "border-accent-600 bg-accent-600" : "border-ink-300 bg-white"}`}
    >
      {on && (
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
          <path d="M2.5 6.2 5 8.5l4.5-5" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </span>
  );
  return (
    <div
      className="absolute overflow-hidden rounded-lg border border-ink-100 bg-white"
      style={{ left: DETAIL_X, width: DETAIL_W, top: CLASS_Y, height }}
    >
      {empty.visible && !saved && (
        <div className="absolute inset-x-4 top-0 flex h-[48px] items-center gap-2" style={empty.style}>
          <span className="text-sm text-ink-500">Esta reunión no está clasificada.</span>
          <span
            className="ml-auto text-sm font-medium text-accent-600"
            style={{ transform: `scale(${pressScale(frame, CLICK.clasificar)})` }}
          >
            Clasificar
          </span>
        </div>
      )}
      {editing && (
        <div className="absolute inset-x-4 top-4 space-y-4" style={form.style}>
          <label className="block max-w-xs">
            <span className="mb-1.5 block text-sm font-medium text-ink-700">¿Con quién fue?</span>
            <Box>Familia y profesionales</Box>
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700">Familia</span>
              <Box>
                Familia Romero <span className="text-ink-400">· 1482</span>
              </Box>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700">Motivo</span>
              <Box>Seguimiento de convivencia</Box>
            </label>
          </div>
          <div className="absolute inset-x-0" style={{ top: SEVERITY_Y - 16 - 26 }}>
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Gravedad</span>
            <div className="flex gap-2">
              {SEVERITY_BUTTONS.map((item) => {
                const on = item.id === "amarillo" ? amarillo : item.id === "" ? !amarillo : false;
                const dot = item.id === "verde" ? "bg-emerald-500" : item.id === "amarillo" ? "bg-amber-400" : "bg-red-500";
                return (
                  <span
                    key={item.label}
                    className={`flex items-center justify-center gap-2 rounded-lg border py-1.5 text-sm ${
                      on ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 text-ink-600"
                    }`}
                    style={{
                      width: item.w,
                      transform: item.id === "amarillo" ? `scale(${pressScale(frame, CLICK.amarillo)})` : undefined,
                    }}
                  >
                    {item.id && <span className={`h-2 w-2 rounded-full ${dot}`} />}
                    {item.label}
                  </span>
                );
              })}
            </div>
          </div>
          <div className="absolute inset-x-0" style={{ top: MEMBER_Y - 16 - 26 }}>
            <span className="mb-1.5 block text-sm font-medium text-ink-700">¿Quiénes vinieron?</span>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-sm" style={{ transform: `scale(${pressScale(frame, CLICK.madre)})`, transformOrigin: "8px 50%" }}>
                {check(madre)}
                <span className="text-ink-800">Laura Romero</span>
                <Badge tone="indigo">madre</Badge>
              </div>
              <div className="flex items-center gap-2 text-sm">
                {check(false)}
                <span className="text-ink-800">Martín Romero</span>
                <Badge tone="indigo">padre</Badge>
              </div>
            </div>
          </div>
          <div className="absolute flex gap-2" style={{ top: GUARDAR.y - CLASS_Y - 16 - 18, left: 0 }}>
            <Button style={{ width: 84, transform: `scale(${pressScale(frame, CLICK.guardar)})` }}>Guardar</Button>
            <Button variant="ghost">Cancelar</Button>
          </div>
        </div>
      )}
      {saved && (
        <div className="absolute inset-x-4 top-0 flex h-[48px] items-center gap-2" style={chips.style}>
          <Badge tone="indigo">Familia Romero</Badge>
          <Badge tone="sky">Familia y profesionales</Badge>
          <Badge>Seguimiento de convivencia</Badge>
          <Badge tone="amber">Amarillo</Badge>
          <Badge tone="amber">Faltó alguno</Badge>
          <span className="ml-auto text-sm font-medium text-accent-600">Editar</span>
        </div>
      )}
    </div>
  );
}

function Box({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full items-center gap-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm">
      <span className="min-w-0 flex-1 truncate text-ink-900">{children}</span>
      <svg width={14} height={14} viewBox="0 0 16 16" fill="none" className="shrink-0 text-ink-400">
        <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

function Tabs({ active, top }: { active: DetailTab; top: number }) {
  return (
    <div className="absolute flex gap-1 border-b border-ink-100" style={{ left: DETAIL_X, width: DETAIL_W, top }}>
      {TABS.map((tab) => (
        <span
          key={tab.id}
          className={`-mb-px border-b-2 py-2.5 text-center text-sm font-medium ${
            tab.id === active ? "border-ink-900 text-ink-900" : "border-transparent text-ink-400"
          }`}
          style={{ width: tab.w }}
        >
          {tab.label}
        </span>
      ))}
    </div>
  );
}

function Transcript({ frame, highlightFrom }: { frame: number; highlightFrom?: number }) {
  const glow = highlightFrom == null ? 0 : ramp(frame, highlightFrom, highlightFrom + 14);
  return (
    <div className="absolute" style={{ left: DETAIL_X, width: DETAIL_W, top: CONTENT_Y }}>
      <div className="flex items-center gap-3">
        <div className="w-72 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-400">
          Buscar en el transcript…
        </div>
        <span className="ml-auto text-sm font-medium text-accent-600">Exportar .md</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-ink-500">Quién habló (tocá para corregir):</span>
        {Object.values(SPEAKERS).map((speaker) => (
          <span key={speaker.name} className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 bg-white px-2.5 py-1 font-medium text-ink-700">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: speaker.color }} />
            {speaker.name}
          </span>
        ))}
      </div>
      <div className="absolute inset-x-0" style={{ top: SEGMENT_TOP - CONTENT_Y }}>
        {SEGMENTS.map((segment, index) => (
          <div
            key={segment.ms}
            className="absolute inset-x-0 rounded-lg px-3 py-2"
            style={{
              top: index * SEGMENT_STEP,
              backgroundColor: index === HIGHLIGHT_INDEX && glow > 0 ? `rgba(99,102,241,${0.1 * glow})` : undefined,
            }}
          >
            <div className="mb-0.5 flex items-baseline gap-2 text-xs">
              <span className="font-mono tabular-nums text-ink-400">{segment.ms}</span>
              <span className="font-semibold" style={{ color: SPEAKERS[segment.who].color }}>
                {SPEAKERS[segment.who].name}
              </span>
            </div>
            <p className="text-[15px] leading-relaxed text-ink-900">{segment.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Minutes({ frame }: { frame: number }) {
  const status = frame >= CLICK.aprobar ? "approved" : frame >= CLICK.enviarRevision ? "in_review" : "draft";
  const badge =
    status === "approved" ? (
      <Badge tone="green">Aprobada</Badge>
    ) : status === "in_review" ? (
      <Badge tone="amber">En revisión</Badge>
    ) : (
      <Badge>Borrador</Badge>
    );
  const verifying = presence(frame, -20, CLAIMS_AT[0] - 4, 1, 8);
  const card = presence(frame, CLAIMS_AT[0] - 4, Infinity, 10);
  return (
    <div className="absolute" style={{ left: DETAIL_X, width: DETAIL_W, top: CONTENT_Y }}>
      <div className="flex h-9 items-center gap-2">
        <Badge tone="indigo">Acta N.º 14</Badge>
        {badge}
        <span className="text-xs text-ink-400">v1 · Generada automáticamente</span>
      </div>
      {actaButtons(status).map((button) => {
        const click = button.id === "estado" ? (status === "draft" ? CLICK.enviarRevision : CLICK.aprobar) : button.id === "imprimir" ? CLICK.imprimir : -99;
        return (
          <Button
            key={button.id + button.label}
            variant={button.variant}
            className="absolute"
            style={{
              left: button.x - DETAIL_X,
              top: ACTA_ROW2_Y - CONTENT_Y,
              width: button.w,
              transform: `scale(${pressScale(frame, click)})`,
            }}
          >
            {button.label}
          </Button>
        );
      })}
      <div className="absolute inset-x-0" style={{ top: VERIFY_Y - CONTENT_Y }}>
        {verifying.visible && (
          <div className="absolute inset-x-0 top-0 flex items-center gap-2 rounded-lg bg-ink-50 px-4 py-3 text-sm text-ink-600" style={verifying.style}>
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" style={{ transform: `rotate(${frame * 9}deg)` }}>
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
              <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
            El acta ya está lista. Echo sigue verificando cada afirmación contra el transcript…
          </div>
        )}
        {card.visible && (
          <div style={card.style}>
            <Card className="border-amber-200 bg-amber-50/50">
              <h3 className="mb-2 text-sm font-semibold text-amber-800">Verificación: 1 afirmación necesita revisión</h3>
              <ul className="space-y-1.5 text-sm">
                {CLAIMS.map((claim, index) => {
                  const at = CLAIMS_AT[index];
                  const shown = presence(frame, at, Infinity, 8);
                  return (
                    <li key={index} className="flex items-start gap-2" style={{ opacity: frame >= at ? 1 : 0.35 }}>
                      <span className="inline-block w-3" style={shown.style}>
                        {frame >= at ? (claim.status === "verified" ? "✓" : "⚠") : ""}
                      </span>
                      <span className={frame >= at ? (claim.status === "verified" ? "text-emerald-800" : "text-amber-800") : "text-ink-500"}>
                        {claim.text}
                        {claim.ms && frame >= at && <span className="ml-2 font-mono text-xs">{claim.ms}</span>}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </div>
        )}
        <div className="absolute inset-x-0" style={{ top: 158 }}>
          <Card>
            <div className="text-[15px] leading-relaxed text-ink-800">
              <h2 className="mb-2 text-lg font-semibold">Motivo</h2>
              <p className="my-2">Seguimiento de convivencia: Pedro está más callado y no quiere venir al colegio.</p>
              <h2 className="mb-2 mt-5 text-lg font-semibold">Acuerdos</h2>
              <ul className="my-2 list-disc pl-5">
                <li className="my-0.5">Reunión con la psicopedagoga el viernes 2 de octubre.</li>
              </ul>
              <h2 className="mb-2 mt-5 text-lg font-semibold">Compromisos</h2>
              <ul className="my-2 list-disc pl-5">
                <li className="my-0.5">Directora: coordinar el horario con la psicopedagoga.</li>
                <li className="my-0.5">Orientadora (DOE): seguimiento con la familia.</li>
              </ul>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Tasks() {
  const rows = [
    { text: "Coordinar reunión con la psicopedagoga", who: "Directora", date: "2026-10-02" },
    { text: "Seguimiento con la familia Romero", who: "Orientadora (DOE)", date: "2026-10-09" },
  ];
  return (
    <div className="absolute" style={{ left: DETAIL_X, width: DETAIL_W, top: CONTENT_Y }}>
      <Card className="overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink-100 text-left text-xs uppercase tracking-wide text-ink-400">
              <th className="px-5 py-3 font-medium">Tarea</th>
              <th className="px-3 py-3 font-medium">Responsable</th>
              <th className="px-3 py-3 font-medium">Fecha</th>
              <th className="px-3 py-3 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {rows.map((row) => (
              <tr key={row.text}>
                <td className="px-5 py-3 text-ink-800">{row.text}</td>
                <td className="px-3 py-3 text-ink-600">{row.who}</td>
                <td className="px-3 py-3 font-mono text-ink-600">{row.date}</td>
                <td className="px-3 py-3">
                  <span className="inline-flex w-32 items-center gap-2 rounded-lg border border-ink-200 bg-white px-2.5 py-1 text-xs text-ink-900">
                    <span className="flex-1">Pendiente</span>
                    <svg width={12} height={12} viewBox="0 0 16 16" fill="none" className="text-ink-400">
                      <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/** Tab activa en cada frame y cuándo cambió (para el cruce de contenido). */
export function tabAt(frame: number, sourceJump: boolean): { tab: DetailTab; since: number } {
  if (sourceJump) return { tab: "transcript", since: CLICK.fuente };
  if (frame >= CLICK.tabTareas) return { tab: "tasks", since: CLICK.tabTareas };
  if (frame >= CLICK.tabActa) return { tab: "minutes", since: CLICK.tabActa };
  return { tab: "transcript", since: -100 };
}

export function Detail({ frame, sourceJump = false }: { frame: number; sourceJump?: boolean }) {
  const { tab, since } = tabAt(frame, sourceJump);
  const content = presence(frame, since, Infinity, 12);
  const tabTop = tabsY(classHeight(frame));
  const shift = tabTop - tabsY(CLASS_COLLAPSED_H);
  return (
    <div className="absolute inset-y-0 right-0 overflow-hidden bg-[#fafbfc]" style={{ left: MAIN_X }}>
      <div className="absolute inset-0" style={{ left: -MAIN_X, transform: `translateY(${-detailScroll(frame)}px)` }}>
        <Header frame={frame} />
        <Tabs active={tab} top={tabTop} />
        <div className="absolute inset-0" style={{ transform: `translateY(${shift}px)`, ...content.style }}>
          {tab === "transcript" && <Transcript frame={frame} highlightFrom={sourceJump ? CLICK.fuente + 10 : undefined} />}
          {tab === "minutes" && <Minutes frame={frame} />}
          {tab === "tasks" && <Tasks />}
        </div>
      </div>
    </div>
  );
}
