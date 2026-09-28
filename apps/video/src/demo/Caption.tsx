import { Easing, interpolate } from "remotion";
import { CAPTIONS } from "./timeline";

/**
 * Copy de dos tonos arriba de la superficie, como en la demo de Testra: cada
 * palabra entra con un blur corto; quieto, el texto queda nítido.
 */
export function Captions({ frame }: { frame: number }) {
  return (
    <>
      {CAPTIONS.map((caption) => {
        if (frame < caption.from || frame > caption.to + 12) return null;
        const out = interpolate(frame, [caption.to, caption.to + 12], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={caption.from}
            className="absolute inset-x-0 flex justify-center gap-[0.26em] text-[54px] font-semibold tracking-[-0.02em]"
            style={{ top: 64, lineHeight: "72px" }}
          >
            {caption.words.map((word, index) => {
              const t = interpolate(frame, [caption.from + index * 3, caption.from + index * 3 + 14], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
                easing: Easing.out(Easing.cubic),
              });
              const visible = t * (1 - out);
              const blur = (1 - t) * 10 + out * 8;
              return (
                <span
                  key={index}
                  className={word.accent ? "text-accent-600" : "text-ink-900"}
                  style={{
                    opacity: visible,
                    filter: blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : undefined,
                    transform: `translateY(${(1 - t) * 10 - out * 6}px)`,
                  }}
                >
                  {word.text}
                </span>
              );
            })}
          </div>
        );
      })}
    </>
  );
}
