import { presence } from "../anim";
import { TILE } from "../camera";
import { ACT, B } from "../timeline";

/** Cierre: el ícono de Echo (el favicon) con la marca y el tagline del README. */
export function LogoLockup({ frame }: { frame: number }) {
  // Entra cuando el ícono ya llegó a su lugar: nunca se pisan.
  const word = presence(frame, ACT.logo + 32, ACT.loop - 4, 14, 12);
  const tagline = presence(frame, B(74.5), ACT.loop - 8, 14, 12);
  if (!word.visible && !tagline.visible) return null;
  const [x, y, w, h] = TILE;
  return (
    <>
      <div
        className="absolute text-[80px] font-semibold tracking-[-0.03em] text-ink-900"
        style={{ left: x + w + 26, top: y + h / 2 - 50, lineHeight: "100px", ...word.style }}
      >
        Echo
      </div>
      <p
        className="absolute inset-x-0 text-center text-[30px] text-ink-500"
        style={{ top: y + h + 44, ...tagline.style }}
      >
        La reunión termina. <span className="text-ink-900">Echo recuerda.</span>
      </p>
    </>
  );
}
