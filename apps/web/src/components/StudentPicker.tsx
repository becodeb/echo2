import type { FamilyOut } from "../api/types";

/**
 * De qué hijo(s) de la familia es la reunión. Va al acta con iniciales y
 * curso aunque nadie los diga en voz alta. Con un solo hijo no pregunta.
 */
export function StudentPicker({
  family,
  value,
  onChange,
}: {
  family: FamilyOut | undefined;
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const kids = (family?.members ?? []).filter((member) => member.relationship_type === "estudiante");
  if (kids.length < 2) return null;
  return (
    <div className="sm:col-span-2">
      <span className="mb-1.5 block text-sm font-medium text-ink-700">¿De qué hijo es la reunión?</span>
      <div role="group" aria-label="De qué hijo es la reunión" className="flex flex-wrap gap-1.5">
        {kids.map((kid) => {
          const on = value.includes(kid.id);
          return (
            <button
              key={kid.id}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? value.filter((id) => id !== kid.id) : [...value, kid.id])}
              className={`min-h-9 rounded-full border px-3 py-1 text-sm transition-colors ${
                on ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-white text-ink-700 hover:border-ink-300"
              }`}
            >
              {kid.name}
              {kid.curso && <span className={on ? "text-white/70" : "text-ink-400"}> · {kid.curso}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Iniciales del alumno, como las arma la API para el acta: "MUNAFO, Allegra" → "A. M.". */
export function studentInitials(name: string): string {
  const clean = name.split(/\s+/).filter(Boolean).join(" ");
  const words = clean.includes(",")
    ? [...clean.split(",")[1].split(/\s+/), ...clean.split(",")[0].split(/\s+/)]
    : clean.split(" ");
  return words
    .filter((word) => /^\p{L}/u.test(word))
    .map((word) => `${word[0].toUpperCase()}.`)
    .join(" ");
}

/** El hijo que se elige solo: si la familia tiene uno, es ese. */
export function onlyStudent(family: FamilyOut | undefined): string[] {
  const kids = (family?.members ?? []).filter((member) => member.relationship_type === "estudiante");
  return kids.length === 1 ? [kids[0].id] : [];
}
