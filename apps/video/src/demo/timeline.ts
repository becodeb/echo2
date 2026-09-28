/**
 * La grilla del video. La música (public/music.mp3, la de la demo de Testra)
 * va a 120 BPM exactos con el primer golpe en el frame 17 (medido): a 60 fps,
 * un golpe = 30 frames. Todo evento que se ve (un click, un cambio de estado)
 * cae en un golpe; el resto se deriva de estos números.
 */
export const FPS = 60;
/** La demo en sí (30 s); todos los frames de este archivo son relativos a ella. */
export const DURATION = 1800;
/**
 * Antes de la demo va el video del hero de la landing (variante "lee",
 * 5,6 s). La demo arranca a los 5,5 s: 330 frames = 11 golpes, así cada click
 * sigue cayendo en su golpe. La música entra a los 1,5 s, cuando sube la luz,
 * y termina justo con el video (su final natural: 34 s).
 */
export const INTRO = 330;
export const MUSIC_START = 90;
export const TOTAL = INTRO + DURATION; // 2130 = 35,5 s
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
  print: B(38),
  tasks: B(41),
  ask: B(43),
  source: B(49),
  families: B(51),
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
  // "Imprimir" abre la hoja del acta (ActaPrint): un click con resultado a la
  // vista. "PDF" descarga un archivo y en pantalla no pasaba nada.
  imprimir: B(38),
  volver: B(40),
  tabTareas: B(41),
  navAsk: B(43),
  input: B(44),
  enviar: B(46),
  fuente: B(49),
  navFamilias: B(51),
  reuniones: B(52),
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
export const TYPE_START = B(44) + 6;
export const TYPE_END = B(46) - 8;
export const ANSWER_AT = B(47);

/** Copy de dos tonos arriba de la superficie (1 a 4 palabras). */
export type CaptionWord = { text: string; accent?: boolean };
export const CAPTIONS: { from: number; to: number; words: CaptionWord[] }[] = [
  // El problema y, enseguida, que con Echo se termina: las notas se tachan.
  { from: B(0), to: B(3.1), words: [{ text: "Alguien" }, { text: "siempre" }, { text: "toma", accent: true }, { text: "notas.", accent: true }] },
  { from: B(3.4), to: B(7.6), words: [{ text: "Con" }, { text: "Echo," }, { text: "nadie", accent: true }, { text: "más.", accent: true }] },
  { from: B(10), to: B(17.5), words: [{ text: "Vos" }, { text: "escuchás." }, { text: "Echo", accent: true }, { text: "anota.", accent: true }] },
  // Guardar el audio completo es una opción ("Grabar el audio completo",
  // apagada por defecto): no se promete que nunca se guarde.
  { from: B(18.5), to: B(21.8), words: [{ text: "Guardar" }, { text: "el" }, { text: "audio:" }, { text: "opcional.", accent: true }] },
  { from: B(22.3), to: B(25.6), words: [{ text: "Sabe" }, { text: "quién", accent: true }, { text: "habló.", accent: true }] },
  { from: B(25.8), to: B(29.8), words: [{ text: "Por" }, { text: "familia" }, { text: "y", accent: true }, { text: "gravedad.", accent: true }] },
  { from: B(30.4), to: B(35.3), words: [{ text: "Acta" }, { text: "verificada.", accent: true }] },
  { from: B(35.5), to: B(40.6), words: [{ text: "La" }, { text: "institución" }, { text: "decide.", accent: true }] },
  { from: B(41.1), to: B(42.8), words: [{ text: "Tareas" }, { text: "con", accent: true }, { text: "fecha.", accent: true }] },
  { from: B(43.4), to: B(50.8), words: [{ text: "Echo", accent: true }, { text: "recuerda." }] },
  { from: B(51.4), to: B(53.6), words: [{ text: "Todo" }, { text: "en", accent: true }, { text: "orden.", accent: true }] },
];
