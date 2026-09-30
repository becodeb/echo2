import { Button } from "../../../../web/src/components/ui";
import { pressScale, presence, typed } from "../anim";
import { ASK_INPUT, ASK_R, ASK_SEND, ASK_X, MAIN_X } from "../layout";
import { ANSWER_AT, CLICK, QUESTION, TYPE_END, TYPE_START } from "../timeline";
import { Face } from "../ui/Face";

const SUGGESTIONS = [
  "¿Qué decisiones tomamos esta semana?",
  "¿Qué tareas siguen pendientes?",
  "¿Qué reuniones mencionaron presupuesto?",
  "¿Qué decisiones siguen sin ejecutarse?",
];

/** Posición del link de la fuente (para el cursor). */
export const SOURCE_LINK = { x: ASK_X + 16 + 150, y: 243 };

/** pages/AskEcho.tsx: estado vacío, pregunta, respuesta con fuentes. */
export function Ask({ frame }: { frame: number }) {
  const sent = frame >= CLICK.enviar;
  const empty = presence(frame, -20, CLICK.enviar, 1, 8);
  const question = presence(frame, CLICK.enviar + 2, Infinity, 10);
  const searching = presence(frame, CLICK.enviar + 8, ANSWER_AT, 8, 6);
  const answer = presence(frame, ANSWER_AT, Infinity, 12);
  const text = sent ? "" : typed(QUESTION, frame, TYPE_START, TYPE_END);
  const focused = frame >= CLICK.input && !sent;
  const caretOn = Math.floor(frame / 16) % 2 === 0;
  const width = ASK_R - ASK_X;

  return (
    <div className="absolute inset-y-0 right-0 bg-[#fafbfc]" style={{ left: MAIN_X }}>
      <div className="absolute inset-0" style={{ left: -MAIN_X }}>
        {empty.visible && (
          <div className="absolute flex flex-col items-center gap-3 text-center text-ink-500" style={{ left: ASK_X, width, top: 96, ...empty.style }}>
            <span className="text-ink-300">
              <Face size={56} frame={frame} blinkAt={[CLICK.navAsk + 20]} />
            </span>
            <p className="font-medium text-ink-700">Preguntale a Echo</p>
            <div className="max-w-sm text-sm">
              <p className="mb-5">Echo responde usando la memoria de todas tus reuniones, siempre con fuentes.</p>
            </div>
            <div className="-mt-2 flex max-w-[640px] flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <span key={suggestion} className="rounded-full border border-ink-200 bg-white px-3.5 py-1.5 text-sm text-ink-600">
                  {suggestion}
                </span>
              ))}
            </div>
          </div>
        )}

        {sent && (
          <div className="absolute space-y-5" style={{ left: ASK_X, width, top: 40 }}>
            <div className="flex justify-end" style={question.style}>
              <div className="max-w-[85%] rounded-2xl bg-ink-900 px-4 py-3 text-[15px] leading-relaxed text-white">{QUESTION}</div>
            </div>
            {searching.visible && (
              <div className="flex items-center gap-2.5 text-ink-400" style={searching.style}>
                <Face size={22} mood="thinking" frame={frame} />
                <span className="text-sm">Buscando en la memoria de reuniones…</span>
              </div>
            )}
            {answer.visible && (
              <div className="flex justify-start" style={answer.style}>
                <div className="max-w-[85%] rounded-2xl border border-ink-100 bg-white px-4 py-3 text-[15px] leading-relaxed text-ink-900 shadow-sm">
                  <p>
                    Con la familia Romero se acordó una <strong className="font-semibold">reunión con la psicopedagoga el viernes 2 de octubre</strong>.
                    La Directora coordina el horario y la Orientadora (DOE) hace el seguimiento con la familia.
                  </p>
                  <div className="mt-3 space-y-1 border-t border-ink-100 pt-2.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Fuentes</p>
                    <span
                      className="block text-xs text-accent-600"
                      style={{
                        textDecoration: frame >= CLICK.fuente - 14 ? "underline" : undefined,
                        transform: `scale(${pressScale(frame, CLICK.fuente)})`,
                        transformOrigin: "left center",
                      }}
                    >
                      «Familia Romero · 28 sept» — 00:13 · Orientadora (DOE)
                    </span>
                    <span className="block text-xs text-accent-600">«Familia Romero · 28 sept» — 00:16 · Directora</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Entrada */}
        <div className="absolute border-t border-ink-100 pt-4" style={{ left: ASK_X, width, top: ASK_INPUT.y - 16 }}>
          <div className="flex gap-2">
            <div
              className={`flex flex-1 items-center rounded-xl border bg-white px-4 py-3 text-[15px] shadow-sm ${
                focused ? "border-accent-500" : "border-ink-200"
              }`}
              style={{ height: ASK_INPUT.h }}
            >
              {text ? <span className="text-ink-900">{text}</span> : <span className="text-ink-400">Preguntá sobre cualquier reunión…</span>}
              {focused && <span className="ml-px inline-block h-5 w-px bg-ink-900" style={{ opacity: caretOn ? 1 : 0 }} />}
            </div>
            <Button className="!px-5" style={{ width: ASK_SEND.w, height: ASK_INPUT.h, transform: `scale(${pressScale(frame, CLICK.enviar)})` }}>
              Enviar
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
