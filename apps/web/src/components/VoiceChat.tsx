import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { VoiceConversation } from "@elevenlabs/client";
import { api, ApiError } from "../api/client";
import { useBilling } from "./billing";
import { EchoOrb, type OrbState } from "./EchoOrb";
import { micErrorMessage } from "../lib/micError";

interface SessionOut {
  signed_url: string;
  max_seconds: number;
  seconds_left: number | null;
  user_name: string;
  dynamic_variables: Record<string, string>;
}

type Phase = "idle" | "connecting" | "activating" | "listening" | "thinking" | "speaking" | "ending" | "error";

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

/** El error para mostrar: los del micrófono traducidos, los del servidor tal cual. */
function micError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return micErrorMessage(error, "No se pudo conectar.");
}

/**
 * Conversación por voz con Echo (plan Individual + voz). El navegador habla
 * con el agente de ElevenLabs por una URL firmada que da el servidor; cuando
 * el agente necesita algo de las reuniones, llama a `consultar_reuniones`, que
 * se resuelve acá con el mismo "Preguntale a Echo" (con seudonimización y sin
 * las reuniones donde hablan menores).
 */
export function VoiceChatButton() {
  const { data: billing } = useBilling();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
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
      {open && <VoiceChat onClose={close} />}
    </>
  );
}

