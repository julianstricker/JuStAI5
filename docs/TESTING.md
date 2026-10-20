# Tests and test status

*[Deutsch](de/TESTING.md) · English*

As of: 2026-10-20. This document clearly separates **tested automatically**, **checked
live against the running Docker instance**, **checked with real hardware** and **not
tested**.

## Test suites

| Suite | Location | Needs | Result |
| --- | --- | --- | --- |
| Unit | `backend/tests/unit` | nothing | 138 passed |
| Audio with real models | `backend/tests/audio` | models (`JUSTAI_TEST_MODELS_DIR`) | 9 passed; `test_speaker.py` fails in about 1 of 4 runs (Piper synthesis is random, the other voice then scores 0.49 instead of < 0.45) |
| Database | `backend/tests/db` | PostgreSQL + pgvector (`JUSTAI_TEST_DATABASE_URL`) | 3 passed |
| End-to-end | `backend/tests/e2e` | running instance (`JUSTAI_E2E_URL`, `JUSTAI_E2E_PASSWORD`), Gemini | 13 passed (see note) |
| Example plugin | `plugins/example-weather/tests` | nothing | 6 passed |
| Frontend | `frontend` | Node | `tsc` and ESLint without errors; a missing translation fails `tsc` |
| Static analysis | whole repo | – | ruff without errors, mypy `--strict` without errors (backend, SDK, sandbox) |

```bash
uv run pytest backend/tests/unit
uv run python scripts/fetch_models.py .models
JUSTAI_TEST_MODELS_DIR=$PWD/.models uv run pytest backend/tests/audio
JUSTAI_TEST_DATABASE_URL=postgresql+asyncpg://justai:pw@127.0.0.1:55432/justai_test uv run pytest backend/tests/db
JUSTAI_E2E_URL=http://localhost:8080 JUSTAI_E2E_PASSWORD=… uv run pytest backend/tests/e2e
uv run pytest plugins/example-weather/tests     # run separately (own pytest configuration)
cd frontend && npm run typecheck && npm run lint
```

A test database can be started e.g. with
`docker run -d --name j5-testdb -e POSTGRES_USER=justai -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=justai_test -p 127.0.0.1:55432:5432 pgvector/pgvector:0.8.1-pg17`.

### What the suites cover

* **Unit**: event bus (isolation, duplicates, hop limit), output router (all rules), tool
  executor (permissions, confirmation, timeout, errors), display components, echo
  building blocks (reference buffer, GCC-PHAT, tracker), wakeword arbitration (incl. late
  duplicates), calibration (onset), AI router (fallback, hanging provider, cooldown, role
  auto-configuration), conversation state machine, vision logic, automation model (incl.
  filling in missing types, `at` fires once), PTZ control, static check of generated code,
  plugin generation prompts, `FakePluginContext` (jobs, events, HTTP routes), required
  plugin settings, voice control tools (privacy mode, listening pause with resume),
  login throttling, discovery merging.
