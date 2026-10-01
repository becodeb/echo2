import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { EchoChat } from "./EchoChat";

/**
 * "Preguntar", como el Ask de ElevenLabs: un panel a la derecha que no saca a
 * la persona de lo que estaba haciendo (la app se achica a una tarjeta al lado).
 * En el celular ocupa toda la pantalla. El chat es el mismo de "Preguntale a Echo".
 */
export function AskPanel({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [count, setCount] = useState(0);
  const [resetKey, setResetKey] = useState(0);
  const onMessagesChange = useCallback((value: number) => setCount(value), []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const iconButton =
    "flex h-9 w-9 items-center justify-center rounded-full text-ink-500 transition-colors hover:bg-ink-200/60 hover:text-ink-900";

  return (
    <aside className="flex h-full w-full flex-col" aria-label="Preguntale a Echo">
      <EchoChat
        resetKey={resetKey}
        onMessagesChange={onMessagesChange}
        header={
          <header className="flex shrink-0 items-center gap-0.5 px-3 pb-1 pt-[max(0.5rem,env(safe-area-inset-top))]">
            <h2 className="flex-1 pl-1 text-[15px] font-semibold text-ink-900">Preguntale a Echo</h2>
            {count > 0 && (
              <button type="button" className={iconButton} onClick={() => setResetKey((key) => key + 1)} aria-label="Nuevo chat" title="Nuevo chat">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M12 20h8M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
                </svg>
              </button>
            )}
            <button
              type="button"
              className={`${iconButton} hidden md:flex`}
              onClick={() => navigate("/ask")}
              aria-label="Abrir en pantalla completa"
              title="Pantalla completa"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5" />
              </svg>
            </button>
            <button type="button" className={iconButton} onClick={onClose} aria-label="Cerrar" title="Cerrar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </header>
        }
      />
    </aside>
  );
}
