# PTZ: movable cameras

*[Deutsch](de/PTZ.md) · English*

Code: `backend/src/justai/ptz/` (logic in `tracking.py` without I/O, service in
`service.py`). Drivers implement the port `justai_sdk.ports.ptz.PtzController`: Tapo
(pytapo, cloud password), ONVIF (also Tapo via port 2020 with the camera account),
simulated (panorama image with a movable crop). Reusable ONVIF building block for
plugins: `justai_sdk.contrib.onvif_ptz`.

## Capabilities

Determined per device: pan, tilt, zoom, presets, absolute positioning. Cameras without an
absolute position (e.g. Tapo) are moved relatively. The service then estimates the
position relative to the home position.

## Control

| Way | |
| --- | --- |
| Admin UI → *Devices* → PTZ pad, presets | `POST /api/ptz/{id}/move|stop|home`, `/presets`, `/presets/{p}/goto` |
| Assistant | tools `ptz.move`, `ptz.home`, `ptz.goto_preset`, `ptz.follow`, `ptz.stop_follow`, `vision.search_area` |

* **Home position**: Tapo cameras have no built-in home position. *Save as home* in the
  PTZ panel stores the current view as the camera preset "home" (an existing one is
  replaced); *Home* moves there (checked live: back to < 1 pixel). Without a saved home
  position *Home* undoes the movements JuStAI5 has made since the start (approximately,
  since Tapo only moves relatively); if there are none, a hint appears instead of an
  error.
* **Manual control has priority**: every manual command pauses a running tracking for
  20 s.
* **Soft limits** per device (`ptz_limits`: `pan_min/max`, `tilt_min/max` in field of view
  units relative to home), e.g. so the camera never points at the neighbours.
* Permission: `camera.ptz`. Every PTZ action of the assistant is in the tool log
  (`/api/tools/executions`), tracking starts through the API in the audit log.

## Tracking

`ptz.follow` (or `POST /api/ptz/{id}/track`) with target `person` (largest or previously
followed person), `label` (e.g. `dog`, also a registered pet) or `person_id` (recognised
person). The vision engine analyses every frame of the camera for this.

Control loop (`TrackingParams`):

| Parameter | Default | Meaning |
| --- | --- | --- |
| `dead_zone` | 0.12 | area around the image centre without movement (against jitter) |
| `gain` | 0.8 | share of the offset corrected per command |
| `max_step` | 0.35 | maximum movement per command (share of the field of view) |
| `min_interval_s` | 1.2 | minimum time between commands (Tapo needs time) |
| `lost_hold_s` | 6 | hold the position after the target disappeared |
| `return_home_after_s` | 30 | then return to the home position once |
| `tilt_enabled` | true | |

States: `searching`, `following`, `holding`, `home`, `paused`. Tracking stays on the
current target instead of jumping between people. Events: `ptz.tracking.started/stopped`.

## Searching a room

`vision.search_area` ("Look for my keys in the pool house"):

1. **Sweep over the whole room**: from home 5 directions (far left … far right, ±1.6
   image widths ≈ ±150° with the C200) at two heights (straight ahead and ~25° down for
   tables and floor), as a snake line: 10 images. If there are at least three own camera
   presets (besides "home"), those are used instead.
2. **Evaluation**: for classes of the local detector (person, dog, car …) YOLOX searches
   locally. For everything else (keys, glasses, phone …) the vision model gets **all
   images in one request** and names image and place ("on the desk to the right of the
   laptop stand"). The room's privacy rules apply (images not to the cloud → local vision
   model or refusal).
3. **Result**: on a find the camera points at the place, otherwise it returns home.

Duration with the C200: just under 50 s (motor plus 2 s settling per direction, one
model request). Checked live: "keys" found (on the desk, confirmed in the image), "a
window" found.

Before, the search found nothing: it only used the local detector, which does not know
keys, and with a single preset only went in one direction, undoing the assistant's
movements every time with "home".

## Test status

* Unit tests of the control loop (`tests/unit/test_ptz_tracking.py`): dead zone,
  proportional and limited steps, rate limit, target binding, holding and a single return
  home, manual override, target by person ID; home position (`test_ptz_home.py`).
* Simulated PTZ device for the UI.
* Real hardware (Tapo C200): pan from the admin UI and the API, save and move to home,
  searching a room (see above). Tracking a walking person with the real camera has not
  been tested systematically yet.
