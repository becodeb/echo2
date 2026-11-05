import { useEffect, useRef, useState } from "react";

export interface DotsMenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

/** Los tres puntitos: un menú chico que se abre al tocarlos y se cierra al tocar afuera o con Escape. */
export function DotsMenu({ label, items }: { label: string; items: DotsMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    box.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={box} className="relative">
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={`flex h-10 w-10 items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-accent-500 md:h-9 md:w-9 ${
          open ? "bg-ink-100 text-ink-900" : "text-ink-400 hover:bg-ink-100 hover:text-ink-900"
        }`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <circle cx="5" cy="12" r="1.8" />
          <circle cx="12" cy="12" r="1.8" />
          <circle cx="19" cy="12" r="1.8" />
        </svg>
      </button>
      {open && (
        <div
          role="menu"
          className="animate-fade-up absolute right-0 top-full z-30 mt-1 w-56 rounded-2xl border border-ink-100 bg-white p-1.5 shadow-[0_16px_48px_-12px_rgba(20,24,36,0.25)]"
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`block w-full rounded-xl px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none ${
                item.danger
                  ? "text-red-600 hover:bg-red-50 focus-visible:bg-red-50"
                  : "text-ink-700 hover:bg-ink-50 hover:text-ink-900 focus-visible:bg-ink-50"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
