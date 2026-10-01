import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { VoiceConversation } from "@elevenlabs/client";
import { api } from "../api/client";
import { useBilling } from "./billing";
import { Modal, Spinner } from "./ui";

interface SessionOut {
  signed_url: string;
  max_seconds: number;
  seconds_left: number | null;
  user_name: string;
}

type Phase = "idle" | "connecting" | "listening" | "speaking" | "ending" | "error";

/** Lo que la IA escribió para leer, dicho en voz alta: sin markdown ni citas [1]. */
function forSpeech(text: string): string {
  return text
    .replace(/\[\d+\]/g, "")
    .replace(/[*_#>`]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function clock(seconds: number): string {
  const safe = Math.max(0, Math.round(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

/**
 * Conversación por voz con Echo (plan Individual + voz). El navegador habla
 * con el agente de ElevenLabs por una URL firmada que da el servidor; cuando
 * el agente necesita algo de las reuniones, llama a `consultar_reuniones`, que
 * se resuelve acá con el mismo "Preguntale a Echo" (y su seudonimización).
 */
export function VoiceChatButton() {
  const { data: billing } = useBilling();
  const [open, setOpen] = useState(false);
  if (!billing) return null;
  if (!billing.features.voice) {
    return (
      <Link
        to="/plans"
        className="inline-flex items-center gap-2 rounded-full border border-ink-200 bg-white px-3.5 py-1.5 text-sm font-medium text-ink-600 transition-colors hover:border-ink-300 hover:text-ink-900"
      >
        <MicIcon /> Hablale a Echo con el plan + voz
      </Link>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-full bg-ink-900 px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-ink-700 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
      >
        <MicIcon /> Hablar con Echo
      </button>
      {open && <VoiceChat onClose={() => setOpen(false)} />}
    </>
  );
}

export function VoiceChat({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [level, setLevel] = useState(0);
  const [lastLine, setLastLine] = useState<string>("");
  const conversation = useRef<VoiceConversation | null>(null);
  const started = useRef<number>(0);
  const conversationId = useRef<string | null>(null);

  const finish = async () => {
    const current = conversation.current;
    conversation.current = null;
    if (!current) return;
    setPhase("ending");
    await current.endSession().catch(() => undefined);
  };

  const report = async () => {
    const id = conversationId.current;
    conversationId.current = null;
    if (!id) return;
    const seconds = (Date.now() - started.current) / 1000;
    await api("/api/voice/sessions/end", {
      method: "POST",
      body: JSON.stringify({ conversation_id: id, seconds }),
    }).catch(() => undefined);
    queryClient.invalidateQueries({ queryKey: ["billing"] });
    queryClient.invalidateQueries({ queryKey: ["usage"] });
  };

  const start = async () => {
    setError(null);
    setPhase("connecting");
    try {
      // Primero el micrófono: sin permiso no tiene sentido abrir la conversación.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      const session = await api<SessionOut>("/api/voice/sessions", { method: "POST" });
      const { Conversation } = await import("@elevenlabs/client");
      const voice = (await Conversation.startSession({
        signedUrl: session.signed_url,
        connectionType: "websocket",
        dynamicVariables: { user_name: session.user_name },
        clientTools: {
          consultar_reuniones: async ({ pregunta }: { pregunta: string }) => {
            try {
              const answer = await api<{ answer: string }>("/api/ask", {
                method: "POST",
                body: JSON.stringify({ question: String(pregunta ?? "").slice(0, 2000), history: [] }),
              });
              return forSpeech(answer.answer).slice(0, 3000);
            } catch {
              return "No pude consultar las reuniones en este momento.";
            }
          },
        },
        onConnect: ({ conversationId: id }) => {
          conversationId.current = id;
          started.current = Date.now();
          setRemaining(session.max_seconds);
          setPhase("listening");
        },
        onModeChange: ({ mode }) => setPhase(mode === "speaking" ? "speaking" : "listening"),
        onMessage: ({ message, source }) => {
          // Sin las marcas de expresión de la voz ("[curious]", "[warm]").
          if (source === "ai") setLastLine(message.replace(/\[[a-z ]+\]\s*/gi, "").trim());
        },
        onDisconnect: () => {
          void report();
          setPhase("idle");
          setLevel(0);
          setRemaining(null);
        },
        onError: (message) => {
          setError(typeof message === "string" ? message : "Se cortó la conversación.");
        },
      })) as VoiceConversation;
      conversation.current = voice;
    } catch (caught) {
      setPhase("error");
      setError(
        caught instanceof DOMException
          ? "Echo necesita permiso para usar el micrófono."
          : caught instanceof Error
            ? caught.message
            : "No se pudo conectar.",
      );
    }
  };

  // Volumen para el orbe y cuenta regresiva de los minutos que quedan.
  useEffect(() => {
    if (phase !== "listening" && phase !== "speaking") return;
    let frame = 0;
    const tick = () => {
      const current = conversation.current;
      if (current) {
        const volume = phase === "speaking" ? current.getOutputVolume() : current.getInputVolume();
        setLevel((previous) => previous * 0.7 + Math.min(1, volume * 2.2) * 0.3);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    const timer = window.setInterval(() => {
      setRemaining((value) => {
        if (value == null) return value;
        if (value <= 1) {
          void finish();
          return 0;
        }
        return value - 1;
      });
    }, 1000);
    return () => {
      cancelAnimationFrame(frame);
      window.clearInterval(timer);
    };
  }, [phase]);

  // Cerrar la ventana corta la conversación.
  useEffect(() => () => void finish(), []);

  const active = phase === "listening" || phase === "speaking";
  const label = {
    idle: "Tocá para empezar",
    connecting: "Conectando…",
    listening: "Te escucho",
    speaking: "Echo está hablando",
    ending: "Cortando…",
    error: "No se pudo conectar",
  }[phase];

  return (
    <Modal
      open
      onClose={() => {
        void finish();
        onClose();
      }}
      title="Hablar con Echo"
    >
      <div className="flex flex-col items-center gap-6 py-4 text-center">
        <button
          type="button"
          onClick={() => (active ? void finish() : phase === "idle" || phase === "error" ? void start() : undefined)}
          aria-label={active ? "Terminar la conversación" : "Empezar a hablar"}
          className="relative flex h-44 w-44 items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-500"
        >
          {/* Anillos que respiran con la voz: del micrófono al escuchar, de Echo al hablar. */}
          <span
            aria-hidden
            className={`absolute inset-0 rounded-full transition-colors duration-500 ${phase === "speaking" ? "bg-accent-500/15" : "bg-ink-900/[0.06]"}`}
            style={{ transform: `scale(${1 + level * 0.28})`, transition: "transform 90ms linear, background-color 500ms" }}
          />
          <span
            aria-hidden
            className={`absolute inset-5 rounded-full transition-colors duration-500 ${phase === "speaking" ? "bg-accent-500/25" : "bg-ink-900/10"}`}
            style={{ transform: `scale(${1 + level * 0.16})`, transition: "transform 90ms linear, background-color 500ms" }}
          />
          <span
            className={`relative flex h-24 w-24 items-center justify-center rounded-full text-white shadow-[0_12px_30px_-10px_rgba(20,24,36,0.55)] transition-colors duration-500 ${
              phase === "speaking" ? "bg-accent-600" : "bg-ink-900"
            }`}
          >
            {phase === "connecting" || phase === "ending" ? <Spinner className="h-6 w-6" /> : active ? <StopIcon /> : <MicIcon size={28} />}
          </span>
        </button>
        <div aria-live="polite">
          <p className="text-base font-semibold text-ink-900">{label}</p>
          {remaining != null && (
            <p className="mt-1 text-xs tabular-nums text-ink-400">Quedan {clock(remaining)} en esta conversación</p>
          )}
        </div>
        {lastLine && active && (
          <p key={lastLine} className="animate-fade-up max-w-sm text-sm leading-relaxed text-ink-500">
            {lastLine}
          </p>
        )}
        {error && <p className="max-w-sm text-sm text-red-600">{error}</p>}
        <p className="max-w-sm text-xs leading-relaxed text-ink-400">
          Preguntale por tus reuniones, tus tareas o lo que se acordó. Echo solo consulta: no cambia nada. La voz pasa
          por ElevenLabs y los minutos se descuentan de tu plan.
        </p>
      </div>
    </Modal>
  );
}

function MicIcon({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden>
      <rect x="7" y="7" width="10" height="10" rx="2.5" fill="currentColor" />
    </svg>
  );
}
