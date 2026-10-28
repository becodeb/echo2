import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { EchoFace } from "./EchoFace";
import { Icon } from "./icons";
import { Modal } from "./ui";
import type { MyVoice } from "./VoiceRecorder";

// El grabador no viaja en el arranque de la app: se baja al abrir un aviso.
const VoiceRecorder = lazy(() => import("./VoiceRecorder").then((module) => ({ default: module.VoiceRecorder })));

/*
 * Grabar "Mi voz" es "medio obligatorio" (pedido de Bauti, 27/10): con ella
 * Echo reconoce a cada uno en las reuniones sin depender de que digan su
 * nombre. Mientras falte (o sea una de antes del mínimo de 8 s, que Echo no
 * usa) se pide por cuatro lados:
 * - VoiceNudge: fijo en la barra lateral (en el celular, una línea arriba del
 *   contenido). "Más tarde" lo achica unas horas, nunca lo saca.
 * - VoicePrompt: la ventana al entrar; "Más tarde" la frena un día (lo guarda
 *   el servidor). El viejo "No volver a mostrar" ya no existe.
 * - VoiceBeforeMeeting: antes de iniciar una reunión, sin frenarla.
 * - La campanita, cada 3 días (services/voice_reminder.py en la API).
 */

export function useMyVoice() {
  return useQuery({
    queryKey: ["my-voice"],
    queryFn: () => api<MyVoice>("/api/me/voice", { skipOrg: true }),
    staleTime: 5 * 60_000,
  });
}

/** Le falta la voz: no la grabó, o la que tiene quedó corta y Echo no la usa. */
export function needsVoice(voice: MyVoice | undefined): boolean {
  return !!voice && (!voice.has_sample || voice.warning === "corta");
}

const isLive = (pathname: string) => /^\/meetings\/[^/]+\/live/.test(pathname);

/** El grabador en una ventana; queda abierta después de guardar para mostrar el "¡Listo!". */
function RecordVoiceModal({
  open,
  onClose,
  title,
  heading,
  text,
  done,
  later,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  heading: string;
  text: ReactNode;
  /** Botón al terminar de guardar. */
  done: { label: string; onClick: () => void };
  /** La otra salida mientras no la grabó. */
  later: { label: string; onClick: () => void; dismissible: boolean };
}) {
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (open) setSaved(false);
  }, [open]);
  return (
    <Modal open={open} onClose={onClose} title={title} dismissible={saved || later.dismissible}>
      <div className="space-y-5">
        <div className="text-center">
          <span className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-ink-50 text-ink-900">
            <EchoFace mood="listening" size={40} />
          </span>
          <h3 className="mt-3 text-xl font-semibold tracking-tight text-ink-900">{heading}</h3>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-ink-500">{text}</p>
        </div>
        {open && (
          <Suspense fallback={null}>
            <VoiceRecorder compact onSaved={() => setSaved(true)} />
          </Suspense>
        )}
        {/* En el celular queda fijo abajo: "Ahora no, empezar igual" siempre a la vista. */}
        <div className="sticky -bottom-3 -mx-5 border-t border-ink-100 bg-white px-5 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:static sm:mx-0 sm:border-0 sm:p-0">
          {saved ? (
            <button
              onClick={done.onClick}
              className="min-h-11 w-full rounded-full bg-ink-900 text-sm font-medium text-white hover:bg-ink-700"
            >
              {done.label}
            </button>
          ) : (
            <button
              onClick={later.onClick}
              className="min-h-11 w-full rounded-full bg-ink-50 text-sm font-medium text-ink-600 hover:bg-ink-100 hover:text-ink-900"
            >
              {later.label}
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}

const WHY =
  'En tus reuniones vas a aparecer con tu nombre, no como "Persona 1". Es la forma más segura de que Echo sepa quién habló. Se usa solo para eso y la podés borrar cuando quieras.';

/**
 * La ventana al entrar a Echo. "Más tarde" la frena un día (el servidor
 * guarda cuándo). No aparece en la reunión en vivo (no tapa el botón de
 * grabar) ni sobre un aviso de novedades abierto, para no apilar ventanas.
 */
export function VoicePrompt() {
  const { activeOrg } = useAuth();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(true);
  const live = isLive(useLocation().pathname);
  const { data: voice } = useMyVoice();
  const { data: announcements } = useQuery({
    queryKey: ["announcements", activeOrg?.id],
    queryFn: () =>
      api<{ notifications: { kind: string }[] }>("/api/notifications?unread_only=true"),
    enabled: !!activeOrg,
    staleTime: Infinity,
  });
  const announcementOpen = (announcements?.notifications ?? []).some((item) => item.kind.startsWith("announcement:"));
  // Se decide una vez: al guardar deja de faltar la voz, pero la ventana sigue con el "¡Listo!".
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!show && open && !live && voice && needsVoice(voice) && !voice.prompt_seen && announcements && !announcementOpen) {
      setShow(true);
    }
  }, [show, open, live, voice, announcements, announcementOpen]);

  if (!show) return null;
  const later = () => {
    setOpen(false);
    void api("/api/me/voice/prompt-seen", { method: "POST", skipOrg: true })
      .then(() => queryClient.invalidateQueries({ queryKey: ["my-voice"] }))
      .catch(() => {});
  };
  return (
    <RecordVoiceModal
      open={open}
      onClose={() => setOpen(false)}
      title="Tu voz en Echo"
      heading="Que Echo sepa cuando hablás vos"
      text={
        voice?.has_sample
          ? `La grabación que tenés quedó corta y Echo no la usa. Grabala de nuevo: son 12 segundos. ${WHY}`
          : `Grabá 12 segundos de tu voz. ${WHY}`
      }
      done={{ label: "Listo", onClick: () => setOpen(false) }}
      later={{ label: "Más tarde", onClick: later, dismissible: false }}
    />
  );
}

