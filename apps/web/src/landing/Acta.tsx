import { Reveal } from "./Reveal";

/**
 * El acta con el formato de la institución: membrete, logo, título, campos y
 * el texto que Echo completa con lo que se dijo. Datos de ejemplo.
 */
export function Acta() {
  return (
    <Reveal className="mx-auto max-w-6xl px-6 py-24 md:px-12 md:py-32">
      <div className="grid gap-12 md:grid-cols-12 md:items-center">
        <div className="md:col-span-5">
          <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">
            El acta, lista al terminar
          </h2>
          <p className="mt-6 leading-relaxed text-ink-600 md:text-lg">
            Cargás una vez el modelo de tu institución: logo, membrete y campos. Al finalizar cada
            reunión, Echo lo completa con lo que se dijo y lo contrasta con el transcript.
          </p>
          <p className="mt-4 leading-relaxed text-ink-600 md:text-lg">
            Lo que no se dijo queda como «No especificado». Imprimís, firmás, y queda guardado en
            Drive.
          </p>
        </div>

        <div className="md:col-span-7">
          <div className="acta-hoja">
            <div className="acta-membrete">
              <p>
                Colegio del Parque
                <br />
                Nivel primario
                <br />
                Av. de los Tilos 1240, Escobar
              </p>
              <span className="acta-logo" aria-hidden>
                CP
              </span>
            </div>
            <h3 className="acta-titulo">Acta de entrevista</h3>
            <dl className="acta-campos">
              <div>
                <dt>Alumna</dt>
                <dd>Julieta Ferraro</dd>
              </div>
              <div>
                <dt>Curso</dt>
                <dd>3.º A</dd>
              </div>
              <div>
                <dt>Solicitada por</dt>
                <dd className="italic text-ink-500">No especificado durante la reunión</dd>
              </div>
              <div>
                <dt>Motivo</dt>
                <dd>Organización de las tareas en casa</dd>
              </div>
            </dl>
            <p className="acta-texto">
              A los 10 días del mes de septiembre de 2026, en las instalaciones del Colegio del Parque,
              se reúnen la docente Martina Oyola y Carolina Ferraro, madre de la alumna. Se acuerda
              implementar una agenda semanal de tareas, que la docente revisará con la familia los
              viernes. Se fija una nueva entrevista en un mes.
            </p>
            <p className="acta-marcas">
              <span>verificada 12:21</span>
              <span>verificada 13:07</span>
            </p>
            <div className="acta-firmas">
              <span>Firma docente</span>
              <span>Firma familia</span>
            </div>
          </div>
          <p className="mt-4 text-sm text-ink-500">Se imprime con un clic, o se guarda en Drive.</p>
        </div>
      </div>
    </Reveal>
  );
}
