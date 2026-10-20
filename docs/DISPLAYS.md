# Displays

*[Deutsch](de/DISPLAYS.md) · English*

Every browser can be a JuStAI5 display: TV with a browser, tablet, old laptop. Code:
`backend/src/justai/display/`, client: `frontend/src/display/`, renderer:
`frontend/src/shared/render/`.

## Pairing

1. Open `http://HOST:8080/display` on the device. The client connects by WebSocket
   (`/api/display/ws`) with its capabilities and shows a **6-digit pairing code**.
2. Admin UI → *Displays* → enter the code, choose name and room.
3. The core creates a device with the driver `browser-display` and sends the client a
   random token. The client stores it locally; the core only keeps the hash. On every new
   connection the token is enough.

Removing the device in the admin UI invalidates the token.

The display client and the device app show their texts in English, German or Italian
(language picker on the start screen; default: browser language).

## Device app (phone, tablet, PC as microphone, speaker, camera)

At `https://HOST:8443/app` the same client runs as an installable web app (PWA). It turns
any device into a full JuStAI5 device:

| Function | Path |
| --- | --- |
| Microphone | `getUserMedia` with the browser's echo cancellation, noise suppression and AGC → AudioWorklet → PCM16, 16 kHz, 20 ms frames → wakeword, conversations, speaker recognition |
| Speaker | speech output of the output router as PCM16, 16 kHz → AudioWorklet with 60 ms jitter buffer |
| Camera | front or back camera, a JPEG every 500 ms (max. 960 px wide) → vision, face recognition, snapshot, live view in the admin UI and on displays (MJPEG instead of MP4, since there is no go2rtc stream) |
| Screen | like every display (presentations, "listening" indicator) |

**Setting up**

