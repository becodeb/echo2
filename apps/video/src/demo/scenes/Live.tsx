import { Button } from "../../../../web/src/components/ui";
import { pressScale, presence, ramp } from "../anim";
import {
  FOOTER_BUTTONS,
  FOOTER_START,
  INICIAR,
  LIVE_ASIDE_X,
  LIVE_FOOTER_Y,
  LIVE_HEADER_H,
  LIVE_TEXT_W,
  LIVE_TEXT_X,
  MAIN_CX,
  MAIN_X,
} from "../layout";
import { B, CLICK, FPS, LIVE_LINES } from "../timeline";
import { Face } from "../ui/Face";

const fmt = (ms: number) => {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};

/** MeetingLive: antes de empezar, grabando, y el pie de acciones. */
export function Live({ frame }: { frame: number }) {
  const recording = frame >= CLICK.iniciar;
  // El reloj de la reunión corre 4× para que se note el paso del tiempo
  // (las líneas quedan en 00:02, 00:07 y 00:13 como en el transcript).
  const elapsed = recording ? ((frame - CLICK.iniciar) / FPS) * 4000 : 0;
  const pre = presence(frame, -20, CLICK.iniciar, 1, 10);
  const rec = presence(frame, CLICK.iniciar + 2, Infinity, 12);
  const level = recording ? 0.35 + 0.3 * Math.abs(Math.sin(frame / 5.3)) * Math.abs(Math.cos(frame / 11)) : 0;

  return (
    <div className="absolute inset-y-0 right-0 bg-[#fafbfc]" style={{ left: MAIN_X }}>
      {/* Header */}
      <header
        className="absolute inset-x-0 top-0 flex items-center gap-x-4 border-b border-ink-100 bg-white px-6"
        style={{ height: LIVE_HEADER_H }}
      >
        <span className={recording ? "text-red-500" : "text-ink-700"}>
          <Face size={30} frame={frame} mood={recording ? "listening" : "idle"} level={level} blinkAt={[B(12.6), B(16.4)]} />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-semibold text-ink-900">Familia Romero · 28 sept</h1>
          <p className="text-xs text-ink-400">Directora, Orientadora (DOE), Mamá de Pedro</p>
        </div>
        <div className="font-mono text-lg tabular-nums text-ink-700">{fmt(elapsed)}</div>
        {recording && (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-600"
            style={rec.style}
          >
            <span
              className="h-2 w-2 rounded-full bg-red-500"
              style={{ opacity: 0.35 + 0.65 * (0.5 + 0.5 * Math.cos(((frame - CLICK.iniciar) / 96) * Math.PI * 2)) }}
            />
            Grabando
          </span>
        )}
      </header>

      {/* Antes de empezar */}
      {pre.visible && (
        <div className="absolute inset-x-0 bottom-0" style={{ top: LIVE_HEADER_H, ...pre.style }}>
          <div className="absolute flex flex-col items-center text-center" style={{ left: MAIN_CX - MAIN_X - 224, width: 448, top: 36 }}>
            <span className="text-ink-300">
              <Face size={64} frame={frame} blinkAt={[B(8.6)]} />
            </span>
            <h2 className="mt-5 text-lg font-semibold text-ink-900">Todo listo para empezar</h2>
            <p className="mt-1 text-sm text-ink-500">
              Asegurate de que los participantes sepan que la reunión está siendo transcripta.
            </p>
            <div className="mt-6 w-full space-y-3 rounded-2xl border border-ink-100 bg-white p-5 text-left shadow-sm">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-ink-700">Micrófono</span>
                <div className="flex w-full items-center gap-2 rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm">
                  <span className="flex-1 text-ink-900">Micrófono predeterminado</span>
                  <svg width={14} height={14} viewBox="0 0 16 16" fill="none" className="text-ink-400">
                    <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              </label>
              <label className="flex items-start gap-2 text-sm text-ink-600">
                <span className="mt-0.5 h-4 w-4 shrink-0 rounded border border-ink-300 bg-white" />
                <span>
                  Grabar el audio completo
                  <span className="block text-xs text-ink-400">
                    Al terminar lo podés descargar durante 48 horas; después se borra.
                  </span>
                </span>
              </label>
              <div className="border-t border-ink-100 pt-3">
                <span className="mb-1.5 block text-sm font-medium text-ink-700">Motor de transcripción</span>
                <label className="flex items-start gap-2 text-sm text-ink-600">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-ink-900">
                    <span className="h-2 w-2 rounded-full bg-ink-900" />
                  </span>
                  <span>
                    Motor cloud
                    <span className="block text-xs text-ink-400">(envía temporalmente el audio al proveedor configurado)</span>
                  </span>
                </label>
              </div>
            </div>
          </div>
          <Button
            className="absolute !py-3 text-base"
            style={{
              left: INICIAR.x - MAIN_X - INICIAR.w / 2,
              top: INICIAR.y - LIVE_HEADER_H - INICIAR.h / 2,
              width: INICIAR.w,
              height: INICIAR.h,
              transform: `scale(${pressScale(frame, CLICK.iniciar)})`,
            }}
          >
            Iniciar reunión
          </Button>
        </div>
      )}

      {/* Grabando: transcript */}
      {recording && (
        <div className="absolute" style={{ left: LIVE_TEXT_X - MAIN_X, width: LIVE_TEXT_W, top: LIVE_HEADER_H + 24, ...rec.style }}>
          <div className="space-y-4">
            {LIVE_LINES.map((line, index) => {
              if (frame < line.partial) return null;
              const final = frame >= line.final;
              const show = presence(frame, line.partial, Infinity, 8);
              return (
                <div key={index} style={show.style}>
                  {final && (
                    <div className="mb-0.5 flex items-baseline gap-2 text-xs text-ink-400">
                      <span className="font-mono tabular-nums">{fmt(line.ms)}</span>
                    </div>
                  )}
                  <p className={`leading-relaxed ${final ? "text-ink-900" : "text-ink-400"}`}>
                    {final ? line.text : line.text.slice(0, Math.ceil(line.text.length * 0.62)) + "…"}
                  </p>
                </div>
              );
            })}
            {LIVE_LINES.every((line) => frame < line.partial || frame >= line.final) && (
              <p className="text-sm text-ink-300">
                <span style={{ opacity: 0.35 + 0.65 * (0.5 + 0.5 * Math.cos((frame / 96) * Math.PI * 2)) }}>●</span>{" "}
                escuchando…
              </p>
            )}
          </div>
        </div>
      )}

      {/* Panel lateral */}
      {recording && (
        <aside
          className="absolute flex flex-col border-l border-ink-100 bg-white p-5"
          style={{ left: LIVE_ASIDE_X - MAIN_X, right: 0, top: LIVE_HEADER_H, bottom: 720 - LIVE_FOOTER_Y, ...rec.style }}
        >
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-400">Echo está detectando</h3>
          <ul className="space-y-2 text-sm">
            {[
              { label: "Decisiones", value: frame >= B(14.5) ? 1 : 0 },
              { label: "Tareas", value: frame >= B(15) ? 1 : 0 },
              { label: "Preguntas", value: 0 },
            ].map((item) => (
              <li key={item.label} className="flex justify-between text-ink-700">
                <span>{item.label}</span>
                <span className="font-semibold">{item.value}</span>
              </li>
            ))}
          </ul>
          <div className="mt-auto space-y-1.5 border-t border-ink-100 pt-4 text-[11px] text-ink-400">
            <p><kbd className="rounded border border-ink-200 px-1">M</kbd> marcar momento</p>
            <p><kbd className="rounded border border-ink-200 px-1">N</kbd> nota</p>
            <p><kbd className="rounded border border-ink-200 px-1">D</kbd> decisión</p>
            <p><kbd className="rounded border border-ink-200 px-1">T</kbd> tarea</p>
          </div>
        </aside>
      )}

      {/* Pie de acciones */}
      {recording && (
        <footer
          className="absolute inset-x-0 bottom-0 border-t border-ink-100 bg-white"
          style={{ top: LIVE_FOOTER_Y, ...rec.style }}
        >
          <div className="absolute flex h-6 items-end gap-0.5" style={{ left: FOOTER_START - MAIN_X, top: 18 }}>
            {[0.3, 0.6, 1, 0.75, 0.45].map((weight, index) => (
              <span
                key={index}
                className="w-1 rounded-full bg-accent-500"
                style={{ height: `${Math.max(12, Math.min(100, level * 100 * weight + 10 + 18 * Math.sin(frame / 4 + index)))}%` }}
              />
            ))}
          </div>
          {(() => {
            let x = FOOTER_START - MAIN_X + 48;
            return FOOTER_BUTTONS.map((button) => {
              const left = x;
              x += button.w + 8;
              const click = button.id === "momento" ? CLICK.momento : button.id === "finalizar" ? CLICK.finalizar : -99;
              return (
                <Button
                  key={button.id}
                  variant={button.variant}
                  className="absolute"
                  style={{
                    left,
                    top: 12,
                    width: button.w,
                    transform: `scale(${pressScale(frame, click)})`,
                    backgroundColor:
                      button.id === "momento" && frame >= CLICK.momento && frame < CLICK.momento + 40
                        ? `rgba(236,238,242,${1 - ramp(frame, CLICK.momento + 16, CLICK.momento + 40)})`
                        : undefined,
                  }}
                >
                  {button.label}
                </Button>
              );
            });
          })()}
        </footer>
      )}
    </div>
  );
}
