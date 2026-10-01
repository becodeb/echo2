import { useEffect, useRef } from "react";
import { Reveal } from "./Reveal";

/**
 * La app funcionando (docs/plan-correcciones.md §3.6): la demo de producto de
 * apps/video (composición EchoDemo, sin la intro de marca), con datos de
 * ejemplo. Arranca sin sonido cuando entra en pantalla y se pausa al salir;
 * con "reducir movimiento" no arranca sola.
 */
export function Demo() {
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const el = video.current;
    if (!el || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) void el.play().catch(() => {});
        else el.pause();
      },
      { threshold: 0.5 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <Reveal className="mx-auto max-w-6xl px-6 py-12 md:px-12 md:py-20">
      <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">Mirá cómo funciona</h2>
      <p className="mt-4 max-w-xl leading-relaxed text-ink-600 md:text-lg">
        Una entrevista con una familia, de punta a punta: la reunión, el acta, la aprobación y lo que queda.
      </p>
      <video
        ref={video}
        className="mt-10 aspect-video w-full rounded-3xl border border-ink-200 bg-white shadow-[0_24px_64px_-24px_rgba(20,24,36,0.35)]"
        src="/demo/echo-demo.mp4"
        poster="/demo/echo-demo-poster.jpg"
        muted
        playsInline
        loop
        controls
        preload="none"
      >
        Tu navegador no puede mostrar el video.
      </video>
    </Reveal>
  );
}
