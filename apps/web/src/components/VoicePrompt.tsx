import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { EchoFace } from "./EchoFace";
import { Modal } from "./ui";
import { VoiceRecorder } from "./VoiceRecorder";

interface VoiceState {
  has_sample: boolean;
  prompt_seen: boolean;
}

// Cerrada con "Ahora no": no vuelve hasta la próxima vez que se entra a Echo
// (otra pestaña o volver a abrir el navegador), no en cada recarga.
const DISMISSED_KEY = "echo_mi_voz_ahora_no";

function dismissedThisVisit(): boolean {
  try {
    return sessionStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Invitación a grabar la muestra de voz ("Mi voz"): con ella Echo reconoce a
 * cada uno en las reuniones sin depender de que digan su nombre. Aparece cada
 * vez que se entra a Echo, a quien todavía no la grabó, hasta que la graba o
 * elige "No volver a mostrar" (eso lo guarda el servidor).
 * Se graba ahí mismo (VoiceRecorder), sin ir a Ajustes.
 * Espera a que no haya un aviso de novedades abierto, para no apilar ventanas.
 */
export function VoicePrompt() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [closed, setClosed] = useState(dismissedThisVisit);
  const [saved, setSaved] = useState(false);

  const { data: voice } = useQuery({
    queryKey: ["my-voice-prompt"],
    queryFn: () => api<VoiceState>("/api/me/voice", { skipOrg: true }),
    staleTime: Infinity,
  });
  const { data: announcements } = useQuery({
    queryKey: ["announcements", activeOrg?.id],
    queryFn: () =>
      api<{ notifications: { kind: string }[] }>("/api/notifications?unread_only=true"),
    enabled: !!activeOrg,
    staleTime: Infinity,
  });
  const announcementOpen = (announcements?.notifications ?? []).some((item) => item.kind.startsWith("announcement:"));

  // Una vez guardada, el aviso sigue abierto para mostrar el "¡Listo!".
  if (closed || !voice || (voice.has_sample && !saved) || voice.prompt_seen || !announcements || announcementOpen) {
    return null;
  }

  const close = () => {
    setClosed(true);
    try {
      sessionStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      // Sin almacenamiento: vuelve a aparecer al recargar.
    }
  };

  const never = () => {
    setClosed(true);
    void api("/api/me/voice/prompt-seen", { method: "POST", skipOrg: true })
      .then(() => queryClient.invalidateQueries({ queryKey: ["my-voice-prompt"] }))
      .catch(() => {});
  };

  return (
    <Modal open onClose={() => close()} title="Tu voz en Echo">
      <div className="space-y-5">
        <div className="text-center">
          <span className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-ink-50 text-ink-900">
            <EchoFace mood="listening" size={40} />
          </span>
          <h3 className="mt-3 text-xl font-semibold tracking-tight text-ink-900">Que Echo sepa cuando hablás vos</h3>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-ink-500">
            Grabá 10 segundos de tu voz y en tus reuniones vas a aparecer con tu nombre, no como "Persona 1". Es la
            forma más segura de que Echo sepa quién habló. Se usa solo para eso y la podés borrar cuando quieras.
          </p>
        </div>
        <VoiceRecorder compact onSaved={() => setSaved(true)} />
        <div className="space-y-1">
          <button
            onClick={() => close()}
            className="min-h-11 w-full rounded-full text-sm font-medium text-ink-500 hover:bg-ink-50 hover:text-ink-800"
          >
            {saved ? "Listo" : "Ahora no"}
          </button>
          {!saved && (
            <button
              onClick={() => never()}
              className="min-h-11 w-full rounded-full text-xs text-ink-400 hover:bg-ink-50 hover:text-ink-700"
            >
              No volver a mostrar este mensaje
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}
