import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, getAccessToken, refreshAccessToken, wsUrl } from "../api/client";
import type { LiveEvent, MeetingOut, RecordingState } from "../api/types";
import { MicrophoneSource, SystemAudioSource, canCaptureSystemAudio, listMicrophones, type AudioSource } from "../lib/audio";
import { BridgeSttSession, checkBridge, type BridgeHealth } from "../lib/bridge";
import { RecordToggle } from "../components/RecordToggle";
import { ChoiceCards, PillSwitch, SettingRow, SettingsGroup } from "../components/SettingRows";
import { Select } from "../components/Select";
import { Button, Modal, Spinner, formatMs } from "../components/ui";
import { EchoFace, type EchoMood } from "../components/EchoFace";
import { micErrorMessage } from "../lib/micError";

interface LiveLine {
  key: string;
  seq: number;
  start_ms: number;
  text: string;
  speaker_hint: string | null;
  confidence: number | null;
}

type EngineMode = "bridge" | "cloud";

// Sin frames durante este tiempo = el sistema cortó el micrófono. El worklet
// manda frames también en silencio, así que un silencio de la sala no cuenta.
const STALL_MS = 4000;
// Audio y texto que se guardan mientras se reconecta con el servidor y se
// mandan al volver (5 min de frames de 100 ms). Antes se tiraban: faltaban
// en el transcript y también en el audio de la transcripción final.
const MAX_PENDING_SENDS = 3000;
// Tope para esperar que el servidor transcriba lo último al finalizar.
const FLUSH_TIMEOUT_MS = 20000;

/** Web app agregada a la pantalla de inicio del iPhone/iPad. Ahí iOS corta el
 *  micrófono al bloquear la pantalla o cambiar de app (en Safari no): la web
 *  app no tiene el modo de fondo "audio" que sí tiene Safari. WebKit 226620. */
function isIOSHomeScreenApp(): boolean {
  const ios =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone =
    (navigator as Navigator & { standalone?: boolean }).standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches;
  return ios && standalone;
}

const clock = (ms: number) =>
  new Date(ms).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });

const gapLabel = (ms: number) =>
  ms < 60_000 ? `${Math.max(1, Math.round(ms / 1000))} s` : `${Math.round(ms / 60_000)} min`;

interface Interruption {
  from: number;
  /** null mientras sigue cortado. */
  to: number | null;
}

