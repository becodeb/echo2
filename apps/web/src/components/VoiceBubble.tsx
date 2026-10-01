import { useVoice } from "../state/voice";
import { EchoFace } from "./EchoFace";

/**
 * El globito de "Hablar con Echo" (docs/plan-correcciones.md §7.6): abajo a la
 * derecha, siempre a mano, respetando las zonas seguras del iPhone. Liviano a
 * propósito: la carita de Echo y dos ondas en CSS (sin video), que se quedan
 * quietas con "reducir movimiento". Lo ve todo el mundo; a quien no tiene voz
 * en su plan, al tocarlo le explica y lo lleva a Planes.
 */
export function VoiceBubble() {
  const { open, isOpen } = useVoice();
  if (isOpen) return null;
  return (
    <button
      type="button"
      onClick={open}
      className="voice-bubble group fixed bottom-[max(1.25rem,env(safe-area-inset-bottom))] right-[max(1.25rem,env(safe-area-inset-right))] z-30 flex h-14 w-14 items-center justify-center rounded-full bg-ink-900 text-white shadow-[0_10px_30px_-8px_rgba(20,24,36,0.55)] transition-transform duration-200 hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent-500 active:scale-95"
      aria-label="Hablar con Echo"
      title="Hablar con Echo"
    >
      <span aria-hidden className="voice-bubble-wave absolute inset-0 rounded-full border-2 border-accent-400/60" />
      <span aria-hidden className="voice-bubble-wave voice-bubble-wave-late absolute inset-0 rounded-full border-2 border-accent-400/40" />
      <EchoFace mood="idle" size={28} />
    </button>
  );
}
