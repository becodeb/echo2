import type { Level } from "../state/access";
import { LEVELS, LEVEL_LABEL } from "../state/access";

/**
 * El nivel de cada hijo (inicial, primaria, secundaria): un color por nivel,
 * igual en la lista de familias y en la página de cada una.
 */

const LEVEL_STYLE: Record<Level, { badge: string; active: string }> = {
  inicial: { badge: "bg-amber-50 text-amber-800", active: "bg-amber-500 text-white" },
  primaria: { badge: "bg-sky-50 text-sky-800", active: "bg-sky-600 text-white" },
  secundaria: { badge: "bg-violet-50 text-violet-800", active: "bg-violet-600 text-white" },
};

export function LevelBadge({ level }: { level: Level | null | undefined }) {
  if (!level) {
    return (
      <span className="inline-flex items-center rounded-full border border-dashed border-ink-200 px-2 py-0.5 text-xs text-ink-400">
        Sin nivel
      </span>
    );
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${LEVEL_STYLE[level].badge}`}>
      {LEVEL_LABEL[level]}
    </span>
  );
}

/** Tres botones: tocar uno elige el nivel; tocar el elegido lo saca. */
export function LevelPicker({
  value,
  onChange,
  disabled = false,
  label = "Nivel",
}: {
  value: Level | null | undefined;
  onChange: (next: Level | null) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full bg-ink-100 p-0.5">
      {LEVELS.map((level) => {
        const active = value === level.value;
        return (
          <button
            key={level.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(active ? null : level.value)}
            className={`min-h-8 rounded-full px-2.5 text-xs font-medium transition-colors disabled:opacity-60 sm:px-3 ${
              active ? LEVEL_STYLE[level.value].active : "text-ink-600 hover:bg-white hover:text-ink-900"
            }`}
          >
            {level.label}
          </button>
        );
      })}
    </div>
  );
}
