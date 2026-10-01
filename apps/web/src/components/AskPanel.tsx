import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ChatOut } from "../api/types";
import { AnswerText } from "./AnswerText";
import { useBilling } from "./billing";
import { EchoFace } from "./EchoFace";
import { formatMs } from "./ui";
import { VoiceChat } from "./VoiceChat";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: ChatOut["sources"];
}

const SUGGESTIONS = ["¿Qué tareas siguen pendientes?", "¿Qué decidimos esta semana?", "¿Qué reuniones hablaron de presupuesto?"];

/**
 * "Preguntar", como el Ask de ElevenLabs: un panel a la derecha que no saca a
 * la persona de lo que estaba haciendo (la app se achica a una tarjeta al lado).
 * Usa la misma memoria de reuniones que "Preguntale a Echo", con fuentes.
 */
export function AskPanel({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const { data: billing } = useBilling();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
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
        { role: "assistant", content: error instanceof Error ? error.message : "No pude responder. Probá de nuevo." },
      ]),
  });

  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, ask.isPending]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const send = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setInput("");
    ask.mutate(trimmed);
  };

  const iconButton =
    "flex h-8 w-8 items-center justify-center rounded-full text-ink-500 transition-colors hover:bg-ink-200/60 hover:text-ink-900";

  return (
    <aside className="flex h-full w-full flex-col" aria-label="Preguntale a Echo">
      <header className="flex h-14 shrink-0 items-center gap-1 px-4">
        <h2 className="flex-1 text-[15px] font-semibold text-ink-900">{messages.length ? "Preguntale a Echo" : "Nuevo chat"}</h2>
        <button type="button" className={iconButton} onClick={() => navigate("/ask")} aria-label="Abrir en pantalla completa" title="Pantalla completa">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5" />
          </svg>
        </button>
        <button type="button" className={iconButton} onClick={() => setMessages([])} aria-label="Nuevo chat" title="Nuevo chat">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden>
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
        <button type="button" className={iconButton} onClick={onClose} aria-label="Cerrar" title="Cerrar">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
            <path d="M6 6l12 12M18 6 6 18" />
          </svg>
        </button>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        {messages.length === 0 && (
          <div className="animate-fade-up space-y-4 pt-1">
            <p className="text-[15px] text-ink-700">¡Hola! ¿Qué querés saber de tus reuniones?</p>
            <div className="flex flex-col items-start gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => send(suggestion)}
                  className="rounded-full border border-ink-200 bg-white px-3.5 py-1.5 text-left text-[13px] text-ink-600 transition-colors hover:border-ink-300 hover:text-ink-900"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <div key={index} className="animate-fade-up flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-ink-900 px-3.5 py-2.5 text-sm text-white">
                {message.content}
              </p>
            </div>
          ) : (
            <div key={index} className="animate-fade-up text-sm leading-relaxed text-ink-800">
              <AnswerText text={message.content} />
              {message.sources && message.sources.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {message.sources.slice(0, 4).map((source, sourceIndex) => (
                    <Link
                      key={sourceIndex}
                      to={`/meetings/${source.meeting_id}?t=${source.start_ms}`}
                      className="rounded-full bg-ink-100 px-2.5 py-1 text-[11px] font-medium text-ink-600 transition-colors hover:bg-ink-200 hover:text-ink-900"
                    >
                      {source.meeting_title} · {formatMs(source.start_ms)}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ),
        )}
        {ask.isPending && (
          <div className="flex items-center gap-2 text-ink-400">
            <EchoFace mood="thinking" size={22} />
            <span className="text-[13px]">Buscando en tus reuniones…</span>
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="m-3 mt-0 rounded-2xl border border-ink-200 bg-white p-2 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-colors focus-within:border-ink-300"
      >
        <textarea
          ref={inputRef}
          rows={2}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send(input);
            }
          }}
          placeholder="Preguntá lo que quieras…"
          className="w-full resize-none bg-transparent px-2 py-1 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none"
        />
        <div className="flex items-center justify-end gap-1.5">
          {billing?.features.voice ? (
            <button type="button" onClick={() => setVoiceOpen(true)} className={iconButton} aria-label="Hablar con Echo" title="Hablar con Echo">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden>
                <rect x="9" y="3" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
              </svg>
            </button>
          ) : null}
          <button
            type="submit"
            disabled={ask.isPending || !input.trim()}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-ink-900 text-white transition-all hover:bg-ink-700 active:scale-95 disabled:bg-ink-200"
            aria-label="Enviar"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M12 19V5M6 11l6-6 6 6" />
            </svg>
          </button>
        </div>
      </form>
      {voiceOpen && <VoiceChat onClose={() => setVoiceOpen(false)} />}
    </aside>
  );
}
