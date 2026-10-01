import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { VoiceConversation } from "@elevenlabs/client";
import { api, ApiError } from "../api/client";
import { EchoOrb, type OrbState } from "./EchoOrb";
import { micErrorMessage } from "../lib/micError";

interface SessionOut {
  signed_url: string;
  max_seconds: number;
  seconds_left: number | null;
  user_name: string;
  dynamic_variables: Record<string, string>;
}

interface StatusOut {
  allowed: boolean;
  seconds_total: number | null;
  seconds_left: number | null;
  seconds_used: number;
  max_conversation_seconds: number;
}

interface EndOut {
  seconds: number;
  seconds_left: number | null;
  pending: boolean;
}

type Phase =
  | "loading"
  | "upsell"
  | "ready"
  | "connecting"
  | "activating"
  | "listening"
  | "thinking"
  | "speaking"
  | "ending"
  | "ended"
  | "error";

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

function minutes(seconds: number): string {
  const value = Math.floor(Math.max(0, seconds) / 60);
  return `${value} min`;
}

/** El error para mostrar: los del micrófono traducidos, los del servidor tal cual. */
function micError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return micErrorMessage(error, "No se pudo conectar.");
}

/**
 * Hablar con Echo (plan Individual + voz), lo que abre el globito
 * (docs/plan-correcciones.md §7.6): pantalla previa con los minutos que quedan
 * y "Empezar"; durante la charla, ondas que siguen la voz, silenciar y colgar;
 * al terminar, cuánto se usó. A quien no tiene voz en su plan, en vez de la
 * charla, qué es y "Pasate al plan con voz".
 *
 * El navegador habla con el agente de ElevenLabs por una URL firmada que da el
 * servidor; cuando el agente necesita algo de las reuniones, llama a
 * `consultar_reuniones`, que se resuelve acá con el mismo "Preguntale a Echo"
 * (con seudonimización y sin las reuniones donde hablan menores).
 */
