# Architektur

JuStAI5 ist ein **modularer Monolith** mit klaren Ports & Adapters: ein Core-Prozess
(FastAPI, asyncio) enthält die Domänenmodule. Hardware, KI-Provider und
Integrationen kommen ausschließlich über Plugins. Was nicht vertrauenswürdig ist,
läuft in einem getrennten Sandbox-Container. Begründung: [ADR 0001](adr/0001-modular-monolith.md).

## Container (Docker Compose)

| Dienst | Aufgabe | Netze |
| --- | --- | --- |
| `secrets-init` | erzeugt einmalig DB-Passwort, Master-Key, Sandbox-Token im Volume `secrets` | keins |
| `postgres` | PostgreSQL 17 + pgvector (Konfiguration, Events, Gedächtnis, Embeddings, Jobs) | `db` (intern) |
| `go2rtc` | Medienserver: RTSP/Tapo/ONVIF-Streams, Snapshots, Talkback (Backchannel) | `media` |
| `core` | API, Admin-UI, Audio, Gespräche, Vision, Automationen, vertrauenswürdige Plugins | `db`, `media`, `sandbox` |
| `sandbox` | führt nicht vertrauenswürdige Plugins/generierte Tools aus | `sandbox` (intern) |

Die Netze `db` und `sandbox` sind `internal`: Datenbank und Sandbox haben weder
Internet noch LAN-Zugriff; die Sandbox erreicht nur den Core.

## Module im Core (`backend/src/justai`)

```
api/            HTTP/WebSocket-Schicht (Routen, Auth-Abhängigkeiten) – keine Logik
container.py    Composition Root: baut alle Komponenten, explizite DI
extensions.py   Feature-Module (Speech, Memory, Vision, PTZ, Display, Automation, Devtools, Retention)
common/         Fehler, Secret-Redaktion, Verschlüsselung, Supervisor, spawn()
db/             SQLAlchemy-Modelle, Alembic-Migrationen
events/         Event-Katalog, Event-Bus, Event-Store
system/         Settings, Job-Queue, Telemetrie, Retention
auth/           Benutzer, Rollen (RBAC), JWT, Audit
rooms/ devices/ endpoints/    Topologie: Räume, Geräte (+ Discovery), Interaction Endpoints
media/          go2rtc-Client
audio/          DSP, VAD, Echo, I/O-Kanäle, Prozessor pro Endpoint, Arbitrierung, Engine
conversation/   Zustandsautomat, Sessions (Realtime- und Pipeline-Treiber), Echo-Filter
ai/             KI-Konfiguration, Router (Fallback, Privacy, Kosten), Nutzungserfassung
output/         Output Router, Topologie, Sprachausgabe
tools/          Tool-Registry, Executor, Bestätigungen, eingebaute Tools
plugins/        Loader, Manager, Kontext, Provider-Registry, Sandbox-Client
memory/ identity/ vision/ ptz/ display/ automation/ devtools/   Fachmodule
```

Regeln:

* Module hängen nur von Ports (Protokollen/ABCs) ab, nicht von konkreten Plugins.
  Die Ports liegen im SDK (`justai_sdk.ports.*`), damit Plugins und Core dieselben
  Verträge nutzen.
* `container.py` ist der einzige Ort, der alles kennt. Komponenten bekommen ihre
  Abhängigkeiten über den Konstruktor.
* Langlaufende Tasks laufen unter dem `Supervisor` (Neustart mit Backoff) oder
  werden mit `spawn()` gestartet (Fehler werden geloggt, Referenzen gehalten).

## Zentrale Datenflüsse

### Sprachinteraktion

```
Mikrofon ─► go2rtc ─► FfmpegMicSource (16 kHz PCM, Zeitstempel)
          ─► MicChannel (Fan-out an alle Endpoints, die das Gerät nutzen)
          ─► EndpointAudioProcessor
               HPF/AEC3 (Referenz um gemessene Latenz verschoben) · NS · Silero-VAD
               Echo-Fenster (PlaybackTracker) · Half-Duplex-Gating · openWakeWord
          ─► WakeArbiter (pro Arbitrierungsgruppe, 0,8 s Fenster)
          ─► ConversationManager.start_session(endpoint)
               Realtime-Treiber (z. B. Gemini Live)  oder  Pipeline-Treiber (STT → LLM → TTS)
          ─► Tools (Registry, Rechteprüfung, Bestätigung, Audit)
          ─► OutputRouter.resolve(endpoint-raum) ─► SpeakerChannel ─► go2rtc-Backchannel
                                                    └─► ReferenceBuffer/PlaybackTracker (Echo-Referenz)
```

