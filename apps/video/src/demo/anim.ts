import { Easing, interpolate, spring } from "remotion";
import { FPS } from "./timeline";

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Spring suave, sin rebote visible: 0 → 1 a partir de `start`. */
export const settle = (frame: number, start: number, stiffness = 140) =>
  frame < start
    ? 0
    : spring({ frame: frame - start, fps: FPS, config: { damping: 26, mass: 0.9, stiffness }, durationInFrames: 34 });

/** Lineal con clamp, con easing opcional. */
export const ramp = (frame: number, from: number, to: number, easing = Easing.bezier(0.33, 0, 0.2, 1)) =>
  interpolate(frame, [from, to], [0, 1], { ...CLAMP, easing });

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/**
 * Valores por tramos: cada clave dice "desde el frame f, andá hacia v".
 * Entre clave y clave se interpola con `settle`, arrancando desde donde
 * estaba la anterior, así una transición nunca salta.
 */
export function keyed(frame: number, keys: { f: number; v: number[] }[], stiffness?: number): number[] {
  let value = keys[0].v;
  for (let index = 1; index < keys.length; index++) {
    const key = keys[index];
    if (frame < key.f) break;
    const t = settle(frame, key.f, stiffness);
    value = value.map((from, i) => mix(from, key.v[i], t));
  }
  return value;
}

/**
 * Entrada y salida de un bloque de contenido: blur cortísimo (≤ 6 px) solo
 * mientras cruza; quieto, el texto queda nítido.
 */
export function presence(frame: number, from: number, to = Infinity, inFrames = 12, outFrames = 10) {
  const enter = ramp(frame, from, from + inFrames);
  const leave = Number.isFinite(to) ? ramp(frame, to, to + outFrames) : 0;
  const t = Math.min(enter, 1 - leave);
  const blur = (1 - t) * 6;
  return {
    visible: t > 0.001,
    style: {
      opacity: t,
      filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined,
    },
    t,
  };
}

/** El botón se hunde en el click y vuelve: 1 → 0.96 → 1 en ~14 frames. */
export const pressScale = (frame: number, click: number) => {
  const d = frame - click;
  if (d < -4 || d > 12) return 1;
  return interpolate(d, [-4, 0, 12], [1, 0.955, 1], { ...CLAMP, easing: Easing.out(Easing.quad) });
};

/** Texto que se escribe letra por letra entre dos frames. */
export const typed = (text: string, frame: number, from: number, to: number) =>
  text.slice(0, Math.round(ramp(frame, from, to, Easing.linear) * text.length));
