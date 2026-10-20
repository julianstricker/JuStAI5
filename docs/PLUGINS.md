# Plugins and SDK

*[Deutsch](de/PLUGINS.md) · English*

Everything that connects hardware, AI providers or external services is a plugin. Plugins
use the SDK package `justai_sdk` (`sdk/python/src/justai_sdk`), which the core also uses
for its ports. Complete example: [`plugins/example-weather`](../plugins/example-weather).
The assistant can also write plugins itself: [self-developed plugins](#self-developed-plugins).

## Layout

```
plugins/my-plugin/
├── plugin.yaml      manifest (validated before any import)
├── plugin.py        entry point, e.g. entrypoint: plugin:MyPlugin
├── __init__.py
└── tests/           tests with justai_sdk.testing.FakePluginContext
```

## Manifest (`plugin.yaml`)

Model: `justai_sdk/manifest.py`. Important fields:

| Field | Meaning |
| --- | --- |
| `id` | `^[a-z][a-z0-9_-]{1,62}$`, unique |
| `name`, `description` | English |
| `i18n` | translations, e.g. `{de: {name: …, description: …}, it: {…}}`; the interface shows the user's language |
| `version` | PEP 440 |
| `types` | e.g. `device`, `discovery`, `ai_provider`, `realtime_ai`, `stt`, `tts`, `wakeword`, `embedding`, `vision`, `ptz`, `display`, `tool`, `integration` |
| `api` | compatible SDK API versions (currently `1.0`), e.g. `">=1.0,<2.0"` |
| `entrypoint` | `module:Class` relative to the plugin folder |
| `trust` | `builtin` / `trusted` (in the core process) or `untrusted` (sandbox) |
| `runtime` | optional `in_process` / `sandbox`; `untrusted` + `in_process` is forbidden |
| `permissions` | requested permissions (see below) |
| `network_allowlist` | hosts reachable with `network.http` |
| `dependencies` | other plugins with version range, optional |
| `config_schema` | JSON schema of the configuration; the admin UI builds the form from it. Field labels in other languages: `"x-i18n": {"de": {"title": …, "description": …}}` per property |
| `secret_fields` | configuration keys that are stored encrypted and never returned |
| `requirements` | `memory_mb`, `gpu`, required binaries |
| `default_enabled` | only for bundled plugins: enable at first start |

## Lifecycle

```python
class Plugin:
    async def setup(self)  # register tools, providers, components, event types, jobs
    async def start(self)  # start background work
    async def stop(self)   # release everything
    async def health(self) -> PluginHealth          # ok | degraded | failed
    async def on_config_changed(self, config) -> bool  # True = applied live, otherwise restart
```

The `PluginManager` (`backend/src/justai/plugins/manager.py`):

1. validates the manifest, checks API compatibility and dependencies,
2. starts in dependency order (`setup` and `start` with 120 s timeout each),
3. marks a failing plugin as `failed`, releases everything it registered and keeps the
   rest of the system running,
4. checks `health()` regularly; status changes appear as `plugin.status.changed`.

Disabling is blocked as long as other active plugins depend on it.

## Permissions

Vocabulary: `justai_sdk/permissions.py`. A plugin only gets the intersection of
*requested* (manifest) and *granted by the admin* (admin UI → Plugins). Every access
through the context checks the permission (`ctx.require(...)`).

* Bundled plugins: all requested permissions are granted at first start. On an update
  they only get new permissions if the admin never revoked one.
* Uploaded plugins (`POST /api/plugins/install`, zip) are **always** installed as
  `untrusted` and start without granted permissions. On updates only already granted
  permissions that the new manifest still requests are kept.
* `untrusted`/sandbox plugins can never get: `devices.provide`, `devices.control`,
  `ai.provide`, `network.lan`, `network.discovery`, `system.manage`, `biometric.enroll`,
  `tools.develop`.
* Own permissions in the namespace `plugin.<id>.*` are allowed.

## Context API

`PluginContext` (`justai_sdk/plugin.py`):

| Method | Permission |
| --- | --- |
| `config` | the plugin's configuration (secrets decrypted) |
| `register_tool(definition, handler)` | `tools.provide` |
| `register_provider(kind, provider)` – `device_driver`, `discovery`, `llm`, `realtime`, `stt`, `tts`, `embedding`, `wakeword`, `object_detector`, `face_analyzer` | depending on the kind, e.g. `ai.provide`, `devices.provide` |
| `register_display_component(spec)` | `display.write` |
| `register_event_type(type, description)` | only `plugin.<id>.*` |
| `publish(event)` / `subscribe(pattern, handler)` | `events.publish` / `events.subscribe` (subscribe not in the sandbox) |
| `run_every(seconds, callback, name=…)` | none; in the sandbox at least 60 s apart, at most 5 jobs |
| `http.get/post/request` | `network.http`, only hosts from `network_allowlist` |
| `store.get/put/delete/keys` | `storage.plugin`, isolated key-value store per plugin |
| `services.list_devices/list_rooms` | `devices.read` |
| `services.snapshot(device_id)` | `camera.read` |
| `services.memory_search(...)` | `memory.read` |
| `services.say(room_id, text)` | `speaker.write`, through the output router |
| `services.show(room_id, document)` | `display.write`, through the output router |
| `services.complete(prompt, role=…)` | `ai.invoke`, through the AI router (privacy rules apply) |

Plugins never talk to speakers or displays directly. Every output goes through the output
router.

## Tools

```python
class Params(BaseModel):
    location: str | None = Field(None, description="Place")

ctx.register_tool(ToolDefinition(
    name="weather.current", description="Current weather at a place.",
    parameters=Params, category="information", timeout_s=15,
    permissions=[], side_effect=SideEffect.READ, requires_confirmation=False,
), handler)

async def handler(args: Params, tc: ToolContext) -> ToolResult:
    return ToolResult.success({"temperature": 21.4}, message="It is 21 degrees.")
```

Tool descriptions, parameter descriptions and result messages are English; the language
model answers in the language of the conversation. `tc.language` is the conversation
language (`en`, `de`, `it`) for data that depends on it, e.g. weather descriptions.

The executor (`tools/registry.py`) validates the parameters, checks the caller's
permissions (role of the conversation endpoint or of the user), enforces the timeout,
asks for spoken confirmation with `requires_confirmation`
(`assistant.confirm_action`/`assistant.cancel_action`) and records every execution
(`/api/tools/executions`). Errors are reported as `ToolResult.failure(code, message)`,
never as an exception to the model.

## Background jobs and events

A plugin that watches something registers an event type and a job:

```python
async def setup(self) -> None:
    self.ctx.register_event_type(f"plugin.{self.ctx.plugin_id}.rain_started",
                                 "It started raining at the configured place")
    self.ctx.run_every(300, self.poll, name="rain")

async def poll(self) -> None:
    raining = await self._raining()
    before = await self.ctx.store.get("raining")
    if raining and before is not None and not before.get("value"):
        await self.ctx.publish(Event(type=f"plugin.{self.ctx.plugin_id}.rain_started",
                                     payload={"place": "Bolzano"}))
    await self.ctx.store.put("raining", {"value": raining})
```

* `run_every` runs the callback right away and then every `seconds` while the plugin runs;
  errors are logged and do not end the job. Jobs stop with the plugin.
* Registered event types appear in the event catalog with owner `plugin:<id>` (also from
  the sandbox) and disappear when the plugin stops. Automations can use them as triggers;
  the assistant lists them with the tool `events.types` ("Which events can I use for
  automations?").

## Sandbox (untrusted)

* The core sends the plugin files (only `.py/.yaml/.json/.txt/.md`, max. 2 MB) to the
  sandbox service. It starts its own host process per plugin with rlimits (address space,
  CPU, files, processes, file size, no core dump).
* Communication: JSON-RPC over stdin/stdout; access to core functions through the plugin
  gateway (`/internal/plugin-gateway/<id>`) with a plugin-bound token. The gateway checks
  every operation against the granted permissions.
* HTTP requests are executed by the core (allowlist check, no private addresses). The
  sandbox container itself has no network except to the core.
* Tools from the sandbox are registered in the core as proxy tools; the parameters are
  additionally validated in the core by JSON schema.
* Event types and jobs work in the sandbox too (limits above).

## Self-developed plugins

When the assistant has no tool for a request ("Build a plugin that tells me when it starts
raining"), it calls `tools.develop`. The devtools module (`backend/src/justai/devtools`)
then:

1. **checks** whether existing tools already cover the request (then nothing is built),
2. **generates** manifest, `plugin.py` and tests with the role *tool generation*, with
   `plugins/example-weather` as reference; tools, background jobs, events and settings
   (`config_schema`, `secret_fields`) are possible,
3. **checks statically**: only allowed permissions (`tools.provide`, `network.http`,
   `storage.plugin`, `display.write`, `speaker.write`, `memory.read`, `camera.read`,
   `ai.invoke`, `events.publish`, `devices.read`), no forbidden modules (`os`,
   `subprocess`, `socket`, `requests`, `pathlib` …) or calls (`eval`, `exec`, `open`,
   `getattr` …), valid manifest,
4. **runs the tests** in the sandbox with `FakePluginContext`,
5. **reviews** the code with the role *reasoning* (security, privacy, does it do what was
   asked),
6. revises itself up to 2 times if a step fails.

A version that passes everything waits for an admin under *Tools* (status "awaiting
approval"; code, tests and results are visible). On approval it is installed as an
`untrusted` sandbox plugin `gen-<name>` with exactly the requested permissions. Does it
need settings (API key, place), the status is "needs settings" until the admin fills them
in under *Plugins*; then it starts. Earlier versions can be restored (rollback).

By voice: `tools.develop` (new), `tools.projects` ("Which plugins have you built?"),
`tools.revise` ("Change the rain plugin so it also reports when the rain stops"; creates
a new version that is tested and approved again). Residents and admins may ask for
plugins (permission `tools.develop`); only an admin can approve them.

## Tests for plugins

```python
from justai_sdk.testing import FakePluginContext

ctx = FakePluginContext(manifest, config={"default_location": "Bolzano"},
                        http_routes={"api.open-meteo.com/*": {"current": {"rain": 0.4}}})
plugin = WeatherPlugin(ctx)
await plugin.setup()
result = await ctx.call_tool("weather.current", {"location": "Bolzano"})
await ctx.run_jobs()            # runs every run_every callback once
assert ctx.events               # published events
```

`FakePluginContext` keeps tools, events, event types, jobs, storage and HTTP answers in
memory. It grants all permissions requested in the manifest and checks access against
them; HTTP requests to hosts outside the allowlist fail as in the core. HTTP routes match
with or without scheme and answer with an `HttpResponse`, a `dict`/`list` (JSON), a `str`
or a function. For audio plugins there is `justai_sdk.simulation.AcousticRoom` (echo,
reverb, noise, ducking).

```bash
uv run pytest plugins/example-weather/tests
```

## Bundled plugins

| Plugin | Kind | Trust |
| --- | --- | --- |
| `tapo` | device driver TP-Link Tapo (go2rtc `tapo://`, backchannel, PTZ and privacy mode via pytapo) | builtin |
| `onvif` | ONVIF/RTSP driver, PTZ, WS-Discovery (unicast), mDNS | builtin |
| `simulated` | simulated camera/microphone/speaker with acoustic echo, tool `simulator.say` | builtin |
| `openwakeword` | wakeword provider | builtin |
| `faster-whisper` | local STT | builtin |
| `piper` | local TTS | builtin |
| `fastembed` | local embeddings | builtin |
| `gemini` | LLM, vision, realtime (Gemini Live) | builtin |
| `openai-compat` | LLM through an OpenAI-compatible API (Ollama and others) | builtin |
| `vision-opencv` | object detection (YOLOX), faces (YuNet/SFace) | builtin |
| `finance` | prices and charts (unofficial Yahoo chart API, see note) | builtin |
| `example-weather` | weather from Open-Meteo, **reference example**, runs in the sandbox | untrusted |

Note `finance`: the Yahoo chart API is not officially documented and can change without
notice. Stooq as an alternative was blocked by a JavaScript challenge during testing.

## Distributing a plugin

Upload a zip archive with the plugin folder (manifest in the root or in exactly one
subfolder) in the admin UI under *Plugins → Install*. Then check, grant and configure the
permissions and enable it.
