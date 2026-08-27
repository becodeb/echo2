import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, getAccessToken, wsUrl } from "../api/client";
import type { LiveEvent, MeetingOut } from "../api/types";
import { MicrophoneSource, SystemAudioSource, listMicrophones, type AudioSource } from "../lib/audio";
import { BridgeSttSession, checkBridge, type BridgeHealth } from "../lib/bridge";
import { Button, Modal, Spinner, formatMs } from "../components/ui";
import { EchoFace, type EchoMood } from "../components/EchoFace";

interface LiveLine {
  key: string;
  seq: number;
  start_ms: number;
  text: string;
  speaker_hint: string | null;
  confidence: number | null;
}

type EngineMode = "bridge" | "cloud";

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
            navigate(`/meetings/${id}`);
          } else if (event.status === "failed") {
            setProcessing(null);
            setError("El procesamiento falló. Podés reintentar desde la página de la reunión.");
          }
          break;
        case "warning":
          setWarning(event.message);
          break;
        case "error":
          setError(event.message);
          break;
      }
    },
    [id, navigate, queryClient],
  );

  const openWs = useCallback((): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      const token = getAccessToken();
      if (!token || !id) return reject(new Error("Sesión inválida"));
      const socket = new WebSocket(wsUrl(`/api/meetings/${id}/ws?token=${encodeURIComponent(token)}`));
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        socket.send(JSON.stringify({ type: "hello", role: "recorder", sample_rate: 16000 }));
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
      socket.onclose = () => {
        setWsConnected(false);
        wsRef.current = null;
        // reconexión con backoff mientras se graba (transcript confirmado nunca se pierde)
        if (recordingRef.current && reconnectTimer.current == null) {
          reconnectTimer.current = window.setTimeout(() => {
            reconnectTimer.current = null;
            openWs()
              .then((ws) => {
                wsRef.current = ws;
              })
              .catch(() => {});
          }, 1500);
        }
      };
    });
  }, [id, handleLiveEvent]);

  const start = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      await api(`/api/meetings/${id}/start`, { method: "POST" });
      const ws = await openWs();
      wsRef.current = ws;

      const source: AudioSource = captureSystem
        ? new SystemAudioSource(deviceId || undefined)
        : new MicrophoneSource(deviceId || undefined);
      audioRef.current = source;
      if (deviceId) localStorage.setItem("echo_pref_mic", deviceId);

      let streamMs = lines.length ? Math.max(...lines.map((line) => line.start_ms)) : 0;

      if (engine === "bridge" && bridge && bridge !== "checking" && bridge.engine.available) {
        // MODO LOCAL: audio → bridge (127.0.0.1) → texto → servidor
        const session = new BridgeSttSession();
        bridgeRef.current = session;
        await session.open(
          meeting?.language ?? "es",
          (bridgeEvent) => {
            const socket = wsRef.current;
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            if (bridgeEvent.type === "partial" && bridgeEvent.text) {
              socket.send(
                JSON.stringify({
                  type: "partial",
                  text: bridgeEvent.text,
                  start_ms: bridgeEvent.start_ms ?? 0,
                  speaker_hint: bridgeEvent.speaker,
                }),
              );
            } else if (bridgeEvent.type === "final" && bridgeEvent.text) {
              socket.send(
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
        await source.start((frame) => {
          bridgeRef.current?.sendPcm(frame);
        }, setLevel);
      } else {
        // MODO CLOUD: audio → servidor (RAM) → provider STT → texto
        await source.start((frame) => {
          const socket = wsRef.current;
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(frame.buffer);
          }
        }, setLevel);
      }

      startedAtMs.current = Date.now() - streamMs;
      recordingRef.current = true;
      setRecording(true);
      setPaused(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar la captura");
      await audioRef.current?.stop().catch(() => {});
      bridgeRef.current?.close();
    }
  }, [id, engine, bridge, deviceId, captureSystem, meeting?.language, lines, openWs]);

  const pause = useCallback(async () => {
    if (!id) return;
    await audioRef.current?.stop().catch(() => {});
    audioRef.current = null;
    bridgeRef.current?.flush();
    wsRef.current?.send(JSON.stringify({ type: "flush" }));
    await api(`/api/meetings/${id}/pause`, { method: "POST" }).catch(() => {});
    setPaused(true);
  }, [id]);

  const resume = useCallback(async () => {
    await start();
  }, [start]);

  const finish = useCallback(async () => {
    if (!id) return;
    recordingRef.current = false;
    await audioRef.current?.stop().catch(() => {});
    audioRef.current = null;
    bridgeRef.current?.flush();
    bridgeRef.current?.close();
    bridgeRef.current = null;
    wsRef.current?.send(JSON.stringify({ type: "flush" }));
    setProcessing({ stage: "queued", progress: 0 });
    try {
      await api(`/api/meetings/${id}/finish`, { method: "POST" });
    } catch (err) {
      setProcessing(null);
      setError(err instanceof Error ? err.message : "No se pudo finalizar");
    }
  }, [id]);

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
      speakers: "Consolidando hablantes…",
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
        {recording && !paused && (
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
      </header>

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
            <div className="mx-auto flex max-w-md flex-col items-center gap-6 pt-[8vh] text-center">
              <span className="text-ink-300"><EchoFace mood="idle" size={64} /></span>
              <div>
                <h2 className="text-lg font-semibold text-ink-900">Todo listo para empezar</h2>
                <p className="mt-1 text-sm text-ink-500">
                  Asegurate de que los participantes sepan que la reunión está siendo transcripta.
                </p>
              </div>

              <div className="w-full space-y-3 rounded-2xl border border-ink-100 bg-white p-5 text-left shadow-sm">
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-ink-700">Micrófono</span>
                  <select
                    value={deviceId}
                    onChange={(event) => setDeviceId(event.target.value)}
                    className="w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm"
                  >
                    <option value="">Micrófono predeterminado</option>
                    {micDevices.map((device) => (
                      <option key={device.deviceId} value={device.deviceId}>
                        {device.label || `Micrófono ${device.deviceId.slice(0, 6)}`}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex items-center gap-2 text-sm text-ink-600">
                  <input
                    type="checkbox"
                    checked={captureSystem}
                    onChange={(event) => setCaptureSystem(event.target.checked)}
                    className="rounded border-ink-300"
                  />
                  Incluir audio del sistema (Meet, Zoom, Teams)
                </label>

                <div className="border-t border-ink-100 pt-3">
                  <span className="mb-1.5 block text-sm font-medium text-ink-700">Motor de transcripción</span>
                  <div className="space-y-1.5">
                    <label className="flex items-center gap-2 text-sm text-ink-600">
                      <input
                        type="radio"
                        name="engine"
                        checked={engine === "bridge"}
                        disabled={!(bridge !== "checking" && bridge?.engine.available)}
                        onChange={() => setEngine("bridge")}
                      />
                      <span className={`h-2 w-2 rounded-full ${bridgeState.dot}`} />
                      {bridgeState.label}
                      <span className="text-xs text-ink-400">(el audio nunca sale de tu máquina)</span>
                    </label>
                    <label className="flex items-center gap-2 text-sm text-ink-600">
                      <input
                        type="radio"
                        name="engine"
                        checked={engine === "cloud"}
                        onChange={() => setEngine("cloud")}
                      />
                      Motor cloud
                      <span className="text-xs text-ink-400">
                        (envía temporalmente el audio al proveedor configurado)
                      </span>
                    </label>
                  </div>
                </div>
              </div>

              {error && <p className="text-sm text-red-600">{error}</p>}
              <Button onClick={start} className="w-full max-w-xs !py-3 text-base">
                Iniciar reunión
              </Button>
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
        <footer className="flex items-center justify-center gap-2 border-t border-ink-100 bg-white px-6 py-3">
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
          {paused && <Button variant="soft" onClick={resume}>Reanudar</Button>}
          {!recording && lines.length > 0 && (
            <Button variant="soft" onClick={start}>Reanudar grabación</Button>
          )}
          <Button variant="ghost" onClick={() => addBookmark("moment")}>⭐ Momento</Button>
          <Button variant="ghost" onClick={() => setNoteModal({ kind: "note", label: "Agregar nota" })}>
            Nota
          </Button>
          <Button variant="danger" onClick={finish}>Finalizar</Button>
        </footer>
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
