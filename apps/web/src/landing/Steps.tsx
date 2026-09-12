import { EchoFace, type EchoMood } from "../components/EchoFace";
import { Reveal } from "./Reveal";

/** Cómo se usa, en cuatro pasos. La cara de Echo cambia de estado en cada uno,
 *  igual que en la app y en el dispositivo. */
const STEPS: { mood: EchoMood; title: string; text: string }[] = [
  {
    mood: "listening",
    title: "Iniciá la reunión",
    text: "Con una familia, el equipo docente o un cliente. Elegís micrófono y motor de voz; el indicador de grabación queda siempre a la vista.",
  },
  {
    mood: "thinking",
    title: "Finalizá",
    text: "Echo separa hablantes, extrae acuerdos y tareas, resuelve fechas como «el viernes» y redacta el acta con el modelo de tu institución.",
  },
  {
    mood: "done",
    title: "Imprimí el acta",
    text: "Apenas termina la reunión, el acta está lista con tu logo y tu membrete. Cada afirmación se contrasta con el transcript; lo que no se dijo queda como «No especificado». Firmás, imprimís, y queda en Drive.",
  },
  {
    mood: "idle",
    title: "Preguntá después",
    text: "Sobre esa entrevista o sobre todo el año. Responde con fuentes y minutos; si no hay evidencia, lo dice.",
  },
];

export function Steps() {
  return (
    <Reveal className="mx-auto max-w-6xl px-6 py-24 md:px-12 md:py-32">
      <h2 className="text-3xl font-semibold tracking-tighter text-ink-950 md:text-5xl">Así se usa</h2>
      <ol className="mt-10 md:mt-14">
        {STEPS.map((step) => (
          <li
            key={step.title}
            className="grid grid-cols-[56px_1fr] items-start gap-x-6 gap-y-3 border-t border-ink-200 py-8 md:grid-cols-[132px_1fr_1.4fr] md:gap-x-10 md:py-12"
          >
            <div className={"w-14 text-ink-950 md:w-24 [&>svg]:h-auto [&>svg]:w-full " + (step.mood === "listening" ? "listen" : "")}>
              <EchoFace mood={step.mood} level={0.35} size={96} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-xl font-medium tracking-tight text-ink-950 md:text-2xl">{step.title}</h3>
              {step.mood === "listening" && (
                <span className="inline-flex items-center gap-2 rounded-full bg-ink-950 px-3 py-1 text-xs font-medium text-[#fafbfc]">
                  <i className="recording-dot h-2 w-2 rounded-full bg-live" aria-hidden />
                  Grabando
                </span>
              )}
            </div>
            <p className="col-start-2 leading-relaxed text-ink-600 md:col-start-3 md:text-lg">{step.text}</p>
          </li>
        ))}
      </ol>
    </Reveal>
  );
}
