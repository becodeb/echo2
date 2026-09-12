import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LetterheadOut, MeetingOut, MinutesOut } from "../api/types";
import { MarkdownView } from "../components/MarkdownView";
import { Spinner, formatDate, formatDuration } from "../components/ui";
import "./acta-print.css";

/**
 * La hoja del acta tal como se imprime: membrete de la organización (líneas,
 * logo, dirección), título, datos de la reunión, el acta y las firmas. Con
 * ?print=1 abre el diálogo de impresión apenas carga.
 */
export default function ActaPrint() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();

  const { data: meeting } = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<MeetingOut>(`/api/meetings/${id}`),
    enabled: !!id,
  });
  const { data: minutes } = useQuery({
    queryKey: ["minutes", id],
    queryFn: () => api<MinutesOut | null>(`/api/meetings/${id}/minutes`),
    enabled: !!id,
  });
  const { data: letterhead } = useQuery({
    queryKey: ["letterhead"],
    queryFn: () => api<LetterheadOut>("/api/org/letterhead"),
  });

  const ready = !!meeting && minutes !== undefined && !!letterhead;

  useEffect(() => {
    if (!ready || params.get("print") !== "1") return;
    // Un respiro para que el logo (data URL) y las fuentes estén pintados.
    const timer = window.setTimeout(() => window.print(), 400);
    return () => window.clearTimeout(timer);
  }, [ready, params]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const version = minutes?.version ?? null;
  const body = version?.body_markdown ?? "";
  // Si el modelo ya trae su propio título como encabezado, no lo repetimos.
  const bodyHasTitle = /^\s*#\s/.test(body);
  const contact = [letterhead.address, letterhead.phone, letterhead.email].filter(Boolean).join(" · ");

  return (
    <div className="acta-print">
      <div className="acta-print-toolbar no-print">
        <Link to={`/meetings/${id}?tab=minutes`} className="acta-print-link">
          Volver a la reunión
        </Link>
        <div className="flex items-center gap-3">
          {minutes?.status !== "approved" && <span className="text-sm text-ink-500">Borrador</span>}
          <button type="button" className="acta-print-btn" onClick={() => window.print()}>
            Imprimir
          </button>
        </div>
      </div>

      <article className="acta-hoja-print">
        <header className="acta-print-membrete">
          <div className="acta-print-lineas">
            {letterhead.lines.map((line, index) => (
              <p key={index}>{line}</p>
            ))}
          </div>
          {letterhead.logo_data_url && (
            <img src={letterhead.logo_data_url} alt={letterhead.institution} className="acta-print-logo" />
          )}
        </header>
        <p className="acta-print-institucion">
          <strong>{letterhead.institution}</strong>
          {contact && <span> · {contact}</span>}
        </p>

        {!bodyHasTitle && <h1 className="acta-print-titulo">{letterhead.title}</h1>}

        <p className="acta-print-meta">
          {meeting.title} · {formatDate(meeting.started_at)} · {formatDuration(meeting.duration_seconds)}
          {meeting.participants.length > 0 &&
            ` · ${meeting.participants.map((participant) => participant.name).join(", ")}`}
        </p>

        {version ? (
          <MarkdownView markdown={body} />
        ) : (
          <p className="text-ink-500">Todavía no hay acta para esta reunión.</p>
        )}

        {letterhead.signatures.length > 0 && (
          <div className="acta-print-firmas">
            {letterhead.signatures.map((label, index) => (
              <span key={index}>{label}</span>
            ))}
          </div>
        )}

        <p className="acta-print-pie">
          {minutes?.status === "approved" ? "Acta aprobada" : "Borrador sujeto a revisión"}
          {version?.version ? ` · versión ${version.version}` : ""} · Generada con Echo
        </p>
      </article>
    </div>
  );
}
