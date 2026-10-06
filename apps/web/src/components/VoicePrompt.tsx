import { useState } from "react";
import { useLocation } from "react-router-dom";
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

/**
 * Invitación a grabar la muestra de voz ("Mi voz"): con ella Echo reconoce a
 * cada uno en las reuniones sin depender de que digan su nombre. A quien
 * todavía no la grabó le aparece al entrar a Echo y lo más fácil es grabarla:
 * no hay cruz ni "Ahora no", la única otra salida es "No volver a mostrar"
 * (lo guarda el servidor). Se graba ahí mismo (VoiceRecorder).
 * No aparece en la reunión en vivo (no tapa el botón de grabar) ni sobre un
 * aviso de novedades abierto, para no apilar ventanas.
 */
export function VoicePrompt() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [closed, setClosed] = useState(false);
  const [saved, setSaved] = useState(false);
  const live = /^\/meetings\/[^/]+\/live/.test(useLocation().pathname);

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
  if (
    closed ||
    live ||
    !voice ||
    (voice.has_sample && !saved) ||
    voice.prompt_seen ||
    !announcements ||
    announcementOpen
  ) {
    return null;
  }

  const never = () => {
    setClosed(true);
    void api("/api/me/voice/prompt-seen", { method: "POST", skipOrg: true })
      .then(() => queryClient.invalidateQueries({ queryKey: ["my-voice-prompt"] }))
      .catch(() => {});
  };

  return (
    <Modal open onClose={() => setClosed(true)} title="Tu voz en Echo" dismissible={false}>
      <div className="space-y-5">
        <div className="text-center">
          <span className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-ink-50 text-ink-900">
            <EchoFace mood="listening" size={40} />
          </span>
          <h3 className="mt-3 text-xl font-semibold tracking-tight text-ink-900">Que Echo sepa cuando hablás vos</h3>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-ink-500">
            Grabá 12 segundos de tu voz y en tus reuniones vas a aparecer con tu nombre, no como "Persona 1". Es la
            forma más segura de que Echo sepa quién habló. Se usa solo para eso y la podés borrar cuando quieras.
          </p>
        </div>
        <VoiceRecorder compact onSaved={() => setSaved(true)} />
        {saved ? (
          <button
            onClick={() => setClosed(true)}
            className="min-h-11 w-full rounded-full bg-ink-900 text-sm font-medium text-white hover:bg-ink-700"
          >
            Listo
          </button>
        ) : (
          <button
            onClick={() => never()}
            className="min-h-11 w-full rounded-full text-xs text-ink-400 hover:bg-ink-50 hover:text-ink-700"
          >
            No volver a mostrar este mensaje
          </button>
        )}
      </div>
    </Modal>
  );
}
