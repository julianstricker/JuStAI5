# Rooms, interaction endpoints and output router

*[Deutsch](de/ROOMS.md) · English*

## Terms

| Term | Meaning |
| --- | --- |
| **Room** | physical area (living room, kitchen). Devices and endpoints belong to exactly one room. |
| **Device** | camera, microphone, speaker, display … with determined capabilities ([DEVICES.md](DEVICES.md)) |
| **Interaction endpoint** | concrete place where you talk to the assistant: combines independent devices in the roles `mic`, `speaker`, `camera`, `display` |
| **Arbitration group** | endpoints that can hear the same wakeword at the same time (e.g. open-plan kitchen). Exactly one wins per group ([AUDIO.md](AUDIO.md)). |

An endpoint can for example combine the microphone of a Tapo camera, a network speaker
and a TV. A device can appear in several endpoints (the microphone channel is shared).

## Room policies (`policy`)

| Field | Default | Effect |
| --- | --- | --- |
| `shared_space` | true | personal content is not shown on displays here |
| `vision_allowed` | true | cameras in this room are analysed |
| `face_recognition_allowed` | true | face recognition in this room |
| `cloud_media_allowed` | true | images/audio from this room may go to cloud AI |
| `announcements_allowed` | true | the room accepts announcements from other rooms |

## Endpoint configuration

Model: `backend/src/justai/endpoints/service.py`.

```yaml
wakeword:
  enabled: true           # false = do not listen (also by voice: "stop listening here for an hour")
  models: [hey_jarvis]
  threshold: 0.5
  threshold_during_playback: 0.85   # full duplex only
audio:
  duplex: auto            # auto | half | full
  aec: true
  noise_suppression: true
  output_latency_ms: null # measured by calibration
  echo_tail_ms: 600
  input_gain_db: 0
  vad_threshold: 0.5
  barge_in: true
  barge_in_min_speech_ms: 300
conversation:
  mode: default           # default (global setting) | realtime | pipeline
  inactivity_timeout_s: 10
  end_of_utterance_silence_ms: 700
  max_utterance_s: 30
  voice: null
  default_role: resident  # permissions of anonymous speakers at this endpoint
  follow_up_listening: true
  send_video: false       # camera images to realtime providers that support it
  resume_window_s: 300    # a new wakeword within 5 min continues the last conversation (0 = never)
  speaker_check: true     # ... but only if voice/camera do not point to another person
```

### Continuing conversations

If a conversation ends through inactivity and the wakeword is heard again at the same
endpoint within `resume_window_s`, the assistant continues the last conversation (the
previous history is in the context). It does not continue if …

* the conversation was ended on purpose ("Bye", admin),
* the endpoint's camera now sees a different recognised person than before,
* the voice in the wakeword clearly does not match the voice of the last conversation.

The voice comparison uses a speaker model (WeSpeaker ResNet34). The voice fingerprints
exist only in memory, are not assigned to any person and are discarded when the window
expires; recorded speech is deleted right after the calculation. Measured values: same
voice 0.68–0.82, other voice 0.26–0.34 (threshold 0.45; also in 8 kHz camera quality). If
no comparison is possible (e.g. too little speech), the conversation continues within the
window.

At the start of every conversation the assistant also takes over the person that the
endpoint's camera recognised as the only one within the last minute ("You are talking to
Julian").

Further fields: `room_id`, `arbitration_group` (default `default`), `priority`,
`language`, `enabled`.

The conversation language follows the speaker: whoever speaks Italian gets Italian
answers. `language` (or the default language under *AI providers*) is only the starting
point, e.g. for the speech recognition before the first words.

## Output router

`backend/src/justai/output/router.py` is the **only** place that decides which device
may output. The rules are deterministic and never delegated to the language model:

1. Output goes to the room of the triggering interaction. The endpoint's room has
   priority over any room claimed elsewhere.
2. Another target room needs three things: an **explicit** cross-room request (only tools
   like `conversation.announce` set it), the permission `output.cross_room` and a target
   room with `announcements_allowed`.
3. An explicitly requested device must be in the target room, online and have the
   required capability.
4. Audio prefers the speaker of the triggering endpoint. The fallback is another speaker
   **of the same room**, never another room.
5. Personal content does not appear on displays in `shared_space` rooms unless explicitly
   allowed.
6. Offline devices are never chosen. If nothing is available, the output fails with
   `RoutingDenied` instead of silently moving to another room.
7. Output without an origin room (e.g. test tones from the admin UI) is only allowed for
   admins.

Every decision contains reasons (`reasons`) that are visible in the log and the
diagnosis.

### Binding conversations to their room

A conversation session belongs to exactly one endpoint. Every audio output of the session
(answers, tool results, confirmation questions, error notes) asks the output router with
the session's `origin_endpoint_id`. This also applies:

* after long tool calls and waiting times,
* after reconnects or fallbacks of the AI provider,
* when automations start a session: room = room of the triggering event
  (`room: trigger`) or an explicitly configured room.

Verified by the E2E tests (`backend/tests/e2e/test_simulated_rooms.py`): the answer only
appears at the living room speaker, the kitchen speaker does not get a single audio
frame.

## Parallel conversations

Endpoints in **different** arbitration groups can have their own sessions at the same
time. Every session has its own state, history and output. In the E2E test two rooms ask
"2+2" and "3+3" in parallel, and each room gets its own answer.
