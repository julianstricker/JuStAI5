# 0005 – Multi-layer echo handling with own bulk delay compensation

*[Deutsch](../de/adr/0005-echo-handling.md) · English*

**Status:** accepted

## Context

The assistant must never react to its own voice. With network cameras as microphone and
speaker, its own output comes back with 1–2 s delay (C200: ~1.8 s), fluctuating with the
network load. Some devices mute their microphone during playback.

Measurement (`scripts/measure_aec.py`): WebRTC AEC3 attenuates 32–40 dB up to ~0.4 s
delay, from 0.6 s only ~10 dB. With bulk delay compensation in front it stays at ~40 dB
even at 1.8 s.

## Decision

Several independent layers instead of a single echo canceller
([AUDIO.md](../AUDIO.md#protection-layers-against-talking-to-itself)):

1. AEC3 (via livekit) with a reference shifted by the delay measured with GCC-PHAT,
2. deterministic echo window with a half duplex gate (default), full duplex only after a
   measured echo attenuation ≥ 18 dB,
3. wakeword suppression during its own playback,
4. transcript echo filter against recently said text,
5. ignoring the wakeword tail, inactivity timer only after the echo window.

Calibration measures the delay with sweeps and detects devices that mute their
microphone.

## Alternatives

* **Only AEC3 / Speex**: fails with network latency (measurement above).
* **Always half duplex without AEC**: safe, but no barge-in on suitable devices.
* **Only transcript comparison**: reacts only after STT, i.e. too late for the wakeword.

## Consequences

* Safe also on devices with unknown, fluctuating latency.
* Barge-in only on devices with real full duplex and measured echo attenuation; not
  possible with the C200.
