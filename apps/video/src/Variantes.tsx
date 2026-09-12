import { AbsoluteFill, Easing, interpolate, interpolateColors, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Maneras de pasar de negro a blanco en las que los ojos ya están desde el
 * primer frame: el blanco los destapa, no los trae. Los ojos se dibujan arriba
 * de todo y pestañean al final. Algunas variantes cambian el color de los ojos
 * al pasar el arco; otras los hacen actuar (cansado, mira, lee, guiña).
 *
 * La geometría sale del tamaño de la composición, así la misma variante se
 * renderiza horizontal (1920x1080) o vertical (1080x1920) para celular.
 */
const INK = "#0c0e16";
const PAPER = "#fafbfc";
const EYE = { w: 150, h: 225, gap: 112 };

export type VarianteId =
  | "horizonte"
  | "horizonte-suave"
  | "horizonte-lento"
  | "cae"
  | "ola"
  | "lateral"
  | "diagonal"
  | "cortina"
  | "dos-luces"
  | "halo-ojos"
  | "cae-suave"
  | "cae-rebote"
  | "cae-agua"
  | "invierte"
  | "invierte-rebote"
  | "despierta"
  | "funde"
  | "cansado"
  | "mira"
  | "lee"
  | "guino";

export type VarianteCfg = {
  id: VarianteId;
  code?: string; // id de la composición; si falta, v01, v02...
  nombre: string;
  segundos: number;
  rise: [number, number];
  blinks: [number, number];
  vertical?: boolean; // además se registra una composición 1080x1920
};

export const VARIANTES: VarianteCfg[] = [
  { id: "horizonte", nombre: "Horizonte: sube un arco desde abajo", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "horizonte-suave", nombre: "Horizonte con borde difuso", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "horizonte-lento", nombre: "Horizonte lento", segundos: 4.6, rise: [0.5, 2.5], blinks: [3.0, 3.4] },
  { id: "cae", nombre: "Cae un arco desde arriba", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "ola", nombre: "Sube como una ola", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "lateral", nombre: "Entra desde la izquierda", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "diagonal", nombre: "Barrido diagonal", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "cortina", nombre: "Se cierra desde los dos lados", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "dos-luces", nombre: "Dos discos que salen de los ojos", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "halo-ojos", nombre: "Luz suave que nace en cada ojo", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  // Tres caídas más, aparte de v04: manejan su propio tiempo (usan `seg`).
  { id: "cae-suave", code: "v04a", nombre: "Cae despacio y se asienta", segundos: 4.2, rise: [0.5, 2.0], blinks: [2.5, 2.9] },
  { id: "cae-rebote", code: "v04b", nombre: "Cae, toca los ojos y rebota", segundos: 4.6, rise: [0.5, 2.45], blinks: [2.9, 3.3] },
  { id: "cae-agua", code: "v04c", nombre: "Cae como agua, el borde ondula y se calma", segundos: 4.5, rise: [0.5, 2.3], blinks: [2.8, 3.2] },
  // Caídas donde los ojos arrancan blancos y cambian de color al pasar el arco.
  { id: "invierte", code: "v04d", nombre: "Ojos blancos que se invierten al pasar el arco", segundos: 4, rise: [0.5, 1.7], blinks: [2.2, 2.6] },
  { id: "invierte-rebote", code: "v04e", nombre: "Se invierten y el arco rebota en ellos", segundos: 4.6, rise: [0.5, 2.45], blinks: [2.9, 3.3] },
  { id: "despierta", code: "v04f", nombre: "Arrancan cerrados y se abren al pasar el arco", segundos: 4.2, rise: [0.5, 2.0], blinks: [2.6, 3.0] },
  { id: "funde", code: "v04g", nombre: "Se funden de blanco a negro al pasar el arco", segundos: 4.2, rise: [0.5, 2.0], blinks: [2.5, 2.9] },
  // Caídas donde, después del arco, los ojos actúan.
  { id: "cansado", code: "v04h", nombre: "Se despierta cansado: abre a medias, se le caen, pestañeo lento", segundos: 5.4, rise: [0.5, 1.7], blinks: [4.5, 4.5] },
  { id: "mira", code: "v04i", nombre: "Mira a un lado, al otro, y de vuelta al frente", segundos: 5.2, rise: [0.5, 1.7], blinks: [4.1, 4.5] },
  { id: "lee", code: "v04j", nombre: "Lee dos renglones, resume y te mira", segundos: 5.6, rise: [0.5, 1.7], blinks: [4.5, 4.9], vertical: true },
  { id: "guino", code: "v04k", nombre: "Guiña un ojo y después pestañea", segundos: 4.8, rise: [0.5, 1.7], blinks: [3.4, 3.8] },
];

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
/** Progreso 0..1 entre dos segundos, con una curva de Remotion. */
const tramo = (seg: number, desde: number, hasta: number, curva: (x: number) => number) =>
  curva(clamp01((seg - desde) / (hasta - desde)));
/** Valor por tramos: en cada tiempo de `ts` vale `vs`, y entre medio interpola (suave). */
const curva = (seg: number, ts: number[], vs: number[], easing = Easing.inOut(Easing.quad)) =>
  interpolate(seg, ts, vs, { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing });

/** Geometría según el tamaño del cuadro. */
type Geo = {
  W: number;
  H: number;
  EYE_CX: [number, number];
  EYE_CY: number;
  /** Elipse gigante: su borde es un arco muy abierto, como el horizonte de un planeta. */
  PLANETA: { w: number; h: number; sag: number }; // sag: cuánto baja el arco en los bordes del cuadro
  LATERAL: { w: number; h: number; sag: number };
};

function geometria(W: number, H: number): Geo {
  // En vertical el cuadro es más alto que ancho: la elipse tiene que ser más
  // alta que el recorrido completo, si no queda una banda sin cubrir arriba.
  const planeta = { w: 2 * W, h: Math.max(1.4 * W, 1.25 * H) };
  const lateral = { w: 2 * H, h: 2.5 * H };
  // sag = b * (1 - sqrt(1 - (a/2 / a)^2)) con el cuadro ocupando la mitad del eje mayor
  const sag = (b: number) => (b / 2) * (1 - Math.sqrt(0.75));
  return {
    W,
    H,
    EYE_CX: [W / 2 - (EYE.gap / 2 + EYE.w / 2), W / 2 + (EYE.gap / 2 + EYE.w / 2)],
    EYE_CY: H / 2,
    PLANETA: { ...planeta, sag: sag(planeta.h) },
    LATERAL: { ...lateral, sag: sag(lateral.w) },
  };
}

/** Borde inferior (y del centro) de una caída con gravedad que toca los ojos,
 *  rebota dos veces y termina de cubrir. */
function bordeRebote(g: Geo, seg: number) {
  const contacto = g.EYE_CY + EYE.h / 2;
  const fin = g.H + g.PLANETA.sag + 60;
  if (seg < 0.5) return -60;
  if (seg < 1.2) return lerp(-60, contacto, tramo(seg, 0.5, 1.2, Easing.in(Easing.quad)));
  if (seg < 1.55) return contacto - 92 * Math.sin(((seg - 1.2) / 0.35) * Math.PI);
  if (seg < 1.8) return contacto - 28 * Math.sin(((seg - 1.55) / 0.25) * Math.PI);
  return lerp(contacto, fin, tramo(seg, 1.8, 2.45, Easing.inOut(Easing.cubic)));
}

/** Borde inferior del arco en las caídas simples; null si la variante no cae así. */
function bordeDe(g: Geo, variant: VarianteId, seg: number): number | null {
  const fin = g.H + g.PLANETA.sag + 60;
  switch (variant) {
    case "invierte":
    case "cansado":
    case "mira":
    case "lee":
    case "guino":
      return lerp(-60, fin, tramo(seg, 0.5, 1.7, Easing.inOut(Easing.cubic)));
    case "despierta":
    case "funde":
      return lerp(-60, fin, tramo(seg, 0.5, 2.0, Easing.inOut(Easing.cubic)));
    case "cae-rebote":
    case "invierte-rebote":
      return bordeRebote(g, seg);
    default:
      return null;
  }
}

function Blanco({ g, variant, t, seg }: { g: Geo; variant: VarianteId; t: number; seg: number }) {
  const { W, H, EYE_CX, EYE_CY, PLANETA, LATERAL } = g;
  const elipse = (extra: React.CSSProperties = {}): React.CSSProperties => ({
    position: "absolute",
    width: PLANETA.w,
    height: PLANETA.h,
    left: (W - PLANETA.w) / 2,
    borderRadius: "50%",
    background: PAPER,
    ...extra,
  });
  const vertical = (extra: React.CSSProperties = {}): React.CSSProperties => ({
    position: "absolute",
    width: LATERAL.w,
    height: LATERAL.h,
    top: (H - LATERAL.h) / 2,
    borderRadius: "50%",
    background: PAPER,
    ...extra,
  });

  const borde = bordeDe(g, variant, seg);
  if (borde !== null) return <div style={elipse({ top: borde - PLANETA.h })} />;

  switch (variant) {
    case "horizonte":
    case "horizonte-lento":
      return <div style={elipse({ top: lerp(H + 40, -(PLANETA.sag + 40), t) })} />;

    case "horizonte-suave":
      return <div style={elipse({ top: lerp(H + 160, -(PLANETA.sag + 200), t), filter: "blur(70px)" })} />;

    case "cae":
      return <div style={elipse({ top: lerp(-PLANETA.h - 40, H + PLANETA.sag + 40 - PLANETA.h, t) })} />;

    case "cae-suave": {
      // Cae lento, con el borde apenas difuso, y se asienta.
      const tt = tramo(seg, 0.5, 2.0, Easing.inOut(Easing.cubic));
      return <div style={elipse({ top: lerp(-PLANETA.h - 80, H + PLANETA.sag + 80 - PLANETA.h, tt), filter: "blur(10px)" })} />;
    }

    case "cae-agua": {
      // Cae como agua: el borde es un arco que ondula suave y se calma al final.
      const tt = tramo(seg, 0.5, 2.3, Easing.inOut(Easing.cubic));
      const sag = PLANETA.sag * 0.83;
      const A = 22 * (1 - tt * 0.7);
      const y0 = lerp(-60, H + sag + 80, tt);
      const puntos: string[] = [];
      for (let i = 0; i <= 64; i++) {
        const x = (W * i) / 64;
        const u = (x - W / 2) / (W / 2);
        const y = y0 - sag * u * u + A * Math.sin((x / W) * Math.PI * 2 * 2.2 + seg * Math.PI * 1.8);
        puntos.push(`${x.toFixed(1)} ${y.toFixed(1)}`);
      }
      const d = `M ${puntos.join(" L ")} L ${W} -300 L 0 -300 Z`;
      return (
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, filter: "blur(2.5px)" }}>
          <path d={d} fill={PAPER} />
        </svg>
      );
    }

    case "ola": {
      const A = 45;
      const y0 = lerp(H + A + 20, -A - 20, t);
      const phase = t * Math.PI * 2;
      const puntos: string[] = [];
      for (let i = 0; i <= 48; i++) {
        const x = (W * i) / 48;
        const y = y0 + A * Math.sin((x / W) * Math.PI * 3 + phase);
        puntos.push(`${x.toFixed(1)} ${y.toFixed(1)}`);
      }
      const d = `M ${puntos.join(" L ")} L ${W} ${H + 200} L 0 ${H + 200} Z`;
      return (
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <path d={d} fill={PAPER} />
        </svg>
      );
    }

    case "lateral":
      return <div style={vertical({ left: lerp(-LATERAL.w - 40, W + LATERAL.sag + 40 - LATERAL.w, t) })} />;

    case "diagonal":
      return (
        <div style={{ position: "absolute", inset: 0, transform: "rotate(-20deg)" }}>
          <div
            style={elipse({
              width: PLANETA.w * 1.15,
              height: PLANETA.h * 1.12,
              left: (W - PLANETA.w * 1.15) / 2,
              top: lerp(H + 900, -1200, t),
            })}
          />
        </div>
      );

    case "cortina":
      return (
        <>
          <div style={vertical({ left: lerp(-LATERAL.w - 40, W / 2 + LATERAL.sag + 40 - LATERAL.w, t) })} />
          <div style={vertical({ left: lerp(W + 40, W / 2 - LATERAL.sag - 40, t) })} />
        </>
      );

    case "dos-luces": {
      const r = t * Math.hypot(W, H) * 0.56;
      return (
        <>
          {EYE_CX.map((cx) => (
            <div
              key={cx}
              style={{
                position: "absolute",
                left: cx - r,
                top: EYE_CY - r,
                width: r * 2,
                height: r * 2,
                borderRadius: "50%",
                background: PAPER,
              }}
            />
          ))}
        </>
      );
    }

    case "halo-ojos": {
      const f = 260;
      const r = lerp(-f, Math.hypot(W, H) * 0.56 + f, t);
      const capa = (cx: number) =>
        `radial-gradient(circle at ${cx}px ${EYE_CY}px, ${PAPER} ${r - f}px, rgba(250, 251, 252, 0) ${r + f}px)`;
      return <div style={{ position: "absolute", inset: 0, background: EYE_CX.map(capa).join(", ") }} />;
    }

    default:
      return null;
  }
}

