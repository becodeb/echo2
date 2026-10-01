import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api, apiDownload } from "../api/client";
import { Button, Spinner } from "./ui";
import { useMyDrive } from "./RecordToggle";

type Kind = "minutes" | "transcript";

const FORMATS: { fmt: string; label: string; hint: string }[] = [
  { fmt: "pdf", label: "PDF", hint: "Para imprimir o mandar" },
  { fmt: "docx", label: "Word (.docx)", hint: "Para seguir editando" },
  { fmt: "md", label: "Markdown (.md)", hint: "Texto con formato" },
  { fmt: "txt", label: "Texto plano (.txt)", hint: "Sin formato" },
];

/**
 * «Exportar» con todos los formatos. Las descargas van por fetch con el token:
 * un link directo al export no lo lleva y el API responde 401.
 * «Documento de Google» aparece si la persona conectó su Drive.
 */
export function ExportMenu({
  meetingId,
  kind,
  title,
  disabled = false,
}: {
  meetingId: string;
  kind: Kind;
  title: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const { data: drive } = useMyDrive(open);
  const [docUrl, setDocUrl] = useState<string | null>(null);
  const prefix = kind === "minutes" ? "acta" : "transcript";

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent | TouchEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const download = useMutation({
    mutationFn: (fmt: string) =>
      apiDownload(`/api/meetings/${meetingId}/export/${kind}.${fmt}`, `${prefix}-${title}.${fmt}`),
    onSuccess: () => setOpen(false),
  });
  const googleDoc = useMutation({
    mutationFn: () =>
      api<{ url: string }>(`/api/meetings/${meetingId}/export/${kind}/google-doc`, { method: "POST" }),
    onSuccess: (result) => setDocUrl(result.url),
  });

  const error = download.error ?? googleDoc.error;
  const busy = download.isPending || googleDoc.isPending;

  return (
    <div ref={boxRef} className="relative inline-block">
      <Button
        variant="ghost"
        onClick={() => {
          setOpen((current) => !current);
          setDocUrl(null);
        }}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Exportar
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="ml-1" aria-hidden>
          <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-1 w-64 rounded-2xl border border-ink-100 bg-white p-1.5 shadow-lg"
        >
          {FORMATS.map((item) => (
            <button
              key={item.fmt}
              role="menuitem"
              type="button"
              disabled={busy}
              onClick={() => download.mutate(item.fmt)}
              className="flex w-full flex-col rounded-xl px-3 py-2 text-left hover:bg-ink-50 disabled:opacity-50"
            >
              <span className="text-sm font-medium text-ink-800">{item.label}</span>
              <span className="text-xs text-ink-400">{item.hint}</span>
            </button>
          ))}
          {drive?.enabled && (
            <div className="mt-1 border-t border-ink-100 pt-1">
              {drive.connected ? (
                docUrl ? (
                  <a
                    href={docUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-xl px-3 py-2 text-sm font-medium text-accent-600 hover:bg-ink-50"
                  >
                    Documento creado: abrir en Google Docs ↗
                  </a>
                ) : (
                  <button
                    type="button"
                    role="menuitem"
                    disabled={busy}
                    onClick={() => googleDoc.mutate()}
                    className="flex w-full flex-col rounded-xl px-3 py-2 text-left hover:bg-ink-50 disabled:opacity-50"
                  >
                    <span className="flex items-center gap-2 text-sm font-medium text-ink-800">
                      Documento de Google {googleDoc.isPending && <Spinner className="h-3.5 w-3.5" />}
                    </span>
                    <span className="text-xs text-ink-400">Se crea en tu Drive ({drive.connected_email})</span>
                  </button>
                )
              ) : (
                <Link
                  to="/settings/my-drive"
                  className="block rounded-xl px-3 py-2 text-sm text-ink-500 hover:bg-ink-50"
                >
                  <span className="font-medium text-accent-600">Conectá tu Drive</span> para crear un Documento de
                  Google
                </Link>
              )}
            </div>
          )}
          {error && (
            <p className="px-3 py-2 text-xs text-red-600">
              {error instanceof Error ? error.message : "No se pudo exportar"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
