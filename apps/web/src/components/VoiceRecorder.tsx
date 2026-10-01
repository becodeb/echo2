import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { micErrorMessage } from "../lib/micError";
import { useAuth } from "../state/auth";
import { Spinner } from "./ui";

export interface MyVoice {
  has_sample: boolean;
  duration_ms: number | null;
  recorded_at: string | null;
  prompt_seen?: boolean;
  learn_from_meetings?: boolean;
  learned_count?: number;
  /** "baja" | "ruido": se guardó, pero conviene grabarla de nuevo. */
  warning?: string | null;
}

const SECONDS = 10;

const WARNINGS: Record<string, string> = {
  baja: "Quedó muy baja. Si podés, grabala de nuevo más cerca del micrófono.",
  ruido: "Se escucha mucho ruido de fondo. Si podés, grabala de nuevo en un lugar más tranquilo.",
};

type Stage = "idle" | "recording" | "review" | "saving" | "saved";

/**
 * Grabar "Mi voz" de punta a punta (docs/plan-correcciones.md §7.5): texto
 * para leer (~10 s), medidor de nivel mientras se graba, escucharla antes de
 * guardar, y aviso si quedó baja o con ruido. Se usa en el aviso de
 * bienvenida (sin ir a Ajustes) y en Ajustes → Mi voz.
 */
