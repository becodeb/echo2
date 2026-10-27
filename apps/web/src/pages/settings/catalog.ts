import type { IconName } from "../../components/icons";

/**
 * Qué hay en Ajustes: los cuatro grupos, sus secciones y el índice del
 * buscador. Sin React para que se pueda probar solo (catalog.test.ts).
 */

/** Lo que define qué ve cada uno en Ajustes. */
export interface Viewer {
  /** Admin u owner de la sede (o superadmin): ve todo. */
  admin: boolean;
  /** Dirección o directivo de algún nivel (rank 2 o 3). */
  directive: boolean;
  /** Dirige algún nivel: asigna quién ve qué. */
  managesLevels: boolean;
}

export type SectionId =
  | "my-voice"
  | "my-drive"
  | "privacy"
  | "org"
  | "access"
  | "drive"
  | "template"
  | "letterhead"
  | "numbering"
  | "reasons"
  | "dictionary"
  | "devices";

export type GroupId = "account" | "org" | "actas" | "advanced";

export interface SectionMeta {
  id: SectionId;
  label: string;
  /** Una frase de qué es: va debajo del título. */
  description: string;
  icon: IconName;
  group: GroupId;
  visible?: (viewer: Viewer) => boolean;
}

export interface GroupMeta {
  id: GroupId;
  label: string;
  /** Avanzado arranca cerrado: casi nadie lo toca. */
  collapsed?: boolean;
  visible?: (viewer: Viewer) => boolean;
}

const leads = (viewer: Viewer) => viewer.admin || viewer.directive;

export const GROUPS: GroupMeta[] = [
  { id: "account", label: "Mi cuenta" },
  { id: "org", label: "Sede" },
  { id: "actas", label: "Actas", visible: leads },
  { id: "advanced", label: "Avanzado", collapsed: true, visible: (viewer) => viewer.admin },
];

export const SECTIONS: SectionMeta[] = [
  {
    id: "my-voice",
    label: "Mi voz",
    description: "Grabá 12 segundos de tu voz y en el acta vas a aparecer con tu nombre.",
    icon: "mic",
    group: "account",
  },
  {
    id: "my-drive",
    label: "Mi Google Drive",
    description: "Adónde van las grabaciones que hacés vos.",
    icon: "cloud",
    group: "account",
  },
  {
    id: "privacy",
    label: "Tus datos",
    description: "Cómo cuida Echo lo que se graba, y cómo pedir tus datos o la baja.",
    icon: "shield",
    group: "account",
  },
  {
    id: "org",
    label: "Organización y miembros",
    description: "Quiénes están en la sede y cómo invitar a alguien más.",
    icon: "building",
    group: "org",
  },
  {
    id: "access",
    label: "Niveles y accesos",
    description: "Qué reuniones ve cada persona de los niveles que dirigís.",
    icon: "layers",
    group: "org",
    visible: (viewer) => viewer.managesLevels,
  },
  {
    id: "drive",
    label: "Drive de la sede",
    description: "La carpeta compartida donde Echo guarda, sin que nadie suba nada, las actas y las grabaciones con familias.",
    icon: "projects",
    group: "org",
  },
  {
    id: "template",
    label: "Formato de acta",
    description: "El modelo que sigue Echo al redactar cada acta, y en qué idioma.",
    icon: "doc",
    group: "actas",
  },
  {
    id: "letterhead",
    label: "Membrete",
    description: "Lo que va arriba y abajo del acta impresa: logo, encabezado y firmas.",
    icon: "letterhead",
    group: "actas",
  },
  {
    id: "numbering",
    label: "Numeración",
    description: "El número correlativo que lleva cada acta de la sede.",
    icon: "hash",
    group: "actas",
  },
  {
    id: "reasons",
    label: "Motivos de reunión",
    description: "La lista cerrada que se elige al clasificar una reunión.",
    icon: "tasks",
    group: "actas",
  },
  {
    id: "dictionary",
    label: "Diccionario",
    description: "Nombres propios y siglas para que la transcripción los escriba bien.",
    icon: "book",
    group: "advanced",
  },
  {
    id: "devices",
    label: "Dispositivos",
    description: "Los Echo Device vinculados a la sede.",
    icon: "device",
    group: "advanced",
  },
];

/** Rutas viejas de /settings/... que ahora viven adentro de otra sección. */
const ALIASES: Record<string, { section: SectionId; target?: string }> = {
  ai: { section: "template", target: "minutes-language" },
};

export interface SettingEntry {
  section: SectionId;
  label: string;
  keywords: string[];
  /** data-setting-id del ajuste dentro de la sección; sin él, la sección entera. */
  target?: string;
}

