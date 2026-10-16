// AudioWorklet processors of the JuStAI5 device app.
// "justai-capture": microphone -> 20 ms frames of 16 kHz PCM16 (posted to the main thread)
// "justai-playback": 16 kHz PCM16 from the core -> speaker, with a small jitter buffer

const TARGET_RATE = 16000;
const FRAME = 320; // 20 ms at 16 kHz

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE; // input samples per output sample
    this.pos = 0;
    this.out = new Int16Array(FRAME);
    this.n = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    // Linear resampling to 16 kHz (no-op when the context already runs at 16 kHz).
    while (this.pos < input.length) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = input[i];
      const b = i + 1 < input.length ? input[i + 1] : a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * frac));
      this.out[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === FRAME) {
        this.port.postMessage(this.out.buffer, [this.out.buffer]);
        this.out = new Int16Array(FRAME);
        this.n = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= input.length;
    return true;
  }
}

class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = TARGET_RATE / sampleRate; // source samples per output sample
    this.buffer = new Float32Array(TARGET_RATE * 10); // ring buffer, 10 s
    this.read = 0;
    this.write = 0;
    this.playing = false;
    this.port.onmessage = (e) => {
      if (e.data === "clear") {
        this.read = this.write;
        this.playing = false;
        return;
      }
      const pcm = new Int16Array(e.data);
      for (let i = 0; i < pcm.length; i++) {
        this.buffer[this.write % this.buffer.length] = pcm[i] / 0x8000;
        this.write++;
      }
    };
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    const available = this.write - this.read;
    // Start only with 60 ms buffered (network jitter), stop when empty.
    if (!this.playing && available >= TARGET_RATE * 0.06) this.playing = true;
    for (let i = 0; i < out.length; i++) {
      if (this.playing && this.write - this.read >= 1) {
        const idx = Math.floor(this.read);
        const frac = this.read - idx;
        const a = this.buffer[idx % this.buffer.length];
        const b = this.buffer[(idx + 1) % this.buffer.length];
        out[i] = a + (b - a) * frac;
        this.read += this.step;
      } else {
        out[i] = 0;
        this.playing = false;
      }
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    return true;
  }
}

registerProcessor("justai-capture", CaptureProcessor);
registerProcessor("justai-playback", PlaybackProcessor);
