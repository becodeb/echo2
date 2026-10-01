import { createContext, useContext, useState, type ReactNode } from "react";
import { VoiceChat } from "../components/VoiceChat";

/**
 * "Hablar con Echo" se abre desde varios lados (el globito, la barra lateral,
 * Inicio, el micrófono de "Preguntale a Echo"): una sola conversación a la vez.
 */
const VoiceContext = createContext<{ open: () => void; isOpen: boolean }>({ open: () => {}, isOpen: false });

export function VoiceProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  return (
    <VoiceContext.Provider value={{ open: () => setOpen(true), isOpen }}>
      {children}
      {isOpen && <VoiceChat onClose={() => setOpen(false)} />}
    </VoiceContext.Provider>
  );
}

export function useVoice() {
  return useContext(VoiceContext);
}
