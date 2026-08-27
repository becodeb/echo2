/**
 * Cliente de Echo Bridge (servicio local en la máquina del usuario).
 *
 * Modo bridge: el browser manda el audio a 127.0.0.1 (nunca sale de la
 * máquina); el bridge lo transcribe con el motor local (Murmur/whisper) y
 * devuelve texto. Solo el TEXTO sube al servidor de Echo.
 */

export const BRIDGE_BASE = "http://127.0.0.1:8974";

export type BridgeStatus = "connected" | "connecting" | "not_found";

export interface BridgeHealth {
  status: string;
  version: string;
  engine: { kind: string; name: string; available: boolean; detail?: string };
  models?: string[];
}

export async function checkBridge(timeoutMs = 1500): Promise<BridgeHealth | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const response = await fetch(`${BRIDGE_BASE}/health`, { signal: controller.signal });
    clearTimeout(timer);
    if (!response.ok) return null;
    return (await response.json()) as BridgeHealth;
  } catch {
    return null;
  }
}

export interface BridgeSttEvent {
  type: "partial" | "final" | "error" | "ready";
  text?: string;
  start_ms?: number;
  end_ms?: number;
  confidence?: number;
  speaker?: string;
  message?: string;
}

export class BridgeSttSession {
  private ws: WebSocket | null = null;
  private sessionToken: string | null = null;

  async open(
    language: string,
    onEvent: (event: BridgeSttEvent) => void,
    onClose: (reason: string) => void,
  ): Promise<void> {
    // pairing: pedir un token de sesión (el bridge valida el Origin)
    const pair = await fetch(`${BRIDGE_BASE}/session`, { method: "POST" });
    if (!pair.ok) throw new Error("Echo Bridge rechazó la sesión");
    const { token } = (await pair.json()) as { token: string };
    this.sessionToken = token;

    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(
        `ws://127.0.0.1:8974/stt?token=${encodeURIComponent(token)}&lang=${encodeURIComponent(language)}`,
      );
      ws.binaryType = "arraybuffer";
      ws.onopen = () => {
        this.ws = ws;
        resolve();
      };
      ws.onerror = () => reject(new Error("No se pudo conectar a Echo Bridge"));
      ws.onmessage = (message) => {
        try {
          onEvent(JSON.parse(message.data as string) as BridgeSttEvent);
        } catch {
          /* frame no-json */
        }
      };
      ws.onclose = (event) => {
        this.ws = null;
        onClose(event.reason || "closed");
      };
    });
  }

  sendPcm(frame: Int16Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(frame.buffer);
    }
  }

  flush(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "flush" }));
    }
  }

  close(): void {
    this.ws?.close();
    this.ws = null;
  }
}
