import { B } from "../timeline";
import { ramp, typed } from "../anim";

/** El problema: alguien escribe apurado mientras los demás hablan. 293×360. */
const LINES: { text: string; from: number; to: number; strike?: [number, number] }[] = [
  { text: "Reunión flia. Romero — 28/9", from: 10, to: 44 },
  { text: "• Pedro: problemas en recreos", from: 48, to: 80 },
  { text: "• mamá: “no quiere venir”", from: 84, to: 112 },
  { text: "• ¿quién llama? dire / DOE", from: 116, to: 140, strike: [16, 20] },
  { text: "• psicopedag… ¿viernes?", from: 144, to: B(5) - 6 },
];

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
          const strikeT = line.strike ? ramp(frame, line.to + 6, line.to + 16) : 0;
          return (
            <div key={index} className="relative flex h-9 items-end border-b border-ink-100 pb-1.5">
              <span className={`text-[15px] ${index === 0 ? "font-medium text-ink-800" : "text-ink-600"}`}>
                {line.strike && shown.length > line.strike[0] ? (
                  <>
                    {shown.slice(0, line.strike[0])}
                    <span className="relative">
                      {shown.slice(line.strike[0], line.strike[1])}
                      <span
                        className="absolute left-0 top-1/2 h-px bg-ink-500"
                        style={{ width: `${strikeT * 100}%` }}
                      />
                    </span>
                    {shown.slice(line.strike[1])}
                  </>
                ) : (
                  shown
                )}
                {index === current && frame >= line.from && (
                  <span className="ml-px inline-block h-4 w-px translate-y-0.5 bg-ink-800" style={{ opacity: caretOn ? 1 : 0 }} />
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
