# Betrieb

## Voraussetzungen

* Linux-Host x86_64 mit Docker Engine und Compose v2. Andere Plattformen sind
  nicht getestet; openWakeWord/tflite und die Images sind auf linux/amd64 gebaut.
* Gemessener Bedarf auf dem Entwicklungsrechner (8 Kerne, 32 GB RAM), mit zwei
  Kameras, Vision mit 2 fps auf einer Kamera und allen lokalen Modellen geladen:

  | Container | RAM | CPU im Leerlauf |
  | --- | --- | --- |
  | core | ~1,5 GB | ~20 % eines Kerns (Vision + Audio-Pipeline) |
  | postgres | ~60 MB | < 1 % |
  | go2rtc | ~20 MB | ~2 % |
  | sandbox | ~75 MB (Limit 1 GB) | < 1 % |

  YOLOX braucht auf dieser CPU ca. 320 ms pro analysiertem Bild; es läuft nur bei
  Bewegung bzw. alle 20 s. Eine GPU wird nicht benötigt.
* Plattenplatz: Core-Image ca. 2,7 GB (inkl. aller Modelle), Sandbox ca. 220 MB,
  dazu die Datenbank.
* Netzwerk: Der Core-Container muss Kameras im LAN erreichen (Netz `media`, normales
  Bridge-Netz mit NAT). Für Multicast-Discovery (WS-Discovery, mDNS) ist ein
  Bridge-Netz ungünstig; JuStAI5 sucht deshalb per Unicast in freigegebenen
  Bereichen ([DEVICES.md](DEVICES.md#hinzufügen)).

## Installation

Ausführliche Anleitung für Einsteiger (Docker installieren, API-Key, erste Geräte):
[INSTALLATION.md](INSTALLATION.md). Automatisch: `scripts/install.sh` (prüft
Plattform und Docker, legt `.env` mit LAN-Adresse, Netzbereich und freien Ports an,
startet und wartet auf `/api/health`; erneuter Aufruf behält `.env` und baut neu).
Von Hand:

```bash
git clone https://github.com/julianstricker/JuStAI5.git justai5 && cd justai5
cp .env.example .env        # optional: Port, Admin-Passwort, Google-API-Key, Netzbereiche
docker compose up -d --build
docker compose exec core cat /data/initial_admin_password.txt
```

Beim ersten Start:

1. `secrets-init` erzeugt DB-Passwort, Master-Key und Sandbox-Token im Volume `secrets`.
2. PostgreSQL startet; der Core migriert das Schema (Alembic) automatisch.
3. Mitgelieferte Plugins werden registriert und mit `default_enabled` aktiviert.
4. Ohne Benutzer wird `admin` mit zufälligem Passwort angelegt.

## Konfiguration

Bootstrap-Werte als Umgebungsvariablen (`.env`, Präfix `JUSTAI_`, vollständig in
`backend/src/justai/config.py`). Alles andere (Räume, Geräte, KI, Plugins,
Aufbewahrung) wird in der Admin-UI gepflegt und liegt in der Datenbank.

| Variable | Standard | |
| --- | --- | --- |
| `JUSTAI_HTTP_PORT` | 8080 | Port auf dem Host |
| `JUSTAI_HTTPS_PORT` | 8443 | HTTPS-Port auf dem Host (Geräte-App); im Container lauscht der Core immer auf 8443 |
| `JUSTAI_TLS_ENABLED` | true | HTTPS mit lokaler Zertifizierungsstelle |
| `JUSTAI_TLS_NAMES` | – | zusätzliche Namen/Adressen fürs Zertifikat, z. B. `["192.168.0.10","justai.fritz.box"]` (auch in der UI ergänzbar) |
| `JUSTAI_PUBLIC_URL` | http://localhost:8080 | bei `https://` werden Cookies `Secure` |
| `JUSTAI_ADMIN_USERNAME` / `JUSTAI_ADMIN_PASSWORD` | admin / zufällig | nur wenn noch kein Benutzer existiert |
| `GOOGLE_API_KEY` | – | aktiviert Gemini (auch in der UI eintragbar) |
| `JUSTAI_DISCOVERY_DEFAULT_CIDRS` | – | z. B. `["192.168.0.0/24"]` |
| `JUSTAI_LOG_LEVEL` | INFO | |
| `JUSTAI_ENABLE_SIMULATED_DEVICES` | true | Simulationstreiber anbieten |

### Lokale KI mit Ollama

Das Plugin *OpenAI-kompatibel* hat bereits einen Endpoint `ollama` mit
`http://host.docker.internal:11434/v1` vorkonfiguriert (der Core-Container kennt
`host.docker.internal`). Ollama auf dem Host starten und so konfigurieren, dass es
nicht nur auf 127.0.0.1 lauscht (`OLLAMA_HOST=0.0.0.0`). Weitere Server (llama.cpp,
vLLM) lassen sich dort als zusätzliche Endpoints mit `locality: local` eintragen. Danach unter *KI-Provider* die Rollen zuordnen,
z. B. `conversation` → Ollama-Modell, Gemini als Fallback, oder `local_only`.

## Update

```bash
git pull
docker compose up -d --build
```

Migrationen laufen beim Start. Plugin-Konfigurationen und gewährte Rechte bleiben
erhalten. Gekoppelte Displays laden die neue Oberfläche nach dem Wiederverbinden
selbst ([DISPLAYS.md](DISPLAYS.md)). Vor größeren Updates ein Backup anlegen.

## Backup und Wiederherstellung

```bash
./scripts/backup.sh [zielordner]       # Standard: ./backups
./scripts/restore.sh backups/justai5-backup-JJJJMMTT-HHMMSS.tar.gz
```

* Das Backup enthält den Datenbank-Dump (`pg_dump -Fc`), die Volumes `data`
  (Plugins, hochgeladene Dateien) und `secrets` (Master-Key!), `docker-compose.yml`
  und `.env`. Die Datei wird mit Rechten `600` geschrieben. **Sie enthält Secrets:
  verschlüsselt und getrennt vom Server aufbewahren.**
* Die Wiederherstellung stoppt Core und Sandbox, ersetzt die Volumes und die
  Datenbank, übernimmt das DB-Passwort aus dem Backup und startet alles neu.
* Für ein anderes Compose-Projekt: `COMPOSE_PROJECT_NAME=<name>`.

Getestet (2026-10-15): Backup der laufenden Instanz, Wiederherstellung in ein
**getrenntes** Compose-Projekt ohne LAN-Zugang. Räume, Geräte, Endpoints, Plugins,
Automationen und Personen waren identisch, die Admin-Anmeldung funktionierte, und
alle verschlüsselten Zugangsdaten ließen sich mit dem wiederhergestellten
Master-Key entschlüsseln.

## Überwachung

* `GET /api/health` (auch Docker-Healthcheck des Core)
* `GET /api/system/status`: Plugins, Geräte, Medienserver, Ressourcen
* `GET /api/metrics`: Prometheus-Format
* Admin-UI → *Dashboard* und *Diagnose* (Events, Tasks, Bus-Queues, Audit-Log)
* Logs: `docker compose logs -f core` (JSON; `JUSTAI_LOG_JSON=false` für Klartext)

## Fehlersuche

| Symptom | Prüfen |
| --- | --- |
| Gerät `offline` | Admin-UI → Geräte: Warnungen des Treibers; IP geändert? Akku-Kamera im Schlaf? |
| Kein Wakeword | *Audio*: Pegel und VAD bewegen sich? Wakeword-Score beim Sprechen? Endpoint aktiv? |
| Ausgabe kommt nicht an | Log `output denied` mit Grund; mit `JUSTAI_LOG_LEVEL=DEBUG` jede Entscheidung als `output routed` mit Raum, Gerät und Begründung |
| Assistent hört sich selbst | Kalibrieren; Duplex auf `half`; `output_latency_ms` erhöhen |
| Cloud-KI antwortet nicht | *Dashboard → KI-Provider*: pausierte Modelle (orange) nach Fehlern/Quota; Fallback-Kette in *KI-Provider* |
| Display zeigt nichts | Display verbunden? Seite sichtbar (nicht im Hintergrund)? Fehlergrund im Tool-Protokoll |
| Plugin `failed` | Fehlertext in *Plugins*, Logs mit `plugin=<id>` |

## Deinstallation

```bash
docker compose down          # Container entfernen, Daten bleiben
docker compose down -v       # ACHTUNG: löscht auch Datenbank, Secrets und Daten
```
