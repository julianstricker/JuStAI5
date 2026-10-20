# 0004 – go2rtc as media server, streams only in memory

*[Deutsch](../de/adr/0004-go2rtc-media.md) · English*

**Status:** accepted

## Context

Cameras speak different protocols (Tapo protocol, RTSP, ONVIF), have a limited number of
connections and often an audio return channel (backchannel) only through
manufacturer-specific ways. Several consumers (audio, vision, live view, snapshots) need
the same streams.

## Decision

go2rtc (1.9.14) as its own container. The core registers streams at runtime through the
API and consumes them by RTSP (ffmpeg) or HTTP. Audio output: the core provides a live WAV
stream paced in real time, which go2rtc pulls into the camera's backchannel. Streams with
credentials are created **only in memory** (`PATCH /api/streams`). The configuration file
is read-only and contains no cameras.

## Alternatives

* **Directly from the core with ffmpeg/PyAV**: every camera connected several times, no
  Tapo backchannel.
* **Frigate/MediaMTX**: Frigate brings its own vision pipeline; MediaMTX cannot do the
  Tapo backchannel.

## Consequences

* One camera connection, many consumers. Exception: the speaker gets its own short-lived
  stream `<stream>_talk` per conversation, because a Tapo camera only plays the talk
  session opened last ([AUDIO.md](../AUDIO.md#signal-path)).
* go2rtc forgets the streams on a restart. A watchdog in the core compares the registered
  streams with those in go2rtc every 5 s and restores missing ones. Tested: after
  `docker compose restart go2rtc` snapshots of the C200 worked again after 2 s, the
  microphones kept running. Before (without the watchdog) the camera stayed unreachable
  permanently. This was only discovered while checking this ADR.
* The core paces the output itself and therefore knows the output time of every frame.
  This is the basis of the echo handling ([0005](0005-echo-handling.md)).
* Found during testing: a `PUT` on `/api/streams` writes the source with credentials into
  `go2rtc.yaml`. Therefore only `PATCH` is used.
