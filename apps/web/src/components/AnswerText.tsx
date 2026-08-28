import ReactMarkdown from "react-markdown";

/**
 * Respuestas de Echo renderizadas como markdown.
 *
 * El modelo devuelve `**negrita**`, encabezados y listas; sin esto se veían
 * los asteriscos y los guiones crudos. La tipografía se define acá y no en
 * cada pantalla para que el chat de reunión y «Preguntale a Echo» se vean
 * igual.
 */
export function AnswerText({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-ink-900">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => <ul className="ml-1 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="ml-1 space-y-1">{children}</ol>,
          li: ({ children }) => (
            <li className="flex gap-2">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-ink-300" />
              <span className="min-w-0 flex-1">{children}</span>
            </li>
          ),
          h1: ({ children }) => (
            <p className="mt-1 font-semibold text-ink-900">{children}</p>
          ),
          h2: ({ children }) => (
            <p className="mt-1 font-semibold text-ink-900">{children}</p>
          ),
          h3: ({ children }) => (
            <p className="mt-1 font-semibold text-ink-900">{children}</p>
          ),
          code: ({ children }) => (
            <code className="rounded bg-ink-50 px-1 py-0.5 font-mono text-[0.85em]">
              {children}
            </code>
          ),
          a: ({ children, href }) => (
            <a href={href} className="text-brand-600 underline" rel="noreferrer noopener">
              {children}
            </a>
          ),
          // Una regla horizontal en una burbuja de chat es solo ruido.
          hr: () => null,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