export function VoiceRecorder({ onSaved, compact = false }: { onSaved?: (voice: MyVoice) => void; compact?: boolean }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<Stage>("idle");
  const [consent, setConsent] = useState(false);
  const [left, setLeft] = useState(SECONDS);
  const [level, setLevel] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const cleanup = useRef<() => void>(() => {});

  useEffect(() => () => cleanup.current(), []);
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  const firstName = (user?.name ?? "").split(" ")[0] || "…";

  const start = async () => {
    setError(null);
    setWarning(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      context.createMediaStreamSource(stream).connect(analyser);
      const buffer = new Float32Array(analyser.fftSize);
      let frame = 0;
      const meter = () => {
        analyser.getFloatTimeDomainData(buffer);
        let sum = 0;
        for (const value of buffer) sum += value * value;
        // Escala cómoda: hablar normal llena más o menos la mitad.
        setLevel(Math.min(1, Math.sqrt(sum / buffer.length) * 6));
        frame = requestAnimationFrame(meter);
      };
      meter();

      const chunks: Blob[] = [];
      const media = new MediaRecorder(stream);
      recorder.current = media;
      const started = Date.now();
      const tick = window.setInterval(() => {
        const remaining = SECONDS - Math.floor((Date.now() - started) / 1000);
        setLeft(Math.max(0, remaining));
        if (remaining <= 0 && media.state === "recording") media.stop();
      }, 250);
      cleanup.current = () => {
        window.clearInterval(tick);
        cancelAnimationFrame(frame);
        stream.getTracks().forEach((track) => track.stop());
        void context.close().catch(() => {});
      };
      media.ondataavailable = (event) => event.data.size && chunks.push(event.data);
      media.onstop = () => {
        cleanup.current();
        setLevel(0);
        const recorded = new Blob(chunks, { type: media.mimeType || "audio/webm" });
        setBlob(recorded);
        setUrl(URL.createObjectURL(recorded));
        setStage("review");
      };
      media.start();
      setLeft(SECONDS);
      setStage("recording");
    } catch (err) {
      setError(micErrorMessage(err));
    }
  };

  const save = async () => {
    if (!blob) return;
    setStage("saving");
    try {
      const form = new FormData();
      const extension = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
      form.append("audio", blob, `voz.${extension}`);
      form.append("consent", "true");
      const voice = await api<MyVoice>("/api/me/voice", { method: "POST", body: form, skipOrg: true });
      setWarning(voice.warning ? WARNINGS[voice.warning] ?? null : null);
      setStage("saved");
      await queryClient.invalidateQueries({ queryKey: ["my-voice"] });
      await queryClient.invalidateQueries({ queryKey: ["my-voice-prompt"] });
      onSaved?.(voice);
    } catch (err) {
      setStage("review");
      setError(err instanceof Error ? err.message : "No se pudo guardar la muestra");
    }
  };

  const again = () => {
    setBlob(null);
    setUrl(null);
    setStage("idle");
  };

  return (
    <div className={`space-y-4 text-left ${compact ? "" : "rounded-3xl border border-ink-100 p-5"}`}>
      {(stage === "idle" || stage === "recording") && (
        <>
          <p className="text-sm text-ink-600">Cuando toques grabar, leé en voz alta, con tu tono normal:</p>
          <blockquote className="rounded-2xl bg-ink-50 px-4 py-3 text-[15px] leading-relaxed text-ink-800">
            «Hola, soy {firstName}. Estoy grabando mi voz para que Echo me reconozca en mis reuniones. Así, en cada
            resumen, va a figurar quién dijo cada cosa.»
          </blockquote>
        </>
      )}

      {stage === "idle" && (
        <>
          <label className="flex items-start gap-3 text-sm text-ink-600">
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
              className="mt-1 h-4 w-4 shrink-0 rounded border-ink-300"
            />
            <span>
              Autorizo a Echo a guardar esta muestra y una huella de mi voz, en su servidor, para reconocerme en las
              reuniones, y a mejorarla con las reuniones donde me reconozca (lo puedo apagar). La puedo borrar cuando
              quiera.
            </span>
          </label>
          <button
            onClick={start}
            disabled={!consent}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-ink-900 px-5 text-sm font-semibold text-white transition-colors hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
          >
            <MicIcon /> Grabar mi voz
          </button>
          {!consent && <p className="text-xs text-ink-400">Marcá la autorización para poder grabar.</p>}
        </>
      )}

      {stage === "recording" && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="recording-dot h-2.5 w-2.5 shrink-0 rounded-full bg-red-500" />
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-ink-100" aria-label="Nivel del micrófono">
              <div
                className={`h-full rounded-full transition-[width] duration-75 ${level < 0.15 ? "bg-amber-400" : "bg-emerald-500"}`}
                style={{ width: `${Math.round(level * 100)}%` }}
              />
            </div>
            <span className="w-10 text-right font-mono text-sm tabular-nums text-ink-600">{left} s</span>
          </div>
          <p className="text-xs text-ink-400">
            {level < 0.15 ? "Te escucho bajito: acercate un poco al micrófono." : "Te escucho bien."}
          </p>
          <button
            onClick={() => recorder.current?.stop()}
            className="inline-flex min-h-11 w-full items-center justify-center rounded-full bg-red-600 px-5 text-sm font-semibold text-white hover:bg-red-700 sm:w-auto"
          >
            Listo
          </button>
        </div>
      )}

      {(stage === "review" || stage === "saving") && url && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-ink-800">Escuchala antes de guardarla:</p>
          <audio src={url} controls className="w-full" />
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              onClick={save}
              disabled={stage === "saving"}
              className="inline-flex min-h-11 flex-1 items-center justify-center rounded-full bg-ink-900 px-5 text-sm font-semibold text-white hover:bg-ink-700 disabled:opacity-50"
            >
              {stage === "saving" ? <Spinner /> : "Guardar mi voz"}
            </button>
            <button
              onClick={again}
              disabled={stage === "saving"}
              className="inline-flex min-h-11 flex-1 items-center justify-center rounded-full bg-ink-100 px-5 text-sm font-semibold text-ink-800 hover:bg-ink-200"
            >
              Grabar de nuevo
            </button>
          </div>
        </div>
      )}

      {stage === "saved" && (
        <div className="space-y-3">
          <p className="rounded-2xl bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
            ¡Listo! Desde la próxima reunión, Echo te reconoce por tu voz.
          </p>
          {warning && (
            <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <span className="min-w-0 flex-1">{warning}</span>
              <button onClick={again} className="min-h-11 rounded-full bg-white px-4 font-medium text-amber-900">
                Grabar de nuevo
              </button>
            </div>
          )}
        </div>
      )}

      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden>
      <rect x="5.5" y="1.5" width="5" height="8.5" rx="2.5" fill="currentColor" />
      <path d="M3 7.5a5 5 0 0 0 10 0M8 12.5V15" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
    </svg>
  );
}