Die Session ist fest an ihren Endpoint gebunden. Auch nach Tool-Aufrufen,
Provider-Wechseln oder Reconnects bestimmt der Output Router das Ziel neu aus dem
Raum des Endpoints, nie aus Modellausgaben. Details: [AUDIO.md](AUDIO.md),
[ROOMS.md](ROOMS.md).

### Events und Automationen

```
Quelle (Vision, Audio, Display, Plugin, Cron) ─► EventBus.publish
   ├─ dauerhafte Events ─► EventStore (Postgres)
   ├─ Abonnenten (eigene Queue je Abonnent, Fehlerisolation)
   └─ AutomationEngine ─► Trigger/Bedingungen ─► Job-Queue (Postgres, SKIP LOCKED)
                                                  └─► Aktionen (assistant.invoke, speak, tool, display.show …)
```

Events tragen `hop` und `caused_by`. Der Bus verwirft Events über dem Hop-Limit
(`system.event_loop_detected`), und eine Automation reagiert nie auf eigene Events.

### Vision

```
go2rtc Substream (niedrige fps) ─► Privatsphärenmaske ─► Bewegung ─► YOLOX (nur bei Bewegung/aktiven Tracks)
  ─► IoU-Tracker ─► Gesichtsprüfung (YuNet + SFace, Full-Res-Snapshot, nur für unbekannte Personen-Tracks)
  ─► Events (vision.*), Sichtungen, Watches, PTZ-Tracking
```

### Displays

```
Tool display.show ─► Komponentenvalidierung ─► OutputRouter (Display im Raum)
  ─► WebSocket an Display-Client ─► Rendern mit eingebauten Komponenten ─► ack
  ─► erst dann meldet das Tool Erfolg
```

## Persistenz

PostgreSQL ist die einzige Datenbank ([ADR 0003](adr/0003-postgres-pgvector.md)):
relationale Tabellen für Topologie, Benutzer, Automationen, Jobs; JSONB für
flexible Konfiguration und Event-Payloads; pgvector (384 Dim.) für
Gedächtnis-Embeddings und Gesichts-Embeddings. Migrationen: Alembic, laufen beim
Start automatisch (`db/migrate.py`).

Konfiguration, die Benutzer zur Laufzeit ändern (Räume, Geräte, KI-Rollen,
Plugin-Einstellungen), liegt in der Datenbank. Umgebungsvariablen (`JUSTAI_*`,
`config.py`) enthalten nur Bootstrap-Werte. Plugin-Secrets werden mit Fernet
(Master-Key aus dem Volume `secrets`) verschlüsselt gespeichert.

## Erweiterbarkeit

* **Plugins** (Manifest, Rechte, Lifecycle): [PLUGINS.md](PLUGINS.md)
* **Provider-Ports**: `ai` (Chat, Realtime, STT, TTS, Embedding), `devices`
  (Treiber, Audio-Quellen/Senken, Snapshots), `ptz`, `vision` (Detektor,
  Gesichtsanalyse), `wakeword`, `display`, `discovery`
* **Tools**: deklarativ mit Pydantic-Parametern, Kategorie, Rechten, Nebenwirkung
  (`none`/`read`/`write`/`physical`) und optionaler Bestätigungspflicht
* **Events**: Plugins können eigene Event-Typen im Namensraum `plugin.<id>.*` registrieren

Die Schnittstellen zwischen den Modulen (Event-Bus, Job-Queue, Provider-Ports)
sind so geschnitten, dass sich Teile später in eigene Prozesse auslagern lassen,
z. B. Vision-Inferenz oder der Bus über NATS. Das ist bewusst noch nicht gemacht.
