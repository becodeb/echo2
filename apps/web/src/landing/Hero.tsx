import { useEffect, useRef, useState, type RefObject } from "react";
import { Link } from "react-router-dom";

// v04j: cae el arco, los ojos leen dos renglones, vuelven al centro y pestañean a 4.5 s y 4.9 s.
// Hay una versión horizontal y una vertical (celular), con la misma línea de tiempo.
// El sufijo de versión evita que el navegador reuse un mp4 viejo con el mismo nombre.
type Fuente = { src: string; w: number; h: number };
const HORIZONTAL: Fuente = { src: "/hero/echo-ojos.mp4?v=lee", w: 1920, h: 1080 };
const VERTICAL: Fuente = { src: "/hero/echo-ojos-vertical.mp4?v=lee", w: 1080, h: 1920 };
const elegirFuente = () =>
  typeof window !== "undefined" && window.matchMedia("(max-aspect-ratio: 1/1)").matches ? VERTICAL : HORIZONTAL;
const LIT_AT = 4.95; // último pestañeo: entra la navbar
const READY_AT = 5.15; // terminó el segundo pestañeo: entra el texto

/**
 * El hero es el video: todo negro, el blanco cae desde arriba y destapa los
 * ojos, que leen dos renglones, vuelven al centro y pestañean dos veces. La
 * navbar aparece en el último pestañeo y el texto cuando termina. Al terminar
 * el video, los ojos pasan a ser elementos reales en el mismo lugar: siguen
 * al mouse y parpadean cada tanto.
 *
 * Si la pestaña está en segundo plano, Chrome pausa el video: se espera a que
 * vuelva a verse y arranca ahí. Si el navegador directamente no deja
 * reproducir, se muestran los ojos vivos y el texto sin esperar.
 *
 * El video corre aunque el sistema pida "menos movimiento": es la apertura de
 * la marca y dura cinco segundos. El resto de la página sí lo respeta.
 */
export function Hero() {
  const host = useRef<HTMLElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [still, setStill] = useState(false); // sin video: ojos vivos y todo visible
  const [lit, setLit] = useState(false); // la pantalla ya es blanca: navbar
  const [ready, setReady] = useState(false); // ya pestañeó: entra el texto
  const [done, setDone] = useState(false); // terminó el video: ojos vivos
  const [fuente] = useState(elegirFuente); // se decide una vez, al montar

  useEffect(() => {
    const el = video.current;
    if (!el || still) return;
    el.muted = true; // por las dudas: sin sonido el autoplay siempre está permitido
    let cancelado = false;

    const sinVideo = () => {
      setStill(true);
      setLit(true);
      setReady(true);
    };
    const intentar = () => {
      if (cancelado || el.currentTime > 0) return;
      el.play().catch((err: unknown) => {
        const e = err as { name?: string; message?: string };
        // Chrome pausa el video de una pestaña en segundo plano ("AbortError");
        // no es un bloqueo: reintentamos cuando la pestaña vuelve a verse.
        if (e?.name === "AbortError") return;
        console.warn("[hero] el navegador no dejó reproducir el video:", e?.name, e?.message);
        sinVideo();
      });
    };
    const alVolver = () => {
      if (document.visibilityState === "visible") intentar();
    };
    intentar();
    document.addEventListener("visibilitychange", alVolver);
    // Tope de seguridad: si en 8 s visibles el video no arrancó, mostramos todo igual.
    const tope = window.setTimeout(() => {
      if (!cancelado && el.currentTime === 0 && document.visibilityState === "visible") sinVideo();
    }, 8000);
    return () => {
      cancelado = true;
      document.removeEventListener("visibilitychange", alVolver);
      window.clearTimeout(tope);
    };
  }, [still]);

  const onTime = () => {
    const t = video.current?.currentTime ?? 0;
    if (t > LIT_AT) setLit(true);
    if (t > READY_AT) setReady(true);
  };

  const onEnded = () => {
    setLit(true);
    setReady(true);
    setDone(true);
  };

  return (
    <section
      ref={host}
      className={"relative min-h-[100dvh] overflow-hidden " + (lit ? "bg-[#fafbfc]" : "bg-ink-950")}
    >
      {!still && (
        <video
          ref={video}
          className="absolute inset-0 h-full w-full object-cover"
          muted
          playsInline
          preload="auto"
          onTimeUpdate={onTime}
          onEnded={onEnded}
          aria-hidden
        >
          <source src={fuente.src} type="video/mp4" />
        </video>
      )}
      {(still || done) && <OjosVivos host={host} fuente={fuente} />}

      <header
        className="hero-fade relative z-10 flex h-16 items-center justify-between px-6 md:px-12"
        data-shown={lit ? "1" : undefined}
      >
        <Link to="/" className="text-lg font-semibold tracking-tight text-ink-950">
          Echo
        </Link>
        <nav className="flex items-center gap-2" aria-label="Cuenta">
          <Link to="/login" className="btn btn-sm btn-ghost">
            Ingresar
          </Link>
          <Link to="/register" className="btn btn-sm btn-ink">
            Crear cuenta
          </Link>
        </nav>
      </header>

      <div
        className="hero-copy-in absolute inset-x-0 bottom-0 z-10 max-w-xl px-6 pb-8 md:px-12 md:pb-14"
        data-shown={ready ? "1" : undefined}
      >
        <h1 className="text-[2rem] font-semibold leading-[1.05] tracking-tighter text-ink-950 md:text-5xl xl:text-6xl">
          La reunión termina.
          <br />
          Echo recuerda.
        </h1>
        <p className="mt-4 max-w-md text-base leading-relaxed text-ink-600 md:text-lg">
          Reuniones con familias, docentes o clientes: transcribe en vivo, saca acuerdos y tareas, y
          deja el acta lista para imprimir. El audio nunca se guarda.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/register" className="btn btn-ink">
            Crear cuenta
          </Link>
          <Link to="/login" className="btn btn-ghost">
            Ingresar
          </Link>
        </div>
      </div>
    </section>
  );
}

