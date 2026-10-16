// Microphone, speaker and camera of the device app. Talks binary over the display
// WebSocket (see backend/src/justai/display/media.py):
//   0x01 mic PCM16 16 kHz · 0x02 camera JPEG · 0x11 speaker PCM16 16 kHz (from the core)

export type CameraMode = "off" | "user" | "environment";

export interface MediaFeatures {
  mic: boolean;
  speaker: boolean;
  camera: CameraMode;
}

export const MIC = 0x01;
export const CAMERA = 0x02;
export const SPEAKER = 0x11;

const CAMERA_INTERVAL_MS = 500;
const CAMERA_WIDTH = 960;

export class DeviceMedia {
  private ctx: AudioContext | null = null;
  private playback: AudioWorkletNode | null = null;
  private streams: MediaStream[] = [];
  private cameraTimer: number | undefined;
  readonly video: HTMLVideoElement = document.createElement("video");
  micLevel = 0;

  constructor(private send: (data: ArrayBuffer | Blob) => void) {
    this.video.muted = true;
    this.video.playsInline = true;
  }

  async start(features: MediaFeatures): Promise<void> {
    await this.stop();
    if (features.mic || features.speaker) {
      // 16 kHz context where supported; the worklets resample otherwise.
      let ctx: AudioContext;
      try {
        ctx = new AudioContext({
          sampleRate: 16000,
          latencyHint: "interactive",
        });
      } catch {
        ctx = new AudioContext({ latencyHint: "interactive" });
      }
      this.ctx = ctx;
      await ctx.audioWorklet.addModule("/app-audio-worklet.js");
      if (ctx.state === "suspended") await ctx.resume();
      if (features.speaker) {
        this.playback = new AudioWorkletNode(ctx, "justai-playback", {
          outputChannelCount: [1],
        });
        this.playback.connect(ctx.destination);
      }
      if (features.mic) {
        const stream = await navigator.mediaDevices.getUserMedia({
          // The browser's echo cancellation removes our own speaker from the microphone.
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
        });
        this.streams.push(stream);
        const capture = new AudioWorkletNode(ctx, "justai-capture");
        capture.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
          const pcm = new Int16Array(e.data);
          let peak = 0;
          for (let i = 0; i < pcm.length; i += 8)
            peak = Math.max(peak, Math.abs(pcm[i]));
          this.micLevel = 0.8 * this.micLevel + 0.2 * (peak / 32768);
          const msg = new Uint8Array(1 + e.data.byteLength);
          msg[0] = MIC;
          msg.set(new Uint8Array(e.data), 1);
          this.send(msg.buffer);
        };
        ctx.createMediaStreamSource(stream).connect(capture);
        const sink = ctx.createGain(); // keep the worklet running without making noise
        sink.gain.value = 0;
        capture.connect(sink).connect(ctx.destination);
      }
    }
    if (features.camera !== "off") {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: features.camera,
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      this.streams.push(stream);
      this.video.srcObject = stream;
      await this.video.play().catch(() => undefined);
      const canvas = document.createElement("canvas");
      this.cameraTimer = window.setInterval(() => {
        const w = this.video.videoWidth;
        const h = this.video.videoHeight;
        if (!w || !h || document.visibilityState === "hidden") return;
        canvas.width = Math.min(CAMERA_WIDTH, w);
        canvas.height = Math.round((canvas.width / w) * h);
        canvas
          .getContext("2d")
          ?.drawImage(this.video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(
          (blob) =>
            blob && this.send(new Blob([new Uint8Array([CAMERA]), blob])),
          "image/jpeg",
          0.75,
        );
      }, CAMERA_INTERVAL_MS);
    }
  }

  /** Speech from the core (payload after the type byte). */
  play(pcm: ArrayBuffer): void {
    this.playback?.port.postMessage(pcm, [pcm]);
  }

  get suspended(): boolean {
    return this.ctx?.state === "suspended";
  }

  async resume(): Promise<void> {
    await this.ctx?.resume();
  }

  async stop(): Promise<void> {
    window.clearInterval(this.cameraTimer);
    for (const s of this.streams) s.getTracks().forEach((t) => t.stop());
    this.streams = [];
    this.video.srcObject = null;
    this.playback = null;
    if (this.ctx) await this.ctx.close().catch(() => undefined);
    this.ctx = null;
    this.micLevel = 0;
  }
}

export function capabilitiesFor(features: MediaFeatures): string[] {
  const caps: string[] = [];
  if (features.mic) caps.push("audio.input");
  if (features.speaker) caps.push("audio.output");
  if (features.camera !== "off") caps.push("video.input", "camera.snapshot");
  return caps;
}
