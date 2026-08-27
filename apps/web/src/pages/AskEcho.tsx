import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ChatOut } from "../api/types";
import { Button, EmptyState, formatMs } from "../components/ui";
import { EchoFace } from "../components/EchoFace";

const SUGGESTIONS = [
  "¿Qué decisiones tomamos esta semana?",
  "¿Qué tareas siguen pendientes?",
  "¿Qué reuniones mencionaron presupuesto?",
  "¿Qué decisiones siguen sin ejecutarse?",
];

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ChatOut["sources"];
}

export default function AskEcho() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: (question: string) =>
      api<ChatOut>("/api/ask", {
        method: "POST",
        body: JSON.stringify({
          question,
          history: messages.slice(-6).map(({ role, content }) => ({ role, content })),
        }),
      }),
    onSuccess: (response) => {
      setMessages((current) => [
        ...current,
        { role: "assistant", content: response.answer, sources: response.sources },
      ]);
    },
    onError: (error) => {
      setMessages((current) => [
        ...current,
        { role: "assistant", content: error instanceof Error ? error.message : "Error" },
      ]);
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, ask.isPending]);

  const send = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setInput("");
    ask.mutate(trimmed);
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-6 py-6">
      <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto py-4">
        {messages.length === 0 && (
          <div className="pt-[10vh]">
            <EmptyState title="Preguntale a Echo" mood="idle">
              <p className="mb-5">
                Echo responde usando la memoria de todas tus reuniones, siempre con fuentes.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => send(suggestion)}
                    className="rounded-full border border-ink-200 bg-white px-3.5 py-1.5 text-sm text-ink-600 hover:border-ink-300 hover:text-ink-900"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </EmptyState>
          </div>
        )}
        {messages.map((message, index) => (
          <div key={index} className={message.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed ${
                message.role === "user" ? "bg-ink-900 text-white" : "border border-ink-100 bg-white text-ink-900 shadow-sm"
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              {message.sources && message.sources.length > 0 && (
                <div className="mt-3 space-y-1 border-t border-ink-100 pt-2.5">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">Fuentes</p>
                  {message.sources.map((source, sourceIndex) => (
                    <Link
                      key={sourceIndex}
                      to={`/meetings/${source.meeting_id}?t=${source.start_ms}`}
                      className="block text-xs text-accent-600 hover:underline"
                    >
                      «{source.meeting_title}» — {formatMs(source.start_ms)}
                      {source.speaker && ` · ${source.speaker}`}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {ask.isPending && (
          <div className="flex items-center gap-2.5 text-ink-400">
            <EchoFace mood="thinking" size={28} />
            <span className="text-sm">Buscando en la memoria de reuniones…</span>
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="flex gap-2 border-t border-ink-100 pt-4"
      >
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Preguntá sobre cualquier reunión…"
          className="flex-1 rounded-xl border border-ink-200 bg-white px-4 py-3 text-[15px] shadow-sm focus:border-accent-500 focus:outline-none"
        />
        <Button type="submit" disabled={ask.isPending || !input.trim()} className="!px-5">
          Enviar
        </Button>
      </form>
    </div>
  );
}
