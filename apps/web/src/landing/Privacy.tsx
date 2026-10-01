import { Reveal } from "./Reveal";

/** La única sección en negro de la página: el audio desaparece. */
const FACTS = [
  {
    title: "Los nombres no le llegan a la IA",
    text: "Antes de redactar el acta, Echo reemplaza los nombres de alumnos, familias y docentes por marcadores, y los devuelve al terminar.",
  },
  {
    title: "Cuando hablan alumnos, más cuidado",
    text: "Si en la reunión hablan menores de 18, se transcribe sin separar quién habló y la conversación por voz no la usa.",
  },
  {
    title: "Vos decidís qué se guarda",
    text: "El acta y el texto quedan en Echo hasta que los borres. El audio, solo si elegís grabar la reunión, y va a tu Google Drive.",
  },
];

export function Privacy() {
  return (
    <Reveal id="privacidad" className="scroll-mt-16 bg-ink-950 text-[#fafbfc]">
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-24 md:grid-cols-12 md:px-12 md:py-32">
        <div className="md:col-span-7">
          <h2 className="text-4xl font-semibold tracking-tighter md:text-6xl">Echo no se queda con el audio.</h2>
          <p className="mt-6 max-w-md text-lg leading-relaxed text-ink-300">
            Se usa mientras se procesa la reunión y Echo lo borra al terminar. Lo que queda es
            texto. Importa cuando en la reunión hay familias y alumnos.
          </p>
          <a href="/legal/privacidad" className="mt-4 inline-block text-sm font-medium text-ink-300 underline underline-offset-4 hover:text-white">
            Quién procesa cada cosa y cuánto se guarda
          </a>
          <p className="mt-10 font-mono text-sm text-ink-300 md:text-base">
            micrófono → transcripción → texto → audio borrado
          </p>
        </div>
        <ul className="space-y-8 md:col-span-5">
          {FACTS.map((fact) => (
            <li key={fact.title}>
              <h3 className="text-lg font-medium tracking-tight">{fact.title}</h3>
              <p className="mt-2 leading-relaxed text-ink-300">{fact.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </Reveal>
  );
}
