"""Per-endpoint audio processing.

For every 10 ms microphone frame the processor decides - deterministically - whether
it may be used as user input:

* **Echo window** (assistant audio may be audible, incl. measured device latency
  and a tail): in *half duplex* the frame is gated; in *full duplex* it passes AEC
  and is only used if a barge-in was detected (sustained speech clearly above the
  expected residual echo).
* **Wakewords** inside the echo window are ignored (half duplex) or need a much
  higher score (full duplex), so the assistant cannot wake itself.

Heavy work (APM, ONNX models) runs on a dedicated worker thread per endpoint.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from justai_sdk.audio import Int16Array
from justai_sdk.ports.wakeword import WakewordDetector

from justai.audio.dsp import FRAME_10MS, SR, Framer, apply_gain, dbfs
from justai.audio.echo import DelayEstimator, EchoCanceller, PlaybackTracker, ReferenceBuffer
from justai.audio.vad import SileroVad
from justai.endpoints.service import AudioConfig, DuplexMode, WakewordConfig


class GateReason(StrEnum):
    OPEN = "open"
    ECHO_WINDOW = "echo_window"
    MUTED = "muted"


@dataclass(frozen=True)
class ProcessedFrame:
    t: float
    pcm: Int16Array  # processed 10 ms frame
    vad: float
    speech: bool  # VAD with hysteresis
    gated: bool  # must not be used as user input
    echo_window: bool


@dataclass(frozen=True)
class WakeCandidate:
    endpoint_id: str
    model: str
    score: float
    t: float
    level_db: float
    snr_db: float
    vad: float
    during_playback: bool


@dataclass
class ProcessorOutput:
    frames: list[ProcessedFrame] = field(default_factory=list)
    wakes: list[WakeCandidate] = field(default_factory=list)
    barge_in: bool = False


@dataclass
class ProcessorStats:
    level_db: float = -120.0
    noise_floor_db: float = -70.0
    vad: float = 0.0
    speech: bool = False
    gated: bool = False
    echo_window: bool = False
    wake_score: float = 0.0
    delay_estimate_s: float | None = None
    delay_confidence: float = 0.0
    erle_db: float | None = None
    effective_duplex: str = "half"
    duplex_reason: str = ""
    frames: int = 0
    gated_frames: int = 0
    suppressed_wakes: int = 0
    processing_ms: float = 0.0


class EndpointAudioProcessor:
    def __init__(
        self,
        endpoint_id: str,
        audio: AudioConfig,
        wakeword: WakewordConfig,
        detector: WakewordDetector | None,
        *,
        reference: ReferenceBuffer,
        tracker: PlaybackTracker,
        output_latency_s: float,
        full_duplex_capable: bool,
    ) -> None:
        self.endpoint_id = endpoint_id
        self.audio = audio
        self.wakeword = wakeword
        self.detector = detector
        self.reference = reference
        self.tracker = tracker
        self.output_latency_s = output_latency_s
        self.full_duplex_capable = full_duplex_capable
        self.stats = ProcessorStats()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"audio-{endpoint_id}")
        self._framer = Framer(FRAME_10MS)
        self._wake_framer = Framer(detector.frame_samples if detector else 1280)
        self._t_next: float | None = None
        self._vad = SileroVad()
        self._speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._barge_in_active = False
        self._barge_window: deque[bool] = deque(maxlen=max(10, audio.barge_in_min_speech_ms // 10 * 4 // 3))
        self._coupling_hist: deque[float] = deque(maxlen=300)
        self._coupling_db: float | None = None
        self._last_wake_t = 0.0
        self._delay = DelayEstimator(max_delay_s=3.5)
        self._raw_hist: deque[tuple[float, Int16Array]] = deque(maxlen=200)  # 2 s raw
        self._last_delay_run = 0.0
        self._erle_hist: deque[float] = deque(maxlen=300)
        self._levels: deque[float] = deque(maxlen=120)  # raw levels of the last 1.2 s (dBFS)
        self._raw_noise_db = -60.0
        self.muted = False
        self._configure_duplex()
        self._aec = EchoCanceller(aec=self.audio.aec and self._duplex_mode == DuplexMode.FULL,
                                  noise_suppression=self.audio.noise_suppression)

    # --------------------------------------------------------------- configuration
    def _configure_duplex(self) -> None:
        mode = self.audio.duplex
        if mode == DuplexMode.AUTO:
            # Auto starts safe. Full duplex is only chosen when the device reports
            # full-duplex audio AND the measured echo cancellation is good enough.
            if not self.full_duplex_capable:
                self._duplex_mode = DuplexMode.HALF
                self.stats.duplex_reason = "device reports no full-duplex audio"
            else:
                self._duplex_mode = DuplexMode.HALF
                self.stats.duplex_reason = "waiting for echo measurement"
        else:
            self._duplex_mode = mode
            self.stats.duplex_reason = "configured"
        self.stats.effective_duplex = self._duplex_mode.value

    @property
    def duplex(self) -> DuplexMode:
        return self._duplex_mode

    @property
    def latency_s(self) -> float:
        """Emission-to-microphone latency used for gating (never below the measured delay)."""
        configured = (self.audio.output_latency_ms / 1000) if self.audio.output_latency_ms else None
        base = configured if configured is not None else self.output_latency_s
        measured = self._delay.delay_s
        if measured is not None:
            base = max(base, measured + 0.15)
        return base

    @property
    def tail_s(self) -> float:
        return self.audio.echo_tail_ms / 1000

    def seed_delay(self, delay_s: float) -> None:
        self._delay.seed(delay_s)

    # ------------------------------------------------------------------- feeding
    async def feed(self, t: float, pcm: Int16Array) -> ProcessorOutput:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._process, t, pcm)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def reset_speech(self) -> None:
        self._speech = False
        self._speech_frames = self._silence_frames = 0
        self._barge_in_active = False
        self._barge_window.clear()

    def end_barge_in(self) -> None:
        self._barge_in_active = False

    def _process(self, t: float, pcm: Int16Array) -> ProcessorOutput:
        started = time.perf_counter()
        out = ProcessorOutput()
        if self._t_next is None or abs(t - self._t_next) > 0.05:
            self._t_next = t
        pcm = apply_gain(pcm, self.audio.input_gain_db)
        for frame in self._framer.push(pcm):
            ft = self._t_next
            self._t_next += FRAME_10MS / SR
            self._process_frame(ft, frame, out)
        self.stats.processing_ms = 0.9 * self.stats.processing_ms + 0.1 * (
            (time.perf_counter() - started) * 1000)
        return out

    def _process_frame(self, t: float, raw: Int16Array, out: ProcessorOutput) -> None:
        st = self.stats
        st.frames += 1
        echo_window = self.tracker.in_echo_window(t, self.latency_s, self.tail_s)
        self._raw_hist.append((t, raw))
        delay = self._delay.delay_s if self._delay.delay_s is not None else self.latency_s
        ref = self.reference.get(t - delay + EchoCanceller.RESIDUAL_DELAY_MS / 1000, FRAME_10MS) \
            if echo_window else None
        processed = self._aec.process(raw, ref)

        level = dbfs(processed)
        raw_db = dbfs(raw)
        self._levels.append(raw_db)
        st.level_db = 0.7 * st.level_db + 0.3 * level
        vad = self._vad.process(processed)
        st.vad = vad
        if not echo_window and vad < 0.2:
            st.noise_floor_db = 0.995 * st.noise_floor_db + 0.005 * level
            self._raw_noise_db = 0.995 * self._raw_noise_db + 0.005 * raw_db

        if echo_window:
            self._measure_echo(t, raw, processed)
            self._measure_coupling(t, raw_db, vad)
        self._update_speech(vad)

        gated = False
        if self.muted:
            gated = True
        elif echo_window:
            if self._duplex_mode == DuplexMode.HALF:
                gated = True
            else:
                gated = not self._detect_barge_in(vad, raw_db, t, out)
        st.gated, st.echo_window, st.speech = gated, echo_window, self._speech
        if gated:
            st.gated_frames += 1
        out.frames.append(ProcessedFrame(t, processed, vad, self._speech, gated, echo_window))
        self._run_wakeword(t, processed, level, vad, echo_window, out)

    def _update_speech(self, vad: float) -> None:
        threshold = self.audio.vad_threshold
        if vad >= threshold:
            self._speech_frames += 1
            self._silence_frames = 0
            if not self._speech and self._speech_frames >= 3:
                self._speech = True
        else:
            self._silence_frames += 1
            self._speech_frames = 0
            if self._speech and self._silence_frames >= 30:
                self._speech = False

    def _detect_barge_in(self, vad: float, raw_db: float, t: float, out: ProcessorOutput) -> bool:
        """Double-talk detection on the *raw* signal.

        The AEC suppressor attenuates near-end speech during double talk, so the
        decision uses the raw microphone level compared with the echo level expected
        from the reference and the measured room coupling.
        """
        if self._barge_in_active:
            return True
        if not self.audio.barge_in:
            return False
        delay = self._delay.delay_s or self.latency_s
        ref_db = self.reference.energy_db(t - delay, FRAME_10MS)
        coupling = self._coupling_db if self._coupling_db is not None else 0.0
        excess = raw_db - max(ref_db + coupling, self.stats.noise_floor_db)
        qualifies = excess >= 8.0 and (vad >= 0.5 or excess >= 14.0)
        self._barge_window.append(qualifies)
        need = max(5, int(self.audio.barge_in_min_speech_ms / 10 * 0.66))
        if sum(self._barge_window) >= need:
            self._barge_in_active = True
            self._barge_window.clear()
            out.barge_in = True
            return True
        return False

    def _measure_coupling(self, t: float, raw_db: float, vad: float) -> None:
        """Room echo coupling (mic level relative to the emitted reference) from
        echo-only frames; used to predict the echo level for double-talk detection."""
        delay = self._delay.delay_s or self.latency_s
        ref_db = self.reference.energy_db(t - delay, FRAME_10MS)
        if ref_db > -50 and vad < 0.3 and raw_db > self.stats.noise_floor_db + 6:
            self._coupling_hist.append(raw_db - ref_db)
            if len(self._coupling_hist) >= 20:
                self._coupling_db = float(np.percentile(self._coupling_hist, 75))

    def _measure_echo(self, t: float, raw: Int16Array, processed: Int16Array) -> None:
        raw_db, out_db = dbfs(raw), dbfs(processed)
        if raw_db > self.stats.noise_floor_db + 10:
            self._erle_hist.append(raw_db - out_db)
            self.stats.erle_db = float(np.median(self._erle_hist))
        if t - self._last_delay_run >= 0.5 and len(self._raw_hist) >= 150:
            self._last_delay_run = t
            t0 = self._raw_hist[0][0]
            mic = np.concatenate([f for _, f in self._raw_hist])
            est = self._delay.estimate(mic, t0, self.reference)
            last = self._delay.last
            self.stats.delay_confidence = last.confidence if last else 0.0
            if est is not None:
                self.stats.delay_estimate_s = self._delay.delay_s
            self._maybe_upgrade_duplex()

    def _maybe_upgrade_duplex(self) -> None:
        if self.audio.duplex != DuplexMode.AUTO or not self.full_duplex_capable:
            return
        erle = self.stats.erle_db
        if self._duplex_mode == DuplexMode.HALF and self._delay.delay_s is not None \
                and erle is not None and len(self._erle_hist) >= 200 and erle >= 18:
            self._duplex_mode = DuplexMode.FULL
            self._aec = EchoCanceller(aec=self.audio.aec,
                                      noise_suppression=self.audio.noise_suppression)
            self.stats.duplex_reason = f"echo cancellation measured at {erle:.0f} dB"
            self.stats.effective_duplex = "full"

    def _run_wakeword(self, t: float, pcm: Int16Array, level: float, vad: float,
                      echo_window: bool, out: ProcessorOutput) -> None:
        if self.detector is None or not self.wakeword.enabled:
            return
        for chunk in self._wake_framer.push(pcm):
            detections = self.detector.process(chunk)
            best = max(detections, key=lambda d: d.score, default=None)
            self.stats.wake_score = best.score if best else 0.0
            if best is None or best.score < self.wakeword.threshold:
                continue
            if t - self._last_wake_t < 1.5:  # refractory period
                continue
            if echo_window and (self._duplex_mode == DuplexMode.HALF
                                or best.score < self.wakeword.threshold_during_playback):
                self.stats.suppressed_wakes += 1
                continue
            if self.muted:
                continue
            self._last_wake_t = t
            # Loudness of the wake phrase itself (not of the frame at detection time,
            # which often falls into the pause after the word): best indicator of which
            # microphone is closest to the speaker.
            # Raw (pre noise suppression) levels: NS would hide the real background noise.
            phrase_level = float(np.percentile(self._levels, 90)) if self._levels else level
            out.wakes.append(WakeCandidate(
                self.endpoint_id, best.model, best.score, t, phrase_level,
                phrase_level - self._raw_noise_db, vad, echo_window))
