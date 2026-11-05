import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { EchoFace } from "./EchoFace";
import { Button, Spinner } from "./ui";

/*
 * Los popups de opinión: una tarjeta flotante, abajo a la derecha, que no frena
 * lo que se está haciendo. Los prende Becode desde su panel; nunca salen durante
 * una reunión en vivo ni encima de otra ventana (Layout.tsx y el chequeo de acá).
 */

export type FeedbackKind = "stars" | "suggestion";

export interface FeedbackPromptOut {
  kind: FeedbackKind;
  title: string;
  question: string;
}

const FIRST_DELAY_MS = 20_000;
const RETRY_MS = 15_000;
const THANKS_MS = 2600;

/** Lo abre "Contanos qué cambiarías", del menú del avatar. */
export const OPEN_FEEDBACK_EVENT = "echo:feedback";
const ON_DEMAND: FeedbackPromptOut = {
  kind: "suggestion",
  title: "Contanos",
  question: "¿Qué cambiarías para mejorar tu día a día con Echo?",
};

function Star({ on }: { on: boolean }) {
  return (
    <svg width="30" height="30" viewBox="0 0 24 24" aria-hidden className={`transition-colors ${on ? "text-amber-400" : "text-ink-200"}`}>
      <path
        fill="currentColor"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z"
      />
    </svg>
  );
}