* **Audio**: talking to itself with real models in a simulated room
  ([AUDIO.md](AUDIO.md#tested)).
* **DB**: permanent forgetting in memory ([MEMORY.md](MEMORY.md)).
* **E2E**: two simulated rooms with acoustic echo, real local STT/TTS/wakeword, Gemini as
  LLM: conversation, room routing, no echo, timeout, duplicate wakewords, parallel
  conversations, display pairing with confirmation, proactive automation, continuing a
  conversation (same voice 0.82 → continued, follow-up "how many people live there?"
  correctly related to Rome; other voice 0.26 → new conversation), a speaking automation
  starts a dialogue, voice profile: created from real conversation speech (3 samples),
  recognised at the next "Hey Jarvis" with the same voice (similarity 0.75), another
  voice not. The flow "have it created in conversation" worked on the first run;
  repetitions failed because of the exhausted Gemini quota (429), not because of the
  function. Device app: a scripted browser device pairs with microphone, speaker and
  camera, automatically gets an endpoint with 4 roles, delivers snapshots; "Hey Jarvis"
  and a question over the WebSocket microphone start a conversation, the answer arrives
  as audio at the device. Questions are in German and Italian; since 2026-10-20 the suite
  runs with the English system prompt and tool texts (13/13).

**Note on E2E:** the suite uses the configured cloud LLM (Gemini). On 2026-10-15 Gemini at
times returned 429 (quota exhausted) for `gemini-3.8-flash` and 503 (overload) for the
fallback at the same time. In this case the assistant answers correctly with an error
message, and three tests failed. The direct repetition passed 5/5, although 8 more
429/503 errors were caught by the fallback chain in the same period. For stable runs add
a local LLM as an additional fallback.

## Acceptance criteria

Legend: ✅ shown · 🟡 partially (what is missing is stated) · ⏳ open.

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Device discovery | ✅ | The network search finds the **Tapo C200** in 6 s, suggests the Tapo driver with model "C200" and recognises it as already added. Once set up it shows the measured capabilities (video, audio in/out, snapshot, PTZ and privacy mode with the cloud password). The C410 (battery) was mostly asleep. |
| 2 | Room assignment | ✅ | Real hardware: C200 (camera, microphone, speaker) as endpoint "Pool house camera" in the room pool house. E2E: combined devices per room. |
| 3 | Voice conversation | ✅ | Real hardware: "Hey Jarvis" at the C200 → session → answer (Gemini Live) through the C200 speaker. E2E: pipeline mode with the answer in the same room. |
| 4 | No echo loop | ✅ | Real hardware (C200): no self-triggering. Audio tests: the answer deliberately contains the wakeword → no wake, no echo passed through. E2E: no echo turns in the transcript. |
| 5 | Timeout | ✅ | Real hardware and E2E: end through inactivity (`end_reason = inactivity`), afterwards a wakeword is needed again. |
| 6 | No output in the wrong room | ✅ | E2E: the kitchen speaker does not get a single frame when the question is asked in the living room. Unit: output router rules. |
| 7 | Duplicate wakewords | ✅ | E2E: the same wakeword in two rooms (quieter in the kitchen) → exactly one session, in the louder room. Unit: arbitration incl. late duplicates. Not tested with two real microphones (C410 not permanently reachable). |
| 8 | Parallel conversations | ✅ | E2E: two rooms in separate arbitration groups ask at the same time, each gets its answer. |
| 9 | Person registration | 🟡 | Introducing by voice (`identity.introduce`), consent with evidence and registration with quality check are implemented; `identity.register_face` requires an explicit confirmation (mechanism unit-tested). **Open:** the flow with a real person in front of the camera. |
| 10 | Recognition | 🟡 | YuNet/SFace are loaded in the container (plugin `vision-opencv` runs, face check active in the vision pipeline); voting over strong and weak hits is implemented. **Open:** test with a real person. |
| 11 | PTZ tracking | 🟡 | Control loop unit-tested (dead zone, step size, rate, target binding, return home, manual override). Real C200: manual panning works (right and back, confirmed by image comparison), home position, room search. **Open:** following a person. |
| 12 | Memory | ✅ | Live: "Remember …" in session A, correct answer in a new session B. Forgetting with follow-up question; permanent (DB test and live). |
| 13 | Automation | 🟡 | Live: the sentence from the criterion (with a person name) creates a correct automation. E2E: the recognition event starts a proactive greeting in the right room, `once` applies. **Open:** triggering by a real face recognition (depends on 9/10). |
| 14 | Display output | ✅ | E2E: display in the living room paired and chosen. Real browser: dashboard with price, chart and table rendered. |
| 15 | Display confirmation | ✅ | E2E: the tool provably waits for the `ack`. Real browser: `ack` after painting; a background page immediately reports "not visible" instead of faking success. |
| 16 | Provider switch | ✅ | Live: role `conversation` switched by configuration only to a new OpenAI-compatible endpoint (Gemini through its OpenAI interface); according to the usage log the answer came from `oai:gemini-oai`. No code change. Fallback on overload (503/429) observed in operation. |
| 17 | Plugin installation | ✅ | Live: zip uploaded → as `untrusted` in the sandbox → start without permissions refused → permission granted → active, tool appears, the assistant uses it → disabled → tool disappears. |
| 18 | Tool development | ✅ | Live: "calendar week and weekday of a date" → specification, code, tests → static check → tests in the sandbox (2 passed) → security review → approval → the assistant answers "calendar week of 24.12.2026?" correctly with the new tool → disabled. Live (2026-10-20): "a plugin that checks every 5 minutes whether it starts raining in Bolzano and reports it" → plugin with tool, background job and event type; revised once; approved → runs in the sandbox, the event type `plugin.gen-rain-monitor.rain_started` is in the catalog and offered for automations. **Open:** a real rain start triggering an automation. |
| 19 | Restart | ✅ | `docker compose down` + `up`: rooms, devices, endpoints, plugins (active), people, memories, automations, AI and system settings identical. Additionally a backup was restored into a separate project. |
| 20 | Error handling | ✅ | Live: the C410 is mostly offline, the C200 works unaffected. Restarts of single services: media server → cameras back after 2 s; database → API after 3 s; sandbox → sandbox plugins restarted automatically after 44 s. A failing plugin (missing permissions) is marked `failed`, everything else keeps running. Gemini overload: fallback instead of failure. Unit: bus error isolation, hanging providers. |

### Further live checks (2026-10-20)

* **Privacy mode by voice** (text chat to the C200): "switch off the camera" → privacy
  mode on, checked directly on the camera with pytapo; "switch it on again" → off.
* **Listening pause**: "stop listening here for one minute" → wakeword off at the
  endpoint, a one-time automation switched it on again after 60 s and ran exactly once.

### What only the user can do (open points)

* **9/10/13 with a real person**: stand in front of the C200, say "I am …", agree to the
  face registration. Later step in front of the camera again; the greeting automation
  should then fire.
* **11**: walk in front of the C200 and say "follow me" (`ptz.follow`).
* **Barge-in with real hardware**: the C200 mutes its microphone during playback, so
  interrupting is physically impossible. A test needs a device with real full duplex
  (e.g. a USB speakerphone).
* **Display on a TV**: so far only checked in a desktop browser.
* **Installation script** (`scripts/install.sh`, 2026-10-16, as its own Compose project
  next to the running instance): via `curl … | bash` in an empty folder (clones from
  GitHub, ports 8080/8443 taken → 8081/8444, LAN IP detected, random password shown and
  login with it successful); interactively in a pseudo terminal (own password, login
  successful, `.env` with permissions 600); running it again (keeps `.env`, rebuilds).
  HTTPS via the LAN IP with the CA certificate checked. Not tested: Docker installation on
  a machine without Docker.
* **Device app on real phones/tablets**: setup page, pairing and settings card checked in
  the desktop browser, the media path by E2E test. Headless Chrome with simulated
  camera/microphone and a strict autoplay rule: after pairing and after a reload without a
  touch, camera images and microphone arrive; the live image (MJPEG) runs in the admin UI.
  The browser's echo cancellation, background behaviour of mobile browsers and certificate
  installation on Android/iOS have not been tested on real devices yet.
* **Voice conversations in English and Italian with the real camera**: so far German by
  voice; Italian only through the E2E suite.

## Bugs found and fixed by live tests

Live checks against the running instance found bugs that no unit test had covered:

| Bug | Fix |
| --- | --- |
| Forgotten content came back through the memory extraction of the old session | tombstones, DB test |
| Dashboard crashed after login (`_cooldowns` as a role in `/api/ai/status`) | own field, defensive UI |
| "Greet X the next time": the model left out `type` and used the name instead of the ID; the answer stayed empty | fill in types, resolve names, validation details to the model, fallback answer |
| Sandbox test run not importable depending on the random directory name | fixed path, `pythonpath` |
| Generated class name renamed, tests could not find it | alias instead of renaming |
| Second tool project with the same name aborted (unique constraint) | unique plugin IDs |
| Disabling the C200 hung for over 2 minutes (device marked disabled, connections stayed) | `Supervisor.stop` waited without limit for tasks that do not react to cancellation and swallowed its own cancellation. Now: at most 5 s, then a warning with the place where the task hangs; every step when stopping a device (audio, vision, driver, go2rtc) at most 10 s, slow steps are logged by name. Live: disabling 0.2–0.3 s |
| Camera speaker (C200) silent although all bytes arrived at the camera; also after restarting go2rtc and the camera. A fresh second connection and the Tapo app were audible | own speaker connection opened anew per conversation (`<stream>_talk`), closed after 90 s of silence; the delivery check now also recognises camera connections that go2rtc lists as a consumer ([AUDIO.md](AUDIO.md)). Test tone then delivered (login 4.1 s) and heard |
| Reminder "in a quarter of an hour" repeated every 5 s (18× in 1.5 min, only then stopped by the limit of 20 runs per hour) | the scheduler checked `run_count` of `at` triggers on its cached copy, which only the database incremented. Now: once via the trigger time, `at` automations are disabled after the run, cache reloaded after every run. Unit test and checked live (1 run, then disabled) |
| Plugin generation crashed ("Replacement index 0 out of range") after the prompt translation | literal braces in the prompt escaped, unit test |
| Generated plugin tests failed ("'dict' object is not callable"): the model passed JSON directly as an HTTP route | `FakePluginContext` accepts `dict`/`list`/`str`/functions as routes, unit test |
| "Hey Jarvis, what time is it?" without a pause stayed unanswered: audio between wakeword and ready session (1.4–1.7 s) was dropped | fixed: buffer per endpoint, replay from the wakeword with VAD decision pause/no pause, pipeline ignores short utterances; E2E in both modes ([AUDIO.md](AUDIO.md#speaking-without-a-pause-after-the-wakeword)) |
| Installation: with a changed `JUSTAI_HTTPS_PORT` (e.g. 8444 because 8443 was taken) the core listened on 8444 inside the container, but Docker forwarded to 8443 – HTTPS unreachable | fixed: container port fixed at 8443, `JUSTAI_HTTPS_PORT` only host port and display |
| Device app: live image in the admin UI "not available" (requested MP4 from go2rtc, app cameras have no stream); after the automatic reload on updates no camera/microphone until someone tapped | fixed: MJPEG live image, self-start, sound can be enabled later by a touch; checked in the browser |
| Display: duplicate axis labels, "conversation" indicator caused by text chats, unclear errors for an invisible page, no reload after updates | fixed, checked in the browser |
| The time zone from the settings was ignored by automations; switches without function in the settings | wired up or removed |
| No protection against password guessing, no security headers | throttling, CSP and others |
| Discovery suggested the ONVIF driver for Tapo (without speaker) | the manufacturer-specific driver has priority |
| After a go2rtc restart all cameras stayed unreachable (streams only in memory) | a watchdog restores the streams; live: 2 s |
| First output after a pause inaudible (channel closed after 2 min, rebuilding too slow) | channel stays open, speech waits for readiness |
| Sound stayed silent permanently after a camera reconnect (go2rtc fetched but did not deliver to the camera) | delivery check at go2rtc, automatic rebuild |

## Known instability

The two full duplex tests in `backend/tests/audio` are not deterministic because Piper
generates the test speech slightly differently on every run. On average about one in three
to six runs fails: sometimes a real interruption is detected too late, sometimes (more
rarely since the tolerance around the estimated echo delay) echo is taken as an
interruption. Half duplex, the mode of the C200, is not affected. Open: reproducible test
speech and tuning over many variants.

## Not tested automatically

* Consolidation of memory (merging, contradictions)
* Realtime mode (Gemini Live) only manually with the C200, not in the E2E suite
* Plugin dependencies and updates of uploaded plugins
* Retention job
* Load behaviour with many cameras
* A self-developed plugin's event triggering a real automation end to end
