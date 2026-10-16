# JuStAI5

JuStAI5 macht aus gewöhnlichen Kameras, Mikrofonen, Lautsprechern und Bildschirmen
einen gemeinsamen, lokal betriebenen KI-Assistenten. Räume und *Interaction
Endpoints* bestimmen, wo zugehört und wo geantwortet wird; ein deterministischer
Output Router sorgt dafür, dass Antworten im Raum der Anfrage bleiben. Der Assistent
reagiert nie auf seine eigene Stimme.

```
Kamera/Mikrofon ──► go2rtc ──► Audio-Engine (AEC, VAD, Wakeword, Arbitrierung)
                                   │
                                   ▼
                          Gesprächssession ──► KI-Router (Realtime | STT→LLM→TTS)
                                   │                 │
                                   ▼                 ▼
                          Output Router ◄──── Tools (Gedächtnis, Vision, PTZ, Display, …)
                                   │
                    Lautsprecher / Display im selben Raum
```

## Schnellstart

Voraussetzung: Docker mit Compose v2 (Linux-Host empfohlen, x86_64).

```bash
docker compose up -d --build
```

* Admin-Oberfläche: <http://localhost:8080>
* Benutzer `admin`, das initiale Passwort steht nach dem ersten Start in
  `/data/initial_admin_password.txt` im Core-Container:

```bash
docker compose exec core cat /data/initial_admin_password.txt
```

* Display-Client (z. B. auf einem Fernseher/Tablet öffnen und in der Admin-UI unter
  *Displays* mit dem angezeigten Code koppeln): <http://HOST:8080/display>
* Geräte-App: Handy, Tablet oder PC als Mikrofon, Lautsprecher, Kamera und
  Bildschirm, installierbar als App: <https://HOST:8443/app> (Einrichtung unter
  *Einstellungen → Geräte-App*, siehe [docs/DISPLAYS.md](docs/DISPLAYS.md))

Wakeword, Spracherkennung, Sprachausgabe, Embeddings und Bildanalyse laufen lokal
(openWakeWord, faster-whisper, Piper, fastembed, OpenCV). **Für die Antworten braucht
es ein Sprachmodell**: entweder einen Google-API-Key (`GOOGLE_API_KEY=…` in `.env`,
siehe `.env.example`, oder in der Admin-UI unter *Plugins → Gemini*), damit sind alle
Rollen sofort belegt; oder ein lokales LLM (z. B. Ollama über das Plugin
*OpenAI-kompatibel*), das unter *KI-Provider* den Rollen zugeordnet wird
([docs/AI.md](docs/AI.md)).

### Erste Schritte

1. *Räume* anlegen (z. B. Wohnzimmer, Küche).
2. *Geräte* hinzufügen – per Netzwerksuche (ONVIF/mDNS/Tapo) oder manuell. Ohne
   Hardware: Treiber **simulated** (simuliertes Gerät mit akustischem Echo).
3. *Endpoints*: Mikrofon und Lautsprecher (optional Kamera/Display) eines Raums zu
   einem Endpoint kombinieren, *Kalibrieren* ausführen.
4. „Hey Jarvis“ sagen. Antworten kommen über den Lautsprecher desselben Endpoints.

## Dokumentation

| Thema | Datei |
| --- | --- |
| Architektur, Module, Datenflüsse | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Technologie-Entscheidungen | [docs/TECH_STACK.md](docs/TECH_STACK.md), [docs/adr/](docs/adr/) |
| Entwicklung | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Plugins & SDK | [docs/PLUGINS.md](docs/PLUGINS.md) |
| Geräte (Tapo, ONVIF, RTSP, simuliert) | [docs/DEVICES.md](docs/DEVICES.md) |
| Räume & Endpoints, Output Router | [docs/ROOMS.md](docs/ROOMS.md) |
| Audio: AEC, VAD, Wakeword, Arbitrierung, Duplex | [docs/AUDIO.md](docs/AUDIO.md) |
| KI-Provider, Rollen, Fallbacks, Datenschutz | [docs/AI.md](docs/AI.md) |
| Vision, Identität | [docs/VISION.md](docs/VISION.md) |
| PTZ-Tracking | [docs/PTZ.md](docs/PTZ.md) |
| Gedächtnis | [docs/MEMORY.md](docs/MEMORY.md) |
| Automationen | [docs/AUTOMATIONS.md](docs/AUTOMATIONS.md) |
| Displays | [docs/DISPLAYS.md](docs/DISPLAYS.md) |
| Sicherheit & Datenschutz | [docs/SECURITY.md](docs/SECURITY.md) |
| Betrieb, Backup, Update | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Tests & Teststatus | [docs/TESTING.md](docs/TESTING.md) |

## Projektstruktur

```
backend/        Core (Python 3.12, FastAPI) – src/justai/<modul>
sdk/python/     Plugin-SDK (justai_sdk): Manifest, Ports, Tools, Events, Testhilfen
sandbox/        Sandbox-Dienst für nicht vertrauenswürdige Plugins
plugins/        Mitgelieferte Plugins (Treiber, KI-Provider, Beispiel-Plugin)
frontend/       Admin-UI und Display-Client (React, Mantine, Vite)
docker/         Dockerfiles, Secret-Initialisierung
go2rtc/         Basis-Konfiguration des Medienservers (ohne Zugangsdaten)
scripts/        Modell-Download, Backup, Restore
docs/           Dokumentation und ADRs
```

## Status

Was mit echter Hardware geprüft wurde und was nur simuliert ist, steht ehrlich in
[docs/TESTING.md](docs/TESTING.md).

## Lizenz

Copyright (C) 2026 Julian Stricker

JuStAI5 steht unter der [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Du darfst
den Code nutzen, ändern und weitergeben. Wer eine geänderte Version als Dienst im Netzwerk
anbietet, muss den Quelltext seiner Änderungen ebenfalls unter der AGPL bereitstellen.

Ausnahmen:

- Das Plugin-SDK ([sdk/python](sdk/python)) steht unter der MIT-Lizenz, damit Plugins beliebig
  lizenziert werden können.
- Die mitgelieferten Plugins geben ihre Lizenz in der jeweiligen `plugin.yaml` an.

Drittkomponenten behalten ihre eigenen Lizenzen. Das gilt auch für die Modelle, die
`scripts/fetch_models.py` lädt (zum Beispiel die vortrainierten openWakeWord-Wake-Words und
die Piper-Stimmen). Prüfe deren Bedingungen, bevor du sie kommerziell einsetzt.

Beiträge sind derzeit nicht vorgesehen. Der Rechteinhaber behält sich vor, den Code zusätzlich
unter anderen Bedingungen zu lizenzieren.
