# Architecture

*[Deutsch](de/ARCHITECTURE.md) · English*

JuStAI5 is a **modular monolith** with clear ports & adapters: one core process (FastAPI,
asyncio) contains the domain modules. Hardware, AI providers and integrations come
exclusively through plugins. Whatever is not trusted runs in a separate sandbox container.
Rationale: [ADR 0001](adr/0001-modular-monolith.md).

## Containers (Docker Compose)

| Service | Task | Networks |
| --- | --- | --- |
| `secrets-init` | creates DB password, master key and sandbox token once in the volume `secrets` | none |
| `postgres` | PostgreSQL 17 + pgvector (configuration, events, memory, embeddings, jobs) | `db` (internal) |
| `go2rtc` | media server: RTSP/Tapo/ONVIF streams, snapshots, talkback (backchannel) | `media` |
| `core` | API, admin UI, audio, conversations, vision, automations, trusted plugins | `db`, `media`, `sandbox` |
| `sandbox` | runs untrusted plugins and generated tools | `sandbox` (internal) |

The networks `db` and `sandbox` are `internal`: database and sandbox have neither internet
nor LAN access; the sandbox only reaches the core.

## Modules in the core (`backend/src/justai`)

```
api/            HTTP/WebSocket layer (routes, auth dependencies) – no logic
container.py    composition root: builds all components, explicit DI
extensions.py   feature modules (speech, memory, vision, PTZ, display, automation, devtools, retention)
common/         errors, secret redaction, encryption, supervisor, spawn()
db/             SQLAlchemy models, Alembic migrations
events/         event catalog, event bus, event store
system/         settings, job queue, telemetry, retention
auth/           users, roles (RBAC), JWT, audit
rooms/ devices/ endpoints/    topology: rooms, devices (+ discovery), interaction endpoints
media/          go2rtc client
audio/          DSP, VAD, echo, I/O channels, processor per endpoint, arbitration, engine
conversation/   state machine, sessions (realtime and pipeline drivers), echo filter
ai/             AI configuration, router (fallback, privacy, cost), usage tracking
output/         output router, topology, speech output
tools/          tool registry, executor, confirmations, built-in tools
plugins/        loader, manager, context, provider registry, sandbox client
memory/ identity/ vision/ ptz/ display/ automation/ devtools/   domain modules
i18n.py         fixed spoken texts in English, German and Italian
```

Rules:

* Modules only depend on ports (protocols/ABCs), not on concrete plugins. The ports live
  in the SDK (`justai_sdk.ports.*`) so plugins and core use the same contracts.
* `container.py` is the only place that knows everything. Components get their
  dependencies through the constructor.
* Long-running tasks run under the `Supervisor` (restart with backoff) or are started with
  `spawn()` (errors are logged, references kept).

## Languages

* **Interface**: English, German, Italian (`frontend/src/shared/i18n`). `en.ts` is the
  source; `de.ts` and `it.ts` are typed against it, so a missing translation fails the
  build. Every user picks their language at the top right; the default follows the
  browser.
* **Backend**: everything the language model reads (system prompt, tool descriptions and
  results, error messages, event catalog) is English, with the instruction to always
  answer in the language of the conversation. The few texts spoken or stored without the
  model (error apology, cloud notice, watch announcements) are in `justai/i18n.py`.
* **Plugins**: name and description in `plugin.yaml` are English, translations under
  `i18n:`; settings forms translate their fields with `x-i18n` in the JSON schema.
* **Documentation**: English in `docs/`, German in `docs/de/`.

## Central data flows

### Voice interaction

```
microphone ─► go2rtc ─► FfmpegMicSource (16 kHz PCM, timestamps)
           ─► MicChannel (fan-out to all endpoints that use the device)
           ─► EndpointAudioProcessor
                HPF/AEC3 (reference shifted by measured latency) · NS · Silero VAD
                echo window (PlaybackTracker) · half-duplex gating · openWakeWord
           ─► WakeArbiter (per arbitration group, 0.8 s window)
           ─► ConversationManager.start_session(endpoint)
                realtime driver (e.g. Gemini Live)  or  pipeline driver (STT → LLM → TTS)
           ─► tools (registry, permission check, confirmation, audit)
           ─► OutputRouter.resolve(endpoint room) ─► SpeakerChannel ─► go2rtc backchannel
                                                     └─► ReferenceBuffer/PlaybackTracker (echo reference)
```

The session is bound to its endpoint. Also after tool calls, provider switches or
reconnects the output router determines the target again from the endpoint's room, never
from model output. Details: [AUDIO.md](AUDIO.md), [ROOMS.md](ROOMS.md).

### Events and automations

```
source (vision, audio, display, plugin, cron) ─► EventBus.publish
   ├─ durable events ─► EventStore (Postgres)
   ├─ subscribers (own queue per subscriber, error isolation)
   └─ AutomationEngine ─► triggers/conditions ─► job queue (Postgres, SKIP LOCKED)
                                                  └─► actions (assistant.invoke, speak, tool, display.show …)
```

Events carry `hop` and `caused_by`. The bus drops events above the hop limit
(`system.event_loop_detected`), and an automation never reacts to its own events.

### Vision

```
go2rtc substream (low fps) ─► privacy mask ─► motion ─► YOLOX (only on motion/active tracks)
  ─► IoU tracker ─► face check (YuNet + SFace, full-res snapshot, only for unknown person tracks)
  ─► events (vision.*), sightings, watches, PTZ tracking
```

### Displays

```
tool display.show ─► component validation ─► OutputRouter (display in the room)
  ─► WebSocket to the display client ─► render with built-in components ─► ack
  ─► only then the tool reports success
```

## Persistence

PostgreSQL is the only database ([ADR 0003](adr/0003-postgres-pgvector.md)): relational
tables for topology, users, automations, jobs; JSONB for flexible configuration and event
payloads; pgvector (384 dim.) for memory and face embeddings. Migrations: Alembic, run
automatically at start (`db/migrate.py`).

Configuration that users change at runtime (rooms, devices, AI roles, plugin settings)
lives in the database. Environment variables (`JUSTAI_*`, `config.py`) only contain
bootstrap values. Plugin secrets are stored encrypted with Fernet (master key from the
volume `secrets`).

## Extensibility

* **Plugins** (manifest, permissions, lifecycle): [PLUGINS.md](PLUGINS.md)
* **Provider ports**: `ai` (chat, realtime, STT, TTS, embedding), `devices` (drivers,
  audio sources/sinks, snapshots, privacy mode), `ptz`, `vision` (detector, face
  analysis), `wakeword`, `display`, `discovery`
* **Tools**: declarative with Pydantic parameters, category, permissions, side effect
  (`none`/`read`/`write`/`physical`) and optional confirmation
* **Events**: plugins can register their own event types in the namespace
  `plugin.<id>.*`; automations can react to them
* **Background jobs**: plugins run periodic work with `ctx.run_every()`

The interfaces between the modules (event bus, job queue, provider ports) are cut so that
parts can later move into their own processes, e.g. vision inference or the bus over
NATS. That is deliberately not done yet.
