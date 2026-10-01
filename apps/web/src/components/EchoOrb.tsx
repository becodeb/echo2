import { useEffect, useRef } from "react";

/**
 * La mascota de Echo en la conversación por voz: el orbe de vidrio líquido
 * (videos renderizados por código, ver Downloads/videos/codigo). Cuatro clips
 * que empiezan y terminan en el mismo orbe quieto, así que se pasa de uno a
 * otro con un fundido sin saltos:
 *   idle       → los ojos (primer cuadro de la activación)
 *   activation → los ojos se funden en el orbe (una vez, después "listening")
 *   listening  → ondas mientras la persona habla
 *   thinking   → hilos de luz girando (conectando, buscando en las reuniones)
 *   speaking   → las barras que bailan con la voz de Echo
 *
 * Transparencia de verdad en todos los navegadores (también Safari, que no
 * reproduce el alfa de WebM): cada mp4 trae la imagen a la izquierda y su
 * transparencia a la derecha ("_alpha.mp4", hechos desde los ProRes con alfa),
 * y acá se arman en un canvas cuadro por cuadro.
 */
export type OrbState = "idle" | "activation" | "listening" | "thinking" | "speaking";

const CLIPS = {
  activation: "/echo-orb/01_activation_alpha.mp4",
  listening: "/echo-orb/02_listening_alpha.mp4",
  thinking: "/echo-orb/03_thinking_alpha.mp4",
  speaking: "/echo-orb/04_speaking_alpha.mp4",
} as const;
type Clip = keyof typeof CLIPS;
const ORDER: Clip[] = ["activation", "listening", "thinking", "speaking"];
const SIDE = 480; // cada mitad del video: 480 × 480

let scratch: HTMLCanvasElement | null = null;
function scratchContext(): CanvasRenderingContext2D | null {
  if (!scratch) {
    scratch = document.createElement("canvas");
    scratch.width = SIDE * 2;
    scratch.height = SIDE;
  }
  return scratch.getContext("2d", { willReadFrequently: true });
}

/** Un cuadro: la mitad izquierda es el color (premultiplicado) y la derecha la transparencia. */
function drawFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement) {
  if (video.readyState < 2) return;
  const source = scratchContext();
  const target = canvas.getContext("2d");
  if (!source || !target) return;
  source.drawImage(video, 0, 0, SIDE * 2, SIDE);
  const both = source.getImageData(0, 0, SIDE * 2, SIDE).data;
  const out = target.createImageData(SIDE, SIDE);
  const pixels = out.data;
  for (let y = 0; y < SIDE; y++) {
    const row = y * SIDE * 8;
    for (let x = 0; x < SIDE; x++) {
      const color = row + x * 4;
      const alpha = both[row + (x + SIDE) * 4];
      const index = (y * SIDE + x) * 4;
      if (alpha < 4) continue;
      const scale = 255 / alpha;
      pixels[index] = Math.min(255, both[color] * scale);
      pixels[index + 1] = Math.min(255, both[color + 1] * scale);
      pixels[index + 2] = Math.min(255, both[color + 2] * scale);
      pixels[index + 3] = alpha;
    }
  }
  target.putImageData(out, 0, 0);
}

export function EchoOrb({
  state,
  onActivated,
  size = 260,
}: {
  state: OrbState;
  // Cuando termina la animación de activación (para pasar a escuchar).
  onActivated?: () => void;
  size?: number;
}) {
  const videos = useRef<Partial<Record<Clip, HTMLVideoElement | null>>>({});
  const canvases = useRef<Partial<Record<Clip, HTMLCanvasElement | null>>>({});
  const clip: Clip = state === "idle" ? "activation" : state;
  const clipRef = useRef(clip);
  clipRef.current = clip;

  const draw = (name: Clip) => {
    const video = videos.current[name];
    const canvas = canvases.current[name];
    if (video && canvas) drawFrame(video, canvas);
  };

  // Mientras un clip se reproduce (o se está desvaneciendo), se dibuja cada cuadro.
  useEffect(() => {
    let frame = 0;
    const loop = () => {
      for (const name of ORDER) {
        const video = videos.current[name];
        if (video && !video.paused) draw(name);
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    for (const name of ORDER) {
      const video = videos.current[name];
      if (!video) continue;
      if (name === clip) {
        // Cada clip arranca en el orbe quieto: desde el principio empalma.
        video.currentTime = 0;
        if (state === "idle" || reduce) {
          video.pause();
          // El primer cuadro (los ojos) igual se dibuja.
          const show = () => draw(name);
          video.addEventListener("seeked", show, { once: true });
          if (video.readyState >= 2) window.setTimeout(show, 30);
          else video.addEventListener("loadeddata", show, { once: true });
        } else {
          void video.play().catch(() => {});
        }
      } else {
        // El que se va termina de desvanecerse antes de pausarse.
        window.setTimeout(() => {
          if (name !== clipRef.current) video.pause();
        }, 450);
      }
    }
  }, [clip, state]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="relative" style={{ width: size, height: size }} aria-hidden>
      {ORDER.map((name) => (
        <div key={name}>
          <video
            ref={(element) => {
              videos.current[name] = element;
            }}
            src={CLIPS[name]}
            muted
            playsInline
            preload="auto"
            loop={name !== "activation"}
            onEnded={name === "activation" ? onActivated : undefined}
            // Fuera de la vista pero "visible", para que el navegador decodifique los cuadros.
            className="pointer-events-none absolute left-0 top-0 h-px w-px opacity-0"
          />
          <canvas
            ref={(element) => {
              canvases.current[name] = element;
            }}
            width={SIDE}
            height={SIDE}
            // En el video el orbe ocupa poco del cuadro: se agranda.
            className="absolute inset-0 h-full w-full scale-[1.45] transition-opacity duration-[450ms] ease-out"
            style={{ opacity: name === clip ? 1 : 0 }}
          />
        </div>
      ))}
    </div>
  );
}