/**
 * Los ojos "vivos": dos elementos del mismo tamaño y en el mismo lugar que los
 * del video (en el video miden 150x225 con 112 de separación, centrados; con
 * object-fit: cover la escala es max(ancho/w, alto/h)). Siguen al mouse con un
 * poco de inercia y parpadean con la animación de la cara de Echo. Al dedo no
 * lo siguen: al scrollear se moverían solos.
 */
function OjosVivos({ host, fuente }: { host: RefObject<HTMLElement>; fuente: Fuente }) {
  const layer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const seccion = host.current;
    const el = layer.current;
    if (!seccion || !el) return;

    let escala = 1;
    const medir = () => {
      escala = Math.max(seccion.clientWidth / fuente.w, seccion.clientHeight / fuente.h);
      el.style.setProperty("--s", escala.toFixed(4));
    };
    medir();
    const ro = new ResizeObserver(medir);
    ro.observe(seccion);

    // Seguir al mouse: el objetivo lo fija el puntero, la posición lo persigue.
    const ojos = Array.from(el.querySelectorAll<HTMLElement>("[data-eye]"));
    let tx = 0;
    let ty = 0;
    let cx = 0;
    let cy = 0;
    let raf = 0;
    const paso = () => {
      raf = 0;
      cx += (tx - cx) * 0.14;
      cy += (ty - cy) * 0.14;
      for (const ojo of ojos) ojo.style.transform = `translate(${cx.toFixed(2)}px, ${cy.toFixed(2)}px)`;
      if (Math.abs(tx - cx) > 0.05 || Math.abs(ty - cy) > 0.05) raf = requestAnimationFrame(paso);
    };
    const alMover = (ev: PointerEvent) => {
      if (ev.pointerType !== "mouse") return;
      const r = seccion.getBoundingClientRect();
      const nx = Math.max(-1, Math.min(1, ((ev.clientX - r.left) / r.width - 0.5) * 2));
      const ny = Math.max(-1, Math.min(1, ((ev.clientY - r.top) / r.height - 0.5) * 2));
      tx = nx * 26 * escala;
      ty = ny * 16 * escala;
      if (!raf) raf = requestAnimationFrame(paso);
    };
    window.addEventListener("pointermove", alMover, { passive: true });
    return () => {
      ro.disconnect();
      window.removeEventListener("pointermove", alMover);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [host, fuente]);

  return (
    <div ref={layer} className="hero-ojos" aria-hidden>
      <div data-eye>
        <i className="echo-eye" />
      </div>
      <div data-eye>
        <i className="echo-eye" />
      </div>
    </div>
  );
}
