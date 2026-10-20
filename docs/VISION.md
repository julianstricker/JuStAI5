# Vision and identity

*[Deutsch](de/VISION.md) · English*

Code: `backend/src/justai/vision/`, `backend/src/justai/identity/`, models through the
plugin `vision-opencv`.

## Pipeline (resource-saving)

```
go2rtc substream ─► ffmpeg (fps per camera, default 2) ─► privacy mask
  ─► motion detection
  ─► object detection YOLOX – only on motion, active tracks or every heartbeat_s (20 s)
  ─► IoU tracker (per class, time-based ageing)
  ─► face check YuNet + SFace on a full-res snapshot – only for still unknown person tracks
  ─► events · sightings (DB) · watches · PTZ tracking listener
```

* One detector and one face model for all cameras, inference in a limited thread pool
  (2 workers).
* During conversations the background frame rate drops (`background_slowdown`). PTZ
  tracking switches on the analysis of every frame for its camera.
* Rooms with `vision_allowed: false` are not analysed; with
  `face_recognition_allowed: false` there is no face recognition there.

## Configuration per camera

Admin UI → *Vision* (`PUT /api/vision/cameras/{device_id}`), or by voice for on/off
("Stop analysing the living room camera", tool `vision.analysis`):

| Field | Default |
| --- | --- |
| `enabled` | true |
| `fps` | 2 (0.2–10) |
| `motion`, `objects`, `faces` | true |
| `labels` | person, dog, cat, car, truck, bicycle, motorcycle, bird |
| `min_score` | 0.5 |
| `privacy_zones` | polygons (normalised coordinates); blacked out before every analysis |
| `heartbeat_s` | 20 |

A camera in privacy mode ("switch off the camera in the bedroom") delivers no image; the
analysis pauses until it is switched on again.

## When does somebody count as "seen"?

The object detector only runs on motion or every 20 s. If somebody sits still, their track
breaks between two runs (after 4 s without a hit) and is recognised again shortly after.
Therefore:

* `vision.person.recognized` is reported at most every 2 minutes per person.
* The event contains `away_s`: seconds since the person was last identified on any camera
  (after a restart from the stored sightings; never seen = one year). This lets
  automations distinguish "came back" from "sat there all the time".

## Events

`vision.motion.started/ended`, `vision.object.appeared/left`, `vision.person.recognized`
(biometric, high priority), `vision.face.unknown`, `vision.watch.triggered`,
`vision.state.changed`.

## Tools for the assistant

| Tool | Purpose |
| --- | --- |
| `vision.look` | snapshot of the camera in the room (or a named one) to the vision model: "What do you see?" |
| `vision.detect` | local object detection on the current image |
| `vision.where_is` | last sighting of a person/pet/object (from the sightings) |
| `vision.watch` / `vision.unwatch` | watch task: "Tell me when a car drives into the driveway" (optionally time-limited). When triggered, an announcement in the room where the task was given, in the language it was given in. |
| `vision.state_teach` / `vision.state_get` | learnable states ("The garage door is open now"), see below |
| `vision.search_area` | search an area with a PTZ camera ([PTZ.md](PTZ.md)) |
| `vision.analysis` | switch the image analysis of a camera on or off |

Images only go to cloud models if the privacy rules allow it (`camera_images_to_cloud`
globally and `cloud_media_allowed` in the room). Otherwise a local vision model from the
role `vision` is used or the request is refused.

## Learnable state detectors

For fixed cameras: a detector watches a region (e.g. the garage door). The user shows
examples by naming the current state; several references per state are possible
(day/night). Classification is a nearest-neighbour comparison on normalised, scaled-down
greyscale crops. It needs no training and no new code. State changes create
`vision.state.changed` and can trigger automations.

Limits: strong light changes without a matching reference lead to wrong states. So create
references in different light conditions.

## People, pets, faces

People and pets are managed in the admin UI under *People* or created in conversation ("I
am Julian", tool `identity.introduce`).

**Biometrics only with consent.**

* Face embeddings are only stored if a consent (kind `face`) with evidence (who, when,
  how) is recorded for the person.
* The tool `identity.register_face` requires an explicit spoken confirmation
  (`requires_confirmation`) and the permission `biometric.enroll`.
* Registration checks the quality: face size ≥ 70 px, sharpness, frontality. Nearly
  identical shots are not stored twice.
* Revoking consent or deleting the person removes **all** biometric data (embeddings,
  thumbnails). People can be exported (`GET /api/people/{id}/export`) and merged.

**Recognition:**

* SFace cosine similarity: from 0.40 "weak", from 0.52 "strong" (configurable in the
  plugin). This is **not a calibrated probability** and is never shown as a percentage.
* A track counts as recognised with one strong hit or two weak hits for the same person.
* Biometrics personalise (form of address, own memories) but **never grant administrator
  rights** (`auth/rbac.py`).
* Pets: if there is exactly one registered animal of a species, a recognised dog or cat is
  assigned to this animal (an assumption, marked as such).

## Voice profiles

Besides the face a person can also be recognised by voice: the face shows who is in the
room, the voice who is speaking.

* **Creating in conversation**: "Remember my voice" (tool `identity.register_voice`,
  confirmation required, permission `biometric.enroll`). The assistant uses what was said
  in this conversation (at least 4 s; otherwise it asks for a few more sentences) and
  stores several voice samples from it (embeddings, no recordings; max. 10 per person, the
  newest are kept). Consent "voice" is recorded with evidence.
* **Recognition**: at the "Hey Jarvis" at the start of every conversation; if that is not
  enough, once more after ~3 s of speech. A name is only given with similarity ≥ 0.55 and
  a margin ≥ 0.08 to the next best person. The voice has priority over the camera.
* **Deleting**: "Forget my voice" (`identity.forget_voice`), *People → Delete voice
  profile*, revoking consent or deleting the person remove all samples. Merging transfers
  them, export contains them.
* A recognised face or voice personalises the conversation (own memories, form of
  address) but never gives admin rights. A voice can be imitated with a recording; it is
  not authentication.

## Tested

* Unit: tracker, motion, privacy mask, state classification, point in polygon
  (`tests/unit/test_vision_logic.py`).
* With a real camera (C200): snapshots and `vision.look` (Gemini, with fallback to
  `gemini-flash-lite-latest` on overload). Face registration and recognition with the
  real camera are **still pending** because a person has to stand in front of the camera.
* E2E: `vision.person.recognized` (injected) triggers a greeting automation in the right
  room.
