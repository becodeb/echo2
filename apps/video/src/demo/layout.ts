/**
 * Coordenadas de la app "virtual" (1280×720, el tamaño de una notebook). La
 * UI se arma con estos números y el cursor apunta a los mismos, así un click
 * siempre cae en el centro del botón que cambia.
 */
export const APP_W = 1280;
export const APP_H = 720;
export const SIDEBAR_W = 240;
export const MAIN_X = SIDEBAR_W;
export const MAIN_W = APP_W - SIDEBAR_W; // 1040
export const MAIN_CX = MAIN_X + MAIN_W / 2; // 760

/** Barra lateral: ítems de 36 px de alto cada 38 px. */
export const NAV_TOP = 112;
export const NAV_STEP = 38;
export const NAV_ITEMS = [
  "Inicio",
  "Reuniones",
  "Mi trabajo",
  "Proyectos",
  "Personas",
  "Familias",
  "Reportes",
  "Preguntale a Echo",
] as const;
export const navCenter = (label: (typeof NAV_ITEMS)[number]) => ({
  x: 112,
  y: NAV_TOP + NAV_ITEMS.indexOf(label) * NAV_STEP + 18,
});

/** Modal "Nueva reunión" (su propio espacio: 512×536). */
export const MODAL_W = 512;
export const MODAL_H = 536;
export const MODAL_COMENZAR = { x: 408, y: 494, w: 160, h: 36 };

/** Vivo. */
export const LIVE_HEADER_H = 56;
export const LIVE_FOOTER_Y = 660;
export const LIVE_ASIDE_X = 1024;
export const LIVE_TEXT_X = 296; // columna max-w-2xl centrada en el área del transcript
export const LIVE_TEXT_W = 672;
export const INICIAR = { x: MAIN_CX, y: 566, w: 320, h: 48 };
/** Pie de acciones: vúmetro + botones, centrado en el área principal. */
export const FOOTER_BUTTONS = [
  { id: "pausar", label: "Pausar", w: 76, variant: "soft" },
  { id: "negra", label: "Pantalla negra", w: 124, variant: "ghost" },
  { id: "momento", label: "⭐ Momento", w: 112, variant: "ghost" },
  { id: "nota", label: "Nota", w: 60, variant: "ghost" },
  { id: "finalizar", label: "Finalizar", w: 90, variant: "danger" },
] as const;
const FOOTER_GAP = 8;
const VU_W = 28 + 12;
const footerTotal = VU_W + FOOTER_BUTTONS.reduce((sum, b) => sum + b.w, 0) + FOOTER_GAP * FOOTER_BUTTONS.length;
export const FOOTER_START = MAIN_CX - footerTotal / 2;
export const footerCenter = (id: (typeof FOOTER_BUTTONS)[number]["id"]) => {
  let x = FOOTER_START + VU_W + FOOTER_GAP;
  for (const button of FOOTER_BUTTONS) {
    if (button.id === id) return { x: x + button.w / 2, y: LIVE_FOOTER_Y + 30 };
    x += button.w + FOOTER_GAP;
  }
  throw new Error(id);
};

/** Detalle de la reunión (contenedor max-w-4xl: x 336–1184). */
export const DETAIL_X = 336;
export const DETAIL_R = 1184;
export const DETAIL_W = DETAIL_R - DETAIL_X;
export const CLASS_Y = 128; // panel de clasificación
export const CLASS_COLLAPSED_H = 50;
export const CLASS_OPEN_H = 386;
export const CLASIFICAR = { x: 1146, y: CLASS_Y + 25 };
/** En el panel abierto (relativo al panel). */
export const SEVERITY_BUTTONS = [
  { id: "", label: "Sin definir", w: 94 },
  { id: "verde", label: "Verde", w: 76 },
  { id: "amarillo", label: "Amarillo", w: 96 },
  { id: "rojo", label: "Rojo", w: 66 },
] as const;
export const SEVERITY_Y = 198; // fila de botones dentro del panel
export const severityCenter = (id: string) => {
  let x = DETAIL_X + 16;
  for (const button of SEVERITY_BUTTONS) {
    if (button.id === id) return { x: x + button.w / 2, y: CLASS_Y + SEVERITY_Y + 16 };
    x += button.w + 8;
  }
  throw new Error(id);
};
export const MEMBER_Y = 272; // primera fila de "¿Quiénes vinieron?"
export const memberCenter = (index: number) => ({ x: DETAIL_X + 24, y: CLASS_Y + MEMBER_Y + 10 + index * 26 });
export const GUARDAR = { x: DETAIL_X + 16 + 42, y: CLASS_Y + 352 };

/** Tabs: debajo del panel de clasificación. */
export const TABS = [
  { id: "summary", label: "Resumen", w: 88 },
  { id: "transcript", label: "Transcript", w: 104 },
  { id: "minutes", label: "Acta", w: 62 },
  { id: "tasks", label: "Tareas", w: 76 },
  { id: "chat", label: "Chat", w: 64 },
] as const;
export const tabsY = (classHeight: number) => CLASS_Y + classHeight + 24;
export const tabCenter = (id: (typeof TABS)[number]["id"], classHeight = CLASS_COLLAPSED_H) => {
  let x = DETAIL_X;
  for (const tab of TABS) {
    if (tab.id === id) return { x: x + tab.w / 2, y: tabsY(classHeight) + 21 };
    x += tab.w + 4;
  }
  throw new Error(id);
};
export const CONTENT_Y = tabsY(CLASS_COLLAPSED_H) + 42 + 24; // 268

/** Acta: botones alineados a la derecha en la segunda fila de la barra. */
export const ACTA_ROW2_Y = CONTENT_Y + 44;
export const actaButtons = (status: "draft" | "in_review" | "approved") => {
  const list = [
    { id: "imprimir", label: "Imprimir", w: 86, variant: "primary" as const },
    { id: "editar", label: "Editar", w: 70, variant: "soft" as const },
    ...(status === "approved"
      ? []
      : [
          status === "draft"
            ? { id: "estado", label: "Enviar a revisión", w: 138, variant: "soft" as const }
            : { id: "estado", label: "Aprobar", w: 82, variant: "soft" as const },
        ]),
    { id: "regenerar", label: "Regenerar", w: 98, variant: "soft" as const },
    { id: "pdf", label: "PDF", w: 54, variant: "ghost" as const },
    { id: "docx", label: "DOCX", w: 66, variant: "ghost" as const },
    { id: "md", label: "MD", w: 50, variant: "ghost" as const },
  ];
  const total = list.reduce((sum, b) => sum + b.w, 0) + 8 * (list.length - 1);
  let x = DETAIL_R - total;
  return list.map((button) => {
    const placed = { ...button, x, cx: x + button.w / 2, cy: ACTA_ROW2_Y + 18 };
    x += button.w + 8;
    return placed;
  });
};
export const VERIFY_Y = ACTA_ROW2_Y + 52; // tarjeta de verificación
export const claimY = (index: number) => VERIFY_Y + 48 + index * 26 + 10;

/** Preguntale a Echo: columna max-w-3xl centrada. */
export const ASK_X = 400;
export const ASK_R = 1120;
export const ASK_INPUT = { x: 400, y: 648, w: 626, h: 48 };
export const ASK_SEND = { x: 1073, y: 672, w: 86 };

/** Familias. */
export const FAM_REUNIONES = { x: 1052, y: 205 };
export const PANEL_X = APP_W - 672;
