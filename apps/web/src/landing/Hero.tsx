import { useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
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
// El video dura 5,65 s: pasado esto la página se muestra sí o sí.
const MAX_WAIT_MS = 7000;

const INTRO_VISTA = "echo_intro_visto";

/** La intro se ve una sola vez; con "reducir movimiento", nunca. */
const sinIntro = () => {
  if (typeof window === "undefined") return false;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return true;
  try {
    return window.localStorage.getItem(INTRO_VISTA) === "1";
  } catch {
    return false;
  }
};

/** Cuánto suben los ojos para no tapar el texto (pantallas 4:3, ventanas
 *  bajas): el fondo del ojo queda 24 px arriba del título, sin chocar la
 *  barra de arriba. En el video los ojos miden 225 de alto, centrados. */
function subidaDeOjos(seccion: HTMLElement, texto: HTMLElement, fuente: Fuente): number {
  const alto = seccion.clientHeight;
  const escala = Math.max(seccion.clientWidth / fuente.w, alto / fuente.h);
  const ojo = 225 * escala;
  const centro = alto / 2;
  const tope = texto.getBoundingClientRect().top - seccion.getBoundingClientRect().top;
  const necesaria = centro + ojo / 2 + 24 - tope;
  const maxima = centro - ojo / 2 - 80;
  return Math.max(0, Math.min(necesaria, maxima));
}

/** iPhone/iPad (en iOS todos los navegadores son Safari por dentro). Ahí el
 *  video puede quedar en negro sin dar error (modo bajo consumo, ahorro de
 *  datos) y la página parece rota: se muestran directo los ojos vivos. */
const esIOS = () =>
  typeof navigator !== "undefined" &&
  (/iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1));

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
 *
 * En iPhone/iPad no se usa: Safari a veces "reproduce" sin pintar los cuadros
 * y el video tapa todo de negro. Y en cualquier navegador, a los 7 s la página
 * se muestra aunque el video no haya avanzado.
 *
 * La intro se ve una sola vez (después, los ojos vivos de entrada), nunca con
 * "reducir movimiento", y un clic, una tecla o el scroll la saltean. La barra
 * de arriba (Ingresar, Crear cuenta) está desde el primer segundo y queda fija.
 * Si el texto no entra debajo de los ojos (4:3), los ojos suben.
 */
