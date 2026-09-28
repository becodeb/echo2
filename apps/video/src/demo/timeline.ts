/**
 * La grilla del video. La música (public/music.mp3, la de la demo de Testra)
 * va a 120 BPM exactos con el primer golpe en el frame 17 (medido): a 60 fps,
 * un golpe = 30 frames. Todo evento que se ve (un click, un cambio de estado)
 * cae en un golpe; el resto se deriva de estos números.
 */
export const FPS = 60;
export const DURATION = 1800; // 30 s
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const BEAT = 30;
export const FIRST_BEAT = 17;
/** Frame del golpe n (acepta medios golpes: B(10.5)). */
export const B = (n: number) => Math.round(FIRST_BEAT + BEAT * n);

/** Actos: cada uno arranca cuando su superficie empieza a transformarse. */
export const ACT = {
  notes: 0,
  modal: B(5),
  live: B(8),
  processing: B(18),
  detail: B(22),
  acta: B(30),
  tasks: B(39),
  ask: B(42),
  source: B(48),
  families: B(50),
  logo: B(54),
  loop: B(58),
} as const;

/** Clicks: el cursor llega y el botón se hunde en ese frame exacto. */
export const CLICK = {
  comenzar: B(7),
  iniciar: B(10),
  momento: B(16),
  finalizar: B(18),
  clasificar: B(26),
  amarillo: B(27),
  madre: B(28),
  guardar: B(29),
  tabActa: B(30),
  enviarRevision: B(36),
  aprobar: B(37),
  pdf: B(38),
  tabTareas: B(39),
  navAsk: B(42),
  input: B(43),
  enviar: B(45),
  fuente: B(48),
  navFamilias: B(50),
  reuniones: B(51),
} as const;

/** Estado del vivo: cada línea entra parcial (gris) y se confirma un golpe después. */
export const LIVE_LINES = [
  { partial: B(11), final: B(12), ms: 2000, text: "Gracias por venir. Queríamos hablar de cómo está Pedro en los recreos." },
  { partial: B(12.4), final: B(13), ms: 7000, text: "En casa lo notamos más callado. No quiere venir al colegio." },
  { partial: B(13.4), final: B(14), ms: 13000, text: "Acordamos una reunión con la psicopedagoga el viernes." },
] as const;

/** Pantalla de proceso: una etapa por golpe (labels reales de MeetingLive). */
export const STAGES = [
  { at: B(18.5), label: "Preparando la reunión…", progress: 6 },
  { at: B(19), label: "Identificando quién habló…", progress: 22 },
  { at: B(20), label: "Extrayendo decisiones y tareas…", progress: 48 },
  { at: B(21), label: "Generando el acta…", progress: 86 },
] as const;

/** Verificación del acta: una afirmación por golpe. */
export const CLAIMS_AT = [B(31), B(32), B(33)] as const;

/** Escritura en Preguntale a Echo. */
export const QUESTION = "¿Qué acordamos con la familia Romero?";
export const TYPE_START = B(43) + 6;
export const TYPE_END = B(45) - 8;
export const ANSWER_AT = B(46);

/** Copy de dos tonos arriba de la superficie (1 a 4 palabras). */
export type CaptionWord = { text: string; accent?: boolean };
export const CAPTIONS: { from: number; to: number; words: CaptionWord[] }[] = [
  { from: B(0), to: B(5), words: [{ text: "Alguien" }, { text: "siempre" }, { text: "toma", accent: true }, { text: "notas.", accent: true }] },
  { from: B(10), to: B(17.5), words: [{ text: "Echo", accent: true }, { text: "escucha." }] },
  { from: B(18.5), to: B(21.8), words: [{ text: "El" }, { text: "audio" }, { text: "no", accent: true }, { text: "se", accent: true }, { text: "guarda.", accent: true }] },
  { from: B(22.3), to: B(25.6), words: [{ text: "Sabe" }, { text: "quién", accent: true }, { text: "habló.", accent: true }] },
  { from: B(25.8), to: B(29.8), words: [{ text: "Por" }, { text: "familia" }, { text: "y", accent: true }, { text: "gravedad.", accent: true }] },
  { from: B(30.4), to: B(35.3), words: [{ text: "Acta" }, { text: "verificada.", accent: true }] },
  { from: B(35.5), to: B(38.8), words: [{ text: "La" }, { text: "institución" }, { text: "decide.", accent: true }] },
  { from: B(39.2), to: B(41.8), words: [{ text: "Tareas" }, { text: "con", accent: true }, { text: "fecha.", accent: true }] },
  { from: B(42.4), to: B(49.8), words: [{ text: "Echo", accent: true }, { text: "recuerda." }] },
  { from: B(50.4), to: B(53.6), words: [{ text: "Todo" }, { text: "en", accent: true }, { text: "orden.", accent: true }] },
];
