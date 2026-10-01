import type { ReactNode } from "react";

/**
 * Ajustes como filas (al estilo de los paneles de ElevenLabs): un grupo con
 * bordes suaves y divisores, cada fila con su nombre, una ayuda corta y el
 * control a la derecha.
 */

export function SettingsGroup({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`divide-y divide-ink-100 overflow-hidden rounded-2xl border border-ink-100 bg-white ${className}`}>
      {children}
    </div>
  );
}

export function SettingRow({
  label,
  hint,
  control,
  disabled = false,
}: {
  label: ReactNode;
  hint?: ReactNode;
  control?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className={`flex items-start justify-between gap-4 px-4 py-3.5 ${disabled ? "opacity-60" : ""}`}>
      <div className="min-w-0 flex-1 text-left">
        <p className="text-sm font-medium text-ink-800">{label}</p>
        {hint && <div className="mt-0.5 text-xs leading-relaxed text-ink-400">{hint}</div>}
      </div>
      {control && <div className="shrink-0 pt-0.5">{control}</div>}
    </div>
  );
}

export function PillSwitch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-[26px] w-[44px] shrink-0 rounded-full transition-colors duration-300 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ${
        checked ? "bg-ink-900" : "bg-ink-200"
      }`}
    >
      <span
        aria-hidden
        className="absolute left-[3px] top-[3px] h-5 w-5 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.25)] transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
        style={{ transform: checked ? "translateX(18px)" : "translateX(0)" }}
      />
    </button>
  );
}

/** Dos o más opciones como tarjetas seleccionables (una sola a la vez). */
export function ChoiceCards<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  options: { value: T; title: ReactNode; hint: ReactNode; disabled?: boolean }[];
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="grid gap-2 sm:grid-cols-2">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={`rounded-xl border px-3.5 py-3 text-left transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ${
              selected
                ? "border-ink-900 bg-white shadow-[0_0_0_1px_var(--color-ink-900)]"
                : "border-ink-100 bg-ink-50/60 hover:border-ink-200 hover:bg-white"
            }`}
          >
            <span className="flex items-center justify-between gap-2 text-sm font-medium text-ink-900">
              {option.title}
              <span
                aria-hidden
                className={`flex h-4 w-4 items-center justify-center rounded-full border transition-colors ${
                  selected ? "border-ink-900 bg-ink-900" : "border-ink-300 bg-white"
                }`}
              >
                {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
              </span>
            </span>
            <span className="mt-1 block text-xs leading-relaxed text-ink-400">{option.hint}</span>
          </button>
        );
      })}
    </div>
  );
}
