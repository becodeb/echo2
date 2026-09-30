import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { EchoFace } from "./EchoFace";
import { Button, Modal } from "./ui";

interface VoiceState {
  has_sample: boolean;
  prompt_seen: boolean;
}

/**
 * Invitación a grabar la muestra de voz ("Mi voz"), una sola vez: al entrar
 * después de crear la cuenta, o al volver a entrar quien todavía no la tiene.
 * Al cerrarla (grabe o no) el servidor guarda que ya la vio.
 * Espera a que no haya un aviso de novedades abierto, para no apilar ventanas.
 */
export function VoicePrompt() {
  const { activeOrg } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [closed, setClosed] = useState(false);

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

  if (closed || !voice || voice.has_sample || voice.prompt_seen || !announcements || announcementOpen) return null;

  const close = (then?: () => void) => {
    setClosed(true);
    void api("/api/me/voice/prompt-seen", { method: "POST", skipOrg: true })
      .then(() => queryClient.invalidateQueries({ queryKey: ["my-voice-prompt"] }))
      .catch(() => {});
    then?.();
  };

  return (
    <Modal open onClose={() => close()} title="Tu voz en Echo">
      <div className="space-y-5 text-center">
        <span className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-ink-50 text-ink-900">
          <EchoFace mood="listening" size={40} />
        </span>
        <div>
          <h3 className="text-xl font-semibold tracking-tight text-ink-900">Que Echo sepa cuando hablás vos</h3>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-ink-500">
            Grabá unos segundos de tu voz y en tus reuniones vas a aparecer con tu nombre, no como "Persona 1". La
            muestra se usa solo para eso y la podés borrar cuando quieras.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row-reverse">
          <Button className="flex-1 rounded-full py-2.5" onClick={() => close(() => navigate("/settings/my-voice"))}>
            Grabar mi voz
          </Button>
          <Button variant="ghost" className="flex-1 rounded-full py-2.5" onClick={() => close()}>
            Ahora no
          </Button>
        </div>
      </div>
    </Modal>
  );
}
