import type { ReactNode } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { EchoFace } from "../components/EchoFace";

/**
 * Privacidad y términos, públicos (con y sin sesión).
 *
 * Regla para editar esto (docs/plan-transcripcion-y-planes.md, tarea 14): lo
 * que no se puede garantizar no se escribe. Cada afirmación sobre un
 * proveedor está verificada en su documentación al 30/9/2026:
 * - Groq: Services Agreement §4.2 (no usa inputs ni outputs para entrenar);
 *   logs de hasta 30 días para errores y abuso.
 * - ElevenLabs: política de privacidad del 20/5/2026, §11 (sin voces de
 *   menores de 18); el entrenamiento está desactivado en la cuenta de Becode
 *   desde el 30/9; la retención cero es solo Enterprise, así que no se promete.
 * - OpenAI (acta, resumen y chat): la API no entrena con los datos salvo opt-in
 *   y guarda logs de abuso hasta 30 días (developers.openai.com, "Your data").
 * Antes de publicarlo como definitivo conviene que lo revise un abogado.
 */

const UPDATED = "30 de septiembre de 2026";

export default function Legal() {
  const { doc } = useParams();
  const terms = doc === "terminos";
  return (
    <div className="min-h-dvh bg-[#fafbfc]">
      <header className="sticky top-0 z-10 border-b border-ink-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-5 py-3">
          <Link to="/" className="flex items-center gap-2 text-ink-900">
            <EchoFace mood="idle" size={22} />
            <span className="font-semibold tracking-tight">Echo</span>
          </Link>
          <nav className="ml-auto flex gap-1 rounded-full bg-ink-100 p-1 text-sm" aria-label="Documentos">
            {[
              { to: "/legal/privacidad", label: "Privacidad" },
              { to: "/legal/terminos", label: "Términos" },
            ].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-full px-3.5 py-1 font-medium transition-colors ${
                    isActive ? "bg-white text-ink-900 shadow-[0_1px_3px_rgba(0,0,0,0.12)]" : "text-ink-500 hover:text-ink-800"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-5 py-12">
        <article key={doc} className="animate-fade-up">
          {terms ? <Terms /> : <Privacy />}
        </article>
      </main>
    </div>
  );
}

function Title({ children }: { children: ReactNode }) {
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight text-ink-900 sm:text-4xl">{children}</h1>
      <p className="mt-2 text-sm text-ink-400">Última actualización: {UPDATED}</p>
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold tracking-tight text-ink-900">{title}</h2>
      <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-ink-600 [&_li]:ml-5 [&_li]:list-disc [&_li]:pl-1 [&_strong]:font-semibold [&_strong]:text-ink-800 [&_ul]:space-y-2">
        {children}
      </div>
    </section>
  );
}

function Provider({ name, what, facts }: { name: string; what: string; facts: string[] }) {
  return (
    <div className="rounded-2xl border border-ink-100 bg-white p-5">
      <p className="text-[15px] font-semibold text-ink-900">{name}</p>
      <p className="mt-0.5 text-sm text-ink-500">{what}</p>
      <ul className="mt-3 space-y-1.5 text-sm">
        {facts.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>
    </div>
  );
}

function Privacy() {
  return (
    <>
      <Title>Privacidad</Title>
      <p className="mt-6 text-[17px] leading-relaxed text-ink-700">
        Echo graba y transcribe reuniones de colegios: entrevistas con familias y reuniones de equipo. Acá contamos qué
        datos usa, quién los procesa, cuánto tiempo se guardan y qué podés hacer con ellos. Echo es un servicio de Becode.
      </p>

      <Section title="Qué datos usa Echo">
        <ul>
          <li><strong>Tu cuenta:</strong> nombre, email y, si entrás con Google, el identificador de tu cuenta de Google.</li>
          <li><strong>Las reuniones:</strong> el texto transcripto, quién habló, el acta, el resumen, las tareas y lo que le preguntes a la IA.</li>
          <li><strong>El audio</strong> de la reunión, solo mientras se procesa (ver más abajo cuánto dura).</li>
          <li><strong>Tu muestra de voz</strong>, si decidís grabarla en Ajustes → Mi voz, para reconocerte en las reuniones.</li>
          <li><strong>El consumo:</strong> cuántos minutos de audio y cuánta IA usa cada persona, para los planes y los créditos.</li>
        </ul>
      </Section>

      <Section title="Quién procesa el audio y el texto">
        <p>Echo no transcribe por su cuenta: usa estos servicios, y solo les manda lo necesario para cada paso.</p>
        <div className="grid gap-3">
          <Provider
            name="Groq"
            what="Transcribe el audio en vivo y, en las reuniones sin separar quién habló, también al terminar."
            facts={[
              "Por contrato no usa lo que le mandamos ni lo que devuelve para entrenar modelos.",
              "Puede guardar registros hasta 30 días, solo para resolver errores y prevenir abusos.",
            ]}
          />
          <Provider
            name="ElevenLabs"
            what="Al terminar, separa quién habló en las reuniones que lo usan (según el plan o un crédito)."
            facts={[
              "Nunca recibe reuniones donde hablan menores de 18 años.",
              "En la cuenta de Echo está desactivado el uso de los datos para mejorar sus modelos.",
              "Conserva datos según su propia política de privacidad; no podemos pedirle que los borre al instante.",
            ]}
          />
          <Provider
            name="OpenAI"
            what="Redacta el acta y el resumen, arma las tareas y responde el chat sobre la reunión."
            facts={[
              "Recibe texto, nunca audio, y con los nombres de las personas reemplazados por marcadores.",
              "Su API no usa los datos para entrenar modelos, salvo que se lo autorice (Echo no lo autoriza).",
              "Puede guardar registros hasta 30 días para prevenir abusos.",
            ]}
          />
        </div>
        <p>
          Una organización puede configurar otro motor en Ajustes → IA y transcripción; en ese caso se aplican las
          condiciones de ese proveedor. Con Echo Bridge el audio se transcribe en tu computadora y no sale de ella, salvo
          que elijas grabar la reunión.
        </p>
      </Section>

      <Section title="Los nombres no le llegan a la IA">
        <p>
          Antes de mandar texto a la IA, Echo reemplaza los nombres de alumnos, familias y personal, y los datos como DNI,
          teléfonos y emails, por marcadores ("[ALUMNO_1]", "[MADRE_1]"). La respuesta vuelve con marcadores y Echo les
          devuelve el nombre real. También reemplaza los nombres que se dijeron en voz alta aunque no estén cargados.
        </p>
      </Section>

      <Section title="Qué guarda Echo y por cuánto tiempo">
        <ul>
          <li><strong>El texto de las reuniones</strong> (transcript, acta, tareas): hasta que la institución o quien la creó lo borre.</li>
          <li><strong>El audio de trabajo</strong> se borra cuando termina de procesarse la reunión. Si la separación de quién habló falló, se guarda una copia comprimida hasta 48 horas para reintentarlo, y después se borra.</li>
          <li><strong>La grabación completa</strong>, solo si se eligió grabar la reunión: va al Google Drive de quien grabó; si no tiene Drive conectado, queda para descargar 48 horas y se borra.</li>
          <li><strong>La muestra de voz</strong>, hasta que la borres desde Ajustes → Mi voz.</li>
        </ul>
      </Section>

      <Section title="Reuniones con alumnos menores de 18">
        <p>
          Al crear una reunión se indica si hablan alumnos menores de 18. En esas reuniones Echo no separa quién habló:
          el audio no se manda a ElevenLabs, porque sus condiciones no admiten voces de menores. Se transcribe igual,
          sin distinguir a cada persona.
        </p>
      </Section>

      <Section title="Aviso y consentimiento">
        <p>
          La institución que usa Echo es responsable de avisar que la reunión se graba y transcribe, y de contar con el
          consentimiento de las familias y de quienes participan. Un aviso posible, al empezar:
        </p>
        <blockquote className="rounded-2xl border-l-4 border-ink-900 bg-white px-5 py-4 text-ink-700">
          "Vamos a transcribir esta reunión con Echo para armar el acta. Echo no se queda con el audio, y los nombres
          no se comparten con la inteligencia artificial. ¿Están de acuerdo?"
        </blockquote>
      </Section>

      <Section title="Tus derechos">
        <p>
          Podés pedir acceso a tus datos, corregirlos o borrarlos, como prevé la Ley 25.326 de Protección de Datos
          Personales. Si una reunión es de una institución, el pedido se hace a través de ella. La Agencia de Acceso a la
          Información Pública es la autoridad de control de esa ley.
        </p>
      </Section>

      <Section title="Cambios">
        <p>Si cambia algo importante de esta página, lo avisamos dentro de Echo antes de que se aplique.</p>
      </Section>
    </>
  );
}

function Terms() {
  return (
    <>
      <Title>Términos de uso</Title>
      <p className="mt-6 text-[17px] leading-relaxed text-ink-700">
        Estos términos rigen el uso de Echo, un servicio de Becode. Al crear una cuenta los aceptás, junto con la{" "}
        <Link to="/legal/privacidad" className="font-medium text-ink-900 underline underline-offset-2">
          página de privacidad
        </Link>
        .
      </p>

      <Section title="Qué es Echo">
        <p>
          Echo transcribe reuniones, separa quién habló, y con inteligencia artificial redacta actas, resúmenes y tareas,
          y responde preguntas sobre lo que se habló. Se organiza por institución, con sus sedes, niveles, familias y
          equipos; quien no pertenece a una institución tiene una cuenta individual.
        </p>
      </Section>

      <Section title="La IA se puede equivocar">
        <p>
          La transcripción y lo que redacta la IA pueden tener errores. El acta es un borrador: revisala antes de
          aprobarla, compartirla o firmarla.
        </p>
      </Section>

      <Section title="Tu responsabilidad">
        <ul>
          <li>Avisar que la reunión se graba y contar con el consentimiento de quienes participan.</li>
          <li>Indicar al crear la reunión si hablan alumnos menores de 18.</li>
          <li>Usar Echo para las reuniones de tu institución o propias, y no para grabar a nadie sin que lo sepa.</li>
          <li>Cuidar el acceso a tu cuenta.</li>
        </ul>
      </Section>

      <Section title="Planes y créditos">
        <ul>
          <li>El plan Gratis incluye reuniones sin límite y una cantidad de créditos por mes: cada crédito es una reunión con quién habló (dos si dura más de una hora). Se renuevan cada mes y no se acumulan.</li>
          <li>Los planes pagos e institucionales se contratan hablando con Becode. Echo todavía no cobra desde la aplicación.</li>
          <li>Becode puede poner topes de uso para evitar abusos.</li>
        </ul>
      </Section>

      <Section title="Disponibilidad">
        <p>
          Echo depende de servicios de terceros para transcribir y para la IA. Hacemos lo posible para que funcione
          siempre, pero puede haber interrupciones. Si la separación de quién habló falla, Echo lo reintenta solo.
        </p>
      </Section>

      <Section title="Ley aplicable">
        <p>Estos términos se rigen por las leyes de la República Argentina.</p>
      </Section>
    </>
  );
}
