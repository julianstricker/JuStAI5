# PTZ: bewegliche Kameras

Code: `backend/src/justai/ptz/` (Logik in `tracking.py` ohne I/O, Dienst in
`service.py`). Treiber implementieren den Port `justai_sdk.ports.ptz.PtzController`:
Tapo (pytapo, Cloud-Passwort), ONVIF (auch Tapo über Port 2020 mit Kamerakonto),
simuliert (Panorama-Bild mit verschiebbarem Ausschnitt).
Wiederverwendbarer ONVIF-Baustein für Plugins: `justai_sdk.contrib.onvif_ptz`.

## Fähigkeiten

Werden pro Gerät ermittelt: Pan, Tilt, Zoom, Presets, absolute Positionierung.
Kameras ohne absolute Position (z. B. Tapo) werden relativ gesteuert. Der Dienst
schätzt dann die Position relativ zur Home-Position mit.

## Steuerung

| Weg | |
| --- | --- |
| Admin-UI → *Geräte* → PTZ-Steuerkreuz, Presets | `POST /api/ptz/{id}/move|stop|home`, `/presets`, `/presets/{p}/goto` |
| Assistent | Tools `ptz.move`, `ptz.home`, `ptz.goto_preset`, `ptz.follow`, `ptz.stop_follow`, `vision.search_area` |

* **Manuelle Steuerung hat Vorrang**: Jeder manuelle Befehl pausiert ein laufendes
  Tracking für 20 s.
* **Weiche Grenzen** pro Gerät (`ptz_limits`: `pan_min/max`, `tilt_min/max` in
  Bildfeld-Einheiten relativ zu Home), z. B. damit die Kamera nie auf den Nachbarn
  zeigt.
* Rechte: `camera.ptz`. Jede PTZ-Aktion des Assistenten steht im Tool-Protokoll
  (`/api/tools/executions`), Tracking-Starts über die API im Audit-Log.

## Tracking

`ptz.follow` (bzw. `POST /api/ptz/{id}/track`) mit Ziel `person` (größte bzw.
bisher verfolgte Person), `label` (z. B. `dog`, auch ein registriertes Haustier)
oder `person_id` (erkannte Person). Die Vision-Engine analysiert dafür jedes Frame
der Kamera.

Regelung (`TrackingParams`):

| Parameter | Standard | Bedeutung |
| --- | --- | --- |
| `dead_zone` | 0,12 | Bereich um die Bildmitte ohne Bewegung (gegen Zittern) |
| `gain` | 0,8 | Anteil des Versatzes, der pro Befehl korrigiert wird |
| `max_step` | 0,35 | maximale Bewegung pro Befehl (Bildfeld-Anteil) |
| `min_interval_s` | 1,2 | Mindestabstand zwischen Befehlen (Tapo braucht Zeit) |
| `lost_hold_s` | 6 | Position halten, nachdem das Ziel verschwunden ist |
| `return_home_after_s` | 30 | danach einmal zur Home-Position |
| `tilt_enabled` | true | |

Zustände: `searching`, `following`, `holding`, `home`, `paused`. Das Tracking
bleibt am aktuellen Ziel, statt zwischen Personen zu springen. Events:
`ptz.tracking.started/stopped`.

## Gebietssuche

`vision.search_area` („Schau mal, ob der Hund im Garten ist“): Die Kamera fährt die
Presets ab oder, ohne Presets, schrittweise nach rechts und links von Home aus.
An jeder Position läuft nach einer Beruhigungszeit (2,5 s) der Objektdetektor.
Das Ergebnis enthält die besuchten Positionen und die Treffer.

## Teststatus

* Unit-Tests der Regelung (`tests/unit/test_ptz_tracking.py`): Totzone,
  proportionale und begrenzte Schritte, Ratenlimit, Zielbindung, Halten und
  einmalige Heimkehr, manuelle Übersteuerung, Ziel per Personen-ID.
* Simuliertes PTZ-Gerät für die UI.
* **Mit echter Hardware nicht getestet**: Für die PTZ-Steuerung der Tapo C200
  fehlte beim Test das Cloud-Passwort bzw. ein Kamerakonto (nur der Passwort-Hash
  war bekannt, der nur für den Stream reicht). Sobald eines davon im Gerät
  eingetragen ist, kann der Test nachgeholt werden.
