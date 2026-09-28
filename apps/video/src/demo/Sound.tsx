import { Audio, Sequence, staticFile } from "remotion";
import { LINES } from "./scenes/Notes";
import { ACT, CLAIMS_AT, CLICK, QUESTION, TYPE_END, TYPE_START } from "./timeline";

/**
 * Efectos de sonido (public/sfx, generados con scripts/sfx.py). Cada uno se
 * dispara en el frame exacto de lo que se ve: el click cuando el botón se
 * hunde, una tecla por letra, un tic por afirmación verificada, un soplo
 * cuando la superficie se transforma. Frames relativos a la demo.
 */
type Hit = { at: number; src: string; volume: number };

const KEYS = ["key1", "key2", "key3", "key4"];
// Variación fija (sin azar en el render): cada tecla suena un poco distinta.
const keyHit = (at: number, index: number, base: number): Hit => ({
  at,
  src: `sfx/${KEYS[(index * 7 + 3) % KEYS.length]}.wav`,
  volume: base * (0.8 + 0.2 * (((index * 37) % 11) / 10)),
});

const typing = (text: string, from: number, to: number, base: number, every = 1): Hit[] => {
  const hits: Hit[] = [];
  for (let index = 0; index < text.length; index += every) {
    if (text[index] === " ") continue;
    hits.push(keyHit(Math.round(from + ((to - from) * (index + 1)) / text.length), index, base));
  }
  return hits;
};

export const HITS: Hit[] = [
  // La libreta: alguien escribe apurado (una tecla cada dos letras, bajito).
  ...LINES.flatMap((line, i) => typing(line.text, line.from, line.to, 0.16, 2).map((hit) => ({ ...hit, at: hit.at + i }))),
  // Preguntale a Echo: letra por letra.
  ...typing(QUESTION, TYPE_START, TYPE_END, 0.24),
  // Clicks.
  ...Object.values(CLICK).map((at) => ({ at, src: "sfx/click.wav", volume: 0.62 })),
  // Cada afirmación verificada.
  ...CLAIMS_AT.map((at) => ({ at, src: "sfx/tick.wav", volume: 0.3 })),
  // La superficie se transforma.
  ...[ACT.modal, ACT.live, ACT.logo, ACT.loop].map((at) => ({ at: at - 4, src: "sfx/whoosh.wav", volume: 0.5 })),
];

export function SoundEffects() {
  return (
    <>
      {HITS.map((hit, index) => (
        <Sequence key={index} from={hit.at} durationInFrames={40} layout="none">
          <Audio src={staticFile(hit.src)} volume={hit.volume} />
        </Sequence>
      ))}
    </>
  );
}