/** Qué hacen los ojos después del arco: desplazamiento del par y escala de cada ojo. */
type Actuacion = { x: number; y: number; sx: number; syIzq: number; syDer: number };

function actuacion(variant: VarianteId, seg: number): Actuacion {
  const base: Actuacion = { x: 0, y: 0, sx: 1, syIzq: 1, syDer: 1 };
  switch (variant) {
    case "cansado": {
      // Cerrados; abren a medias, se le caen, cierran despacio y ahí sí abren bien.
      const sy = curva(seg, [1.8, 2.6, 3.0, 3.15, 3.6], [0.06, 0.55, 0.35, 0.06, 1]);
      const cabeceo = seg > 1.8 && seg < 3.6 ? 10 * Math.sin((seg - 1.8) * 2.4) : 0;
      return { ...base, y: cabeceo, syIzq: sy, syDer: sy };
    }
    case "mira": {
      // Mira a la izquierda, sostiene, a la derecha, sostiene, y vuelve.
      const x = curva(seg, [1.9, 2.2, 2.6, 3.0, 3.4, 3.7], [0, -150, -150, 150, 150, 0]);
      const sx = 1 - (0.1 * Math.abs(x)) / 150; // se achica un poco al girar
      return { ...base, x, sx };
    }
    case "lee": {
      // Lee dos renglones (va y viene), un poco entrecerrado de concentración,
      // vuelve al centro, abre bien y te mira.
      const x = curva(seg, [1.9, 2.7, 2.85, 3.65, 3.95], [-160, 160, -160, 160, 0]);
      const y = curva(seg, [1.9, 2.7, 2.85, 3.65, 3.95], [-24, -24, 24, 24, 0]);
      const sy = curva(seg, [1.8, 2.0, 3.65, 3.95], [1, 0.8, 0.8, 1]);
      return { ...base, x, y, syIzq: sy, syDer: sy };
    }
    case "guino": {
      // Guiña el ojo derecho: cierra rápido, abre un poco más lento.
      const syDer = curva(seg, [2.2, 2.3, 2.55], [1, 0.06, 1], Easing.inOut(Easing.quad));
      return { ...base, syDer };
    }
    default:
      return base;
  }
}

