import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ChatOut } from "../api/types";
import { AnswerText } from "./AnswerText";
import { useBilling } from "./billing";
import { EchoFace } from "./EchoFace";
import { formatMs } from "./ui";
import { useVoice } from "../state/voice";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: ChatOut["sources"];
  failed?: boolean;
}

const SUGGESTIONS = [
  "¿Qué tareas siguen pendientes?",
  "¿Qué decidimos esta semana?",
  "¿Qué reuniones hablaron de presupuesto?",
];

/**
 * El chat con Echo sobre las reuniones. Lo usan el panel "Preguntar" (al
 * costado en la computadora, pantalla completa en el celular) y la página
 * "Preguntale a Echo", así se ven y se comportan igual.
 *
 * Pensado primero para el celular: la pantalla vacía no es un hueco gris sino
 * Echo y tres preguntas para tocar; el cuadro de texto crece con lo que se
 * escribe, respeta la barra del iPhone y usa letra de 16 px (con menos, iOS
 * hace zoom al tocarlo).
 */
export function EchoChat({
  header,
  wide = false,
  onMessagesChange,
  resetKey = 0,
}: {
  // Lo que va arriba del chat (el panel tiene su barra; la página, nada).
  header?: ReactNode;
  // Página completa: las respuestas en una columna centrada más ancha.
  wide?: boolean;
  onMessagesChange?: (count: number) => void;
  // Cambiarlo empieza un chat nuevo.
  resetKey?: number;
}) {
  const { data: billing } = useBilling();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const voice = useVoice();
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const ask = useMutation({
    mutationFn: (question: string) =>
      api<ChatOut>("/api/ask", {
        method: "POST",
        body: JSON.stringify({ question, history: messages.slice(-6).map(({ role, content }) => ({ role, content })) }),
      }),
    onSuccess: (response) =>
      setMessages((current) => [...current, { role: "assistant", content: response.answer, sources: response.sources }]),
    onError: (error) =>
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: error instanceof Error ? error.message : "No pude responder. Probá de nuevo.",
          failed: true,
        },
      ]),
  });

  useEffect(() => {
    setMessages([]);
    setInput("");
  }, [resetKey]);
  useEffect(() => onMessagesChange?.(messages.length), [messages.length, onMessagesChange]);
  useEffect(() => {
    // En el celular no se abre el teclado solo: tapa la mitad de la pantalla.
    if (window.matchMedia?.("(min-width: 768px)").matches) inputRef.current?.focus();
  }, []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, ask.isPending]);
  // El cuadro crece con el texto hasta unas 6 líneas.
  useLayoutEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
  }, [input]);

  const send = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setInput("");
    ask.mutate(trimmed);
  };

  const column = wide ? "mx-auto w-full max-w-3xl" : "w-full";
  const canTalk = !!billing?.features.voice;

  if (billing && !billing.features.paid) {
    // Plan Gratis: se pregunta sobre cada reunión, desde su pestaña Chat.
    return (
      <div className="flex h-full min-h-0 w-full flex-col">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
          <EchoAvatar />
          <div className="max-w-sm">
            <p className="text-lg font-semibold tracking-tight text-ink-900">Preguntale a Echo por todas tus reuniones</p>
            <p className="mt-2 text-sm leading-relaxed text-ink-500">
              «¿Qué quedamos con la familia de Pedro?», «¿qué tareas tengo esta semana?». En el plan Gratis podés
              preguntar sobre cada reunión desde su pestaña Chat.
            </p>
          </div>
          <Link
            to="/plans"
            className="inline-flex min-h-11 items-center rounded-full bg-ink-900 px-5 text-sm font-semibold text-white hover:bg-ink-700"
          >
            Ver planes
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {header}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4">
        {messages.length === 0 ? (
          <Welcome onPick={send} wide={wide} />
        ) : (
          <div className={`${column} space-y-6 pb-6 pt-2`}>
            {messages.map((message, index) =>
              message.role === "user" ? (
                <div key={index} className="animate-fade-up flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-[22px] rounded-br-lg bg-ink-900 px-4 py-2.5 text-[15px] leading-relaxed text-white">
                    {message.content}
                  </p>
                </div>
              ) : (
                <Answer key={index} message={message} onRetry={() => {
                  const question = [...messages.slice(0, index)].reverse().find((item) => item.role === "user");
                  if (question) send(question.content);
                }} />
              ),
            )}
            {ask.isPending && (
              <div className="animate-fade-up flex items-center gap-3">
                <EchoAvatar mood="thinking" />
                <span className="ask-shimmer text-[14px] font-medium">Buscando en tus reuniones…</span>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-1">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            send(input);
          }}
          className={`${column} flex items-end gap-1.5 rounded-[26px] border border-ink-200 bg-white p-1.5 pl-4 shadow-[0_4px_18px_-8px_rgba(20,24,36,0.18)] transition-colors focus-within:border-ink-300`}
        >
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                send(input);
              }
            }}
            placeholder="Preguntale a Echo…"
            aria-label="Tu pregunta"
            enterKeyHint="send"
            className="max-h-40 min-h-[36px] flex-1 resize-none bg-transparent py-[7px] text-[16px] leading-snug text-ink-900 placeholder:text-ink-400 focus:outline-none md:text-[15px]"
          />
          {canTalk && (
            <button
              type="button"
              onClick={voice.open}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900"
              aria-label="Hablar con Echo"
              title="Hablar con Echo"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden>
                <rect x="9" y="3" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            </button>
          )}
          <button
            type="submit"
            disabled={ask.isPending || !input.trim()}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink-900 text-white transition-all hover:bg-ink-700 active:scale-95 disabled:bg-ink-200"
            aria-label="Enviar"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M12 19V5M6 11l6-6 6 6" />
            </svg>
          </button>
        </form>
        {!canTalk && billing && wide && (
          <p className="mt-2 text-center text-xs text-ink-400">
            ¿Preferís hablarle?{" "}
            <Link to="/plans" className="font-medium text-ink-600 hover:text-ink-900">
              Conversá con Echo por voz con el plan + voz
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}

function Welcome({ onPick, wide }: { onPick: (question: string) => void; wide: boolean }) {
  return (
    <div className={`animate-fade-up mx-auto flex min-h-full w-full flex-col justify-center py-8 ${wide ? "max-w-xl" : "max-w-sm"}`}>
      <span className="text-ink-900">
        <EchoFace mood="idle" size={44} />
      </span>
      <h3 className="mt-4 text-[22px] font-semibold tracking-tight text-ink-900">¿Qué querés saber?</h3>
      <p className="mt-1.5 text-[15px] leading-relaxed text-ink-500">
        Echo busca en todas tus reuniones y te dice de cuál sale cada respuesta.
      </p>
      <div className="mt-6 overflow-hidden rounded-3xl border border-ink-100 bg-white">
        {SUGGESTIONS.map((suggestion, index) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onPick(suggestion)}
            className={`flex min-h-[52px] w-full items-center gap-3 px-4 text-left text-[15px] text-ink-700 transition-colors hover:bg-ink-50 active:bg-ink-100 ${
              index > 0 ? "border-t border-ink-100" : ""
            }`}
          >
            <span className="flex-1">{suggestion}</span>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-ink-300" aria-hidden>
              <path d="M7 17 17 7M8 7h9v9" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}

function EchoAvatar({ mood = "idle" }: { mood?: "idle" | "thinking" }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-ink-100 bg-white text-ink-900">
      <EchoFace mood={mood} size={20} />
    </span>
  );
}

function Answer({ message, onRetry }: { message: Message; onRetry: () => void }) {
  return (
    <div className="animate-fade-up flex gap-3">
      <EchoAvatar />
      <div className="min-w-0 flex-1 pt-1 text-[15px] leading-relaxed text-ink-800">
        {message.failed ? (
          <p className="text-red-600">
            {message.content}{" "}
            <button type="button" onClick={onRetry} className="font-semibold underline underline-offset-2">
              Probar de nuevo
            </button>
          </p>
        ) : (
          <div className="[&_.text-sm]:text-[15px]">
            <AnswerText text={message.content} />
          </div>
        )}
        {message.sources && message.sources.length > 0 && (
          <div className="-mx-1 mt-3 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
            {message.sources.slice(0, 6).map((source, index) => (
              <Link
                key={index}
                to={`/meetings/${source.meeting_id}?t=${source.start_ms}`}
                className="flex shrink-0 items-center gap-1.5 rounded-full border border-ink-200 bg-white py-1 pl-2 pr-3 text-[12px] font-medium text-ink-600 transition-colors hover:border-ink-300 hover:text-ink-900"
                title={source.speaker ? `${source.meeting_title} · ${source.speaker}` : source.meeting_title}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
                  <path d="M14 3v5h5" />
                </svg>
                <span className="max-w-[160px] truncate">{source.meeting_title}</span>
                <span className="tabular-nums text-ink-400">{formatMs(source.start_ms)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
