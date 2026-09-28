import type { ReactNode } from "react";
import { keyed, mix } from "./anim";
import { APP_H, APP_W, MODAL_H, MODAL_W } from "./layout";
import { ACT, B, CLICK } from "./timeline";

/**
 * La única superficie del video: una forma que cambia de tamaño, radio y
 * color (libreta → modal → app → ícono de Echo → libreta). Adentro, cada
 * contenido se dibuja en su tamaño "real" y se escala para llenarla.
 */
type Rect = [x: number, y: number, w: number, h: number, radius: number, dark: number];

const NOTES: Rect = [740, 300, 440, 540, 18, 0];
const MODAL: Rect = [576, 138, MODAL_W * 1.5, MODAL_H * 1.5, 24, 0];
const APP: Rect = [192, 196, APP_W * 1.2, APP_H * 1.2, 18, 0];
/** Cierre: el ícono crece hasta ser la pantalla negra con la que abre el hero. */
const BLACK: Rect = [-40, -40, 2000, 1160, 0, 1];
export const TILE: Rect = [793, 404, 112, 112, 26, 1];

export const NOTES_VIRTUAL = { w: 440 / 1.5, h: 540 / 1.5 };

export function surfaceAt(frame: number) {
  const [x, y, w, h, radius, dark] = keyed(
    frame,
    [
      { f: 0, v: NOTES },
      { f: ACT.modal, v: MODAL },
      { f: ACT.live, v: APP },
      { f: ACT.logo, v: TILE },
      { f: ACT.loop, v: BLACK },
    ],
    120,
  );
  return { x, y, w, h, radius, dark };
}

/**
 * Cámara dentro de la app: [foco x, foco y, zoom] en coordenadas de la app.
 * Se mueve solo cuando el texto está quieto; los cambios de texto caen con
 * la cámara ya asentada.
 */
const CAMERA_KEYS = [
  { f: ACT.live, v: [640, 360, 1] },
  { f: B(10.4), v: [660, 240, 1.5] }, // el transcript en vivo
  { f: B(15.2), v: [640, 360, 1] },
  { f: B(22.8), v: [760, 420, 1.35] }, // quién habló
  { f: B(25.5), v: [640, 360, 1] },
  { f: B(32.3), v: [720, 430, 1.7] }, // la verificación, una afirmación por golpe
  { f: B(36.8), v: [700, 480, 1.45] }, // el acta: Motivo, Acuerdos, Compromisos
  { f: B(40.3), v: [752, 190, 1.55] }, // estado y botones juntos: se ve cada cambio
  { f: B(43.8), v: [640, 360, 1] },
  { f: B(45.4), v: [640, 250, 1.5] }, // la hoja: membrete, título y el acta
  { f: B(47.2), v: [640, 560, 1.6] }, // firmas y "Acta aprobada"
  { f: B(49.2), v: [640, 360, 1] },
  { f: B(51.3), v: [760, 330, 1.5] }, // las tareas con responsable y fecha
  { f: B(55.2), v: [640, 360, 1] },
  { f: B(60.3), v: [760, 280, 1.28] }, // la respuesta con fuentes
  { f: B(64.3), v: [760, 520, 1.4] }, // el fragmento resaltado
  { f: B(65.6), v: [640, 360, 1] },
  { f: B(67.8), v: [944, 330, 1.3] }, // el historial de la familia
  { f: B(71.6), v: [640, 360, 1] },
];
export const cameraAt = (frame: number): [number, number, number] => {
  const [fx, fy, zoom] = keyed(frame, CAMERA_KEYS, 170);
  // Nunca se ve fuera de la app: el encuadre queda dentro de sus bordes.
  const halfW = APP_W / 2 / zoom;
  const halfH = APP_H / 2 / zoom;
  return [Math.min(APP_W - halfW, Math.max(halfW, fx)), Math.min(APP_H - halfH, Math.max(halfH, fy)), zoom];
};

/** Scroll de la página de la reunión: baja para leer el acta entera. */
export const detailScroll = (frame: number) =>
  keyed(frame, [
    { f: 0, v: [0] },
    { f: B(36.3), v: [118] },
    { f: CLICK.tabTareas, v: [0] },
  ], 150)[0];

export type Space = "app" | "modal" | "screen" | "detail";

/** De coordenadas de un espacio (app, modal) a pantalla, en ese frame. */
export function toScreen(frame: number, space: Space, x: number, y: number) {
  if (space === "screen") return { x, y };
  const surface = surfaceAt(frame);
  if (space === "modal") {
    const scale = surface.w / MODAL_W;
    return { x: surface.x + x * scale, y: surface.y + y * scale };
  }
  const [fx, fy, zoom] = cameraAt(frame);
  const scale = (surface.w / APP_W) * zoom;
  // "detail": coordenadas de la página de la reunión, que puede estar scrolleada.
  const scrolled = space === "detail" ? y - detailScroll(frame) : y;
  return { x: surface.x + surface.w / 2 + (x - fx) * scale, y: surface.y + surface.h / 2 + (scrolled - fy) * scale };
}

/** Un contenido que llena la superficie, escalado desde su tamaño virtual. */
export function Fill({
  width,
  height,
  surface,
  style,
  children,
}: {
  width: number;
  height: number;
  surface: ReturnType<typeof surfaceAt>;
  style?: React.CSSProperties;
  children: ReactNode;
}) {
  const scale = surface.w / width;
  return (
    <div
      className="absolute left-0 top-0 overflow-hidden"
      style={{ width, height, transform: `scale(${scale})`, transformOrigin: "0 0", ...style }}
    >
      {children}
    </div>
  );
}

/** La app con la cámara aplicada (zoom y paneo dentro de la superficie). */
export function AppViewport({
  frame,
  surface,
  style,
  children,
}: {
  frame: number;
  surface: ReturnType<typeof surfaceAt>;
  style?: React.CSSProperties;
  children: ReactNode;
}) {
  const [fx, fy, zoom] = cameraAt(frame);
  const scale = (surface.w / APP_W) * zoom;
  const tx = surface.w / 2 - fx * scale;
  const ty = surface.h / 2 - fy * scale;
  return (
    <div
      className="absolute left-0 top-0"
      style={{
        width: APP_W,
        height: APP_H,
        transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
        transformOrigin: "0 0",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Surface({ frame, children }: { frame: number; children: (surface: ReturnType<typeof surfaceAt>) => ReactNode }) {
  const surface = surfaceAt(frame);
  const light = [255, 255, 255];
  const ink = [12, 14, 22];
  const color = light.map((c, i) => Math.round(mix(c, ink[i], surface.dark)));
  return (
    <div
      className="absolute overflow-hidden"
      style={{
        left: surface.x,
        top: surface.y,
        width: surface.w,
        height: surface.h,
        borderRadius: surface.radius,
        backgroundColor: `rgb(${color.join(",")})`,
        border: surface.dark > 0.99 ? "none" : `1px solid rgba(236,238,242,${1 - surface.dark})`,
        boxShadow: `0 1px 2px rgba(16,24,40,${0.05 * (1 - surface.dark)}), 0 32px 64px -32px rgba(16,24,40,${0.22 * (1 - surface.dark)})`,
      }}
    >
      {children(surface)}
    </div>
  );
}
