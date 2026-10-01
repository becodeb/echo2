import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

/**
 * Pestañas accesibles (§4.5): una píldora que se desliza hasta la activa,
 * flechas / Inicio / Fin para moverse, y cada pestaña apunta a su panel
 * (`${idPrefix}-panel-${id}`), que quien la usa marca con role="tabpanel".
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  idPrefix,
}: {
  items: readonly { readonly id: T; readonly label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  idPrefix: string;
}) {
  const list = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const active = list.current?.querySelector<HTMLElement>(`[data-tab="${value}"]`);
    if (!active) return;
    const measure = () => setPill({ left: active.offsetLeft, width: active.offsetWidth });
    measure();
    active.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [value, items.length]);

  const move = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = items.findIndex((item) => item.id === value);
    const next =
      event.key === "ArrowRight" ? (index + 1) % items.length
        : event.key === "ArrowLeft" ? (index - 1 + items.length) % items.length
          : event.key === "Home" ? 0
            : event.key === "End" ? items.length - 1
              : -1;
    if (next < 0) return;
    event.preventDefault();
    onChange(items[next].id);
    list.current?.querySelector<HTMLElement>(`[data-tab="${items[next].id}"]`)?.focus();
  };

  return (
    <div
      ref={list}
      role="tablist"
      aria-label={label}
      className="relative flex gap-1 overflow-x-auto rounded-full bg-ink-100/70 p-1 [scrollbar-width:none]"
    >
      {pill && (
        <span
          aria-hidden
          className="absolute inset-y-1 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.12)] transition-[left,width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
          style={{ left: pill.left, width: pill.width }}
        />
      )}
      {items.map((item) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            data-tab={item.id}
            id={`${idPrefix}-tab-${item.id}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={move}
            className={`relative z-10 min-h-10 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-medium transition-colors ${
              selected ? "text-ink-900" : "text-ink-500 hover:text-ink-800"
            }`}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
