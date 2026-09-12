import { Reveal } from "./Reveal";

/** Chat con fuentes: cita «Título», fecha y minuto. Datos de ejemplo. */
const EXCHANGES = [
  {
    q: "¿Qué acordamos con la familia de Julieta?",
    a: (
      <>
        Una agenda semanal de tareas que la docente revisa con la familia los viernes, y una nueva
        entrevista en un mes. Se acordó en{" "}
        <b className="font-medium text-ink-950">«Entrevista con la familia, 3.º A»</b>, 10 sep 2026{" "}
        <span className="font-mono text-sm">[12:21]</span> y <span className="font-mono text-sm">[13:07]</span>.
      </>
    ),
  },
  {
    q: "¿Qué dijo la docente sobre la lectura?",
    a: (
      <>
        Que Julieta mejoró mucho este trimestre. Lo dijo Martina Oyola en{" "}
        <b className="font-medium text-ink-950">«Entrevista con la familia, 3.º A»</b>, 10 sep 2026{" "}
        <span className="font-mono text-sm">[12:04]</span>.
      </>
    ),
  },
];

export function Ask() {
  return (
    <Reveal className="mx-auto max-w-3xl px-6 py-24 md:px-12 md:py-32">
      <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">Preguntale a Echo</h2>
      <p className="mt-4 max-w-xl leading-relaxed text-ink-600 md:text-lg">
        Sobre una entrevista o sobre todo el año. Cita título, fecha y minuto. Si no hay evidencia,
        lo dice.
      </p>
      <dl className="mt-12 space-y-8">
        {EXCHANGES.map((x) => (
          <div key={x.q}>
            <dt className="text-xl font-medium tracking-tight text-ink-950 md:text-2xl">{x.q}</dt>
            <dd className="mt-3 rounded-2xl border border-ink-200 bg-white p-6 leading-relaxed text-ink-700 md:p-7">
              {x.a}
            </dd>
          </div>
        ))}
      </dl>
    </Reveal>
  );
}
