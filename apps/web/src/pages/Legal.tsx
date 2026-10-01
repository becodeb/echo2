import type { ReactNode } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { EchoFace } from "../components/EchoFace";

/**
 * Privacidad y términos, públicos (con y sin sesión).
 *
 * Regla para editar esto (docs/plan-correcciones.md §1.7): lo que no se puede
 * garantizar no se escribe. Cada afirmación sobre un proveedor está
 * verificada en su documentación al 30/9/2026:
 * - Groq: Services Agreement §4.2 (no usa inputs ni outputs para entrenar);
 *   logs de hasta 30 días para errores y abuso.
 * - ElevenLabs: política de privacidad del 20/5/2026, §11 (sin voces de
 *   menores de 18); el entrenamiento está desactivado en la cuenta de Becode
 *   desde el 30/9; la retención cero es solo Enterprise, así que no se promete.
 * - OpenAI (acta, resumen, chat e índice de búsqueda): la API no entrena con
 *   los datos salvo opt-in y guarda logs de abuso hasta 30 días
 *   (developers.openai.com, "Your data"). Desde el 1/10 no recibe audio.
 * - Hablar con Echo: ElevenLabs Agents (voz) con el LLM que elige el agente
 *   (services/voice_agent.py, AGENT_LLM), que ElevenLabs llama por su cuenta.
 * Antes de publicarlo como definitivo conviene que lo revise un abogado.
 */

const UPDATED = "1 de octubre de 2026";

export default function Legal() {
  const { doc } = useParams();
  const terms = doc === "terminos";
  return (
    <LegalShell>
      <article key={doc} className="animate-fade-up">
        {terms ? <Terms /> : <Privacy />}
      </article>
    </LegalShell>
  );
}

const linkClass = "font-medium text-ink-900 underline underline-offset-2";

