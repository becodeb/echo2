import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, apiDownload } from "../api/client";
import type { MeetingOut, RecordingState } from "../api/types";
import { useMyDrive } from "./RecordToggle";
import { Button, Card, Spinner, formatDuration } from "./ui";

const size = (bytes: number | null) =>
  bytes ? `${(bytes / (1024 * 1024)).toFixed(bytes > 10 * 1024 * 1024 ? 0 : 1)} MB` : null;

const until = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("es", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })
    : null;

/**
 * La grabación del audio completo. Echo no la guarda: la sube al Drive de quien
 * grabó o la deja para descargar un rato y la borra (services/recording.py).
 */
export function RecordingCard({ meeting }: { meeting: MeetingOut }) {
  const queryClient = useQueryClient();
  const recording = meeting.recording;
  const { data: drive } = useMyDrive(!!recording);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (state: RecordingState) =>
    queryClient.setQueryData<MeetingOut>(["meeting", meeting.id], (current) =>
      current ? { ...current, recording: state } : current,
    );
  const toDrive = useMutation({
    mutationFn: () => api<RecordingState>(`/api/meetings/${meeting.id}/recording/drive`, { method: "POST" }),
    onSuccess: update,
    onError: (err) => setError(err instanceof Error ? err.message : "No se pudo subir"),
  });
  const discard = useMutation({
    mutationFn: () => api<RecordingState>(`/api/meetings/${meeting.id}/recording/file`, { method: "DELETE" }),
    onSuccess: update,
  });

  if (!recording || (!recording.enabled && recording.status !== "discarded")) return null;

  const details = [
    recording.duration_seconds ? formatDuration(recording.duration_seconds) : null,
    size(recording.size_bytes),
  ]
    .filter(Boolean)
    .join(" · ");

  const download = async () => {
    setDownloading(true);
    setError(null);
    try {
      await apiDownload(`/api/meetings/${meeting.id}/recording/file`, `${meeting.title}.mp3`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo descargar");
    } finally {
      setDownloading(false);
    }
  };

  let body: ReactNode;
  switch (recording.status) {
    case "pending":
    case "recording":
      body = <p className="text-sm text-ink-600">Se está grabando. Al finalizar la reunión se guarda el audio.</p>;
      break;
    case "processing":
      body = (
        <p className="flex items-center gap-2 text-sm text-ink-600">
          <Spinner className="h-3.5 w-3.5" /> Preparando el audio y subiéndolo…
        </p>
      );
      break;
    case "uploaded":
      body = (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ink-600">
            Guardado en Google Drive{details && ` · ${details}`}. Echo no se quedó con una copia.
          </p>
          {recording.drive_url && (
            <a href={recording.drive_url} target="_blank" rel="noopener noreferrer">
              <Button variant="soft">Abrir en Drive ↗</Button>
            </a>
          )}
        </div>
      );
      break;
    case "download":
      body = (
        <div className="space-y-3">
          <p className="text-sm text-ink-600">
            Disponible para descargar hasta el <strong>{until(recording.expires_at)}</strong>
            {details && ` · ${details}`}. Después se borra de Echo.
          </p>
          {recording.error && <p className="text-sm text-amber-700">{recording.error}</p>}
          <div className="flex flex-wrap gap-2">
            <Button onClick={download} disabled={downloading}>
              {downloading ? <Spinner /> : "Descargar audio"}
            </Button>
            {drive?.connected ? (
              <Button variant="soft" onClick={() => toDrive.mutate()} disabled={toDrive.isPending}>
                {toDrive.isPending ? <Spinner /> : "Guardar en mi Drive"}
              </Button>
            ) : (
              drive?.enabled && (
                <Link to="/settings/my-drive">
                  <Button variant="soft">Conectar mi Drive</Button>
                </Link>
              )
            )}
            <Button variant="ghost" onClick={() => discard.mutate()} disabled={discard.isPending}>
              Borrar ya
            </Button>
          </div>
        </div>
      );
      break;
    case "expired":
      body = <p className="text-sm text-ink-500">El audio se borró de Echo al vencer el plazo de descarga.</p>;
      break;
    case "discarded":
      body = <p className="text-sm text-ink-500">El audio se descartó.</p>;
      break;
    case "empty":
      body = <p className="text-sm text-ink-500">No llegó audio para grabar en esta reunión.</p>;
      break;
    default:
      body = <p className="text-sm text-red-600">{recording.error ?? "No se pudo preparar el audio."}</p>;
  }

  return (
    <Card className="space-y-2">
      <h3 className="text-sm font-semibold text-ink-900">Grabación</h3>
      {body}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </Card>
  );
}
