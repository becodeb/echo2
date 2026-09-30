/**
 * Controles de estilo iOS: un selector de dos opciones con la píldora que se
 * desliza, y un interruptor. Colores planos y sombra suave, sin transparencias.
 */

export function SegmentedToggle<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (value: T) => void;
  options: [{ value: T; label: string }, { value: T; label: string }];
  ariaLabel: string;
}) {
  const second = value === options[1].value;
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="relative grid grid-cols-2 rounded-full bg-ink-100 p-1"
    >
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.18),0_1px_1px_rgba(0,0,0,0.08)] transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
        style={{ transform: second ? "translateX(100%)" : "translateX(0)" }}
      />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={`relative z-10 rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-200 ${
            value === option.value ? "text-ink-900" : "text-ink-500 hover:text-ink-700"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-ink-100 bg-white px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink-800">{label}</p>
        {hint && <p className="mt-0.5 text-xs text-ink-400">{hint}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-300 ${
          checked ? "bg-emerald-500" : "bg-ink-200"
        }`}
      >
        <span
          aria-hidden
          className="absolute left-[2px] top-[2px] h-[27px] w-[27px] rounded-full bg-white shadow-[0_2px_4px_rgba(0,0,0,0.25)] transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
          style={{ transform: checked ? "translateX(20px)" : "translateX(0)" }}
        />
      </button>
    </div>
  );
}
