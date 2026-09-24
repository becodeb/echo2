import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

/**
 * Desplegable propio, en lugar del <select> nativo.
 *
 * El nativo no se puede estilar ni buscar, y en el celular abre la rueda del
 * sistema. Este se dibuja en un portal con posición fija: así no lo recorta
 * ninguna tarjeta con overflow ni ensancha la página en pantallas chicas.
 */

export interface SelectOption {
  value: string;
  label: string;
  /** Texto secundario a la derecha; también entra en la búsqueda. */
  hint?: string;
  /** Clase de color de fondo para un punto antes del texto (ej. "bg-red-500"). */
  dot?: string;
}

interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  /** Texto del botón cuando el valor no coincide con ninguna opción. */
  placeholder?: string;
  label?: string;
  ariaLabel?: string;
  /** Por defecto se puede buscar cuando hay más de 7 opciones. */
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Botón fijo al pie de la lista; recibe lo que se estaba buscando. */
  action?: { label: string; onClick: (query: string) => void };
  size?: "sm" | "md";
  disabled?: boolean;
  className?: string;
}

const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

const GAP = 6;
const MARGIN = 8;

export function Select({
  value,
  onChange,
  options,
  placeholder = "Elegir…",
  label,
  ariaLabel,
  searchable,
  searchPlaceholder = "Buscar…",
  action,
  size = "md",
  disabled = false,
  className = "",
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState<{
    left: number;
    width: number;
    top?: number;
    bottom?: number;
    maxHeight: number;
  } | null>(null);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  const canSearch = searchable ?? options.length > 7;
  const selected = options.find((option) => option.value === value);

  const filtered = useMemo(() => {
    const term = normalize(query.trim());
    if (!term) return options;
    return options.filter((option) =>
      normalize(`${option.label} ${option.hint ?? ""}`).includes(term),
    );
  }, [options, query]);

  const close = useCallback((refocus = true) => {
    setOpen(false);
    setPosition(null);
    setQuery("");
    if (refocus) triggerRef.current?.focus();
  }, []);

  const place = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.visualViewport?.height ?? window.innerHeight;

    // Nunca más angosto que el botón ni que 14rem, nunca más ancho que la pantalla.
    const width = Math.min(Math.max(rect.width, 224), viewportWidth - MARGIN * 2);
    let left = rect.left;
    if (left + width > viewportWidth - MARGIN) left = rect.right - width;
    left = Math.max(MARGIN, Math.min(left, viewportWidth - width - MARGIN));

    const below = viewportHeight - rect.bottom - GAP - MARGIN;
    const above = rect.top - GAP - MARGIN;
    if (below >= 240 || below >= above) {
      setPosition({ left, width, top: rect.bottom + GAP, maxHeight: Math.min(360, below) });
    } else {
      setPosition({
        left,
        width,
        bottom: viewportHeight - rect.top + GAP,
        maxHeight: Math.min(360, above),
      });
    }
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
    };
  }, [open, place]);

  // Al aparecer la lista: resaltar lo elegido y, con mouse, poner el foco en
  // la búsqueda. En pantallas táctiles no, para que no salte el teclado sin
  // pedirlo. Se espera a tener posición porque recién ahí existe el popover.
  const shown = open && position !== null;
  useEffect(() => {
    if (!shown) return;
    const index = options.findIndex((option) => option.value === value);
    setActive(index >= 0 ? index : 0);
    const finePointer = window.matchMedia?.("(pointer: fine)").matches ?? true;
    if (canSearch && finePointer) searchRef.current?.focus();
    else listRef.current?.focus();
    // Solo al aparecer: el resto de los cambios no tiene que mover el foco.
  }, [shown]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (popoverRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      close(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const choose = (option: SelectOption) => {
    onChange(option.value);
    close();
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(filtered.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filtered[active];
      if (option) choose(option);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // que no cierre también el modal que lo contiene
      close();
    } else if (event.key === "Tab") {
      close(false);
    }
  };

  const small = size === "sm";
  const trigger = (
    <button
      ref={triggerRef}
      type="button"
      disabled={disabled}
      onClick={() => (open ? close() : setOpen(true))}
      onKeyDown={(event) => {
        if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          event.preventDefault();
          setOpen(true);
        }
      }}
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={open ? listId : undefined}
      id={`${listId}-trigger`}
      aria-label={label ? undefined : ariaLabel}
      aria-labelledby={label ? `${listId}-label ${listId}-trigger` : undefined}
      className={`flex w-full min-w-0 items-center gap-2 rounded-lg border bg-white text-left transition-colors focus:outline-none focus-visible:border-accent-500 focus-visible:ring-2 focus-visible:ring-accent-500/20 disabled:cursor-not-allowed disabled:opacity-50 ${
        open ? "border-accent-500 ring-2 ring-accent-500/20" : "border-ink-200 hover:border-ink-300"
      } ${small ? "px-2.5 py-1 text-xs" : "px-3 py-2 text-sm"}`}
    >
      {selected?.dot && <span className={`h-2 w-2 shrink-0 rounded-full ${selected.dot}`} />}
      <span className={`min-w-0 flex-1 truncate ${selected ? "text-ink-900" : "text-ink-400"}`}>
        {selected?.label ?? placeholder}
      </span>
      <svg
        width={small ? 12 : 14}
        height={small ? 12 : 14}
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden
        className={`shrink-0 text-ink-400 transition-transform ${open ? "rotate-180" : ""}`}
      >
        <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );

  const popover =
    open && position
      ? createPortal(
          <div
            ref={popoverRef}
            onKeyDown={onKeyDown}
            className="animate-fade-up fixed z-[60] flex flex-col overflow-hidden rounded-xl border border-ink-100 bg-white shadow-[0_12px_32px_-8px_rgba(16,24,40,0.18),0_2px_6px_rgba(16,24,40,0.06)]"
            style={{
              left: position.left,
              width: position.width,
              top: position.top,
              bottom: position.bottom,
              maxHeight: position.maxHeight,
            }}
          >
            {canSearch && (
              <div className="flex items-center gap-2 border-b border-ink-100 px-3">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden className="shrink-0 text-ink-400">
                  <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                  <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setActive(0);
                  }}
                  placeholder={searchPlaceholder}
                  aria-label={searchPlaceholder}
                  aria-controls={listId}
                  className="min-w-0 flex-1 bg-transparent py-2.5 text-base text-ink-900 placeholder:text-ink-400 focus:outline-none sm:text-sm"
                />
              </div>
            )}

            <ul
              ref={listRef}
              id={listId}
              role="listbox"
              tabIndex={-1}
              aria-label={label ?? ariaLabel}
              aria-activedescendant={filtered[active] ? `${listId}-${active}` : undefined}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1 focus:outline-none"
            >
              {filtered.map((option, index) => {
                const isSelected = option.value === value;
                return (
                  <li
                    key={option.value || "__empty"}
                    id={`${listId}-${index}`}
                    data-index={index}
                    role="option"
                    aria-selected={isSelected}
                    onPointerMove={() => setActive(index)}
                    onClick={() => choose(option)}
                    className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm ${
                      index === active ? "bg-ink-50" : ""
                    } ${option.value === "" ? "text-ink-500" : "text-ink-800"}`}
                  >
                    {option.dot && <span className={`h-2 w-2 shrink-0 rounded-full ${option.dot}`} />}
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    {option.hint && (
                      <span className="max-w-[40%] shrink-0 truncate text-xs text-ink-400">{option.hint}</span>
                    )}
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 16 16"
                      fill="none"
                      aria-hidden
                      className={`shrink-0 text-accent-600 ${isSelected ? "" : "invisible"}`}
                    >
                      <path d="m3.5 8.5 3 3 6-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </li>
                );
              })}
              {filtered.length === 0 && (
                <li className="px-2.5 py-6 text-center text-sm text-ink-400">
                  {query ? `Nada coincide con «${query}»` : "No hay opciones"}
                </li>
              )}
            </ul>

            {action && (
              <div className="border-t border-ink-100 p-1">
                <button
                  type="button"
                  onClick={() => {
                    const current = query.trim();
                    close(false);
                    action.onClick(current);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium text-accent-600 hover:bg-accent-500/5"
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
                    <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                  <span className="truncate">
                    {action.label}
                    {query.trim() && <span className="text-ink-500"> «{query.trim()}»</span>}
                  </span>
                </button>
              </div>
            )}
          </div>,
          document.body,
        )
      : null;

  return (
    <div className={`min-w-0 ${className}`}>
      {label ? (
        <>
          <span id={`${listId}-label`} className="mb-1.5 block text-sm font-medium text-ink-700">
            {label}
          </span>
          {trigger}
        </>
      ) : (
        trigger
      )}
      {popover}
    </div>
  );
}
