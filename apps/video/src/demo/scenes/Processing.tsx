import { interpolate } from "remotion";
import { presence } from "../anim";
import { MAIN_X } from "../layout";
import { STAGES } from "../timeline";
import { Face } from "../ui/Face";

/** Pantalla post-Finalizar de MeetingLive: una etapa por golpe. */
export function Processing({ frame }: { frame: number }) {
  const current = STAGES.reduce((index, stage, i) => (frame >= stage.at ? i : index), 0);
  const progress = interpolate(
    frame,
    STAGES.map((stage) => stage.at),
    STAGES.map((stage) => stage.progress),
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return (
    <div className="absolute inset-y-0 right-0 flex flex-col items-center justify-center gap-6 bg-[#fafbfc] px-6" style={{ left: MAIN_X }}>
      <span className="text-ink-700">
        <Face mood="thinking" size={72} frame={frame} />
      </span>
      <div className="relative h-14 w-full text-center">
        {STAGES.map((stage, index) => {
          const next = STAGES[index + 1];
          const shown = presence(frame, stage.at, next ? next.at : Infinity, 10, 8);
          if (!shown.visible || Math.abs(index - current) > 1) return null;
          return (
            <div key={stage.label} className="absolute inset-x-0 top-0" style={shown.style}>
              <h2 className="text-xl font-semibold text-ink-900">{stage.label}</h2>
            </div>
          );
        })}
        <p className="absolute inset-x-0 top-8 mt-1 text-sm text-ink-500">Familia Romero · 28 sept</p>
      </div>
      <div className="h-1.5 w-64 overflow-hidden rounded-full bg-ink-100">
        <div className="h-full rounded-full bg-accent-500" style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}
