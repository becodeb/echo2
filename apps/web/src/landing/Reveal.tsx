import { createElement, useEffect, useRef, type ReactNode } from "react";

/**
 * Envuelve una sección y la hace entrar (opacidad + 18px) la primera vez que
 * aparece en pantalla. Usa IntersectionObserver, nada de escuchar el scroll.
 */
export function Reveal({
  as = "section",
  className = "",
  children,
}: {
  as?: "section" | "div" | "footer";
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          el.dataset.shown = "1";
          io.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return createElement(as, { ref, className: "reveal " + className }, children);
}
