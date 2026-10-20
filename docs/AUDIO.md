# Audio: echo, VAD, wakeword, arbitration, duplex

*[Deutsch](de/AUDIO.md) · English*

The most important requirement: **the assistant never reacts to its own voice.** Network
cameras as microphone and speaker make this hard: the output comes back through go2rtc and
the camera backchannel into the microphone with 1–2 s delay and fluctuating latency.
That is why there are several independent protection layers, not just one echo canceller
([ADR 0005](adr/0005-echo-handling.md)).

Code: `backend/src/justai/audio/`.

## Signal path

```
go2rtc (RTSP) ─► ffmpeg ─► 16 kHz mono s16le ─► SampleClock (timestamps)
  ─► MicChannel ─► per endpoint: EndpointAudioProcessor (10 ms frames, own thread)
       1. gain
       2. echo window? (PlaybackTracker: playback bursts + latency + reverb)
       3. WebRTC APM: HPF, AEC3 (reference shifted by the measured latency), NS
       4. Silero VAD, noise floor, speech segmentation
       5. gating: half duplex → drop everything in the echo window
                  full duplex → only pass on detected double talk (barge-in)
       6. openWakeWord (with suppression during playback)
  ─► wake candidates ─► WakeArbiter ─► conversation session
  ─► ProcessedFrame (gated flag) ─► session (STT or realtime upload)

answer ─► output router ─► SpeakerChannel (real-time pacing)
  ─► sink: go2rtc talkback | plugin sink
  ─► every output frame with its output time ─► ReferenceBuffer + PlaybackTracker
```

**A separate speaker connection per conversation:** a Tapo camera only plays the talk
session that was opened last. Earlier the channel to the camera speaker stayed open on
the main connection for hours. If another client had spoken in between (e.g. the Tapo
app), bytes kept arriving at the camera but nothing was audible. go2rtc does not renew
this session as long as the video keeps the connection alive. Observed live on the C200
(2026-10-20): delivery complete, nothing audible, also after restarting go2rtc and the
camera; a freshly opened second connection played immediately. Therefore:

* The speaker has its own go2rtc stream `<stream>_talk` (same source as the main stream,
  thus its own camera connection). It is created anew on every opening: at the wakeword
  (pre-warming), for test tones and automations.
* After 90 s without output it is closed and deleted (`speaker_idle_close_s` can be
  overridden per device). The camera's talk session is then free again for the Tapo app.
* The Tapo login of the new connection takes about 4 s (measured). Until then the core
  holds speech back (plus `talkback_settle_s`, default 1.5 s) instead of sending it into
  the not yet connected line; the beginning is not lost.

**Checking delivery instead of assuming it:** go2rtc keeps fetching the audio stream even
when the connection to the camera speaker was lost (e.g. after a camera reconnect). The
audio then disappeared silently. The core therefore asks go2rtc every second whether
bytes actually go to the camera. Only then does it release speech, and after 6 s without
delivery it rebuilds the path (for an offline camera with growing intervals up to 60 s).
A freshly opened connection has 20 s for the login. The bytes to the camera are also
counted when go2rtc lists the camera connection as a "consumer" (stream only for the
speaker); otherwise the watchdog considered working connections dead and kept rebuilding
them. Checked live: after "Reconnect" of the C200 the path was back after ~15 s (8 KB/s
to the camera, stable).

If a camera still stays silent: "Reconnect the camera in the office" by voice
(`devices.reconnect`) or *Devices → Reconnect*, and "Test the speaker in the office"
(`devices.test_speaker`).

**Talkback to cameras:** the core provides a live WAV stream per speaker
(`/internal/talkback/<token>.wav`, random token, only in the internal network). go2rtc
pulls it as a source into the camera's backchannel
(`POST /api/ffmpeg?dst=<stream>&live=<url>`). The core paces the output itself in real
time. That is why it knows for every frame when it was output; this is the echo
reference. If the path breaks, it is rebuilt.

## Protection layers against talking to itself

