# Plugins und SDK

Alles, was Hardware, KI-Provider oder externe Dienste anbindet, ist ein Plugin.
Plugins nutzen das SDK-Paket `justai_sdk` (`sdk/python/src/justai_sdk`), das auch der
Core für seine Ports verwendet. Vollständiges Beispiel: [`plugins/example-weather`](../plugins/example-weather).

## Aufbau

```
plugins/mein-plugin/
├── plugin.yaml      Manifest (wird vor jedem Import validiert)
├── plugin.py        Einstiegspunkt, z. B. entrypoint: plugin:MeinPlugin
├── __init__.py
└── tests/           Tests mit justai_sdk.testing.FakePluginContext
```

## Manifest (`plugin.yaml`)

Modell: `justai_sdk/manifest.py`. Wichtige Felder:

| Feld | Bedeutung |
| --- | --- |
| `id` | `^[a-z][a-z0-9_-]{1,62}$`, eindeutig |
| `version` | PEP 440 |
| `types` | z. B. `device`, `discovery`, `ai_provider`, `realtime_ai`, `stt`, `tts`, `wakeword`, `embedding`, `vision`, `ptz`, `display`, `tool`, `integration` |
| `api` | kompatible SDK-API-Versionen (aktuell `1.0`), z. B. `">=1.0,<2.0"` |
| `entrypoint` | `modul:Klasse` relativ zum Plugin-Ordner |
| `trust` | `builtin` / `trusted` (im Core-Prozess) oder `untrusted` (Sandbox) |
| `runtime` | optional `in_process` / `sandbox`; `untrusted` + `in_process` ist verboten |
| `permissions` | angeforderte Rechte (siehe unten) |
| `network_allowlist` | Hosts, die mit `network.http` erreichbar sind |
| `dependencies` | andere Plugins mit Versionsbereich, optional |
| `config_schema` | JSON-Schema der Konfiguration; die Admin-UI erzeugt daraus das Formular |
| `secret_fields` | Konfigurationsschlüssel, die verschlüsselt gespeichert und nie ausgegeben werden |
| `requirements` | `memory_mb`, `gpu`, benötigte Binaries |
| `default_enabled` | nur für mitgelieferte Plugins: beim ersten Start aktivieren |

## Lebenszyklus

```python
class Plugin:
    async def setup(self)  # Tools, Provider, Komponenten, Event-Typen registrieren
    async def start(self)  # Hintergrundarbeit starten
    async def stop(self)   # alles freigeben
    async def health(self) -> PluginHealth          # ok | degraded | failed
    async def on_config_changed(self, config) -> bool  # True = live übernommen, sonst Neustart
```

Der `PluginManager` (`backend/src/justai/plugins/manager.py`):

1. validiert das Manifest, prüft API-Kompatibilität und Abhängigkeiten,
2. startet in Abhängigkeitsreihenfolge (`setup` und `start` mit je 120 s Timeout),
3. markiert ein fehlschlagendes Plugin als `failed`, gibt alles frei, was es
   registriert hat, und lässt den Rest des Systems weiterlaufen,
4. prüft regelmäßig `health()`; Statuswechsel erscheinen als `plugin.status.changed`.

Deaktivieren ist blockiert, solange andere aktive Plugins davon abhängen.

## Berechtigungen

Vokabular: `justai_sdk/permissions.py`. Ein Plugin bekommt nur die Schnittmenge aus
*angefordert* (Manifest) und *vom Admin gewährt* (Admin-UI → Plugins). Jeder
Zugriff über den Kontext prüft das Recht (`ctx.require(...)`).

* Mitgelieferte Plugins: alle angeforderten Rechte sind beim ersten Start gewährt.
  Bei einem Update bekommen sie neue Rechte nur, wenn der Admin nie eines entzogen hat.
* Hochgeladene Plugins (`POST /api/plugins/install`, Zip) werden **immer** als
  `untrusted` installiert und starten ohne gewährte Rechte. Bei Updates bleiben
  nur bereits gewährte Rechte erhalten, die das neue Manifest noch anfordert.
* `untrusted`/Sandbox-Plugins können nie bekommen: `devices.provide`,
  `ai.provide`, `network.lan`, `network.discovery`, `system.manage`,
  `biometric.enroll`, `tools.develop`.
* Eigene Rechte im Namensraum `plugin.<id>.*` sind erlaubt.

## Kontext-API

`PluginContext` (`justai_sdk/plugin.py`):

| Methode | Recht |
| --- | --- |
| `register_tool(definition, handler)` | `tools.provide` |
| `register_provider(kind, provider)` – `device_driver`, `discovery`, `llm`, `realtime`, `stt`, `tts`, `embedding`, `wakeword`, `object_detector`, `face_analyzer` | je nach Art, z. B. `ai.provide`, `devices.provide` |
| `register_display_component(spec)` | `display.write` |
| `register_event_type(type, …)` | nur `plugin.<id>.*` |
| `publish(event)` / `subscribe(pattern, handler)` | `events.publish` / `events.subscribe` (subscribe nicht in der Sandbox) |
| `http.get/post/request` | `network.http`, nur Hosts aus `network_allowlist` |
| `store.get/put/delete/keys` | `storage.plugin`, isolierter Key-Value-Speicher pro Plugin |
| `services.list_devices/list_rooms` | `devices.read` |
| `services.snapshot(device_id)` | `camera.read` |
| `services.memory_search(...)` | `memory.read` |
| `services.say(room_id, text)` | `speaker.write`, über den Output Router |
| `services.show(room_id, document)` | `display.write`, über den Output Router |
| `services.complete(prompt, role=…)` | `ai.invoke`, über den KI-Router (Privacy-Regeln gelten) |