/** Lo que encuentra el buscador: cada sección y los ajustes de adentro que se buscan por nombre. */
export const SETTINGS_INDEX: SettingEntry[] = [
  { section: "my-voice", label: "Mi voz", keywords: ["voz", "huella", "grabar mi voz", "reconocer", "mi nombre en el acta", "persona 1"] },
  {
    section: "my-voice",
    label: "Mejorar el reconocimiento con mis reuniones",
    keywords: ["aprender", "mejorar", "voz"],
    target: "voice-learning",
  },
  { section: "my-voice", label: "Borrar mi voz", keywords: ["eliminar voz", "grabar de nuevo"], target: "voice-actions" },
  {
    section: "my-drive",
    label: "Mi Google Drive",
    keywords: ["drive", "google", "grabaciones", "audio", "carpeta", "conectar drive", "mis grabaciones"],
  },
  {
    section: "privacy",
    label: "Tus datos",
    keywords: ["privacidad", "datos", "audio", "menores", "politica de privacidad", "ley 25.326"],
  },
  {
    section: "privacy",
    label: "Pedir mis datos o borrarlos",
    keywords: ["borrar mis datos", "baja", "eliminar cuenta", "borrar cuenta", "copia de mis datos", "corregir"],
    target: "privacy-requests",
  },
  {
    section: "org",
    label: "Organización y miembros",
    keywords: ["organizacion", "sede", "colegio", "miembros", "usuarios", "equipo", "rol"],
  },
  {
    section: "org",
    label: "Invitar a alguien",
    keywords: ["invitar", "invitacion", "codigo", "rol", "email", "sumar", "agregar persona"],
    target: "org-invite",
  },
  {
    section: "access",
    label: "Niveles y accesos",
    keywords: ["nivel", "niveles", "acceso", "permisos", "inicial", "primaria", "secundaria", "direccion", "limitado", "quien ve que", "rol"],
  },
  {
    section: "drive",
    label: "Drive de la sede",
    keywords: ["drive", "google", "carpeta", "carpeta madre", "actas en drive", "familias", "compartir", "conectar drive"],
  },
  { section: "template", label: "Formato de acta", keywords: ["formato", "plantilla", "modelo", "acta", "estructura", "titulos"] },
  {
    section: "template",
    label: "Idioma del acta",
    keywords: ["idioma", "ingles", "english", "portugues", "espanol", "lenguaje", "traducir"],
    target: "minutes-language",
  },
  {
    section: "letterhead",
    label: "Membrete",
    keywords: ["membrete", "encabezado", "imprimir", "impresion", "institucion", "direccion", "telefono", "fuente", "titulo del acta"],
  },
  { section: "letterhead", label: "Logo del acta", keywords: ["logo", "imagen", "escudo"], target: "letterhead-logo" },
  { section: "letterhead", label: "Firmas al pie", keywords: ["firma", "firmas", "pie"], target: "letterhead-signatures" },
  {
    section: "numbering",
    label: "Numeración de actas",
    keywords: ["numero", "numeracion", "n.º", "correlativo", "seguir desde", "numerar"],
  },
  {
    section: "reasons",
    label: "Motivos de reunión",
    keywords: ["motivo", "motivos", "clasificar", "clasificacion", "categoria", "tipo de reunion"],
  },
  {
    section: "dictionary",
    label: "Diccionario",
    keywords: ["diccionario", "palabras", "terminos", "siglas", "nombres propios", "vocabulario", "transcripcion"],
  },
  {
    section: "devices",
    label: "Dispositivos",
    keywords: ["dispositivo", "echo device", "vincular", "esp32", "menores", "microfono", "aparato"],
  },
];

/** Minúsculas y sin acentos: "Inglés" encuentra "ingles" y al revés. */
export function normalize(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

export function sectionMeta(id: string): SectionMeta | undefined {
  return SECTIONS.find((section) => section.id === id);
}

export function groupMeta(id: GroupId): GroupMeta {
  return GROUPS.find((group) => group.id === id)!;
}

export function canSee(section: SectionMeta, viewer: Viewer): boolean {
  const group = groupMeta(section.group);
  return (group.visible?.(viewer) ?? true) && (section.visible?.(viewer) ?? true);
}

export function visibleSections(viewer: Viewer): SectionMeta[] {
  return SECTIONS.filter((section) => canSee(section, viewer));
}

/**
 * La parte de /settings/... que dice qué abrir. Una sección que no existe (o
 * que se sacó, como Notificaciones) abre la ventana sin sección.
 */
export function resolvePath(path: string): { section: SectionId | null; target?: string } {
  const alias = ALIASES[path];
  if (alias) return alias;
  const section = sectionMeta(path);
  return { section: section ? section.id : null };
}

export interface SearchHit extends SettingEntry {
  /** "Actas · Membrete": dónde está el ajuste. */
  where: string;
}

/** Busca en el índice lo que ve esta persona. Todas las palabras tienen que aparecer. */
export function searchSettings(query: string, viewer: Viewer): SearchHit[] {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const phrase = words.join(" ");
  const scored: { hit: SearchHit; score: number; order: number }[] = [];
  SETTINGS_INDEX.forEach((entry, order) => {
    const section = sectionMeta(entry.section)!;
    if (!canSee(section, viewer)) return;
    const label = normalize(entry.label);
    const keywords = entry.keywords.map(normalize);
    const haystack = [label, normalize(section.label), ...keywords].join(" ");
    if (!words.every((word) => haystack.includes(word))) return;
    const score = label.startsWith(phrase)
      ? 0
      : label.includes(phrase)
        ? 1
        : keywords.some((keyword) => keyword.startsWith(phrase))
          ? 2
          : 3;
    const where = `${groupMeta(section.group).label} · ${section.label}`;
    scored.push({ hit: { ...entry, where }, score, order });
  });
  return scored.sort((a, b) => a.score - b.score || a.order - b.order).map(({ hit }) => hit);
}
