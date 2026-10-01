import { useEffect, useRef, useState } from "react";
import { EchoFace } from "./EchoFace";

/**
 * La mascota de Echo en la conversación por voz: el orbe de vidrio líquido
 * (videos renderizados por código). Cuatro clips que empiezan y terminan en el
 * mismo orbe quieto, así que se pasa de uno a otro con un fundido sin saltos:
 *   idle       → los ojos (primer cuadro de la activación)
 *   activation → los ojos se funden en el orbe (una vez, después "listening")
 *   listening  → ondas mientras la persona habla
 *   thinking   → hilos de luz girando (conectando, buscando en las reuniones)
 *   speaking   → las barras que bailan con la voz de Echo
 *
 * Transparencia en todos los navegadores (también Safari, que no reproduce el
 * alfa de WebM): cada mp4 trae la imagen a la izquierda y su transparencia a
 * la derecha ("_alpha.mp4"). Se componen en la GPU (WebGL): antes se armaba
 * píxel por píxel en JavaScript 60 veces por segundo y el iPhone se calentaba
 * (docs/plan-correcciones.md §4.12). Ahora:
 * - se dibuja solo cuando el video tiene un cuadro nuevo
 *   (requestVideoFrameCallback), y nada si está pausado;
 * - los videos se pausan si la pestaña o la mascota no se ven;
 * - el recorte del orbe se hace en el shader, a la resolución de la pantalla
 *   (antes un canvas de 480 px agrandado con CSS: se veía borroso en retina).
 *
 * iPhone: Safari solo deja reproducir un video sin un toque si tiene el
 * atributo `muted` en el HTML, no los carga por adelantado y no reproduce los
 * que no se ven. Si no se puede dibujar nada (sin WebGL), quedan los ojos de
 * Echo de siempre: nunca un hueco.
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
// En el video el orbe ocupa el centro del cuadro: se muestra esta fracción.
const CROP = 1 / 1.45;

const VERTEX = `
attribute vec2 position;
varying vec2 uv;
void main() {
  uv = vec2(position.x * 0.5 + 0.5, 0.5 - position.y * 0.5);
  gl_Position = vec4(position, 0.0, 1.0);
}`;

// Izquierda: color ya premultiplicado; derecha: la transparencia. La salida
// queda premultiplicada, que es lo que espera el canvas.
const FRAGMENT = `
precision mediump float;
uniform sampler2D frame;
uniform float crop;
varying vec2 uv;
void main() {
  vec2 p = 0.5 + (uv - 0.5) * crop;
  vec3 color = texture2D(frame, vec2(p.x * 0.5, p.y)).rgb;
  float alpha = texture2D(frame, vec2(0.5 + p.x * 0.5, p.y)).r;
  gl_FragColor = vec4(color * step(0.015, alpha), alpha);
}`;

type Renderer = (video: HTMLVideoElement) => boolean;

function createRenderer(canvas: HTMLCanvasElement): Renderer | null {
  const gl = canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true, antialias: false });
  if (!gl) return null;
  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type)!;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    return shader;
  };
  const program = gl.createProgram()!;
  gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, "position");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.uniform1f(gl.getUniformLocation(program, "crop"), CROP);
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return (video) => {
    if (video.readyState < 2 || !video.videoWidth) return false;
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return true;
  };
}

/** Lo que iOS necesita para reproducir sin un toque y dentro de la página. */
function prepareVideo(video: HTMLVideoElement) {
  video.muted = true;
  video.defaultMuted = true;
  video.setAttribute("muted", "");
  video.setAttribute("playsinline", "");
  video.setAttribute("webkit-playsinline", "");
}

type FrameVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: () => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

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
  const root = useRef<HTMLDivElement | null>(null);
  const videos = useRef<Partial<Record<Clip, FrameVideo | null>>>({});
  const canvases = useRef<Partial<Record<Clip, HTMLCanvasElement | null>>>({});
  const renderers = useRef<Partial<Record<Clip, Renderer | null>>>({});
  const clip: Clip = state === "idle" ? "activation" : state;
  const clipRef = useRef(clip);
  clipRef.current = clip;
  const [painted, setPainted] = useState(false);
  const [fallback, setFallback] = useState(false);
  const paintedRef = useRef(false);
  // Se ve (pestaña al frente y la mascota en pantalla): si no, todo en pausa.
  const [visible, setVisible] = useState(true);
  const lastPlayed = useRef<Clip | null>(null);
  const pixels = Math.round(size * Math.min(2, typeof window === "undefined" ? 1 : window.devicePixelRatio || 1));

  const draw = (name: Clip) => {
    const video = videos.current[name];
    const canvas = canvases.current[name];
    if (!video || !canvas) return;
    if (renderers.current[name] === undefined) renderers.current[name] = createRenderer(canvas);
    const render = renderers.current[name];
    if (render && render(video) && !paintedRef.current) {
      paintedRef.current = true;
      setPainted(true);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => setFallback(!paintedRef.current), 2500);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", update);
    let observer: IntersectionObserver | null = null;
    if (root.current && "IntersectionObserver" in window) {
      observer = new IntersectionObserver(([entry]) =>
        setVisible(entry.isIntersecting && document.visibilityState === "visible"),
      );
      observer.observe(root.current);
    }
    return () => {
      document.removeEventListener("visibilitychange", update);
      observer?.disconnect();
    };
  }, []);

  // Cada video se dibuja cuando tiene un cuadro nuevo; pausado, no cuesta nada.
  useEffect(() => {
    const stops: (() => void)[] = [];
    for (const name of ORDER) {
      const video = videos.current[name];
      if (!video) continue;
      if (video.requestVideoFrameCallback) {
        let handle = 0;
        const onFrame = () => {
          draw(name);
          handle = video.requestVideoFrameCallback!(onFrame);
        };
        handle = video.requestVideoFrameCallback(onFrame);
        stops.push(() => video.cancelVideoFrameCallback?.(handle));
      } else {
        let frame = 0;
        const loop = () => {
          if (!video.paused) draw(name);
          frame = requestAnimationFrame(loop);
        };
        const play = () => {
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(loop);
        };
        const pause = () => cancelAnimationFrame(frame);
        video.addEventListener("play", play);
        video.addEventListener("pause", pause);
        stops.push(() => {
          pause();
          video.removeEventListener("play", play);
          video.removeEventListener("pause", pause);
        });
      }
    }
    return () => stops.forEach((stop) => stop());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    for (const name of ORDER) {
      const video = videos.current[name];
      if (!video) continue;
      if (name === clip && visible) {
        if (state === "idle" || reduce) {
          // El primer cuadro (los ojos) igual se dibuja. iOS no carga el video
          // hasta que se reproduce: play y pausa en el primer cuadro.
          const show = () => draw(name);
          video.currentTime = 0;
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
          // Cada clip arranca en el orbe quieto: desde el principio empalma. Al
          // volver a la pestaña, en cambio, sigue de donde estaba.
          if (lastPlayed.current !== name) video.currentTime = 0;
          lastPlayed.current = name;
          void video.play().catch(() => {});
        }
      } else if (!visible) {
        video.pause();
      } else {
        // El que se va termina de desvanecerse antes de pausarse.
        window.setTimeout(() => {
          if (name !== clipRef.current) video.pause();
        }, 450);
      }
    }
  }, [clip, state, visible]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={root} className="relative" style={{ width: size, height: size }} aria-hidden>
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
              videos.current[name] = element as FrameVideo | null;
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
            width={pixels}
            height={pixels}
            className="absolute inset-0 h-full w-full transition-opacity duration-[450ms] ease-out"
            style={{ opacity: name === clip ? 1 : 0 }}
          />
        </div>
      ))}
    </div>
  );
}
