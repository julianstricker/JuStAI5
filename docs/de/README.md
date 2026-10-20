# JuStAI5

*Deutsch · [English](../../README.md)*

JuStAI5 macht aus gewöhnlichen Kameras, Mikrofonen, Lautsprechern und Bildschirmen
einen gemeinsamen, lokal betriebenen KI-Assistenten. Räume und *Interaction
Endpoints* bestimmen, wo zugehört und wo geantwortet wird; ein deterministischer
Output Router sorgt dafür, dass Antworten im Raum der Anfrage bleiben. Der Assistent
reagiert nie auf seine eigene Stimme. Er spricht und versteht Deutsch, Englisch und
Italienisch, und die Oberfläche gibt es in allen drei Sprachen.

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

**Was man damit machen kann:** „Wenn du mich das nächste Mal ab morgen um 9 Uhr
siehst, erinnere mich, dass ich den Müll rausbringen soll.“ · „Wo sind meine
Autoschlüssel? Such mal im Poolhaus.“ · „Wo ist Lucky?“ · „Sag mir Bescheid, wenn
ein Auto in die Einfahrt fährt.“ · „Zeig mir den Kurs von Apple.“ · „Schalte die Kamera im Schlafzimmer aus.“ · „Bau
ein Plugin, das mir sagt, wenn der Strom unter 20 Cent kostet.“ Mehr:
[BEISPIELE.md](BEISPIELE.md).

## Installation

Ein Befehl auf einem Linux-Rechner (x86_64) installiert alles, auch Docker, und
fragt nur nach API-Key und Admin-Passwort:

```bash
curl -fsSL https://raw.githubusercontent.com/julianstricker/JuStAI5/main/scripts/install.sh | bash
```

**Schritt für Schritt, ohne Vorkenntnisse:** [INSTALLATION.md](INSTALLATION.md)
(Docker installieren, API-Key, Starten, Handy als Mikrofon, Kameras, Personen).

Von Hand, wenn Docker schon da ist (Compose ≥ 2.24):

```bash
git clone https://github.com/julianstricker/JuStAI5.git
cd JuStAI5
cp .env.example .env        # GOOGLE_API_KEY=… eintragen (oder später in der Oberfläche)
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
  *Einstellungen → Geräte-App*, siehe [DISPLAYS.md](DISPLAYS.md))

Wakeword, Spracherkennung, Sprachausgabe, Embeddings und Bildanalyse laufen lokal
(openWakeWord, faster-whisper, Piper, fastembed, OpenCV). **Für die Antworten braucht
es ein Sprachmodell**: entweder einen Google-API-Key (`GOOGLE_API_KEY=…` in `.env`,
siehe `.env.example`, oder in der Admin-UI unter *Plugins → Gemini*), damit sind alle
Rollen sofort belegt; oder ein lokales LLM (z. B. Ollama über das Plugin
*OpenAI-kompatibel*), das unter *KI-Provider* den Rollen zugeordnet wird
([AI.md](AI.md)).

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
| **Installation Schritt für Schritt** | [INSTALLATION.md](INSTALLATION.md) |
| **Beispiele: was man fragen kann** | [BEISPIELE.md](BEISPIELE.md) |
| Architektur, Module, Datenflüsse | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Technologie-Entscheidungen | [TECH_STACK.md](TECH_STACK.md), [adr/](adr/) |
| Entwicklung | [DEVELOPMENT.md](DEVELOPMENT.md) |
| Plugins & SDK | [PLUGINS.md](PLUGINS.md) |
| Geräte (Tapo, ONVIF, RTSP, simuliert) | [DEVICES.md](DEVICES.md) |
| Räume & Endpoints, Output Router | [ROOMS.md](ROOMS.md) |
| Audio: AEC, VAD, Wakeword, Arbitrierung, Duplex | [AUDIO.md](AUDIO.md) |
| KI-Provider, Rollen, Fallbacks, Datenschutz | [AI.md](AI.md) |
| Vision, Identität | [VISION.md](VISION.md) |
| PTZ-Tracking | [PTZ.md](PTZ.md) |
| Gedächtnis | [MEMORY.md](MEMORY.md) |
| Automationen | [AUTOMATIONS.md](AUTOMATIONS.md) |
| Displays | [DISPLAYS.md](DISPLAYS.md) |
| Sicherheit & Datenschutz | [SECURITY.md](SECURITY.md) |
| Betrieb, Backup, Update | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Tests & Teststatus | [TESTING.md](TESTING.md) |

## Projektstruktur

```
backend/        Core (Python 3.12, FastAPI) – src/justai/<modul>
sdk/python/     Plugin-SDK (justai_sdk): Manifest, Ports, Tools, Events, Testhilfen
sandbox/        Sandbox-Dienst für nicht vertrauenswürdige Plugins
plugins/        Mitgelieferte Plugins (Treiber, KI-Provider, Beispiel-Plugin)
frontend/       Admin-UI und Display-Client (React, Mantine, Vite)
docker/         Dockerfiles, Secret-Initialisierung
go2rtc/         Basis-Konfiguration des Medienservers (ohne Zugangsdaten)
scripts/        Installation, Modell-Download, Backup, Restore
docs/           Dokumentation und ADRs
```

## Status

Was mit echter Hardware geprüft wurde und was nur simuliert ist, steht ehrlich in
[TESTING.md](TESTING.md).

## Lizenz

Copyright (C) 2026 Julian Stricker

JuStAI5 steht unter der [GNU Affero General Public License v3.0](../../LICENSE) (AGPL-3.0). Du darfst
den Code nutzen, ändern und weitergeben. Wer eine geänderte Version als Dienst im Netzwerk
anbietet, muss den Quelltext seiner Änderungen ebenfalls unter der AGPL bereitstellen.

Ausnahmen:

- Das Plugin-SDK ([sdk/python](../../sdk/python)) steht unter der MIT-Lizenz, damit Plugins beliebig
  lizenziert werden können.
- Die mitgelieferten Plugins geben ihre Lizenz in der jeweiligen `plugin.yaml` an.

Drittkomponenten behalten ihre eigenen Lizenzen. Das gilt auch für die Modelle, die
`scripts/fetch_models.py` lädt (zum Beispiel die vortrainierten openWakeWord-Wake-Words und
die Piper-Stimmen). Prüfe deren Bedingungen, bevor du sie kommerziell einsetzt.

Beiträge sind derzeit nicht vorgesehen. Der Rechteinhaber behält sich vor, den Code zusätzlich
unter anderen Bedingungen zu lizenzieren.