Plugins sprechen nie direkt mit Lautsprechern oder Displays. Jede Ausgabe läuft
über den Output Router.

## Tools

```python
class Params(BaseModel):
    location: str | None = Field(None, description="Ort")

ctx.register_tool(ToolDefinition(
    name="weather.current", description="Aktuelles Wetter an einem Ort.",
    parameters=Params, category="information", timeout_s=15,
    permissions=[], side_effect=SideEffect.READ, requires_confirmation=False,
), handler)

async def handler(args: Params, tc: ToolContext) -> ToolResult:
    return ToolResult.success({"temperature": 21.4}, message="Es hat 21 Grad.")
```

Der Executor (`tools/registry.py`) validiert die Parameter, prüft die Rechte des
Aufrufers (Rolle der Gesprächs-Endpoints bzw. des Benutzers), erzwingt den
Timeout, fragt bei `requires_confirmation` mündlich nach
(`assistant.confirm_action`/`assistant.cancel_action`) und protokolliert jede
Ausführung (`/api/tools/executions`). Fehler werden als
`ToolResult.failure(code, message)` gemeldet, nie als Ausnahme an das Modell.

## Sandbox (untrusted)

* Der Core schickt die Plugin-Dateien (nur `.py/.yaml/.json/.txt/.md`, max. 2 MB)
  an den Sandbox-Dienst. Der startet pro Plugin einen eigenen Host-Prozess mit
  rlimits (Adressraum, CPU, Dateien, Prozesse, Dateigröße, kein Core-Dump).
* Kommunikation: JSON-RPC über stdin/stdout; Zugriffe auf Core-Funktionen über das
  Plugin-Gateway (`/internal/plugin-gateway/<id>`) mit plugin-gebundenem Token.
  Das Gateway prüft jede Operation gegen die gewährten Rechte.
* HTTP-Anfragen führt der Core aus (Allowlist-Prüfung, keine privaten Adressen).
  Der Sandbox-Container hat selbst kein Netz außer zum Core.
* Tools aus der Sandbox werden im Core als Proxy-Tools registriert; die Parameter
  werden zusätzlich im Core per JSON-Schema validiert.

## Tests für Plugins

```python
from justai_sdk.testing import FakePluginContext

ctx = FakePluginContext(manifest, config={"default_location": "Bozen"},
                        http_routes={"https://api.open-meteo.com/*": lambda *a: HttpResponse(...)})
plugin = WeatherPlugin(ctx)
await plugin.setup()
result = await ctx.call_tool("weather.current", {"location": "Bozen"})
```

`FakePluginContext` hält Tools, Events, Speicher und HTTP-Antworten im Speicher. Er
gewährt alle im Manifest angeforderten Rechte und prüft Zugriffe dagegen;
HTTP-Anfragen an Hosts außerhalb der Allowlist schlagen wie im Core fehl. Für Audio-Plugins gibt es
`justai_sdk.simulation.AcousticRoom` (Echo, Hall, Rauschen, Ducking).

```bash
uv run pytest plugins/example-weather/tests
```

## Mitgelieferte Plugins

| Plugin | Art | Trust |
| --- | --- | --- |
| `tapo` | Gerätetreiber TP-Link Tapo (go2rtc `tapo://`, Backchannel, PTZ über pytapo) | builtin |
| `onvif` | ONVIF/RTSP-Treiber, PTZ, WS-Discovery (Unicast), mDNS | builtin |
| `simulated` | simulierte Kamera/Mikrofon/Lautsprecher mit akustischem Echo, Tool `simulator.say` | builtin |
| `openwakeword` | Wakeword-Provider | builtin |
| `faster-whisper` | STT lokal | builtin |
| `piper` | TTS lokal | builtin |
| `fastembed` | Embeddings lokal | builtin |
| `gemini` | LLM, Vision, Realtime (Gemini Live) | builtin |
| `openai-compat` | LLM über OpenAI-kompatible API (Ollama u. a.) | builtin |
| `vision-opencv` | Objekterkennung (YOLOX), Gesichter (YuNet/SFace) | builtin |
| `finance` | Kurse und Charts (inoffizielle Yahoo-Chart-API, siehe Hinweis) | builtin |
| `example-weather` | Wetter über Open-Meteo, **Referenzbeispiel**, läuft in der Sandbox | untrusted |

Hinweis `finance`: Die Yahoo-Chart-API ist nicht offiziell dokumentiert und kann sich
ohne Ankündigung ändern. Stooq als Alternative war beim Test durch eine
JavaScript-Challenge blockiert.

## Plugin verteilen

Zip-Archiv mit dem Plugin-Ordner (Manifest im Wurzelverzeichnis oder in genau einem
Unterordner) in der Admin-UI unter *Plugins → Installieren* hochladen. Danach
Rechte prüfen, gewähren, konfigurieren und aktivieren.
