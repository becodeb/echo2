import { Easing, interpolate } from "remotion";
import { toScreen, type Space } from "./camera";
import {
  ASK_INPUT,
  ASK_SEND,
  CLASIFICAR,
  FAM_REUNIONES,
  GUARDAR,
  INICIAR,
  MODAL_COMENZAR,
  actaButtons,
  claimY,
  DETAIL_X,
  footerCenter,
  memberCenter,
  navCenter,
  severityCenter,
  tabCenter,
} from "./layout";
import { PRINT_VOLVER } from "./scenes/ActaPrint";
import { SOURCE_LINK } from "./scenes/Ask";
import { ACT, B, CLICK } from "./timeline";

type Target = { f: number; space: Space; x: number; y: number; click?: boolean };

const estado = (status: "draft" | "in_review") => actaButtons(status).find((b) => b.id === "estado")!;
const imprimir = actaButtons("approved").find((b) => b.id === "imprimir")!;

/** Adónde va el cursor y cuándo llega. Los clicks llegan justo en su golpe. */
const TARGETS: Target[] = [
  { f: B(5) - 8, space: "screen", x: 1560, y: 1130 },
  { f: CLICK.comenzar, space: "modal", x: MODAL_COMENZAR.x, y: MODAL_COMENZAR.y, click: true },
  // Pasa por "Grabar el audio completo" y lo deja sin tildar: es una opción.
  { f: B(9), space: "app", x: 640, y: 381 },
  { f: CLICK.iniciar, space: "app", x: INICIAR.x + 18, y: INICIAR.y + 4, click: true },
  { f: B(11.2), space: "app", x: 1010, y: 560 },
  { f: CLICK.momento, space: "app", ...footerCenter("momento"), click: true },
  { f: CLICK.finalizar, space: "app", ...footerCenter("finalizar"), click: true },
  { f: B(21), space: "app", x: 900, y: 520 },
  { f: B(24.8), space: "app", x: 1040, y: 250 },
  { f: CLICK.clasificar, space: "app", ...CLASIFICAR, click: true },
  { f: CLICK.amarillo, space: "app", ...severityCenter("amarillo"), click: true },
  { f: CLICK.madre, space: "app", ...memberCenter(0), click: true },
  { f: CLICK.guardar, space: "app", ...GUARDAR, click: true },
  { f: CLICK.tabActa, space: "app", ...tabCenter("minutes"), click: true },
  { f: B(32), space: "app", x: DETAIL_X + 420, y: claimY(1) + 4 },
  { f: CLICK.enviarRevision, space: "detail", x: estado("draft").cx, y: estado("draft").cy, click: true },
  { f: CLICK.aprobar, space: "detail", x: estado("in_review").cx, y: estado("in_review").cy, click: true },
  { f: CLICK.imprimir, space: "detail", x: imprimir.cx, y: imprimir.cy, click: true },
  { f: B(39), space: "app", x: 760, y: 470 },
  { f: CLICK.volver, space: "app", ...PRINT_VOLVER, click: true },
  { f: CLICK.tabTareas, space: "app", ...tabCenter("tasks"), click: true },
  { f: B(42.5), space: "app", x: 900, y: 360 },
  { f: CLICK.navAsk, space: "app", ...navCenter("Preguntale a Echo"), click: true },
  { f: CLICK.input, space: "app", x: ASK_INPUT.x + 260, y: ASK_INPUT.y + ASK_INPUT.h / 2, click: true },
  { f: CLICK.enviar, space: "app", x: ASK_SEND.x, y: ASK_SEND.y, click: true },
  { f: CLICK.fuente, space: "app", ...SOURCE_LINK, click: true },
  { f: CLICK.navFamilias, space: "app", ...navCenter("Familias"), click: true },
  { f: CLICK.reuniones, space: "app", ...FAM_REUNIONES, click: true },
  { f: B(53.2), space: "app", x: 560, y: 560 },
  { f: ACT.logo + 26, space: "screen", x: 1560, y: 1130 },
];

const ease = Easing.bezier(0.42, 0, 0.18, 1);

function position(frame: number) {
  const index = Math.max(0, TARGETS.findIndex((t, i) => frame < (TARGETS[i + 1]?.f ?? Infinity)));
  const from = TARGETS[index];
  const to = TARGETS[index + 1];
  const a = toScreen(frame, from.space, from.x, from.y);
  if (!to) return a;
  const b = toScreen(frame, to.space, to.x, to.y);
  const distance = Math.hypot(b.x - a.x, b.y - a.y);
  // Viaje proporcional a la distancia, y siempre con un respiro después del click.
  const travel = Math.min(to.f - from.f - 6, Math.max(16, 12 + distance * 0.028));
  const start = to.f - travel;
  if (frame <= start) return a;
  const t = ease(Math.min(1, (frame - start) / travel));
  // Un arco suave: la mano no va en línea recta.
  const arc = Math.sin(Math.PI * t) * Math.min(60, distance * 0.08);
  const nx = -(b.y - a.y) / (distance || 1);
  const ny = (b.x - a.x) / (distance || 1);
  return { x: a.x + (b.x - a.x) * t + nx * arc, y: a.y + (b.y - a.y) * t + ny * arc };
}

export function Cursor({ frame }: { frame: number }) {
  if (frame < TARGETS[0].f || frame > TARGETS[TARGETS.length - 1].f) return null;
  const { x, y } = position(frame);
  const clicks = TARGETS.filter((t) => t.click).map((t) => t.f);
  const press = clicks.reduce((scale, at) => {
    const d = frame - at;
    if (d < -4 || d > 10) return scale;
    return Math.min(scale, interpolate(d, [-4, 0, 10], [1, 0.84, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  }, 1);
  const ring = clicks
    .map((at) => frame - at)
    .filter((d) => d >= 0 && d <= 16)
    .map((d) => ({ r: interpolate(d, [0, 16], [5, 20], { easing: Easing.out(Easing.cubic) }), o: interpolate(d, [0, 16], [0.4, 0]) }))[0];

  return (
    <>
      {ring && (
        <div
          className="pointer-events-none absolute rounded-full border-2 border-ink-900"
          style={{ left: x - ring.r, top: y - ring.r, width: ring.r * 2, height: ring.r * 2, opacity: ring.o }}
        />
      )}
      <svg
        className="pointer-events-none absolute"
        width={30}
        height={30}
        viewBox="0 0 24 24"
        style={{ left: x - 5, top: y - 2.5, transform: `scale(${press})`, transformOrigin: "5px 2.5px", filter: "drop-shadow(0 1px 1.5px rgba(0,0,0,0.25))" }}
      >
        <path d="M4 2v17l4.5-4.2 2.8 6.4 2.7-1.2-2.7-6.2H17.5L4 2z" fill="#0c0e16" stroke="#ffffff" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    </>
  );
}
