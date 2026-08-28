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
  /** 1 = mono. 2 = intercalado L=micrófono, R=audio del sistema. */
  readonly channels: number;
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

/** Igual que echo-capture pero conserva los dos canales por separado.
 *  Se usa para mic (canal 0) + audio del sistema (canal 1): mezclarlos antes
 *  de enviarlos borra la única señal que distingue quién habló. */
const WORKLET_CODE_STEREO = `
class EchoCaptureStereo extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    const left = input && input[0];
    if (left && left.length) {
      const right = (input[1] && input[1].length === left.length) ? input[1] : left;
      this.port.postMessage({ left: new Float32Array(left), right: new Float32Array(right) });
    }
    return true;
  }
}
registerProcessor("echo-capture-stereo", EchoCaptureStereo);
`;

export const TARGET_SAMPLE_RATE = 16000;

export async function listMicrophones(): Promise<MediaDeviceInfo[]> {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((device) => device.kind === "audioinput");
}

export class MicrophoneSource implements AudioSource {
  readonly sampleRate = TARGET_SAMPLE_RATE;
  readonly channels = 1;
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
 *  para reuniones de Meet/Zoom/Teams/Discord.
 *
 *  Las dos fuentes viajan en canales separados (L=mic, R=sistema) en vez de
 *  mezcladas: así el servidor atribuye cada frase por energía de canal, sin
 *  depender de un modelo de diarización ni de que las etiquetas se mantengan
 *  estables entre chunks. */
export class SystemAudioSource implements AudioSource {
  readonly sampleRate = TARGET_SAMPLE_RATE;
  readonly channels = 2;
  private micStream: MediaStream | null = null;
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
    const workletUrl = URL.createObjectURL(
      new Blob([WORKLET_CODE_STEREO], { type: "application/javascript" }),
    );
    try {
      await this.context.audioWorklet.addModule(workletUrl);
    } finally {
      URL.revokeObjectURL(workletUrl);
    }
    const micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
    this.micStream = micStream;
    const micNode = this.context.createMediaStreamSource(micStream);
    const systemNode = this.context.createMediaStreamSource(new MediaStream(audioTracks));
    // Canal 0 = micrófono (vos), canal 1 = audio del sistema (el remoto).
    // Separados, el servidor sabe quién habló por energía de canal; mezclados
    // esa información se pierde para siempre.
    const merger = this.context.createChannelMerger(2);
    micNode.connect(merger, 0, 0);
    systemNode.connect(merger, 0, 1);
    this.node = new AudioWorkletNode(this.context, "echo-capture-stereo", {
      channelCount: 2,
      channelCountMode: "explicit",
      channelInterpretation: "discrete",
    });
    merger.connect(this.node);

    const inputRate = this.context.sampleRate;
    const ratio = inputRate / TARGET_SAMPLE_RATE;
    let pending = new Float32Array(0);
    const FRAME_SAMPLES = 1600;

    let pendingRight = new Float32Array(0);

    this.node.port.onmessage = (
      event: MessageEvent<{ left: Float32Array; right: Float32Array }>,
    ) => {
      const { left, right } = event.data;
      let sum = 0;
      for (let index = 0; index < left.length; index++) {
        const mixed = left[index] + right[index];
        sum += mixed * mixed;
      }
      onLevel(Math.min(1, Math.sqrt(sum / left.length) * 4));

      const outLength = Math.floor(left.length / ratio);
      const mergedLeft = new Float32Array(pending.length + outLength);
      const mergedRight = new Float32Array(pendingRight.length + outLength);
      mergedLeft.set(pending);
      mergedRight.set(pendingRight);
      for (let index = 0; index < outLength; index++) {
        const source = Math.floor(index * ratio);
        mergedLeft[pending.length + index] = left[source];
        mergedRight[pendingRight.length + index] = right[source];
      }
      let offset = 0;
      while (mergedLeft.length - offset >= FRAME_SAMPLES) {
        // Intercalado L,R,L,R… El servidor separa los canales para atribuir
        // hablante y los mezcla para transcribir.
        const frame = new Int16Array(FRAME_SAMPLES * 2);
        for (let index = 0; index < FRAME_SAMPLES; index++) {
          const l = Math.max(-1, Math.min(1, mergedLeft[offset + index]));
          const r = Math.max(-1, Math.min(1, mergedRight[offset + index]));
          frame[index * 2] = l < 0 ? l * 0x8000 : l * 0x7fff;
          frame[index * 2 + 1] = r < 0 ? r * 0x8000 : r * 0x7fff;
        }
        onFrame(frame);
        offset += FRAME_SAMPLES;
      }
      pending = mergedLeft.slice(offset);
      pendingRight = mergedRight.slice(offset);
    };
  }

  async stop(): Promise<void> {
    this.node?.disconnect();
    this.node = null;
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
    this.displayStream?.getTracks().forEach((track) => track.stop());
    this.displayStream = null;
    this.micStream?.getTracks().forEach((track) => track.stop());
    this.micStream = null;
    await this.mic.stop();
  }
}