export default function MeetingLive() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: meeting } = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<MeetingOut>(`/api/meetings/${id}`),
    enabled: !!id,
  });

  // ── estado de captura ──────────────────────────────────────────
  const [recording, setRecording] = useState(false);
  const [paused, setPaused] = useState(false);
  const [level, setLevel] = useState(0);
  const [micDevices, setMicDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>(() => localStorage.getItem("echo_pref_mic") ?? "");
  const [captureSystem, setCaptureSystem] = useState(false);
  const [bridge, setBridge] = useState<BridgeHealth | null | "checking">("checking");
  const [engine, setEngine] = useState<EngineMode>("cloud");
  const [wsConnected, setWsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  // ── transcript en vivo ─────────────────────────────────────────
  const [lines, setLines] = useState<LiveLine[]>([]);
  const [partial, setPartial] = useState<{ text: string; speaker_hint: string | null } | null>(null);
  const [insightTotals, setInsightTotals] = useState<{ decisions: number; tasks: number; questions: number } | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [processing, setProcessing] = useState<{ stage: string; progress: number } | null>(null);
  const [noteModal, setNoteModal] = useState<null | { kind: string; label: string }>(null);
  const [noteText, setNoteText] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<AudioSource | null>(null);
  const bridgeRef = useRef<BridgeSttSession | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const startedAtMs = useRef<number>(0);
  const recordingRef = useRef(false);
  const reconnectTimer = useRef<number | null>(null);
  const pendingSends = useRef<(ArrayBuffer | string)[]>([]);
  const flushWaiter = useRef<(() => void) | null>(null);
  const openWsRef = useRef<(() => Promise<WebSocket>) | null>(null);
  // Mientras arranca (pedir el micrófono puede tardar) no se puede arrancar
  // otra vez: cada arranque abría otro micrófono y el audio se mezclaba.
  const startingRef = useRef(false);
  const [starting, setStarting] = useState(false);

  // ── cortes del micrófono ───────────────────────────────────────
  const frameHandlerRef = useRef<((frame: Int16Array) => void) | null>(null);
  const lastFrameAt = useRef(0);
  const interruptedAt = useRef<number | null>(null);
  const [interruption, setInterruption] = useState<Interruption | null>(null);
  const [blackout, setBlackout] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const lastTapAt = useRef(0);
  const homeScreenApp = useMemo(isIOSHomeScreenApp, []);

  // Grabación del audio completo: la decide la reunión (se elige al crearla o
  // acá antes de empezar). El servidor escribe el audio mientras llega.
  const recordingOn = !!meeting?.recording?.enabled;
  const recordingOnRef = useRef(recordingOn);
  recordingOnRef.current = recordingOn;
  const [recordingBusy, setRecordingBusy] = useState(false);
  const setRecordAudio = useCallback(
    async (enabled: boolean) => {
      if (!id) return;
      setRecordingBusy(true);
      try {
        const state = await api<RecordingState>(`/api/meetings/${id}/recording`, {
          method: "PUT",
          body: JSON.stringify({ enabled }),
        });
        queryClient.setQueryData<MeetingOut>(["meeting", id], (current) =>
          current ? { ...current, recording: state } : current,
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "No se pudo cambiar la grabación");
      } finally {
        setRecordingBusy(false);
      }
    },
    [id, queryClient],
  );

  // dispositivos + bridge al montar
  useEffect(() => {
    listMicrophones().then(setMicDevices).catch(() => {});
    let cancelled = false;
    checkBridge().then((health) => {
      if (cancelled) return;
      setBridge(health);
      if (health?.engine.available) setEngine("bridge");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // cargar transcript existente (reunión reanudada)
  useEffect(() => {
    if (!id || !meeting) return;
    api<{ segments: { id: string; seq: number; start_ms: number; text: string; confidence: number | null }[] }>(
      `/api/meetings/${id}/transcript?limit=500`,
    )
      .then((page) => {
        setLines(
          page.segments.map((segment) => ({
            key: segment.id,
            seq: segment.seq,
            start_ms: segment.start_ms,
            text: segment.text,
            speaker_hint: null,
            confidence: segment.confidence,
          })),
        );
      })
      .catch(() => {});
  }, [id, meeting?.id]);

  // timer
  useEffect(() => {
    if (!recording || paused) return;
    const interval = window.setInterval(() => {
      setElapsedMs(Date.now() - startedAtMs.current);
    }, 1000);
    return () => window.clearInterval(interval);
  }, [recording, paused]);

  // autoscroll estable: solo si el usuario está al fondo
  useEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) {
      element.scrollTop = element.scrollHeight;
    }
  }, [lines, partial]);

  const kindRef = useRef(meeting?.kind);
  kindRef.current = meeting?.kind;

  const handleLiveEvent = useCallback(
    (event: LiveEvent) => {
      switch (event.type) {
        case "segment":
          setPartial(null);
          setLines((current) => {
            if (current.some((line) => line.key === event.id)) return current;
            return [
              ...current,
              {
                key: event.id,
                seq: event.seq,
                start_ms: event.start_ms,
                text: event.text,
                speaker_hint: event.speaker_hint,
                confidence: event.confidence,
              },
            ];
          });
          break;
        case "partial":
          setPartial({ text: event.text, speaker_hint: event.speaker_hint ?? null });
          break;
        case "insights":
          setInsightTotals(event.totals);
          break;
        case "processing":
          setProcessing({ stage: event.stage, progress: event.progress });
          break;
        case "status":
          if (event.status === "completed") {
            queryClient.invalidateQueries({ queryKey: ["meeting", id] });
            // Al terminar, lo que sigue es revisar y confirmar el acta. Las
            // internas no tienen acta: van al resumen.
            navigate(`/meetings/${id}?tab=${kindRef.current === "interna" ? "summary" : "minutes"}`);
          } else if (event.status === "failed") {
            setProcessing(null);
            setError("El procesamiento falló. Podés reintentar desde la página de la reunión.");
          }
          break;
        case "warning":
          setWarning(event.message);
          break;
        case "flushed":
          flushWaiter.current?.();
          break;
        case "error":
          setError(event.message);
          break;
      }
    },
    [id, navigate, queryClient],
  );

  const bridgeMode = engine === "bridge" && !!bridge && bridge !== "checking" && bridge.engine.available;

  /** Manda al servidor, o lo guarda para cuando vuelva la conexión. */
  const sendOrQueue = useCallback((data: ArrayBuffer | string) => {
    const socket = wsRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(data);
      return;
    }
    const pending = pendingSends.current;
    pending.push(data);
    if (pending.length > MAX_PENDING_SENDS) pending.splice(0, pending.length - MAX_PENDING_SENDS);
  }, []);

  /** Reconexión mientras se graba, sin tope de intentos. Antes, si el primer
   *  reintento fallaba no había otro: la pantalla seguía en "Grabando" y todo
   *  lo que se decía después se perdía. */
  const scheduleReconnect = useCallback((attempt: number) => {
    if (!recordingRef.current || reconnectTimer.current != null) return;
    const delay = Math.min(1500 * 2 ** attempt, 15000);
    reconnectTimer.current = window.setTimeout(async () => {
      reconnectTimer.current = null;
      if (!recordingRef.current || wsRef.current || !openWsRef.current) return;
      // El access token dura 15 minutos y el WebSocket no lo renueva solo.
      await refreshAccessToken().catch(() => false);
      try {
        wsRef.current = await openWsRef.current();
      } catch {
        scheduleReconnect(attempt + 1);
      }
    }, delay);
  }, []);

  const openWs = useCallback(async (): Promise<WebSocket> => {
    // El WebSocket no puede renovar la sesión por su cuenta: el token de
    // acceso dura 15 minutos y con la pantalla abierta un rato el servidor lo
    // rechazaba ("No se pudo conectar al servidor"). Un pedido común antes de
    // abrirlo lo renueva si hace falta.
    if (id) await api(`/api/meetings/${id}`).catch(() => undefined);
    return new Promise((resolve, reject) => {
      const token = getAccessToken();
      if (!token || !id) return reject(new Error("Sesión inválida"));
      const socket = new WebSocket(wsUrl(`/api/meetings/${id}/ws?token=${encodeURIComponent(token)}`));
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        // channels=2 avisa que el PCM viene intercalado L=micrófono, R=sistema,
        // que es como el servidor distingue quién habló.
        socket.send(
          JSON.stringify({
            type: "hello",
            role: "recorder",
            sample_rate: 16000,
            channels: captureSystem ? 2 : 1,
            // Con el bridge el texto viene de la máquina: si llega audio es
            // solo para grabarlo.
            transcribe: !bridgeMode,
          }),
        );
        wsRef.current = socket;
        // Lo que se juntó mientras no había conexión, en orden.
        const pending = pendingSends.current;
        pendingSends.current = [];
        for (const data of pending) socket.send(data);
        setWsConnected(true);
        resolve(socket);
      };
      socket.onmessage = (message) => {
        try {
          handleLiveEvent(JSON.parse(message.data as string) as LiveEvent);
        } catch {
          /* ignorar frames no-json */
        }
      };
      socket.onerror = () => reject(new Error("No se pudo conectar al servidor"));
      socket.onclose = (event) => {
        // Si nunca abrió, el intento falló (el que lo pidió reintenta).
        reject(new Error("No se pudo conectar al servidor"));
        // Una conexión vieja que se cierra no toca a la actual.
        if (wsRef.current !== socket) return;
        setWsConnected(false);
        wsRef.current = null;
        if (event.code === 4409) {
          // El servidor acepta una sola grabadora por reunión: siguió en otra
          // pestaña o dispositivo. Esta deja de grabar y no reconecta.
          recordingRef.current = false;
          void audioRef.current?.stop().catch(() => {});
          audioRef.current = null;
          setRecording(false);
          setError("La grabación siguió en otra pestaña o dispositivo; esta pantalla dejó de grabar.");
          return;
        }
        // reconexión con backoff mientras se graba (transcript confirmado nunca se pierde)
        scheduleReconnect(0);
      };
    });
  }, [id, handleLiveEvent, captureSystem, bridgeMode, scheduleReconnect]);

  useEffect(() => {
    openWsRef.current = openWs;
  }, [openWs]);

  /** Espera a que el servidor transcriba lo último (y lo guarde) antes de
   *  seguir. Si se estaba reconectando, espera la conexión: el audio pendiente
   *  viaja con ella. */
  const flushAndWait = useCallback(async () => {
    const deadline = Date.now() + FLUSH_TIMEOUT_MS;
    while (wsRef.current?.readyState !== WebSocket.OPEN && Date.now() < deadline && recordingRef.current) {
      await new Promise((resolve) => window.setTimeout(resolve, 250));
    }
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    await new Promise<void>((resolve) => {
      const done = () => {
        window.clearTimeout(timer);
        flushWaiter.current = null;
        resolve();
      };
      const timer = window.setTimeout(done, Math.max(0, deadline - Date.now()));
      flushWaiter.current = done;
      socket.send(JSON.stringify({ type: "flush" }));
    });
  }, []);

  const start = useCallback(async () => {
    if (!id || startingRef.current) return;
    startingRef.current = true;
    setStarting(true);
    setError(null);
    try {
      await api(`/api/meetings/${id}/start`, { method: "POST" });
      // Nunca dos micrófonos a la vez: si quedó uno (reanudar), se cierra.
      await audioRef.current?.stop().catch(() => {});
      audioRef.current = null;
      // Al reanudar la conexión sigue abierta: se reusa en vez de abrir otra.
      const current = wsRef.current;
      const ws = current && current.readyState === WebSocket.OPEN ? current : await openWs();
      wsRef.current = ws;

      const source: AudioSource = captureSystem
        ? new SystemAudioSource(deviceId || undefined, () =>
            setWarning(
              "Se dejó de compartir el audio de la pestaña: ya no se escucha a quienes están del otro lado. Pausá y reanudá para volver a compartirlo.",
            ),
          )
        : new MicrophoneSource(deviceId || undefined);
      audioRef.current = source;
      if (deviceId) localStorage.setItem("echo_pref_mic", deviceId);

      let streamMs = lines.length ? Math.max(...lines.map((line) => line.start_ms)) : 0;
      const useBridge = engine === "bridge" && bridge && bridge !== "checking" && bridge.engine.available;

      // Cada frame que llega marca que el micrófono sigue vivo. Si venía de un
      // corte, el corte termina acá.
      const onFrame = (frame: Int16Array) => {
        const now = Date.now();
        if (interruptedAt.current != null) {
          const from = interruptedAt.current;
          interruptedAt.current = null;
          setInterruption({ from, to: now });
          // Queda marcado en la reunión para quien revise el acta.
          void api(`/api/meetings/${id}/bookmarks`, {
            method: "POST",
            body: JSON.stringify({
              kind: "note",
              at_ms: Math.max(0, Math.round(from - startedAtMs.current)),
              note: `Sin audio entre las ${clock(from)} y las ${clock(now)}: se cortó el micrófono.`,
            }),
          }).catch(() => {});
        }
        lastFrameAt.current = now;
        if (useBridge) {
          bridgeRef.current?.sendPcm(frame);
          // El bridge transcribe en la máquina; al servidor el audio va solo
          // si la reunión se graba.
          if (!recordingOnRef.current) return;
        }
        // MODO CLOUD: audio → servidor (RAM) → provider STT → texto
        sendOrQueue(frame.buffer as ArrayBuffer);
      };
      frameHandlerRef.current = onFrame;
      lastFrameAt.current = Date.now();

      if (useBridge) {
        // MODO LOCAL: audio → bridge (127.0.0.1) → texto → servidor
        const session = new BridgeSttSession();
        bridgeRef.current = session;
        await session.open(
          meeting?.language ?? "es",
          (bridgeEvent) => {
            const socket = wsRef.current;
            if (bridgeEvent.type === "partial" && bridgeEvent.text) {
              // Lo efímero no se guarda para después.
              if (!socket || socket.readyState !== WebSocket.OPEN) return;
              socket.send(
                JSON.stringify({
                  type: "partial",
                  text: bridgeEvent.text,
                  start_ms: bridgeEvent.start_ms ?? 0,
                  speaker_hint: bridgeEvent.speaker,
                }),
              );
            } else if (bridgeEvent.type === "final" && bridgeEvent.text) {
              sendOrQueue(
                JSON.stringify({
                  type: "segment",
                  text: bridgeEvent.text,
                  start_ms: bridgeEvent.start_ms ?? 0,
                  end_ms: bridgeEvent.end_ms ?? 0,
                  confidence: bridgeEvent.confidence,
                  speaker_hint: bridgeEvent.speaker,
                }),
              );
            } else if (bridgeEvent.type === "error") {
              setWarning(`Echo Bridge: ${bridgeEvent.message ?? "error del motor local"}`);
            }
          },
          () => {
            if (recordingRef.current) setWarning("Echo Bridge se desconectó; reintentando…");
          },
        );
      }
      await source.start(onFrame, setLevel);
      lastFrameAt.current = Date.now();

      startedAtMs.current = Date.now() - streamMs;
      recordingRef.current = true;
      setRecording(true);
      setPaused(false);
    } catch (err) {
      setError(micErrorMessage(err, "No se pudo iniciar la captura"));
      await audioRef.current?.stop().catch(() => {});
      audioRef.current = null;
      bridgeRef.current?.close();
    } finally {
      startingRef.current = false;
      setStarting(false);
    }
  }, [id, engine, bridge, deviceId, captureSystem, meeting?.language, lines, openWs, sendOrQueue]);

  const pause = useCallback(async () => {
    if (!id) return;
    await audioRef.current?.stop().catch(() => {});
    audioRef.current = null;
    // Un corte que seguía abierto termina en la pausa, no al reanudar.
    if (interruptedAt.current != null) {
      setInterruption({ from: interruptedAt.current, to: Date.now() });
      interruptedAt.current = null;
    }
    bridgeRef.current?.flush();
    sendOrQueue(JSON.stringify({ type: "flush" }));
    await api(`/api/meetings/${id}/pause`, { method: "POST" }).catch(() => {});
    setPaused(true);
  }, [id, sendOrQueue]);

  const resume = useCallback(async () => {
    await start();
  }, [start]);

  /** Vuelve a abrir el micrófono con el mismo destino de frames. Llamado desde
   *  un toque sirve siempre; solo, iOS a veces deja el AudioContext suspendido
   *  hasta que haya un gesto, y ahí queda el botón del aviso. */
  const restartAudio = useCallback(async () => {
    const handler = frameHandlerRef.current;
    if (!handler || captureSystem) return;
    await audioRef.current?.stop().catch(() => {});
    const source = new MicrophoneSource(deviceId || undefined);
    audioRef.current = source;
    await source.start(handler, setLevel);
  }, [captureSystem, deviceId]);

  // Detecta cortes del micrófono y los retoma. Corre también al volver a la
  // app, que es cuando iOS devuelve el control después de bloquear la pantalla.
  useEffect(() => {
    if (!recording || paused) return;
    let busy = false;
    let lastRestart = 0;
    const check = async () => {
      if (busy || document.visibilityState !== "visible" || !audioRef.current) return;
      const silentFor = Date.now() - lastFrameAt.current;
      if (silentFor < STALL_MS) return;
      if (interruptedAt.current == null) {
        interruptedAt.current = lastFrameAt.current;
        setInterruption({ from: lastFrameAt.current, to: null });
      }
      busy = true;
      try {
        const alive = await audioRef.current.revive?.();
        // Vivo según el sistema pero sin frames hace rato: se reabre igual.
        if (alive && silentFor < STALL_MS * 3) return;
        if (Date.now() - lastRestart < 8000) return;
        lastRestart = Date.now();
        await restartAudio();
      } catch {
        /* queda el botón del aviso para retomar con un toque */
      } finally {
        busy = false;
      }
    };
    const interval = window.setInterval(() => void check(), 2000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [recording, paused, restartAudio]);

  // Pantalla encendida mientras se graba: que el celular no se bloquee solo es
  // lo que evita el corte en la app instalada del iPhone. El sistema suelta el
  // bloqueo al ocultarse la página; se vuelve a pedir al volver.
  useEffect(() => {
    if (!recording || paused || !("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let active = true;
    const acquire = async () => {
      try {
        const next = await navigator.wakeLock.request("screen");
        if (active) lock = next;
        else await next.release();
      } catch {
        /* sin permiso o sin soporte: seguimos sin bloqueo */
      }
    };
    void acquire();
    const onVisibility = () => {
      if (document.visibilityState === "visible") void acquire();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisibility);
      lock?.release().catch(() => {});
    };
  }, [recording, paused]);

  const copyLiveLink = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 2500);
    } catch {
      /* sin portapapeles: el link sigue visible en el aviso */
    }
  }, []);

  const finish = useCallback(async () => {
    if (!id) return;
    await audioRef.current?.stop().catch(() => {});
    audioRef.current = null;
    setProcessing({ stage: "queued", progress: 0 });
    // Lo último que se dijo tiene que estar transcripto (y el audio en disco)
    // antes de pedir el acta: si no, el procesamiento arrancaba sin el último
    // tramo. Primero el bridge, que manda su texto por este mismo WebSocket.
    await bridgeRef.current?.flushAndWait();
    bridgeRef.current?.close();
    bridgeRef.current = null;
    await flushAndWait();
    recordingRef.current = false;
    try {
      await api(`/api/meetings/${id}/finish`, { method: "POST" });
    } catch (err) {
      setProcessing(null);
      setError(err instanceof Error ? err.message : "No se pudo finalizar");
    }
  }, [id, flushAndWait]);

  // Mientras procesa, además del aviso en vivo se pregunta al servidor: si la
  // conexión se cortó justo, la pantalla se quedaba esperando para siempre.
  useEffect(() => {
    if (!id || !processing) return;
    const interval = window.setInterval(async () => {
      try {
        const current = await api<MeetingOut>(`/api/meetings/${id}`);
        if (current.status === "completed") {
          queryClient.setQueryData(["meeting", id], current);
          navigate(`/meetings/${id}?tab=${current.kind === "interna" ? "summary" : "minutes"}`);
        } else if (current.status === "failed") {
          setProcessing(null);
          setError("El procesamiento falló. Podés reintentar desde la página de la reunión.");
        }
      } catch {
        /* se reintenta en la próxima vuelta */
      }
    }, 4000);
    return () => window.clearInterval(interval);
  }, [id, processing, navigate, queryClient]);

  // cleanup al desmontar
  useEffect(() => {
    return () => {
      recordingRef.current = false;
      audioRef.current?.stop().catch(() => {});
      bridgeRef.current?.close();
      wsRef.current?.close();
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current);
    };
  }, []);

  const addBookmark = useCallback(
    async (kind: string, note?: string) => {
      if (!id) return;
      const atMs = recording ? Date.now() - startedAtMs.current : elapsedMs;
      await api(`/api/meetings/${id}/bookmarks`, {
        method: "POST",
        body: JSON.stringify({ kind, at_ms: Math.max(0, Math.round(atMs)), note: note || null }),
      }).catch(() => {});
    },
    [id, recording, elapsedMs],
  );

  // atajos de teclado
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) return;
      if (noteModal) return;
      const key = event.key.toLowerCase();
      if (key === "m") addBookmark("moment");
      else if (key === "n") setNoteModal({ kind: "note", label: "Agregar nota" });
      else if (key === "d") setNoteModal({ kind: "decision", label: "Marcar decisión" });
      else if (key === "t") setNoteModal({ kind: "task", label: "Marcar tarea" });
      else if (key === " " && recording) {
        event.preventDefault();
        if (paused) resume();
        else pause();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recording, paused, noteModal, addBookmark, pause, resume]);

  const mood: EchoMood = processing
    ? "thinking"
    : paused
      ? "sleeping"
      : recording
        ? "listening"
        : "idle";

  const bridgeState = useMemo(() => {
    if (bridge === "checking") return { dot: "bg-amber-400", label: "Buscando motor local…" };
    if (bridge?.engine.available)
      return { dot: "bg-emerald-500", label: `Motor local: ${bridge.engine.name}` };
    if (bridge) return { dot: "bg-amber-400", label: "Bridge sin motor STT" };
    return { dot: "bg-ink-300", label: "Echo Bridge no encontrado" };
  }, [bridge]);

  if (!meeting) {
    return (
      <div className="flex h-full items-center justify-center text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  // ── pantalla de procesamiento post-Finalizar ───────────────────
  if (processing || meeting.status === "processing") {
    const stageLabels: Record<string, string> = {
      queued: "Preparando la reunión…",
      speakers: "Identificando quién habló…",
      insights: "Extrayendo decisiones y tareas…",
      embeddings: "Indexando el transcript…",
      summary: "Escribiendo el resumen…",
      minutes: "Generando el acta…",
      memory: "Actualizando la memoria…",
      transcribed: "Transcripción completa…",
      done: "Listo",
    };
    const stage = processing?.stage ?? "queued";
    return (
      <div className="flex h-full flex-col items-center justify-center gap-6 px-6">
        <span className="text-ink-700"><EchoFace mood="thinking" size={72} /></span>
        <div className="text-center">
          <h2 className="text-xl font-semibold text-ink-900">{stageLabels[stage] ?? "Procesando…"}</h2>
          <p className="mt-1 text-sm text-ink-500">{meeting.title}</p>
        </div>
        <div className="h-1.5 w-64 overflow-hidden rounded-full bg-ink-100">
          <div
            className="h-full rounded-full bg-accent-500 transition-all duration-700"
            style={{ width: `${processing?.progress ?? 5}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-ink-100 bg-white px-6 py-3">
        <span className={recording && !paused ? "text-red-500" : "text-ink-700"}>
          <EchoFace mood={mood} size={30} level={level} />
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-semibold text-ink-900">{meeting.title}</h1>
          <p className="text-xs text-ink-400">
            {meeting.participants.map((participant) => participant.name).join(", ") || "Sin participantes"}
          </p>
        </div>
        <div className="font-mono text-lg tabular-nums text-ink-700">{formatMs(elapsedMs)}</div>
        {recording && !paused && interruption && interruption.to === null && (
          <span className="rounded-full bg-red-600 px-2.5 py-1 text-xs font-semibold text-white">
            Micrófono cortado
          </span>
        )}
        {recording && !paused && !(interruption && interruption.to === null) && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-600">
            <span className="recording-dot h-2 w-2 rounded-full bg-red-500" />
            Grabando
          </span>
        )}
        {paused && (
          <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-600">
            En pausa
          </span>
        )}
        {recording && !wsConnected && (
          // En el celular el panel lateral no se ve: el aviso va acá arriba.
          <span
            className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700"
            title="El audio se guarda y se manda al volver la conexión"
          >
            Reconectando…
          </span>
        )}
        {recording && recordingOn && (
          <span
            className="rounded-full bg-ink-900 px-2.5 py-1 text-xs font-semibold text-white"
            title="Se guarda el audio completo de la reunión"
          >
            Audio guardándose
          </span>
        )}
      </header>

      {/* Errores del servidor durante la grabación (ej. stt_not_configured).
          Sin esto la reunión graba en silencio y el transcript queda vacío. */}
      {error && recording && (
        <p className="border-b border-red-100 bg-red-50 px-6 py-2.5 text-sm text-red-700">
          {error}
        </p>
      )}

      {/* Cortes del micrófono. Van acá arriba y no en el panel lateral porque
          el panel no existe en el celular, que es donde pasan. */}
      {recording && interruption && interruption.to === null && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-red-100 bg-red-50 px-6 py-2.5 text-sm text-red-700">
          <p className="min-w-0 flex-1">
            <strong>El micrófono se cortó</strong> a las {clock(interruption.from)}.
            {homeScreenApp && " En la app instalada pasa al bloquear el iPhone o cambiar de app."}
          </p>
          <Button
            variant="danger"
            onClick={() => {
              setBlackout(false);
              void restartAudio().catch((err) =>
                setError(micErrorMessage(err, "No se pudo retomar el micrófono")),
              );
            }}
          >
            Retomar grabación
          </Button>
        </div>
      )}
      {interruption && interruption.to !== null && (
        <div className="flex items-start gap-3 border-b border-amber-100 bg-amber-50 px-6 py-2.5 text-sm text-amber-800">
          <p className="min-w-0 flex-1">
            No se grabó entre las {clock(interruption.from)} y las {clock(interruption.to)} (
            {gapLabel(interruption.to - interruption.from)}): el micrófono estuvo cortado. Ya se retomó
            y quedó una nota en la reunión en ese momento.
          </p>
          <button
            onClick={() => setInterruption(null)}
            className="shrink-0 text-xs font-medium text-amber-700 hover:underline"
          >
            Entendido
          </button>
        </div>
      )}
      {recording && warning && (
        <p className="border-b border-amber-100 bg-amber-50 px-6 py-2.5 text-sm text-amber-800 lg:hidden">
          {warning}
        </p>
      )}

      <div className="flex min-h-0 flex-1">
        {/* Transcript */}
        <div
          ref={scrollRef}
          onScroll={(event) => {
            const element = event.currentTarget;
            stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
          }}
          className="min-w-0 flex-1 overflow-y-auto px-6 py-6"
        >
          {!recording && lines.length === 0 && (
            <div className="mx-auto flex max-w-lg flex-col items-center gap-6 pt-[4vh] text-center sm:pt-[7vh]">
              <span className="flex h-20 w-20 items-center justify-center rounded-full bg-white text-ink-800 shadow-[0_1px_2px_rgba(16,24,40,0.06),0_8px_24px_-12px_rgba(16,24,40,0.18)]">
                <EchoFace mood="idle" size={44} />
              </span>
              <div>
                <h2 className="text-2xl font-semibold tracking-tight text-ink-900">Todo listo para empezar</h2>
                <p className="mt-1.5 text-sm text-ink-500">
                  Avisales a los participantes que la reunión se transcribe.
                </p>
              </div>

              <div className="w-full space-y-3 text-left">
                <SettingsGroup>
                  <div className="px-4 py-3.5">
                    <Select
                      label="Micrófono"
                      value={deviceId}
                      onChange={setDeviceId}
                      options={[
                        { value: "", label: "Micrófono predeterminado" },
                        ...micDevices.map((device) => ({
                          value: device.deviceId,
                          label: device.label || `Micrófono ${device.deviceId.slice(0, 6)}`,
                        })),
                      ]}
                    />
                  </div>
                  <RecordToggle checked={recordingOn} onChange={setRecordAudio} disabled={recordingBusy} />
                  {canCaptureSystemAudio() ? (
                    <SettingRow
                      label="Incluir el audio de la llamada"
                      hint="Meet, Zoom, Teams o Discord: tu voz y la de los demás quedan separadas."
                      control={
                        <PillSwitch
                          checked={captureSystem}
                          onChange={setCaptureSystem}
                          label="Incluir el audio de la llamada"
                        />
                      }
                    />
                  ) : (
                    <SettingRow
                      label="¿Reunión por Meet, Zoom o Teams?"
                      hint="Este dispositivo no puede tomar el audio de la llamada. Ponela en altavoz cerca del micrófono, o grabá desde una computadora."
                    />
                  )}
                </SettingsGroup>

                {/* Solo si hay Echo Bridge en esta computadora: si no, la única
                    opción es la nube y la pregunta sobra (en el celular, siempre). */}
                {bridge !== "checking" && bridge?.engine.available && (
                <div className="pt-1">
                  <p className="mb-2 px-1 text-xs font-medium text-ink-500">Dónde se transcribe</p>
                  <ChoiceCards
                    ariaLabel="Dónde se transcribe"
                    value={engine}
                    onChange={setEngine}
                    options={[
                      {
                        value: "cloud",
                        title: "En la nube",
                        hint: "El audio viaja cifrado al servicio que transcribe y Echo no se lo queda.",
                      },
                      {
                        value: "bridge",
                        title: (
                          <span className="flex items-center gap-1.5">
                            <span className={`h-2 w-2 rounded-full ${bridgeState.dot}`} />
                            Echo Bridge
                          </span>
                        ),
                        hint: "En tu computadora, con tu motor de voz: el audio no sale de ahí.",
                      },
                    ]}
                  />
                </div>
                )}
              </div>

              {homeScreenApp && (
                <div className="w-full space-y-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-left text-sm text-amber-900">
                  <p>
                    <strong>Estás en la app instalada.</strong> Acá el iPhone corta el micrófono si
                    bloqueás la pantalla o cambiás de app (desde Safari no pasa).
                  </p>
                  <p>
                    Mientras grabás, Echo deja la pantalla encendida; para que no se vea, usá{" "}
                    <strong>Pantalla negra</strong>. Si necesitás bloquear el teléfono, abrí esta
                    reunión en Safari.
                  </p>
                  <Button variant="soft" onClick={copyLiveLink} className="w-full">
                    {linkCopied ? "Link copiado: pegalo en Safari" : "Copiar link para abrir en Safari"}
                  </Button>
                </div>
              )}

              {/* Abajo y fijo en el celular, como la barra de acción de ElevenLabs. */}
              <div className="sticky bottom-0 -mx-6 w-[calc(100%+3rem)] bg-gradient-to-t from-[#fafbfc] via-[#fafbfc] to-transparent px-6 pb-[max(1rem,env(safe-area-inset-bottom))] pt-6 sm:static sm:mx-0 sm:w-full sm:bg-none sm:p-0">
                {error && (
                  <p role="alert" className="animate-fade-up mb-3 rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700">
                    {error}
                  </p>
                )}
                <button
                  type="button"
                  onClick={start}
                  disabled={starting}
                  className="flex w-full items-center justify-center gap-2 rounded-full bg-ink-900 py-3.5 text-[15px] font-semibold text-white transition-all duration-200 hover:bg-ink-700 active:scale-[0.99] disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 sm:mx-auto sm:max-w-xs"
                >
                  {starting ? <Spinner /> : <span className="h-2 w-2 rounded-full bg-red-500" aria-hidden />}
                  {starting ? "Iniciando…" : "Iniciar reunión"}
                </button>
              </div>
            </div>
          )}

          {(recording || lines.length > 0) && (
            <div className="mx-auto max-w-2xl space-y-4">
              {lines.map((line) => (
                <div key={line.key} className="animate-fade-up">
                  <div className="mb-0.5 flex items-baseline gap-2 text-xs text-ink-400">
                    <span className="font-mono tabular-nums">{formatMs(line.start_ms)}</span>
                    {line.speaker_hint && <span className="font-medium">{line.speaker_hint}</span>}
                    {line.confidence != null && line.confidence < 0.5 && (
                      <span className="text-amber-500" title="Baja confianza">~</span>
                    )}
                  </div>
                  <p className="leading-relaxed text-ink-900">{line.text}</p>
                </div>
              ))}
              {partial && (
                <div>
                  <p className="leading-relaxed text-ink-400">{partial.text}</p>
                </div>
              )}
              {recording && !paused && !partial && (
                <p className="text-sm text-ink-300">
                  <span className="recording-dot">●</span> escuchando…
                </p>
              )}
            </div>
          )}
        </div>

        {/* Panel lateral */}
        {(recording || lines.length > 0) && (
          <aside className="hidden w-64 shrink-0 flex-col border-l border-ink-100 bg-white p-5 lg:flex">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-400">
              Echo está detectando
            </h3>
            {insightTotals ? (
              <ul className="space-y-2 text-sm">
                <li className="flex justify-between text-ink-700">
                  <span>Decisiones</span>
                  <span className="font-semibold">{insightTotals.decisions}</span>
                </li>
                <li className="flex justify-between text-ink-700">
                  <span>Tareas</span>
                  <span className="font-semibold">{insightTotals.tasks}</span>
                </li>
                <li className="flex justify-between text-ink-700">
                  <span>Preguntas</span>
                  <span className="font-semibold">{insightTotals.questions}</span>
                </li>
              </ul>
            ) : (
              <p className="text-xs leading-relaxed text-ink-400">
                La detección en vivo aparece a medida que avanza la conversación. Requiere un modelo de IA
                configurado en Ajustes → IA.
              </p>
            )}

            {warning && (
              <p className="mt-4 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-700">{warning}</p>
            )}
            {!wsConnected && recording && (
              <p className="mt-4 rounded-lg bg-red-50 p-2.5 text-xs text-red-700">
                Reconectando con el servidor… el transcript confirmado no se pierde.
              </p>
            )}

            <div className="mt-auto space-y-1.5 border-t border-ink-100 pt-4 text-[11px] text-ink-400">
              <p><kbd className="rounded border border-ink-200 px-1">M</kbd> marcar momento</p>
              <p><kbd className="rounded border border-ink-200 px-1">N</kbd> nota</p>
              <p><kbd className="rounded border border-ink-200 px-1">D</kbd> decisión</p>
              <p><kbd className="rounded border border-ink-200 px-1">T</kbd> tarea</p>
              <p><kbd className="rounded border border-ink-200 px-1">Espacio</kbd> pausar</p>
            </div>
          </aside>
        )}
      </div>

      {/* Barra de acciones */}
      {(recording || lines.length > 0) && (
        <footer className="flex flex-wrap items-center justify-center gap-2 border-t border-ink-100 bg-white px-4 py-3 sm:px-6">
          {/* vúmetro */}
          <div className="mr-3 flex h-6 items-end gap-0.5" aria-hidden>
            {[0.3, 0.6, 1, 0.75, 0.45].map((weight, index) => (
              <span
                key={index}
                className="w-1 rounded-full bg-accent-500 transition-all duration-100"
                style={{ height: `${Math.max(12, Math.min(100, level * 100 * weight + 10))}%`, opacity: recording && !paused ? 1 : 0.25 }}
              />
            ))}
          </div>
          {recording && !paused && (
            <Button variant="soft" onClick={pause}>Pausar</Button>
          )}
          {paused && <Button variant="soft" onClick={resume} disabled={starting}>Reanudar</Button>}
          {!recording && lines.length > 0 && (
            <Button variant="soft" onClick={start} disabled={starting}>Reanudar grabación</Button>
          )}
          {recording && !paused && (
            <Button variant="ghost" onClick={() => setBlackout(true)} title="La pantalla queda negra y sigue grabando">
              Pantalla negra
            </Button>
          )}
          <Button variant="ghost" onClick={() => addBookmark("moment")}>⭐ Momento</Button>
          <Button variant="ghost" onClick={() => setNoteModal({ kind: "note", label: "Agregar nota" })}>
            Nota
          </Button>
          <Button variant="danger" onClick={finish}>Finalizar</Button>
        </footer>
      )}

      {/* Pantalla negra: sigue grabando con la pantalla encendida pero sin
          mostrar nada. En pantallas OLED el negro casi no gasta batería. */}
      {blackout && recording && !paused && (
        <div
          className="fixed inset-0 z-[70] flex select-none flex-col items-center justify-end bg-black pb-16"
          onClick={() => {
            const now = Date.now();
            if (now - lastTapAt.current < 400) {
              setBlackout(false);
              // El toque es el gesto que iOS pide para volver a abrir el audio.
              if (interruptedAt.current != null) void restartAudio().catch(() => {});
            }
            lastTapAt.current = now;
          }}
          role="button"
          aria-label="Tocá dos veces para volver"
        >
          {interruption && interruption.to === null ? (
            <p className="px-6 text-center text-sm font-medium text-red-500">
              El micrófono se cortó. Tocá dos veces para retomar.
            </p>
          ) : (
            <p className="flex items-center gap-2 text-xs text-neutral-600">
              <span className="recording-dot h-1.5 w-1.5 rounded-full bg-red-700" />
              {formatMs(elapsedMs)} · tocá dos veces para volver
            </p>
          )}
        </div>
      )}

      <Modal
        open={!!noteModal}
        onClose={() => {
          setNoteModal(null);
          setNoteText("");
        }}
        title={noteModal?.label ?? ""}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (noteModal) addBookmark(noteModal.kind, noteText);
            setNoteModal(null);
            setNoteText("");
          }}
          className="space-y-4"
        >
          <textarea
            value={noteText}
            onChange={(event) => setNoteText(event.target.value)}
            autoFocus
            rows={3}
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm focus:border-accent-500 focus:outline-none"
            placeholder="Escribí el contenido…"
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setNoteModal(null)}>
              Cancelar
            </Button>
            <Button type="submit">Guardar</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
