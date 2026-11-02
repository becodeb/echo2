import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CalendarLinkOut } from "../api/types";
import { useAuth } from "../state/auth";
import { Icon } from "./icons";
import { Button, Modal, Spinner } from "./ui";

/**
 * La Agenda en Google Calendar, iPhone u Outlook: un enlace personal que el
 * calendario vuelve a leer solo. Discreto, debajo del calendario del mes.
 */
export function CalendarConnect() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-full px-2 text-sm text-ink-500 hover:text-ink-800"
      >
        <Icon name="agenda" size={15} />
        Ver en mi calendario
      </button>
      <CalendarModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function CalendarModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const key = ["agenda-calendar", activeOrg?.id];
  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => api<CalendarLinkOut>("/api/agenda/calendar"),
    enabled: open,
  });
  const change = useMutation({
    mutationFn: (method: "POST" | "DELETE") => api<CalendarLinkOut>("/api/agenda/calendar", { method }),
    onSuccess: (link) => {
      queryClient.setQueryData(key, link);
      setCopied(false);
    },
  });

  const https = data?.path ? `${window.location.origin}${data.path}` : "";
  const webcal = https.replace(/^https?:/, "webcal:");

  return (
    <Modal open={open} onClose={onClose} title="Ver la Agenda en mi calendario">
      <p className="text-sm text-ink-600">
        Tus reuniones agendadas aparecen en Google Calendar, el del iPhone u Outlook, y se actualizan solas.
      </p>
      {isLoading && (
        <div className="flex justify-center py-6 text-ink-400">
          <Spinner className="h-5 w-5" />
        </div>
      )}
      {data && !data.path && (
        <div className="mt-4 flex justify-end">
          <Button disabled={change.isPending} onClick={() => change.mutate("POST")}>
            {change.isPending && <Spinner />}
            Crear mi enlace
          </Button>
        </div>
      )}
      {data?.path && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap gap-2">
            <a
              href={`https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal)}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-10 items-center rounded-full bg-ink-900 px-4 text-sm font-medium text-white hover:bg-ink-700"
            >
              Agregar a Google Calendar
            </a>
            <a
              href={webcal}
              className="inline-flex min-h-10 items-center rounded-full bg-ink-100 px-4 text-sm font-medium text-ink-800 hover:bg-ink-200"
            >
              iPhone, Mac u Outlook
            </a>
          </div>
          <div className="flex gap-2">
            <input
              readOnly
              aria-label="Enlace del calendario"
              value={https}
              onFocus={(event) => event.currentTarget.select()}
              className="min-w-0 flex-1 rounded-full border border-ink-200 bg-ink-50 px-3 text-xs text-ink-600"
            />
            <Button variant="soft" onClick={() => navigator.clipboard?.writeText(https).then(() => setCopied(true))}>
              {copied ? "Copiado" : "Copiar"}
            </Button>
          </div>
          <p className="text-xs text-ink-500">
            Google tarda unas horas en traer los cambios. El enlace es personal y lleva nombres de familias: no lo
            compartas.
          </p>
          <div className="flex flex-wrap gap-x-3 text-xs">
            <button
              type="button"
              disabled={change.isPending}
              onClick={() => change.mutate("POST")}
              className="min-h-9 text-ink-500 underline-offset-2 hover:text-ink-800 hover:underline"
            >
              Hacer un enlace nuevo (corta el anterior)
            </button>
            <button
              type="button"
              disabled={change.isPending}
              onClick={() => change.mutate("DELETE")}
              className="min-h-9 text-ink-500 underline-offset-2 hover:text-red-700 hover:underline"
            >
              Desconectar
            </button>
          </div>
        </div>
      )}
      {change.isError && (
        <p className="mt-2 text-sm text-red-700">
          {change.error instanceof Error ? change.error.message : "No se pudo cambiar el enlace"}
        </p>
      )}
    </Modal>
  );
}
