import type { ScheduledMeetingOut } from "../api/types";

/** Lo que dice cada tarjeta: la familia y el alumno, o el grupo de la interna. */
export function agendaTitle(item: ScheduledMeetingOut): { title: string; detail: string } {
  if (item.kind === "interna") {
    return { title: "Reunión interna", detail: item.group_name ?? item.title };
  }
  const students = item.students.map((s) => (s.curso ? `${s.name}, ${s.curso}` : s.name)).join(" · ");
  return { title: item.family_name ?? (item.title || "Reunión"), detail: students };
}

/**
 * Fechas de la Agenda, siempre en la hora local (la del colegio): "yyyy-mm-dd"
 * sin pasar por UTC, que de noche corre el día.
 */

const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];
const DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const DIAS_CORTOS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

export function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function parseDay(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function addDays(iso: string, days: number): string {
  const date = parseDay(iso);
  date.setDate(date.getDate() + days);
  return isoDay(date);
}

/** El lunes de la semana de ese día. */
export function weekStart(iso: string): string {
  const offset = (parseDay(iso).getDay() + 6) % 7;
  return addDays(iso, -offset);
}

/** "Lunes 2 de noviembre" */
export function dayLabel(iso: string): string {
  const date = parseDay(iso);
  const name = DIAS[date.getDay()];
  return `${name[0].toUpperCase()}${name.slice(1)} ${date.getDate()} de ${MESES[date.getMonth()]}`;
}

/** "lun" */
export function shortWeekday(iso: string): string {
  return DIAS_CORTOS[parseDay(iso).getDay()];
}

/** "Noviembre 2026" */
export function monthLabel(iso: string): string {
  const date = parseDay(iso);
  const name = MESES[date.getMonth()];
  return `${name[0].toUpperCase()}${name.slice(1)} ${date.getFullYear()}`;
}

/** El primer día del mes anterior (-1) o siguiente (+1). */
export function shiftMonth(iso: string, months: number): string {
  const date = parseDay(iso);
  return isoDay(new Date(date.getFullYear(), date.getMonth() + months, 1));
}

/**
 * La grilla del mes que contiene ese día: semanas completas de lunes a
 * domingo. Los días de los meses vecinos van con `inMonth: false`.
 */
export function monthGrid(iso: string): { iso: string; inMonth: boolean }[][] {
  const date = parseDay(iso);
  const first = isoDay(new Date(date.getFullYear(), date.getMonth(), 1));
  const last = isoDay(new Date(date.getFullYear(), date.getMonth() + 1, 0));
  const weeks: { iso: string; inMonth: boolean }[][] = [];
  for (let start = weekStart(first); start <= last; start = addDays(start, 7)) {
    weeks.push(
      Array.from({ length: 7 }, (_, index) => {
        const day = addDays(start, index);
        return { iso: day, inMonth: parseDay(day).getMonth() === date.getMonth() };
      }),
    );
  }
  return weeks;
}

const NUMEROS: Record<string, number> = {
  un: 1, una: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, diez: 10, quince: 15, veinte: 20,
};

/** Cuántos días dice la frase ("en dos semanas", "en 15 días", "en un mes"); null si no dice. */
function daysFrom(sentence: string): number | null {
  const text = sentence.toLowerCase();
  if (/(semana que viene|pr[oó]xima semana)/.test(text)) return 7;
  if (/(mes que viene|pr[oó]ximo mes)/.test(text)) return 30;
  const match = /\b(\d{1,2}|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|diez|quince|veinte)\s+(d[ií]as?|semanas?|mes(?:es)?)\b/.exec(text);
  if (!match) return null;
  const amount = /^\d+$/.test(match[1]) ? Number(match[1]) : NUMEROS[match[1]];
  if (match[2].startsWith("sem")) return amount * 7;
  if (match[2].startsWith("mes")) return amount * 30;
  return amount;
}

/**
 * Si el acta dice que se acordó volver a reunirse: la frase y un día sugerido
 * (lo que diga la frase; si no dice, dos semanas). El día cae siempre en un
 * día hábil.
 */
export function nextMeetingIn(markdown: string, from: string): { sentence: string; date: string } | null {
  const plain = markdown.replace(/[*_#>`]/g, " ").replace(/\s+/g, " ");
  const sentences = plain.split(/(?<=[.!?])\s+/);
  const sentence = sentences.find((text) =>
    /(nueva reuni[oó]n|volver a reunir|pr[oó]xima reuni[oó]n|reunirse nuevamente|otra reuni[oó]n|nuevo encuentro)/i.test(text),
  );
  if (!sentence) return null;
  // "en diciembre": el primer día hábil de ese mes (del año que viene si ya pasó).
  const month = MESES.findIndex((name) => new RegExp(`\\b${name}\\b`, "i").test(sentence));
  const start = parseDay(from);
  const monthStart =
    month >= 0 && month !== start.getMonth()
      ? isoDay(new Date(start.getFullYear() + (month < start.getMonth() ? 1 : 0), month, 1))
      : null;
  let date = monthStart ?? addDays(from, daysFrom(sentence) ?? 14);
  while ([0, 6].includes(parseDay(date).getDay())) date = addDays(date, 1);
  return { sentence: sentence.trim(), date };
}