export const Variante = ({ variant }: { variant: VarianteId }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const g = geometria(width, height);
  const cfg = VARIANTES.find((v) => v.id === variant) ?? VARIANTES[0];
  const at = (seconds: number) => seconds * fps;
  const seg = frame / fps;

  const t = interpolate(frame, [at(cfg.rise[0]), at(cfg.rise[1])], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  // Un pestañeo: cierra en 80 ms, abre en 120 ms.
  const blink = (start: number) =>
    interpolate(frame, [at(start), at(start + 0.08), at(start + 0.2)], [1, 0.06, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.inOut(Easing.quad),
    });
  const pestaneo = Math.min(blink(cfg.blinks[0]), blink(cfg.blinks[1]));

  const borde = bordeDe(g, variant, seg) ?? -1e9;
  let apertura = 1;
  let color: React.CSSProperties = { background: INK };
  if (variant === "invierte" || variant === "invierte-rebote" || variant === "despierta") {
    // Blancos "por diferencia": blancos sobre el negro, negros cuando el arco los cubre.
    color = { background: PAPER, mixBlendMode: "difference" };
  }
  if (variant === "despierta") {
    // Cerrados (una línea) hasta que el borde del arco los cruza; ahí se abren.
    apertura = lerp(0.06, 1, Easing.out(Easing.cubic)(clamp01((borde - (g.EYE_CY - 40)) / 160)));
  }
  if (variant === "funde") {
    // Se funden de blanco a negro mientras el arco los cruza.
    const mezcla = clamp01((borde - (g.EYE_CY - 110)) / 220);
    color = { background: interpolateColors(mezcla, [0, 1], [PAPER, INK]) };
  }
  const act = actuacion(variant, seg);

  // Cada ojo se ubica solo (sin un contenedor con transform): un contenedor
  // así aísla el blend "difference" y los ojos dejarían de verse sobre el blanco.
  const eye = (cx: number, sy: number): React.CSSProperties => ({
    position: "absolute",
    width: EYE.w,
    height: EYE.h,
    left: cx - EYE.w / 2 + act.x,
    top: g.EYE_CY - EYE.h / 2 + act.y,
    borderRadius: 999,
    transform: `scale(${act.sx}, ${Math.min(apertura, pestaneo, sy)})`,
    ...color,
  });

  return (
    <AbsoluteFill style={{ background: INK, overflow: "hidden" }}>
      <Blanco g={g} variant={variant} t={t} seg={seg} />
      <div style={eye(g.EYE_CX[0], act.syIzq)} />
      <div style={eye(g.EYE_CX[1], act.syDer)} />
    </AbsoluteFill>
  );
};