export function VoiceChat({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [lastLine, setLastLine] = useState("");
  const conversation = useRef<VoiceConversation | null>(null);
  const conversationId = useRef<string | null>(null);
  // Cuándo empezó y cuánto puede durar: el reloj se calcula de acá, no restando de a uno.
  const startedAt = useRef(0);
  const maxSeconds = useRef(0);
  // Se cerró la ventana mientras conectaba: lo que llegue después se corta.
  const closed = useRef(false);
  const toolBusy = useRef(0);

  const report = useCallback(async () => {
    const id = conversationId.current;
    conversationId.current = null;
    if (!id) return;
    // Aunque esto no llegue (pestaña cerrada), el servidor lo anota igual.
    await api("/api/voice/sessions/end", {
      method: "POST",
      body: JSON.stringify({ conversation_id: id, seconds: (Date.now() - startedAt.current) / 1000 }),
    }).catch(() => undefined);
    queryClient.invalidateQueries({ queryKey: ["billing"] });
    queryClient.invalidateQueries({ queryKey: ["usage"] });
  }, [queryClient]);

  const finish = useCallback(async () => {
    const current = conversation.current;
    conversation.current = null;
    if (!current) return;
    setPhase("ending");
    await current.endSession().catch(() => undefined);
  }, []);

  const start = async () => {
    setError(null);
    setPhase("connecting");
    try {
      // Primero el micrófono: sin permiso no tiene sentido abrir la conversación.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      const session = await api<SessionOut>("/api/voice/sessions", { method: "POST" });
      if (closed.current) return;
      const { Conversation } = await import("@elevenlabs/client");
      const voice = (await Conversation.startSession({
        signedUrl: session.signed_url,
        connectionType: "websocket",
        dynamicVariables: session.dynamic_variables,
        clientTools: {
          consultar_reuniones: async ({ pregunta }: { pregunta: string }) => {
            toolBusy.current += 1;
            setPhase("thinking");
            try {
              const answer = await api<{ answer: string }>("/api/ask", {
                method: "POST",
                body: JSON.stringify({ question: String(pregunta ?? "").slice(0, 2000), history: [], voice: true }),
              });
              return forSpeech(answer.answer).slice(0, 3000);
            } catch {
              return "No pude consultar las reuniones en este momento.";
            } finally {
              toolBusy.current -= 1;
            }
          },
        },
        onConnect: ({ conversationId: id }) => {
          conversationId.current = id;
          startedAt.current = Date.now();
          maxSeconds.current = session.max_seconds;
          setRemaining(session.max_seconds);
          setPhase("activating");
        },
        onModeChange: ({ mode }) => {
          if (toolBusy.current > 0) return;
          setPhase((current) => (current === "activating" && mode !== "speaking" ? current : mode === "speaking" ? "speaking" : "listening"));
        },
        onMessage: ({ message, source }) => {
          // Sin las marcas de expresión de la voz ("[curious]", "[warm]").
          if (source === "ai") setLastLine(message.replace(/\[[a-z ]+\]\s*/gi, "").trim());
        },
        onDisconnect: () => {
          void report();
          setPhase("idle");
          setRemaining(null);
        },
        onError: (message) => {
          setError(typeof message === "string" ? message : "Se cortó la conversación.");
        },
      })) as VoiceConversation;
      if (closed.current) {
        // Se cerró la ventana mientras conectaba: no dejar la charla abierta sin pantalla.
        await voice.endSession().catch(() => undefined);
        return;
      }
      conversation.current = voice;
    } catch (caught) {
      if (closed.current) return;
      setPhase("error");
      setError(micError(caught));
    }
  };

  // Reloj: lo que queda se calcula desde que empezó, así no se atrasa.
  useEffect(() => {
    if (remaining == null) return;
    const timer = window.setInterval(() => {
      const left = maxSeconds.current - (Date.now() - startedAt.current) / 1000;
      if (left <= 0) {
        setRemaining(0);
        void finish();
        return;
      }
      setRemaining(left);
    }, 500);
    return () => window.clearInterval(timer);
  }, [remaining == null, finish]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cerrar la ventana corta la conversación (también si todavía estaba conectando).
  useEffect(() => {
    closed.current = false;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => {
      closed.current = true;
      window.removeEventListener("keydown", onKey);
      void finish();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => {
    closed.current = true;
    void finish();
    onClose();
  };

  const active = phase === "activating" || phase === "listening" || phase === "thinking" || phase === "speaking";
  const orb: OrbState =
    phase === "activating"
      ? "activation"
      : phase === "thinking" || phase === "ending"
        ? "thinking"
        : phase === "listening"
          ? "listening"
          : phase === "speaking"
            ? "speaking"
            : "idle";
  const label = {
    idle: "Conectando…",
    connecting: "Conectando…",
    activating: "Hola",
    listening: "Te escucho",
    thinking: "Buscando en tus reuniones…",
    speaking: "Echo está hablando",
    ending: "Cortando…",
    error: "No se pudo conectar",
  }[phase];

  // Aparece y arranca de una: abrir la ventana ya es pedir hablar.
  useEffect(() => {
    void start();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    // Sin fondo oscuro: la mascota aparece sobre la página, apenas velada con
    // el mismo color de la app para que el texto de atrás no se le cruce, y un
    // solo botón para cerrar.
    <div
      className="voice-veil fixed inset-0 z-[60] flex flex-col items-center justify-center bg-ink-50/80 px-6 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label="Hablar con Echo"
    >
      <button
        type="button"
        onClick={close}
        className="absolute right-4 top-[max(1rem,env(safe-area-inset-top))] flex h-10 w-10 items-center justify-center rounded-full border border-ink-200 bg-white text-ink-600 shadow-sm transition-colors hover:text-ink-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
        aria-label="Cerrar"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </button>

      <button
        type="button"
        onClick={() => (phase === "error" ? void start() : undefined)}
        aria-label={phase === "error" ? "Probar de nuevo" : "Echo"}
        className="rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-500"
      >
        <EchoOrb
          size={320}
          state={orb}
          onActivated={() => setPhase((current) => (current === "activating" ? "listening" : current))}
        />
      </button>

      <div aria-live="polite" className="mt-1 flex flex-col items-center gap-2 text-center">
        <p
          key={label}
          className="animate-fade-up rounded-full border border-ink-200/80 bg-white/90 px-4 py-1.5 text-sm font-semibold text-ink-900 shadow-sm backdrop-blur"
        >
          {label}
          {remaining != null && <span className="ml-2 font-normal tabular-nums text-ink-400">{clock(remaining)}</span>}
        </p>
        {active && lastLine && (
          <p
            key={lastLine}
            className="animate-fade-up max-w-md rounded-2xl border border-ink-200/80 bg-white/90 px-4 py-2.5 text-[15px] leading-relaxed text-ink-700 shadow-sm backdrop-blur"
          >
            {lastLine}
          </p>
        )}
        {error && (
          <p role="alert" className="max-w-sm rounded-2xl border border-red-200 bg-white px-4 py-2.5 text-sm text-red-700 shadow-sm">
            {error}{" "}
            <button type="button" onClick={() => void start()} className="font-semibold underline underline-offset-2">
              Probar de nuevo
            </button>
          </p>
        )}
      </div>
    </div>
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
