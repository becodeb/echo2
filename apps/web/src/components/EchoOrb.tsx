import { useEffect, useRef, useState } from "react";
import { EchoFace } from "./EchoFace";

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
 *
 * iPhone: Safari solo deja reproducir un video sin un toque si tiene el
 * atributo `muted` en el HTML (React pone la propiedad, no el atributo), no
 * los carga por adelantado (para mostrar el primer cuadro hay que darle play y
 * pausarlo) y no reproduce los que no se ven. Si igual no se dibuja nada, quedan
 * los ojos de Echo de siempre: nunca un hueco.
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
function drawFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement): boolean {
  if (video.readyState < 2 || !video.videoWidth) return false;
  const source = scratchContext();
  const target = canvas.getContext("2d");
  if (!source || !target) return false;
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
  return true;
}

/** Lo que iOS necesita para reproducir sin un toque y dentro de la página. */
function prepareVideo(video: HTMLVideoElement) {
  video.muted = true;
  video.defaultMuted = true;
  video.setAttribute("muted", "");
  video.setAttribute("playsinline", "");
  video.setAttribute("webkit-playsinline", "");
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
  // Si en un rato no se pudo dibujar ningún cuadro, se muestran los ojos de siempre.
  const [painted, setPainted] = useState(false);
  const [fallback, setFallback] = useState(false);
  const paintedRef = useRef(false);

  const draw = (name: Clip) => {
    const video = videos.current[name];
    const canvas = canvases.current[name];
    if (video && canvas && drawFrame(video, canvas) && !paintedRef.current) {
      paintedRef.current = true;
      setPainted(true);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => setFallback(!paintedRef.current), 2500);
    return () => window.clearTimeout(timer);
  }, []);

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
          // El primer cuadro (los ojos) igual se dibuja. iOS no carga el video
          // hasta que se reproduce: play y pausa en el primer cuadro.
          const show = () => draw(name);
          video.addEventListener("seeked", show, { once: true });
          video.addEventListener("loadeddata", show, { once: true });
          if (video.readyState >= 2) {
            video.pause();
            window.setTimeout(show, 30);
          } else {
            void video
              .play()
              .then(() => {
                if (clipRef.current !== name || state !== "idle") return;
                video.pause();
                video.currentTime = 0;
                show();
              })
              .catch(() => {});
          }
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
      {fallback && !painted && (
        <span className="absolute inset-0 flex items-center justify-center text-ink-900">
          <EchoFace mood={state === "thinking" ? "thinking" : state === "listening" ? "listening" : "idle"} size={size / 3} />
        </span>
      )}
      {ORDER.map((name) => (
        <div key={name}>
          <video
            ref={(element) => {
              if (element) prepareVideo(element);
              videos.current[name] = element;
            }}
            src={CLIPS[name]}
            muted
            playsInline
            preload="auto"
            loop={name !== "activation"}
            onEnded={name === "activation" ? onActivated : undefined}
            // Casi transparente y en el centro, tapado por el orbe: iOS no
            // reproduce los videos que considera invisibles (opacidad 0). Lo
            // que se ve es el canvas.
            className="pointer-events-none absolute left-1/2 top-1/2 h-[2px] w-[2px] opacity-[0.01]"
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
