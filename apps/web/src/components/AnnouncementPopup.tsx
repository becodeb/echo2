import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { EchoFace } from "./EchoFace";
import { Button, Modal } from "./ui";

interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string | null;
}

/**
 * Avisos de la plataforma ("la transcripción ahora es más precisa"). Salen una
 * sola vez por persona: al cerrarlos, el servidor los marca leídos en todas sus
 * sedes (routers/notifications.py), así no vuelven en otro dispositivo.
 */
export function AnnouncementPopup() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const { data } = useQuery({
    queryKey: ["announcements", activeOrg?.id],
    queryFn: () =>
      api<{ notifications: NotificationItem[] }>("/api/notifications?unread_only=true"),
    enabled: !!activeOrg,
    staleTime: Infinity,
  });

  const announcement = (data?.notifications ?? []).find(
    (item) => item.kind.startsWith("announcement:") && !dismissed.has(item.id),
  );
  if (!announcement) return null;

  const close = () => {
    setDismissed((current) => new Set(current).add(announcement.id));
    void api(`/api/notifications/${announcement.id}/read`, { method: "POST" })
      .then(() => queryClient.invalidateQueries({ queryKey: ["notifications"] }))
      .catch(() => {});
  };

  return (
    <Modal open onClose={close} title="Novedades en Echo">
      <div className="space-y-4 text-center">
        <span className="inline-block text-accent-600">
          <EchoFace mood="done" size={56} />
        </span>
        <h3 className="text-lg font-semibold text-ink-900">{announcement.title}</h3>
        {announcement.body && <p className="text-sm leading-relaxed text-ink-600">{announcement.body}</p>}
        <Button onClick={close} className="w-full">
          ¡Buenísimo!
        </Button>
      </div>
    </Modal>
  );
}