// "Más tarde" en el aviso fijo: lo achica por un rato, en este navegador.
const LATER_KEY = "echo_voz_mas_tarde";
const LATER_MS = 4 * 60 * 60_000;

function laterUntil(): number {
  try {
    return Number(localStorage.getItem(LATER_KEY)) || 0;
  } catch {
    return 0;
  }
}

/**
 * El aviso fijo: en la barra lateral ("sidebar"; "icon" con la barra en
 * íconos) o una línea arriba del contenido en el celular ("mobile"). No tiene cruz:
 * está hasta que la persona grabe su voz. Fuera de la reunión en vivo.
 */
export function VoiceNudge({ variant }: { variant: "sidebar" | "icon" | "mobile" }) {
  const { data: voice } = useMyVoice();
  const live = isLive(useLocation().pathname);
  const [recording, setRecording] = useState(false);
  const [small, setSmall] = useState(() => laterUntil() > Date.now());

  // Pasado el rato vuelve a agrandarse, aunque no se cambie de página.
  useEffect(() => {
    if (!small) return;
    const timer = window.setTimeout(() => setSmall(false), Math.max(0, laterUntil() - Date.now()));
    return () => window.clearTimeout(timer);
  }, [small]);

  const later = () => {
    try {
      localStorage.setItem(LATER_KEY, String(Date.now() + LATER_MS));
    } catch {
      // Sin almacenamiento se achica igual, hasta recargar.
    }
    setSmall(true);
  };
  const short = !!voice?.has_sample;
  const visible = !live && needsVoice(voice);

  const modal = (
    <RecordVoiceModal
      open={recording}
      onClose={() => setRecording(false)}
      title="Tu voz en Echo"
      heading={short ? "Grabá tu voz de nuevo" : "Que Echo sepa cuando hablás vos"}
      text={short ? `La grabación que tenés quedó corta y Echo no la usa. ${WHY}` : WHY}
      done={{ label: "Listo", onClick: () => setRecording(false) }}
      later={{ label: "Más tarde", onClick: () => setRecording(false), dismissible: true }}
    />
  );
  if (!visible) return modal;

  const open = () => setRecording(true);
  const message = short
    ? "Tu grabación de voz quedó corta. Grabala de nuevo (12 segundos) para que Echo sepa cuándo hablás."
    : "Grabá tu voz (12 segundos) para que Echo sepa cuándo hablás.";

  if (variant === "icon") {
    return (
      <>
        <button
          type="button"
          onClick={open}
          title={message}
          aria-label="Grabar mi voz"
          className="relative mx-auto mb-2 hidden h-10 w-10 items-center justify-center rounded-full bg-ink-900 text-white hover:bg-ink-700 md:flex"
        >
          <Icon name="mic" size={18} />
          <span className="recording-dot absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-[#f1f2f5]" />
        </button>
        {modal}
      </>
    );
  }

  if (variant === "mobile") {
    // Una línea fina, entera tocable: en el celular no puede comerse la quinta parte
    // de la pantalla en cada página. La insistencia la pone la ventana al entrar.
    return (
      <>
        <button
          type="button"
          onClick={open}
          className="flex min-h-9 w-full items-center gap-2 border-b border-accent-100 bg-accent-50 px-4 text-left text-[13px] text-ink-800 md:hidden"
        >
          <span className="relative flex shrink-0 text-accent-600">
            <Icon name="mic" size={15} />
            <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-red-500" />
          </span>
          <span className="min-w-0 flex-1 truncate">{short ? "Tu voz quedó corta · grabala de nuevo" : "Falta grabar tu voz · 12 s"}</span>
          <span className="shrink-0 font-semibold text-accent-700">Grabar</span>
        </button>
        {modal}
      </>
    );
  }

  return (
    <>
      {small ? (
        <button
          type="button"
          onClick={open}
          title={message}
          className="mb-2 flex w-full items-center gap-2.5 rounded-2xl border border-accent-100 bg-accent-50 px-3 py-2 text-left text-[13px] font-medium text-ink-800 transition-colors hover:border-accent-300"
        >
          <span className="relative flex text-accent-600">
            <Icon name="mic" size={17} />
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-red-500" />
          </span>
          <span className="min-w-0 flex-1 truncate">Falta grabar tu voz</span>
          <span className="text-[11px] text-ink-400">12 s</span>
        </button>
      ) : (
        <div className="mb-2 rounded-3xl border border-accent-100 bg-accent-50 p-3.5" role="status">
          <div className="flex items-center gap-2 text-accent-700">
            <Icon name="mic" size={17} />
            <span className="text-xs font-semibold">Falta tu voz</span>
          </div>
          <p className="mt-1.5 text-[13px] leading-snug text-ink-800">{message}</p>
          <button
            type="button"
            onClick={open}
            className="mt-3 flex min-h-9 w-full items-center justify-center gap-1.5 rounded-full bg-ink-900 text-[13px] font-semibold text-white transition-colors hover:bg-ink-700"
          >
            <span className="h-2 w-2 rounded-full bg-red-500" aria-hidden /> Grabar mi voz
          </button>
          <button
            type="button"
            onClick={later}
            className="mt-1 w-full rounded-full py-1.5 text-xs font-medium text-ink-500 hover:text-ink-800"
          >
            Más tarde
          </button>
        </div>
      )}
      {modal}
    </>
  );
}

/**
 * Antes de iniciar una reunión, a quien le falta la voz: grabarla ahí mismo o
 * "Ahora no, empezar igual". Nunca frena la reunión: puede haber familias
 * esperando.
 */
export function VoiceBeforeMeeting({ open, onClose, onStart }: { open: boolean; onClose: () => void; onStart: () => void }) {
  return (
    <RecordVoiceModal
      open={open}
      onClose={onClose}
      title="Tu voz en Echo"
      heading="Antes de empezar, grabá tu voz: 12 segundos"
      text="Así Echo sabe cuándo hablás vos y en el resumen aparecés con tu nombre, no como «Persona 1». Si te están esperando, podés hacerlo después."
      done={{ label: "Iniciar reunión", onClick: onStart }}
      later={{ label: "Ahora no, empezar igual", onClick: onStart, dismissible: true }}
    />
  );
}
