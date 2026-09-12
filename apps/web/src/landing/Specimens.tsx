import { Reveal } from "./Reveal";

/** Lo que queda después de una entrevista con una familia, con datos de
 *  ejemplo: el transcript en vivo, lo que Echo extrae y cómo verifica. */
const LINES = [
  { t: "12:04", who: "Martina Oyola, docente", text: "Julieta mejoró mucho en lectura este trimestre. Lo que nos preocupa es la entrega de tareas." },
  { t: "12:21", who: "Carolina Ferraro, mamá", text: "En casa nos cuesta organizarnos. ¿Podemos probar con una agenda semanal?" },
  { t: "13:07", who: "Martina Oyola, docente", text: "Dale. La revisamos juntas el viernes y lo vemos de nuevo en un mes." },
];

export function Specimens() {
  return (
    <Reveal className="mx-auto max-w-6xl px-6 py-24 md:px-12 md:py-32">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">
          Lo que queda de una reunión
        </h2>
        <span className="text-sm text-ink-500">Ejemplo</span>
      </div>

      <div className="mt-10 grid gap-4 md:mt-14 md:grid-cols-12">
        <article className="rounded-2xl bg-ink-950 p-6 text-ink-200 md:col-span-7 md:p-8">
          <header className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span className="font-medium text-[#fafbfc]">Entrevista con la familia, 3.º A</span>
            <span className="text-ink-400">jue 10 sep 2026</span>
          </header>
          <ol className="mt-8 space-y-5 font-mono text-[15px] leading-7">
            {LINES.map((line) => (
              <li key={line.t} className="grid grid-cols-[52px_1fr] gap-x-4">
                <time className="text-ink-500">{line.t}</time>
                <p>
                  <span className="text-[#fafbfc]">{line.who}</span>
                  <br />
                  {line.text}
                </p>
              </li>
            ))}
            <li className="grid grid-cols-[52px_1fr] gap-x-4 text-ink-500">
              <time>13:12</time>
              <p className="italic">Y con matemática venimos</p>
            </li>
          </ol>
        </article>

        <div className="grid gap-4 md:col-span-5">
          <article className="rounded-2xl border border-ink-200 bg-white p-6 md:p-7">
            <h3 className="text-sm font-medium text-ink-500">Acuerdos y tareas</h3>
            <p className="mt-5 text-lg font-medium leading-snug tracking-tight text-ink-950">
              Agenda semanal de tareas para Julieta.
            </p>
            <p className="mt-1 font-mono text-sm text-ink-500">acuerdo · 12:21</p>
            <p className="mt-6 text-lg font-medium leading-snug tracking-tight text-ink-950">
              Revisar la agenda con la familia
            </p>
            <p className="mt-1 text-sm text-ink-600">
              Martina Oyola, vence vie 11 sep 2026. «El viernes» se resolvió con la fecha de la entrevista.
            </p>
          </article>

          <article className="rounded-2xl bg-ink-100 p-6 md:p-7">
            <h3 className="text-sm font-medium text-ink-500">Acta verificada</h3>
            <p className="mt-5 leading-relaxed text-ink-900">
              Se acuerda implementar una agenda semanal de tareas, revisada con la familia.
            </p>
            <p className="mt-2">
              <span className="inline-flex items-center rounded-full bg-ink-950 px-2.5 py-0.5 font-mono text-xs text-[#fafbfc]">
                verificada 12:21
              </span>
            </p>
            <p className="mt-6 leading-relaxed text-ink-900">Solicitada por: familia o colegio.</p>
            <p className="mt-1 text-sm italic text-ink-500">No especificado durante la reunión.</p>
          </article>
        </div>
      </div>
    </Reveal>
  );
}