export function Hero() {
  const host = useRef<HTMLElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const [still, setStill] = useState(() => esIOS() || sinIntro()); // sin video: ojos vivos y todo visible
  const [lit, setLit] = useState(still); // la pantalla ya es blanca: navbar
  const [ready, setReady] = useState(still); // ya pestañeó: entra el texto
  const [done, setDone] = useState(false); // terminó el video: ojos vivos
  const [fuente] = useState(elegirFuente); // se decide una vez, al montar
  const [subida, setSubida] = useState(0);
  const [scrolled, setScrolled] = useState(false);

  // Vista una vez, no se repite.
  useEffect(() => {
    try {
      window.localStorage.setItem(INTRO_VISTA, "1");
    } catch {
      // Sin almacenamiento: la intro se vuelve a ver, nada más.
    }
  }, []);

  // Saltear la intro: cualquier clic, tecla o scroll muestra todo al instante.
  useEffect(() => {
    if (still) return;
    const saltar = () => {
      setStill(true);
      setLit(true);
      setReady(true);
    };
    const opciones = { once: true, passive: true } as const;
    window.addEventListener("pointerdown", saltar, opciones);
    window.addEventListener("keydown", saltar, opciones);
    window.addEventListener("wheel", saltar, opciones);
    window.addEventListener("touchmove", saltar, opciones);
    return () => {
      window.removeEventListener("pointerdown", saltar);
      window.removeEventListener("keydown", saltar);
      window.removeEventListener("wheel", saltar);
      window.removeEventListener("touchmove", saltar);
    };
  }, [still]);

  // Barra de arriba con fondo apenas se baja.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Cuando entra el texto, los ojos suben si hace falta (y se recalcula al cambiar el tamaño).
  useEffect(() => {
    if (!ready) return;
    const medir = () => {
      if (host.current && copy.current) setSubida(subidaDeOjos(host.current, copy.current, fuente));
    };
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, [ready, fuente]);

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
    // Tope de seguridad: pasado el largo del video, si la página todavía no se
    // mostró (video trabado o en negro), se saca el video y se muestra todo.
    // Se rearma cada vez que la pestaña vuelve a verse.
    let tope = 0;
    const armarTope = () => {
      window.clearTimeout(tope);
      tope = window.setTimeout(() => {
        if (!cancelado && document.visibilityState === "visible" && el.currentTime < READY_AT) sinVideo();
      }, MAX_WAIT_MS);
    };
    const alVolver = () => {
      if (document.visibilityState !== "visible") return;
      intentar();
      armarTope();
    };
    intentar();
    armarTope();
    document.addEventListener("visibilitychange", alVolver);
    el.addEventListener("error", sinVideo);
    return () => {
      cancelado = true;
      document.removeEventListener("visibilitychange", alVolver);
      el.removeEventListener("error", sinVideo);
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
      style={{ "--subida": `${subida}px` } as CSSProperties}
    >
      {!still && (
        <video
          ref={video}
          className="hero-sube absolute inset-0 h-full w-full object-cover"
          poster="/hero/echo-ojos-poster.png"
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

      {/* Fija y a la vista desde el primer segundo, también durante la intro
          (en negro, con los colores invertidos). */}
      <header
        className={`fixed inset-x-0 top-0 z-40 transition-colors duration-500 ${
          scrolled ? "border-b border-ink-200/60 bg-[#fafbfc]/80 backdrop-blur-md" : "border-b border-transparent"
        }`}
      >
        <div className="relative flex h-16 items-center justify-between gap-4 px-6 md:px-12">
          <Link
            to="/"
            className={`text-lg font-semibold tracking-tight text-ink-950 transition-opacity duration-700 ${lit ? "opacity-100" : "pointer-events-none opacity-0"}`}
          >
            Echo
          </Link>
          <nav
            className={`absolute left-1/2 hidden -translate-x-1/2 items-center gap-6 text-sm font-medium text-ink-600 transition-opacity duration-700 lg:flex [&>a:hover]:text-ink-950 ${
              lit ? "opacity-100" : "pointer-events-none opacity-0"
            }`}
            aria-label="Secciones"
          >
            <a href="#como-funciona">Cómo funciona</a>
            <a href="#precios">Precios</a>
            <a href="#privacidad">Privacidad</a>
            <a href="#preguntas">Preguntas</a>
          </nav>
          {/* Durante la intro, en una píldora oscura translúcida: se lee sobre
              el negro y sobre el blanco del video. */}
          <nav
            className={`flex items-center gap-2 rounded-full transition-colors duration-700 ${
              lit ? "" : "bg-ink-950/70 p-1 backdrop-blur-md"
            }`}
            aria-label="Cuenta"
          >
            <Link
              to="/login"
              className={`btn btn-sm ${lit ? "btn-ghost" : "border-0 bg-transparent text-white hover:bg-white/10"}`}
            >
              Ingresar
            </Link>
            <Link to="/register" className={`btn btn-sm ${lit ? "btn-ink" : "bg-white text-ink-950 hover:bg-ink-100"}`}>
              Crear cuenta
            </Link>
          </nav>
        </div>
      </header>

      <div
        ref={copy}
        className="hero-copy-in absolute inset-x-0 bottom-0 z-10 max-w-xl px-6 pb-8 md:px-12 md:pb-14"
        data-shown={ready ? "1" : undefined}
      >
        <h1 className="text-[2rem] font-semibold leading-[1.05] tracking-tighter text-ink-950 md:text-5xl xl:text-6xl">
          La reunión termina.
          <br />
          Echo recuerda.
        </h1>
        <p className="mt-4 max-w-md text-base leading-relaxed text-ink-600 md:text-lg">
          Entrevistas con familias y reuniones del equipo docente: Echo transcribe en vivo, saca acuerdos y
          tareas, y deja el acta lista para imprimir. El audio no queda guardado.
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
    <div ref={layer} className="hero-ojos hero-sube" aria-hidden>
      <div data-eye>
        <i className="echo-eye" />
      </div>
      <div data-eye>
        <i className="echo-eye" />
      </div>
    </div>
  );
}
