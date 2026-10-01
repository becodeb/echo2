import { Link } from "react-router-dom";
import { Reveal } from "./Reveal";

/** Preguntas frecuentes. Cada respuesta es algo que Echo hace hoy (ver /legal/privacidad). */
const QUESTIONS: { q: string; a: React.ReactNode }[] = [
  {
    q: "¿Echo guarda el audio de las reuniones?",
    a: "No. Lo usa mientras procesa la reunión y lo borra al terminar (si algo falla, como mucho 48 horas). Solo si elegís grabar una reunión, el audio va a tu Google Drive.",
  },
  {
    q: "¿La inteligencia artificial ve los nombres de los alumnos?",
    a: "No. Antes de redactar el acta o responder, Echo reemplaza los nombres de alumnos, familias y docentes por marcadores, y los vuelve a poner en lo que te muestra.",
  },
  {
    q: "¿Qué pasa si en la reunión hablan alumnos?",
    a: "Al crearla marcás «Hablan alumnos». Se transcribe igual, pero sin separar quién habló, y la conversación por voz no la usa.",
  },
  {
    q: "¿Cómo sabe Echo quién habló?",
    a: "Separa las voces al terminar la reunión. Para poner los nombres, sirve que cada uno diga «Hola, soy…» al empezar, y quien grabó su voz en Mi voz aparece con su nombre solo.",
  },
  {
    q: "¿Necesito instalar algo?",
    a: "No. Funciona en el navegador, en la computadora o en el celular. Para salas fijas hay un dispositivo, Echo Device.",
  },
  {
    q: "¿Cómo se paga?",
    a: (
      <>
        Todavía no se cobra desde Echo: elegís un plan y te escribimos para darlo de alta. Para un colegio entero,{" "}
        <Link to="/contacto?tema=ventas" className="font-medium text-ink-950 underline underline-offset-2">
          hablemos
        </Link>
        .
      </>
    ),
  },
];

export function Faq() {
  return (
    <Reveal id="preguntas" className="mx-auto max-w-3xl scroll-mt-20 px-6 py-24 md:px-12 md:py-32">
      <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">Preguntas frecuentes</h2>
      <div className="mt-10 divide-y divide-ink-200 border-y border-ink-200">
        {QUESTIONS.map((item) => (
          <details key={item.q} className="group py-5">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-lg font-medium tracking-tight text-ink-950">
              {item.q}
              <span
                aria-hidden
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-100 text-ink-700 transition-transform duration-300 group-open:rotate-45"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              </span>
            </summary>
            <p className="mt-3 max-w-2xl leading-relaxed text-ink-600">{item.a}</p>
          </details>
        ))}
      </div>
    </Reveal>
  );
}
