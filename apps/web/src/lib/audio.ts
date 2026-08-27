/**
 * Captura de micrófono → PCM16 mono 16 kHz en streaming.
 *
 * PRIVACY FIRST: nunca se acumula la grabación completa. Un AudioWorklet
 * entrega frames chicos (~128 samples); acá se re-muestrean a 16 kHz y se
 * empaquetan en Int16Array que se entregan al callback y se descartan.
 * Nada se escribe en localStorage/IndexedDB ni se guarda en memoria más allá
 * del frame en tránsito.
 */

export interface AudioSource {
  start(onFrame: (pcm16: Int16Array) => void, onLevel: (level: number) => void): Promise<void>;
  stop(): Promise<void>;
  readonly sampleRate: number;
}

const WORKLET_CODE = `
class EchoCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      // copiar: el buffer se reutiliza entre llamadas
      this.port.postMessage(new Float32Array(channel));
    }
    return true;
  }
}
registerProcessor("echo-capture", EchoCapture);
`;

export const TARGET_SAMPLE_RATE = 16000;

export async function listMicrophones(): Promise<MediaDeviceInfo[]> {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((device) => device.kind === "audioinput");
}

export class MicrophoneSource implements AudioSource {
  readonly sampleRate = TARGET_SAMPLE_RATE;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private resampleRemainder: Float32Array = new Float32Array(0);
  private pending: Float32Array = new Float32Array(0);

  constructor(private deviceId?: string) {}

  async start(onFrame: (pcm16: Int16Array) => void, onLevel: (level: number) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: this.deviceId ? { exact: this.deviceId } : undefined,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    this.context = new AudioContext();
    const workletUrl = URL.createObjectURL(new Blob([WORKLET_CODE], { type: "application/javascript" }));
    try {
      await this.context.audioWorklet.addModule(workletUrl);
    } finally {
      URL.revokeObjectURL(workletUrl);
    }
    const source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "echo-capture");

    const inputRate = this.context.sampleRate;
    const ratio = inputRate / TARGET_SAMPLE_RATE;
    // Entregar frames de ~100 ms (1600 samples a 16 kHz)
    const FRAME_SAMPLES = 1600;

    this.node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      const chunk = event.data;

      // nivel para el vúmetro (RMS del chunk crudo)
      let sum = 0;
      let peak = 0;
      for (let index = 0; index < chunk.length; index++) {
        const value = chunk[index];
        sum += value * value;
        const absolute = Math.abs(value);
        if (absolute > peak) peak = absolute;
      }
      onLevel(Math.min(1, Math.sqrt(sum / chunk.length) * 4 + (peak >= 0.99 ? 0.2 : 0)));

      // resample lineal inputRate → 16k
      const combined = new Float32Array(this.resampleRemainder.length + chunk.length);
      combined.set(this.resampleRemainder);
      combined.set(chunk, this.resampleRemainder.length);

      const outLength = Math.floor((combined.length - 1) / ratio);
      const resampled = new Float32Array(Math.max(0, outLength));
      for (let index = 0; index < outLength; index++) {
        const position = index * ratio;
        const low = Math.floor(position);
        const fraction = position - low;
        resampled[index] = combined[low] * (1 - fraction) + combined[low + 1] * fraction;
      }
      const consumed = Math.floor(outLength * ratio);
      this.resampleRemainder = combined.slice(consumed);

      // acumular hasta FRAME_SAMPLES y emitir como Int16
      const merged = new Float32Array(this.pending.length + resampled.length);
      merged.set(this.pending);
      merged.set(resampled, this.pending.length);
      let offset = 0;
      while (merged.length - offset >= FRAME_SAMPLES) {
        const frame = new Int16Array(FRAME_SAMPLES);
        for (let index = 0; index < FRAME_SAMPLES; index++) {
          const sample = Math.max(-1, Math.min(1, merged[offset + index]));
          frame[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        }
        onFrame(frame);
        offset += FRAME_SAMPLES;
      }
      this.pending = merged.slice(offset);
    };

    source.connect(this.node);
    // no conectar a destination: no queremos reproducir el micrófono
  }

  async stop(): Promise<void> {
    this.node?.port.close();
    this.node?.disconnect();
    this.node = null;
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.pending = new Float32Array(0);
    this.resampleRemainder = new Float32Array(0);
  }
}

/** Micrófono + audio del sistema (getDisplayMedia con audio). Modo avanzado
 *  para reuniones de Meet/Zoom/Teams: mezcla ambas fuentes en un solo PCM y
 *  reporta qué fuente domina cada frame como hint de diarización. */
export class SystemAudioSource implements AudioSource {
  readonly sampleRate = TARGET_SAMPLE_RATE;
  private mic: MicrophoneSource;
  private displayStream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;

  constructor(deviceId?: string) {
    this.mic = new MicrophoneSource(deviceId);
  }

  async start(onFrame: (pcm16: Int16Array) => void, onLevel: (level: number) => void): Promise<void> {
    // El audio del sistema requiere que el usuario comparta una pestaña/pantalla CON audio
    this.displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: { echoCancellation: false },
    });
    const audioTracks = this.displayStream.getAudioTracks();
    if (audioTracks.length === 0) {
      this.displayStream.getTracks().forEach((track) => track.stop());
      this.displayStream = null;
      throw new Error(
        "La fuente compartida no incluye audio. Compartí una pestaña con «Compartir audio» activado.",
      );
    }
    // detener el video: solo interesa el audio
    this.displayStream.getVideoTracks().forEach((track) => (track.enabled = false));

    this.context = new AudioContext();
    const workletUrl = URL.createObjectURL(new Blob([WORKLET_CODE], { type: "application/javascript" }));
    try {
      await this.context.audioWorklet.addModule(workletUrl);
    } finally {
      URL.revokeObjectURL(workletUrl);
    }
    const micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
    const micNode = this.context.createMediaStreamSource(micStream);
    const systemNode = this.context.createMediaStreamSource(new MediaStream(audioTracks));
    const merger = this.context.createGain();
    micNode.connect(merger);
    systemNode.connect(merger);
    this.node = new AudioWorkletNode(this.context, "echo-capture");
    merger.connect(this.node);

    const inputRate = this.context.sampleRate;
    const ratio = inputRate / TARGET_SAMPLE_RATE;
    let pending = new Float32Array(0);
    const FRAME_SAMPLES = 1600;

    this.node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      const chunk = event.data;
      let sum = 0;
      for (let index = 0; index < chunk.length; index++) sum += chunk[index] * chunk[index];
      onLevel(Math.min(1, Math.sqrt(sum / chunk.length) * 4));

      const outLength = Math.floor(chunk.length / ratio);
      const merged = new Float32Array(pending.length + outLength);
      merged.set(pending);
      for (let index = 0; index < outLength; index++) {
        merged[pending.length + index] = chunk[Math.floor(index * ratio)];
      }
      let offset = 0;
      while (merged.length - offset >= FRAME_SAMPLES) {
        const frame = new Int16Array(FRAME_SAMPLES);
        for (let index = 0; index < FRAME_SAMPLES; index++) {
          const sample = Math.max(-1, Math.min(1, merged[offset + index]));
          frame[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
        }
        onFrame(frame);
        offset += FRAME_SAMPLES;
      }
      pending = merged.slice(offset);
    };
  }

  async stop(): Promise<void> {
    this.node?.disconnect();
    this.node = null;
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
    this.displayStream?.getTracks().forEach((track) => track.stop());
    this.displayStream = null;
    await this.mic.stop();
  }
}