/** Encabezado y marco de las páginas públicas (privacidad, términos, contacto). */
export function LegalShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-[#fafbfc]">
      <header className="sticky top-0 z-10 border-b border-ink-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-5 py-3">
          <Link to="/" className="flex items-center gap-2 text-ink-900">
            <EchoFace mood="idle" size={22} />
            <span className="hidden font-semibold tracking-tight sm:inline">Echo</span>
          </Link>
          <nav className="ml-auto flex gap-1 rounded-full bg-ink-100 p-1 text-sm" aria-label="Documentos">
            {[
              { to: "/legal/privacidad", label: "Privacidad" },
              { to: "/legal/terminos", label: "Términos" },
              { to: "/contacto", label: "Contacto" },
            ].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-full px-2.5 py-1 font-medium transition-colors sm:px-3.5 ${
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
      <main className="mx-auto max-w-3xl px-5 py-12">{children}</main>
    </div>
  );
}

export function Title({ children }: { children: ReactNode }) {
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
    <div className="rounded-3xl border border-ink-100 bg-white p-5">
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
        datos usa, quién los procesa, cuánto tiempo se guardan y qué podés hacer con ellos.
      </p>

      <Section title="Quién es el responsable">
        <p>
          Echo es un servicio de <strong>Becode</strong> (Argentina). Para cualquier consulta sobre tus datos, o para
          ejercer tus derechos, escribinos desde el{" "}
          <Link to="/contacto?tema=privacidad" className={linkClass}>formulario de contacto</Link>.
        </p>
        <p>
          Cuando una institución usa Echo, la institución decide qué reuniones se graban y es responsable de sus datos;
          Becode los procesa por cuenta de ella.
        </p>
      </Section>

      <Section title="Qué datos usa Echo">
        <ul>
          <li><strong>Tu cuenta:</strong> nombre, email y, si entrás con Google, el identificador de tu cuenta de Google.</li>
          <li><strong>Las reuniones:</strong> el texto transcripto, quién habló, el acta, el resumen, las tareas y lo que le preguntes a Echo.</li>
          <li><strong>El audio</strong> de la reunión, solo mientras se procesa (ver más abajo cuánto dura).</li>
          <li><strong>Tu muestra de voz</strong>, si decidís grabarla en Mi voz.</li>
          <li><strong>Las charlas con Hablar con Echo</strong>, si tu plan lo incluye.</li>
          <li><strong>El consumo:</strong> cuántos minutos de audio y de voz y cuánta IA usa cada persona, para los planes y los créditos.</li>
        </ul>
      </Section>

      <Section title="Quién procesa el audio y el texto">
        <p>Echo usa estos servicios y solo les manda lo necesario para cada paso.</p>
        <div className="grid gap-3">
          <Provider
            name="Groq"
            what="Transcribe el audio: en vivo y, en las reuniones sin separar quién habló, también al terminar."
            facts={[
              "Es el único servicio que transcribe. Si no responde, Echo reintenta más tarde con Groq: no manda el audio a otro.",
              "Por contrato no usa lo que le mandamos ni lo que devuelve para entrenar modelos.",
              "Puede guardar registros hasta 30 días, solo para resolver errores y prevenir abusos.",
            ]}
          />
          <Provider
            name="ElevenLabs"
            what="Al terminar, separa quién habló en las reuniones que lo usan (según el plan o un crédito). También pone la voz de Hablar con Echo."
            facts={[
              "Nunca recibe audio de reuniones donde hablan menores de 18 años.",
              "En la cuenta de Echo está desactivado el uso de los datos para mejorar sus modelos.",
              "Conserva datos según su propia política de privacidad; no podemos pedirle que los borre al instante.",
            ]}
          />
          <Provider
            name="OpenAI"
            what="Redacta el acta y el resumen, arma las tareas, responde lo que le preguntás a Echo y arma el índice de búsqueda."
            facts={[
              "Recibe texto, nunca audio, y con los nombres de las personas reemplazados por marcadores.",
              "Su API no usa los datos para entrenar modelos, salvo que se lo autorice (Echo no lo autoriza).",
              "Puede guardar registros hasta 30 días para prevenir abusos.",
            ]}
          />
        </div>
        <p>
          Con Echo Bridge el audio se transcribe en tu computadora y no sale de ella, salvo que elijas grabar la reunión.
        </p>
      </Section>

      <Section title="Los nombres no le llegan a la IA">
        <p>
          Antes de mandar texto a la IA, Echo reemplaza los nombres de alumnos, familias y personal, y los datos como DNI,
          teléfonos, emails, direcciones o datos de salud, por marcadores ("[ALUMNO_1]", "[MADRE_1]", "[DATO_1]"). La
          respuesta vuelve con marcadores y Echo les devuelve el nombre real. También reemplaza los nombres que se dijeron
          en voz alta aunque no estén cargados. Ningún sistema automático es perfecto: un nombre poco común dicho al
          principio de una frase puede pasar.
        </p>
      </Section>

      <Section title="Hablar con Echo (conversación por voz)">
        <ul>
          <li>Es solo para mayores de 18 años y para los planes que la incluyen.</li>
          <li>
            Lo que decís y lo que responde Echo pasa por <strong>ElevenLabs</strong> (la voz) y por el modelo de lenguaje
            que usa su agente (hoy, Gemini de Google, a través de ElevenLabs).
          </li>
          <li>
            Para responder, Echo consulta tus reuniones con los nombres reemplazados por marcadores, pero la respuesta
            hablada dice los nombres reales: por eso esos nombres sí llegan a ElevenLabs.
          </li>
          <li>Las reuniones donde hablan menores de 18 nunca se usan en la conversación por voz.</li>
          <li>Echo no guarda el audio de la charla; guarda cuánto duró, para el consumo del plan.</li>
        </ul>
      </Section>

      <Section title="Mi voz (reconocimiento por voz)">
        <p>
          Si grabás tu voz en Mi voz, Echo la usa para poner tu nombre en las reuniones en lugar de "Persona 1". Es un
          dato biométrico, así que te contamos exactamente qué pasa:
        </p>
        <ul>
          <li>
            De la muestra se calcula una <strong>huella de voz</strong> (una lista de números que describe cómo suena tu
            voz). Se calcula en el servidor de Echo: ni la muestra ni la huella se mandan a otros servicios.
          </li>
          <li>
            Después de cada reunión de tu organización, Echo compara la huella con la de cada persona que habló. Solo pone
            tu nombre si la coincidencia es alta; si tiene dudas, lo deja como sugerencia para confirmar. De las demás
            personas de la reunión no se guarda ninguna huella.
          </li>
          <li>
            <strong>Mejorar el reconocimiento con mis reuniones</strong> viene activado al grabar tu voz: cuando Echo te
            reconoce con seguridad, suma lo aprendido a tu huella. Lo podés apagar en Mi voz, y al apagarlo se olvida lo
            aprendido.
          </li>
          <li>
            La muestra y la huella se guardan hasta que las borres desde Ajustes → Mi voz, y se borran también si das de
            baja tu cuenta.
          </li>
        </ul>
      </Section>

      <Section title="Qué guarda Echo y por cuánto tiempo">
        <ul>
          <li><strong>El texto de las reuniones</strong> (transcript, acta, tareas): hasta que la institución o quien la creó lo borre.</li>
          <li><strong>El audio de trabajo</strong> se borra cuando termina de procesarse la reunión. Si la transcripción completa o la separación de quién habló falló, se guarda una copia comprimida hasta 48 horas para reintentarlo, y después se borra.</li>
          <li><strong>La grabación completa</strong>, solo si se eligió grabar la reunión: va al Google Drive de quien grabó; si no tiene Drive conectado, queda para descargar 48 horas y se borra.</li>
          <li><strong>La muestra de voz y su huella</strong>, hasta que las borres.</li>
        </ul>
      </Section>

      <Section title="Reuniones con alumnos menores de 18">
        <p>
          Al crear una reunión se indica si hablan alumnos menores de 18 (en los Echo Devices viene marcado de fábrica,
          porque pueden estar en un aula). En esas reuniones Echo no separa quién habló: el audio no se manda a
          ElevenLabs, porque sus condiciones no admiten voces de menores, y la conversación por voz no las usa. Se
          transcriben igual, sin distinguir a cada persona.
        </p>
      </Section>

      <Section title="Aviso y consentimiento">
        <p>
          La institución que usa Echo es responsable de avisar que la reunión se graba y transcribe, y de contar con el
          consentimiento de las familias y de quienes participan. Un aviso posible, al empezar:
        </p>
        <blockquote className="rounded-3xl border-l-4 border-ink-900 bg-white px-5 py-4 text-ink-700">
          "Vamos a transcribir esta reunión con Echo para armar el acta. Echo no se queda con el audio, y los nombres
          no se comparten con la inteligencia artificial. ¿Están de acuerdo?"
        </blockquote>
      </Section>

      <Section title="Tus derechos">
        <p>
          Como prevé la Ley 25.326 de Protección de Datos Personales, podés pedir acceso a tus datos, corregirlos o
          borrarlos. Pedilo desde el{" "}
          <Link to="/contacto?tema=privacidad" className={linkClass}>formulario de contacto</Link>. Respondemos los
          pedidos de acceso dentro de los 10 días corridos y los de corrección o supresión dentro de los 5 días hábiles.
          Si una reunión es de una institución, también podés pedírselo a ella.
        </p>
        <p>
          Para dar de baja tu cuenta, usá <strong>Ajustes → Privacidad → Pedir la baja de mi cuenta</strong>, o el
          formulario de contacto. Borramos tu cuenta y tus datos personales dentro de los 5 días hábiles; las reuniones
          de una institución quedan en la institución.
        </p>
        <p>
          La Agencia de Acceso a la Información Pública, en su carácter de órgano de control de la Ley 25.326, tiene la
          atribución de atender las denuncias y reclamos que se interpongan con relación al incumplimiento de las
          normas sobre protección de datos personales.
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
        <Link to="/legal/privacidad" className={linkClass}>
          página de privacidad
        </Link>
        .
      </p>

      <Section title="Qué es Echo">
        <p>
          Echo transcribe reuniones, separa quién habló, y con inteligencia artificial redacta actas, resúmenes y tareas,
          y responde preguntas sobre lo que se habló, por escrito o, en los planes que la incluyen, por voz. Se organiza
          por institución, con sus sedes, niveles, familias y equipos; quien no pertenece a una institución tiene una
          cuenta individual.
        </p>
      </Section>

      <Section title="La IA se puede equivocar">
        <p>
          La transcripción y lo que redacta o responde la IA pueden tener errores. El acta es un borrador: revisala antes
          de aprobarla, compartirla o firmarla.
        </p>
      </Section>

      <Section title="Tu responsabilidad">
        <ul>
          <li>Avisar que la reunión se graba y contar con el consentimiento de quienes participan.</li>
          <li>Indicar al crear la reunión si hablan alumnos menores de 18.</li>
          <li>Usar Echo para las reuniones de tu institución o propias, y no para grabar a nadie sin que lo sepa.</li>
          <li>Usar Hablar con Echo solo si sos mayor de 18 años.</li>
          <li>Cuidar el acceso a tu cuenta.</li>
        </ul>
      </Section>

      <Section title="Planes, créditos y cancelación">
        <ul>
          <li>El plan Gratis incluye una cantidad de reuniones por mes con quién habló (créditos); una reunión de más de una hora usa dos. Se renuevan cada mes y no se acumulan.</li>
          <li>Los planes pagos e institucionales se contratan hablando con Becode. Echo todavía no cobra desde la aplicación.</li>
          <li>Podés cancelar un plan pago cuando quieras, desde Planes o desde el <Link to="/contacto?tema=ventas" className={linkClass}>formulario de contacto</Link>. El plan sigue hasta el fin del mes ya pagado, después pasa a Gratis y no se cobra más. No hay reintegros por partes de un mes.</li>
          <li>Becode puede poner topes de uso para evitar abusos.</li>
        </ul>
      </Section>

      <Section title="Baja de la cuenta">
        <p>
          Podés pedir la baja cuando quieras desde Ajustes → Privacidad. Becode borra tu cuenta y tus datos personales
          dentro de los 5 días hábiles. Si sos parte de una institución, las reuniones que se hicieron para ella quedan
          en la institución.
        </p>
      </Section>

      <Section title="Disponibilidad y responsabilidad">
        <p>
          Echo depende de servicios de terceros para transcribir, para la IA y para la voz. Hacemos lo posible para que
          funcione siempre, pero puede haber interrupciones; si la transcripción completa o la separación de quién habló
          falla, Echo lo reintenta solo.
        </p>
        <p>
          Becode no es responsable por las decisiones que se tomen a partir de un acta, un resumen o una respuesta de
          Echo sin revisarlos, ni por el contenido de lo que se habla en las reuniones. En lo que la ley lo permita, la
          responsabilidad de Becode por el servicio se limita a lo que se haya pagado por él en los últimos tres meses.
        </p>
      </Section>

      <Section title="Ley aplicable">
        <p>Estos términos se rigen por las leyes de la República Argentina.</p>
      </Section>
    </>
  );
}
