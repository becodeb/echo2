import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AttachmentOut } from "../api/types";
import { Button, Input, Spinner } from "./ui";

/**
 * Enlaces adjuntos a la reunión: informes, planillas, carpetas de Drive.
 *
 * Echo guarda la URL y nada más. El material sigue viviendo donde la
 * institución ya lo tiene, igual que el audio no se guarda en ningún lado.
 */

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function Attachments({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");

  const { data: attachments } = useQuery({
    queryKey: ["attachments", meetingId],
    queryFn: () => api<AttachmentOut[]>(`/api/meetings/${meetingId}/attachments`),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["attachments", meetingId] });

  const add = useMutation({
    mutationFn: () =>
      api<AttachmentOut>(`/api/meetings/${meetingId}/attachments`, {
        method: "POST",
        body: JSON.stringify({ url, title: title || null }),
      }),
    onSuccess: () => {
      setUrl("");
      setTitle("");
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) =>
      api(`/api/meetings/${meetingId}/attachments/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (url.trim()) add.mutate();
  };

  return (
    <div className="space-y-3">
      <h2 className="text-[15px] font-semibold text-ink-900">Enlaces</h2>

      {(attachments ?? []).length > 0 && (
        <ul className="space-y-1.5">
          {(attachments ?? []).map((item) => (
            <li key={item.id} className="flex items-center gap-2 text-sm">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="truncate font-medium text-accent-600 hover:underline"
                title={item.url}
              >
                {item.title || hostOf(item.url)}
              </a>
              <span className="shrink-0 text-xs text-ink-400">{hostOf(item.url)}</span>
              <button
                onClick={() => remove.mutate(item.id)}
                className="ml-auto shrink-0 text-xs text-ink-400 hover:text-red-600"
              >
                Quitar
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="min-w-[200px] flex-1">
          <Input
            placeholder="https://…"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
        </div>
        <div className="min-w-[140px]">
          <Input
            placeholder="Nombre (opcional)"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <Button type="submit" variant="soft" disabled={add.isPending}>
          {add.isPending ? <Spinner /> : "Adjuntar"}
        </Button>
      </form>
      {add.isError && (
        <p className="text-sm text-red-600">
          {add.error instanceof Error ? add.error.message : "No se pudo adjuntar"}
        </p>
      )}
    </div>
  );
}