| # | Layer | Where | Protects against |
| --- | --- | --- | --- |
| 1 | **AEC3 with bulk delay compensation** | `echo.py` `EchoCanceller` + `DelayEstimator` | echo in the signal (full duplex) |
| 2 | **Echo window + half duplex gate**: while own output can be audible (output + latency + reverb), the microphone is dropped | `PlaybackTracker`, `processor.py` | all echo, deterministically |
| 3 | **Wakeword suppression during playback**: half duplex: no wakewords in the echo window; full duplex: only above `threshold_during_playback` (0.85) | `processor._run_wakeword` | the assistant saying "Hey Jarvis" itself |
| 4 | **Echo transcript filter**: if a user transcript closely resembles what the assistant said in the last 25 s, it is dropped | `conversation/echo_filter.py` | residual echo that was transcribed anyway |
| 5 | **Leaving out the wakeword tail**: after a pause the session starts behind the pause; utterances with less than 200 ms of speech do not start the pipeline at all ([speaking without a pause](#speaking-without-a-pause-after-the-wakeword)) | `conversation/session.py` | "Jarvis" remainder or reverb interpreted as a question or blocking the session |
| 6 | **Inactivity timeout only starts after the echo window ends** | `conversation/state.py` | session ending during output |

In addition the echo window tracker remembers several output bursts, because the echo of
an earlier sentence can still be on its way while the next one begins.

### Measurement: AEC3 and long delays

WebRTC AEC3 only estimates the delay between reference and microphone within a limited
range. Measured with `scripts/measure_aec.py` (synthetic speech-like signal, short
reverb, no near-end speaker; ERLE = echo attenuation after convergence):

| Echo delay | AEC3 alone | AEC3 + bulk delay compensation |
| ---: | ---: | ---: |
| 0.05 s | 32.1 dB | 32.2 dB |
| 0.20 s | 31.4 dB | 32.3 dB |
| 0.40 s | 39.6 dB | 39.7 dB |
| 0.60 s | **10.5 dB** | 40.0 dB |
| 0.80 s | **9.9 dB** | 40.0 dB |
| 1.20 s | **9.8 dB** | 40.3 dB |
| 1.80 s | **9.4 dB** | 40.5 dB |

From about 0.5 s AEC3 alone fails; about 10 dB from the residual suppression remain.
Network cameras are well above that (C200: ~1.8 s). JuStAI5 therefore shifts the
reference itself by the measured delay and leaves only the rest (10 ms) to AEC3. The
delay is estimated continuously by `DelayEstimator` with GCC-PHAT from microphone and
reference (only estimates with sufficient confidence, median of the last 7).

Real rooms with reverb, non-linearities of cheap speakers and fluctuating network latency
achieve less. That is why layer 2 (gating) remains the base protection, and full duplex
is only enabled after measurement.

## Duplex modes

| Mode | Behaviour |
| --- | --- |
| `half` | In the echo window the microphone is dropped completely. No barge-in during output. Safe with every device. |
| `full` | AEC active, microphone stays open. Barge-in via double talk detection. Only for devices with real full duplex audio and good echo separation. |
| `auto` (default) | Starts as `half`. Switches to `full` only if the device reports `audio.full_duplex`, the delay is measured and the measured echo attenuation (median over ≥ 200 frames) is at least 18 dB. The reason is shown in the audio diagnosis (`duplex_reason`). |

**Barge-in (full duplex):** the AEC residual suppression also attenuates the user's voice
during double talk. Detection therefore works on the **raw** signal: microphone level
minus expected echo level (reference energy + measured room coupling). If the level is
≥ 8 dB above (with VAD ≥ 0.5, otherwise ≥ 14 dB) for about two thirds of
`barge_in_min_speech_ms`, it counts as an interruption. Output stops immediately, the
tracker shortens the echo window and the session listens. Echo alone never triggers a
barge-in in the tests.

## Calibration

Admin UI → Endpoints → *Calibrate* (`POST /api/endpoints/{id}/calibrate`): three sweeps
(400–3200 Hz) through the speaker, recording through the microphone, evaluation with
GCC-PHAT. If the correlation is too weak, the onset time with a consensus check over all
sweeps is used.

Results and their meaning:

* `echo delay measured`: the delay is set as the starting value.
* *No echo at the microphone*: the device mutes its microphone during playback (hardware
  half duplex, e.g. **Tapo C200**). That is safe; the conservative default latency stays
  active.
* *Echo audible but not measurable*: keep half duplex.

Without calibration the system conservatively assumes 2.2 s latency for network devices
and 0.35 s for local devices. The latency actually used is never smaller than the
measured delay + 0.15 s.

## VAD and end of utterance

Silero VAD (ONNX) on the processed signal. Speech begins after 3 consecutive frames above
`vad_threshold` (30 ms) and ends after 300 ms below it. In pipeline mode the end of an
utterance is determined by `end_of_utterance_silence_ms` (default 700 ms), maximum length
`max_utterance_s`. In realtime mode the provider takes over turn detection; JuStAI5 only
sends non-gated frames.

## Wakeword

openWakeWord 0.6.0 (ONNX), threshold 0.5 per endpoint, refractory time 1.5 s. Selection:
*Rooms → edit endpoint → Wakeword* (several at the same time possible).

Included: **Hey Jarvis** (default), **Alexa**, **Hey Mycroft**, **Hey Rhasspy**, all
trained on English. They work just as well when the rest of the conversation is German or
Italian.

**Own wakewords** (e.g. "Hey Justi"): train an openWakeWord model (the openWakeWord project
provides a training notebook with synthetic speech data), then install the `.onnx` file
in the same tab with *Upload own wakeword*. The file name becomes the ID
(`hey_justi.onnx` → `hey_justi`). The core checks that it really is an openWakeWord
classifier (input `[1, n, 96]`, output `[1, 1]`) and stores it in the volume
`/data/wakewords`, so it survives updates. Own models can be deleted
(`DELETE /api/ai/wakewords/<id>`) as long as no endpoint uses them.

**Pausing listening:** "Stop listening in the bedroom for an hour" switches off the
wakeword of the room's endpoints (`audio.listening`); a one-time automation switches it on
again ([DEVICES.md](DEVICES.md#operating-devices-by-voice)).

## Room-aware wakeword arbitration

`audio/arbitration.py`. Several microphones hear the same wakeword. Candidates from the
same **arbitration group** that arrive within 0.8 s are collected and scored, and exactly
one wins. A reliable room matters more than the fastest activation.

```
score = 10·wake_score + 0.25·clamp(SNR_phrase, −10, 70) + 2·VAD + priority
        − 3 (if during own playback) + 100 (if a session is already running there)
```

* **SNR of the phrase**: 90th percentile of the *raw* levels of the last 1.2 s (that is
  the wakeword itself, not the pause after it) minus the raw noise floor. Noise
  suppression would distort the real distance. Loudness is the best hint for proximity and
  deliberately dominates small differences in wakeword confidence.
* **Late duplicates**: microphones behind different network paths deliver the same
  utterance with different delays. Candidates of other endpoints of the same group that
  arrive within 2 s after a decision are dropped (`audio.wakeword.rejected`). A later,
  real wakeword is accepted.
* Endpoints in different groups are decided independently: parallel conversations are
  possible.

Events: `audio.wakeword.detected` (every candidate), `audio.wakeword.accepted` (with the
scores of all candidates), `audio.wakeword.rejected`.

## Speaking without a pause after the wakeword

"Hey Jarvis, what time is it?" in one breath works. Between detection and a ready session
1.4–1.7 s pass (measured: arbitration window 0.8 s, session setup 0.55–0.9 s incl.
connection to Gemini Live). So these words are not lost:

* Every endpoint keeps the last 10 s of processed audio (`EndpointAudio.recent`).
* When the session is ready it first gets the buffered audio from the wakeword on, then
  live audio (without an `await` in between: no frame is missing or doubled).
* Where the spoken text begins is decided by the speech activity (`replay_start`):
  * **Pause** (≥ 150 ms below the speech threshold within 0.8 s after detection): from
    the pause; the reverb of "Jarvis" stays out.
  * **No pause**: from 0.15 s **before** detection. openWakeWord reports 0.04–0.27 s
    (measured) after the end of "Hey Jarvis", i.e. often already during the first word of
    the question; this way it is kept.
* The pipeline does not start recognition for "utterances" with less than 200 ms of
  speech (clicks, reverb). Otherwise the session would be deaf to the actual question
  during the unnecessary speech recognition.

Tested: `tests/unit/test_wake_replay.py`, `tests/audio/test_wake_replay.py` (real
openWakeWord, Piper voice: with and without a pause), E2E
`test_question_right_after_the_wakeword_without_a_pause` in pipeline and realtime mode
(failed before: the question was lost).

## Tested

* `backend/tests/unit/test_echo_blocks.py`, `test_wake_arbitration.py`,
  `test_calibration.py`: building blocks (reference buffer, GCC-PHAT, tracker,
  arbitration incl. late duplicates, onset calibration).
* `backend/tests/audio/test_self_speech.py` (real models: Piper, openWakeWord, Silero):
  the assistant deliberately says "Hey Jarvis" in its answer; the output comes back
  through a simulated room (network delay, reverb, noise, optionally Tapo-like ducking).
  * Half duplex Tapo-like, half duplex with loud echo without ducking: no self-wake, no
    echo passed through, the real wakeword afterwards is detected.
  * Underestimated latency is corrected by measurement.
  * Full duplex: AEC suppresses self-wake, real barge-in is detected; echo alone never
    triggers barge-in.
* E2E (`backend/tests/e2e`): conversation through simulated devices with echo, no echo
  turns in the transcript, arbitration between two rooms.
* Real hardware (Tapo C200): wakeword → answer through the camera speaker, no echo loop,
  end through inactivity. Barge-in with the C200 is impossible because of the hardware
  ducking and was not tested.