export function VoiceChat({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<Phase>("loading");
  const [status, setStatus] = useState<StatusOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [lastLine, setLastLine] = useState("");
  const [muted, setMuted] = useState(false);
  const [summary, setSummary] = useState<{ seconds: number; left: number | null } | null>(null);
  const conversation = useRef<VoiceConversation | null>(null);
  const conversationId = useRef<string | null>(null);
  // Cuándo empezó y cuánto puede durar: el reloj se calcula de acá, no restando de a uno.
  const startedAt = useRef(0);
  const maxSeconds = useRef(0);
  // Se cerró la ventana mientras conectaba: lo que llegue después se corta.
  const closed = useRef(false);
  const toolBusy = useRef(0);
  const ring = useRef<HTMLDivElement | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const current = await api<StatusOut>("/api/voice/status");
      setStatus(current);
      setPhase(current.allowed ? "ready" : "upsell");
    } catch (caught) {
      setPhase("error");
      setError(micError(caught));
    }
  }, []);

  const report = useCallback(async () => {
    const id = conversationId.current;
    conversationId.current = null;
    if (!id) return;
    const elapsed = (Date.now() - startedAt.current) / 1000;
    // Aunque esto no llegue (pestaña cerrada), el servidor lo anota igual.
    const ended = await api<EndOut>("/api/voice/sessions/end", {
      method: "POST",
      body: JSON.stringify({ conversation_id: id, seconds: elapsed }),
    }).catch(() => null);
    const seconds = ended && !ended.pending ? ended.seconds : elapsed;
    const left = ended && !ended.pending ? ended.seconds_left : null;
    setSummary({ seconds, left });
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
    setSummary(null);
    setMuted(false);
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
          setRemaining(null);
          setPhase((current) => (current === "error" ? current : "ended"));
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

  const toggleMute = () => {
    const next = !muted;
    conversation.current?.setMicMuted(next);
    setMuted(next);
  };

  const active = phase === "activating" || phase === "listening" || phase === "thinking" || phase === "speaking";

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

  // Ondas que siguen la voz (de quien habla o de Echo): solo durante la charla,
  // y sin re-render: se mueve un anillo por estilo.
  useEffect(() => {
    if (!active) return;
    let frame = 0;
    const loop = () => {
      const voice = conversation.current;
      const level = voice ? Math.max(voice.getInputVolume(), voice.getOutputVolume()) : 0;
      if (ring.current) {
        ring.current.style.transform = `scale(${1 + Math.min(level, 1) * 0.35})`;
        ring.current.style.opacity = String(0.25 + Math.min(level, 1) * 0.6);
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [active]);

  // Cerrar la ventana corta la conversación (también si todavía estaba conectando).
  useEffect(() => {
    closed.current = false;
    void loadStatus();
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

  const orb: OrbState =
    phase === "activating"
      ? "activation"
      : phase === "thinking" || phase === "ending" || phase === "connecting"
        ? "thinking"
        : phase === "listening"
          ? "listening"
          : phase === "speaking"
            ? "speaking"
            : "idle";
  const label: Partial<Record<Phase, string>> = {
    connecting: "Conectando…",
    activating: "Hola",
    listening: muted ? "Micrófono silenciado" : "Te escucho",
    thinking: "Buscando en tus reuniones…",
    speaking: "Echo está hablando",
    ending: "Cortando…",
  };
  const outOfMinutes = status?.seconds_left != null && status.seconds_left < 10;

  return (
    // Sin fondo oscuro: la mascota aparece sobre la página, apenas velada con
    // el mismo color de la app para que el texto de atrás no se le cruce.
    <div
      className="voice-veil fixed inset-0 z-[60] flex flex-col items-center justify-center bg-ink-50/85 px-6 pb-[env(safe-area-inset-bottom)] backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label="Hablar con Echo"
    >
      <button
        type="button"
        onClick={close}
        className="absolute right-4 top-[max(1rem,env(safe-area-inset-top))] flex h-11 w-11 items-center justify-center rounded-full border border-ink-200 bg-white text-ink-600 shadow-sm transition-colors hover:text-ink-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
        aria-label="Cerrar"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </button>

      <div className="relative flex items-center justify-center">
        <div
          ref={ring}
          aria-hidden
          className={`pointer-events-none absolute inset-[18%] rounded-full bg-accent-300/40 blur-2xl transition-opacity duration-300 ${active ? "opacity-40" : "opacity-0"}`}
        />
        <EchoOrb
          size={phase === "ready" || phase === "upsell" || phase === "ended" || phase === "loading" ? 220 : 300}
          state={orb}
          onActivated={() => setPhase((current) => (current === "activating" ? "listening" : current))}
        />
      </div>

      <div aria-live="polite" className="mt-2 flex w-full max-w-sm flex-col items-center gap-3 text-center">
        {phase === "loading" && <p className="text-sm text-ink-500">Un segundo…</p>}

        {phase === "upsell" && (
          <>
            <h2 className="text-xl font-semibold tracking-tight text-ink-900">Hablá con Echo</h2>
            <p className="text-[15px] leading-relaxed text-ink-600">
              Preguntale por tus reuniones hablando, como a una persona: "¿qué quedamos con la familia de Pedro?",
              "¿qué tareas tengo para esta semana?". Viene en el plan Individual + voz.
            </p>
            <Link
              to="/plans"
              onClick={onClose}
              className="inline-flex min-h-11 w-full items-center justify-center rounded-full bg-ink-900 px-6 text-sm font-semibold text-white hover:bg-ink-700"
            >
              Pasate al plan con voz
            </Link>
          </>
        )}

        {phase === "ready" && status && (
          <>
            <h2 className="text-xl font-semibold tracking-tight text-ink-900">Hablá con Echo</h2>
            <p className="text-[15px] leading-relaxed text-ink-600">
              {outOfMinutes
                ? "Ya usaste los minutos de voz de este mes. Se renuevan el 1°."
                : status.seconds_left == null
                  ? "Preguntale lo que quieras sobre tus reuniones."
                  : `Te quedan ${minutes(status.seconds_left)} este mes. Cada charla dura hasta ${minutes(status.max_conversation_seconds)}.`}
            </p>
            {!outOfMinutes && (
              <button
                type="button"
                onClick={() => void start()}
                className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-ink-900 px-6 text-[15px] font-semibold text-white hover:bg-ink-700"
              >
                <MicIcon /> Empezar
              </button>
            )}
          </>
        )}

        {label[phase] && (
          <p
            key={label[phase]}
            className="animate-fade-up rounded-full border border-ink-200/80 bg-white/90 px-4 py-1.5 text-sm font-semibold text-ink-900 shadow-sm backdrop-blur"
          >
            {label[phase]}
            {remaining != null && <span className="ml-2 font-normal tabular-nums text-ink-400">{clock(remaining)}</span>}
          </p>
        )}
        {active && lastLine && (
          <p
            key={lastLine}
            className="animate-fade-up max-w-md rounded-2xl border border-ink-200/80 bg-white/90 px-4 py-2.5 text-[15px] leading-relaxed text-ink-700 shadow-sm backdrop-blur"
          >
            {lastLine}
          </p>
        )}

        {active && (
          <div className="mt-2 flex items-center gap-4">
            <button
              type="button"
              onClick={toggleMute}
              aria-pressed={muted}
              className={`flex h-14 w-14 items-center justify-center rounded-full border shadow-sm transition-colors ${
                muted ? "border-ink-900 bg-ink-900 text-white" : "border-ink-200 bg-white text-ink-700 hover:text-ink-900"
              }`}
              aria-label={muted ? "Activar el micrófono" : "Silenciar el micrófono"}
            >
              {muted ? <MicOffIcon /> : <MicIcon />}
            </button>
            <button
              type="button"
              onClick={() => void finish()}
              className="flex h-14 w-14 items-center justify-center rounded-full bg-red-600 text-white shadow-sm transition-colors hover:bg-red-700"
              aria-label="Colgar"
            >
              <HangUpIcon />
            </button>
          </div>
        )}

        {phase === "ended" && (
          <>
            <h2 className="text-xl font-semibold tracking-tight text-ink-900">¡Hasta la próxima!</h2>
            <p className="text-[15px] text-ink-600">
              {summary ? `Hablaron ${clock(summary.seconds)}.` : "La charla terminó."}
              {summary?.left != null && ` Te quedan ${minutes(summary.left)} este mes.`}
            </p>
            <div className="flex w-full gap-2">
              <button
                type="button"
                onClick={() => void loadStatus()}
                className="min-h-11 flex-1 rounded-full bg-ink-100 px-4 text-sm font-semibold text-ink-800 hover:bg-ink-200"
              >
                Hablar de nuevo
              </button>
              <button
                type="button"
                onClick={close}
                className="min-h-11 flex-1 rounded-full bg-ink-900 px-4 text-sm font-semibold text-white hover:bg-ink-700"
              >
                Listo
              </button>
            </div>
          </>
        )}

        {error && (
          <p role="alert" className="max-w-sm rounded-2xl border border-red-200 bg-white px-4 py-2.5 text-sm text-red-700 shadow-sm">
            {error}{" "}
            <button type="button" onClick={() => void loadStatus()} className="font-semibold underline underline-offset-2">
              Probar de nuevo
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

function MicIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

function MicOffIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M15 9.5V6a3 3 0 0 0-5.7-1.3M9 9v2a3 3 0 0 0 4.9 2.3M5 11a7 7 0 0 0 11.6 5.3M19 11a7 7 0 0 1-.4 2.3M12 18v3M3 3l18 18" />
    </svg>
  );
}

function HangUpIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 9c-3.2 0-6.2.9-8.6 2.6-.6.4-.8 1.2-.4 1.8l1.4 2.1c.4.6 1.2.8 1.8.4l2.3-1.4c.4-.3.7-.8.6-1.3l-.2-1.4c.98-.33 2-.5 3.1-.5s2.1.17 3.1.5l-.2 1.4c-.1.5.2 1 .6 1.3l2.3 1.4c.6.4 1.4.2 1.8-.4l1.4-2.1c.4-.6.2-1.4-.4-1.8C18.2 9.9 15.2 9 12 9z" />
    </svg>
  );
}
