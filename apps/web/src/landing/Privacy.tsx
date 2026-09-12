import { Reveal } from "./Reveal";

/** La única sección en negro de la página: el audio desaparece. */
const FACTS = [
  {
    title: "Con Echo Bridge, en tu computadora",
    text: "Un servicio local transcribe con tu propio motor de voz (Parakeet, whisper.cpp). El audio no sale de la máquina.",
  },
  {
    title: "En modo cloud, cifrado y descartado",
    text: "Viaja al motor que configures y se borra al transcribir. La interfaz siempre muestra qué modo está activo.",
  },
  {
    title: "Claves cifradas",
    text: "Las API keys de tu organización se guardan cifradas y nunca vuelven completas al navegador.",
  },
];

export function Privacy() {
  return (
    <Reveal className="bg-ink-950 text-[#fafbfc]">
      <div className="mx-auto grid max-w-6xl gap-12 px-6 py-24 md:grid-cols-12 md:px-12 md:py-32">
        <div className="md:col-span-7">
          <h2 className="text-4xl font-semibold tracking-tighter md:text-6xl">El audio no se guarda.</h2>
          <p className="mt-6 max-w-md text-lg leading-relaxed text-ink-300">
            Se transcribe en memoria y se destruye. Lo único que persiste es texto. Importa cuando en
            la reunión hay familias y alumnos.
          </p>
          <p className="mt-10 font-mono text-sm text-ink-400 md:text-base">
            micrófono → memoria → motor de voz → texto → audio destruido
          </p>
        </div>
        <ul className="space-y-8 md:col-span-5">
          {FACTS.map((fact) => (
            <li key={fact.title}>
              <h3 className="text-lg font-medium tracking-tight">{fact.title}</h3>
              <p className="mt-2 leading-relaxed text-ink-400">{fact.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </Reveal>
  );
}
