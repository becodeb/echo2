import { B } from "../timeline";
import { ramp, typed } from "../anim";

/**
 * El problema: alguien escribe apurado mientras los demás hablan. Cuando
 * entra "Con Echo, nadie más.", cada renglón se tacha: ya no hace falta.
 * 293×360.
 */
export const LINES: { text: string; from: number; to: number }[] = [
  { text: "Reunión flia. Romero — 28/9", from: 6, to: 26 },
  { text: "• Pedro: problemas en recreos", from: 28, to: 48 },
  { text: "• mamá: “no quiere venir”", from: 50, to: 68 },
  { text: "• ¿quién llama? dire / DOE", from: 70, to: 88 },
  { text: "• psicopedag… ¿viernes?", from: 90, to: B(3) - 2 },
];
/** Se tacha un renglón cada 5 frames desde que cambia el copy. */
export const STRIKE_FROM = B(3.4);

export function Notes({ frame }: { frame: number }) {
  const caretOn = Math.floor(frame / 16) % 2 === 0;
  const current = LINES.findIndex((line) => frame < line.to);
  return (
    <div className="h-full w-full bg-white px-6 pt-6">
      <div className="mb-4 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-ink-400">Notas</span>
        <span className="font-mono text-xs text-ink-300">10:32</span>
      </div>
      <div className="space-y-0">
        {LINES.map((line, index) => {
          const shown = typed(line.text, frame, line.from, line.to);
          const strike = ramp(frame, STRIKE_FROM + index * 5, STRIKE_FROM + index * 5 + 10);
          return (
            <div key={index} className="relative flex h-9 items-end border-b border-ink-100 pb-1.5">
              <span
                className={`relative text-[15px] ${index === 0 ? "font-medium" : ""}`}
                style={{ color: strike > 0 ? `rgba(100,110,132,${1 - 0.55 * strike})` : index === 0 ? "#23293a" : "#4a5268" }}
              >
                {shown}
                {index === current && frame >= line.from && (
                  <span className="ml-px inline-block h-4 w-px translate-y-0.5 bg-ink-800" style={{ opacity: caretOn ? 1 : 0 }} />
                )}
                {strike > 0 && (
                  <span className="absolute left-0 top-1/2 h-[1.5px] bg-ink-500" style={{ width: `${strike * 100}%` }} />
                )}
              </span>
            </div>
          );
        })}
        {[0, 1, 2].map((index) => (
          <div key={`empty-${index}`} className="h-9 border-b border-ink-100" />
        ))}
      </div>
    </div>
  );
}