function Stars({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  const [hover, setHover] = useState(0);
  return (
    <div role="radiogroup" aria-label="Tu puntaje" className="flex" onMouseLeave={() => setHover(0)}>
      {[1, 2, 3, 4, 5].map((stars) => (
        <button
          key={stars}
          type="button"
          role="radio"
          aria-checked={value === stars}
          aria-label={stars === 1 ? "1 estrella" : `${stars} estrellas`}
          onMouseEnter={() => setHover(stars)}
          onClick={() => onChange(stars)}
          className="rounded-lg p-1 transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-accent-500"
        >
          <Star on={stars <= (hover || value)} />
        </button>
      ))}
    </div>
  );
}

/** La tarjeta en sí. El panel de Becode la usa con `onSend` de mentira para ver cómo queda. */
export function FeedbackCard({
  prompt,
  onSend,
  onLater,
  onClose,
  sending = false,
  error = null,
}: {
  prompt: FeedbackPromptOut;
  onSend: (answer: { stars?: number; text?: string }) => Promise<unknown> | void;
  onLater: () => void;
  onClose: () => void;
  sending?: boolean;
  error?: string | null;
}) {
  const [stars, setStars] = useState(0);
  const [text, setText] = useState("");
  const [thanks, setThanks] = useState(false);
  const isStars = prompt.kind === "stars";
  const canSend = isStars ? stars > 0 : text.trim().length > 0;

  useEffect(() => {
    if (!thanks) return;
    const timer = window.setTimeout(onClose, THANKS_MS);
    return () => window.clearTimeout(timer);
  }, [thanks]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = async () => {
    if (!canSend) return;
    try {
      await onSend({ stars: isStars ? stars : undefined, text: text.trim() || undefined });
      setThanks(true);
    } catch {
      /* el error lo muestra quien manda; lo escrito no se borra */
    }
  };

  return (
    <aside
      aria-label={prompt.title}
      className="animate-fade-up fixed inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-40 rounded-3xl border border-ink-100 bg-white p-5 shadow-[0_24px_64px_-16px_rgba(20,24,36,0.35)] md:inset-x-auto md:bottom-5 md:right-5 md:w-[23rem]"
    >
      {thanks ? (
        <div role="status" className="flex items-center gap-3 py-1">
          <span className="text-accent-600">
            <EchoFace mood="done" size={40} />
          </span>
          <div>
            <p className="font-semibold text-ink-900">¡Gracias!</p>
            <p className="text-sm text-ink-500">Lo leemos todo, de verdad.</p>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-start gap-3">
            <span className="shrink-0 text-ink-800">
              <EchoFace mood="idle" size={34} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="pr-6 text-[15px] font-semibold leading-snug text-ink-900">{prompt.title}</p>
              <p className="mt-0.5 text-sm leading-snug text-ink-600">{prompt.question}</p>
            </div>
            <button
              type="button"
              onClick={onLater}
              aria-label="Cerrar"
              className="-mr-2 -mt-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-ink-400 hover:bg-ink-100 hover:text-ink-700"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          {isStars && (
            <div className="mt-3 flex justify-center">
              <Stars value={stars} onChange={setStars} />
            </div>
          )}

          {(!isStars || stars > 0) && (
            <label className="mt-3 block">
              <span className="sr-only">{isStars ? "¿Querés contarnos por qué?" : prompt.question}</span>
              <textarea
                autoFocus={!isStars && window.matchMedia?.("(min-width: 768px)").matches}
                value={text}
                onChange={(event) => setText(event.target.value)}
                maxLength={2000}
                rows={3}
                placeholder={isStars ? "¿Querés contarnos por qué? (opcional)" : "Lo que sea, grande o chico…"}
                className="w-full resize-none rounded-2xl border border-ink-200 bg-white px-3.5 py-2.5 text-[16px] leading-snug text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20 md:text-sm"
              />
            </label>
          )}

          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

          <div className="mt-3 flex items-center justify-end gap-1">
            <Button variant="ghost" onClick={onLater}>Ahora no</Button>
            <Button onClick={() => void send()} disabled={!canSend || sending}>
              {sending ? <Spinner /> : "Enviar"}
            </Button>
          </div>
        </>
      )}
    </aside>
  );
}

/** Pregunta cuando le toca a esta persona. Se monta en Layout.tsx. */
export function FeedbackPrompt() {
  const queryClient = useQueryClient();
  const [waited, setWaited] = useState(false);
  const [closed, setClosed] = useState(false);
  const [onDemand, setOnDemand] = useState(false);
  const [clear, setClear] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setWaited(true), FIRST_DELAY_MS);
    const open = () => {
      setClosed(false);
      setOnDemand(true);
    };
    window.addEventListener(OPEN_FEEDBACK_EVENT, open);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(OPEN_FEEDBACK_EVENT, open);
    };
  }, []);

  const { data: asked } = useQuery({
    queryKey: ["feedback-prompt"],
    queryFn: () => api<FeedbackPromptOut | null>("/api/feedback/prompt", { skipOrg: true }),
    enabled: waited,
    staleTime: Infinity,
  });

  // Nunca encima de otra ventana (Mi voz, novedades, Ajustes): espera a que se cierre.
  useEffect(() => {
    if (!asked || clear) return;
    const check = () => {
      if (!document.querySelector('[role="dialog"]')) setClear(true);
    };
    check();
    const timer = window.setInterval(check, RETRY_MS);
    return () => window.clearInterval(timer);
  }, [asked, clear]);

  const answer = useMutation({
    mutationFn: (body: { kind: FeedbackKind; stars?: number; text?: string }) =>
      api("/api/feedback", { method: "POST", body: JSON.stringify(body) }),
  });
  const dismiss = useMutation({
    mutationFn: (kind: FeedbackKind) =>
      api("/api/feedback/dismiss", { method: "POST", skipOrg: true, body: JSON.stringify({ kind }) }),
  });

  const prompt = onDemand ? ON_DEMAND : asked && clear && !closed ? asked : null;
  if (!prompt) return null;

  const finish = () => {
    setClosed(true);
    setOnDemand(false);
    answer.reset();
    queryClient.setQueryData(["feedback-prompt"], null);
  };

  return (
    <FeedbackCard
      key={prompt.kind + (onDemand ? "-menu" : "")}
      prompt={prompt}
      sending={answer.isPending}
      error={answer.isError ? (answer.error instanceof Error ? answer.error.message : "No se pudo enviar") : null}
      onSend={(body) => answer.mutateAsync({ kind: prompt.kind, ...body })}
      onLater={() => {
        // Abierto a mano no cuenta: la persona no estaba rechazando nada.
        if (!onDemand) dismiss.mutate(prompt.kind);
        finish();
      }}
      onClose={finish}
    />
  );
}