1. Admin UI → *Settings* → *Device app*: if the admin UI is opened through an address that
   is not yet in the HTTPS certificate (e.g. the server's LAN IP), click **Add** there.
   The certificate is issued again and loaded without a restart.
2. Install the **JuStAI5 certificate** (local certificate authority) on the device; the
   steps for Android, iPhone/iPad, Windows and macOS are in the same card. Without
   installing it, confirming the browser warning is usually enough; the page then cannot
   be installed as an app.
3. Open `https://HOST:8443/app` on the device, choose the language, microphone, speaker
   and camera (off/front/back), *Start*. Then use the browser menu "Install app" or "Add
   to Home Screen".
4. Approve the code shown under *Displays & device app* and choose a room. With microphone
   **and** speaker JuStAI5 automatically creates an endpoint in the room (roles
   microphone, speaker, camera and display if present, arbitration group of the room). If
   microphone and speaker are switched on only later, the endpoint is created on the next
   connection.

The selection can be changed with the gear at the top right; the device then registers
with the new capabilities. Once the selection is saved, the app starts microphone, speaker
and camera by itself when opened, also after the automatic reload on a JuStAI5 update. If
the browser does not allow sound without a touch, the camera runs anyway and the top right
shows "Sound paused – tap once"; a touch anywhere is enough. Only if microphone or camera
do not start (e.g. access not yet allowed) "Tap to start" appears. While the app is open,
a wake lock keeps the screen on. When the page runs in the background, browsers no longer
send camera images, and mobile browsers often stop the microphone too. For a permanent
room device use a tablet with a power supply and the app in the foreground.

Why HTTPS: browsers only allow microphone, camera, service worker and installation as an
app on secure origins (HTTPS or `localhost`). The plain display client at
`http://HOST:8080/display` does not need it.

**Media in the WebSocket** (`display/media.py`): binary messages with a type byte at the
beginning.

| Byte | Direction | Content |
| --- | --- | --- |
| `0x01` | client → core | microphone, PCM16 LE, mono, 16 kHz |
| `0x02` | client → core | camera image, JPEG (≤ 2 MB) |
| `0x11` | core → client | speaker, PCM16 LE, mono, 16 kHz |

A browser device may only register the capabilities `display.*`, `audio.input`,
`audio.output`, `video.input` and `camera.snapshot`. Camera images older than 10 s count
as unavailable.

## Protocol (WebSocket, JSON)

| Direction | Message |
| --- | --- |
| client → core | `hello {token?, user_agent, capabilities[]}` |
| core → client | `pairing {code}` · `paired {token, name}` · `ready {name, room, build}` · `error` |
| core → client | `show {presentation_id, document}` · `close {presentation_id}` · `indicator {listening, cloud}` |
| client → core | `ack {presentation_id, status: displayed\|failed, reason?: hidden\|render_error}` · `interaction {presentation_id, action, value}` |

## Lifecycle of a presentation

```
CREATED ─► SENT ─► DISPLAYED (ack from the client) ─► UPDATED … ─► CLOSED
                └► FAILED (with reason)
```

The tool `display.show` only reports success to the assistant when the display has
confirmed receipt **and successful rendering**: the client only confirms after React has
taken over the presentation and the browser has painted. Failure reasons the assistant can
name:

| Reason | Cause |
| --- | --- |
| display not connected | no WebSocket |
| display is not visible | page in the background / screen off (`visibilityState = hidden`), immediate answer |
| content could not be shown | render error of a component (error boundary; the display stays usable) |
| no confirmation from the display | no `ack` within 8 s |

Optionally `duration_s` closes the presentation automatically.

**Updates:** the core sends a build identifier with `ready`. If JuStAI5 has changed since
the page was loaded, the client reloads automatically after reconnecting. Displays such as
TVs therefore do not have to be refreshed by hand after an update. Reconnection with
backoff up to 15 s.

## Safe render schema

A document is a tree of **typed components**. HTML or JavaScript from the language model
or from plugins is never executed.

Built-in components (`display/components.py`):

| Component | Capability |
| --- | --- |
| `text`, `heading`, `markdown` (without HTML), `kv`, `stat`, `list`, `table`, `clock`, `notification` | `display.text` |
| `image` (only `https://`, `/api/media/…` or `data:image/…`) | `display.image` |
| `chart` (line/bar, uPlot), `grid` | `display.dashboard` |
| `weather`, `stock-quote` | `display.text` |
| `camera` (live stream, short-lived signed URL, needs `camera.read`) | `display.video` |
| `choice`, `button` (interaction → event `display.interaction`) | `display.interactive` |
| `card`, `row`, `grid` (containers) | |

Limits: depth ≤ 6, ≤ 200 components, limited text lengths, unknown fields are rejected.
Errors go back to the model with the field path. Dates and numbers are formatted in the
display's language.

**Plugin components** (e.g. `weather-card` from the example plugin) are *templates*: the
plugin supplies a JSON schema for the properties and a template of built-in components.
The core fills in the template; the client only sees built-in components.

## Routing

Displays are chosen like speakers by the output router
([ROOMS.md](ROOMS.md#output-router)):

* display of the triggering endpoint, otherwise a matching display in the same room.
* No matching display in the room → error, no moving to other rooms.
* `personal: true` (calendar, health, finance) is not shown in rooms with `shared_space`.
* Other rooms only with an explicit cross-room request and permission.

## Status indicator

Paired displays discreetly show whether the assistant is listening in the room and
whether a cloud realtime model is active (`indicator`).

## Tools

`display.show`, `display.update`, `display.close`, `display.list`.

## Tested

* Unit (`tests/unit/test_display_components.py`): validation, unsafe URLs, depth/count,
  plugin templates, capability derivation.
* E2E (`tests/e2e/test_simulated_rooms.py::test_display_pairing_presentation_ack_and_room_routing`):
  a WebSocket client pairs with a code, is assigned to the living room, gets a
  presentation; the tool provably waits for the `ack` and only then reports `displayed`.
* Real browser (Chromium in the built-in browser of the development environment): pairing
  by code, dashboard with heading, price, line chart and key-value rendered and confirmed
  (ack after 11 ms); in the background immediately "not visible"; reloaded automatically
  after a core update. Found and fixed on the way: duplicate axis labels for categories,
  conversation display caused by text chats, missing failure reasons.
* A test on a real TV is still pending.
