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

* **Home-Position**: Tapo-Kameras haben keine eingebaute Home-Position. *Als Home
  speichern* im PTZ-Feld legt die aktuelle Ansicht als Kamera-Preset „home“ an
  (ein vorhandenes wird ersetzt); *Home* fährt es an (live geprüft: zurück auf
  < 1 Pixel). Ohne gespeicherte Home-Position macht *Home* die Bewegungen rückgängig,
  die JuStAI5 seit dem Start ausgeführt hat (ungefähr, da Tapo nur relativ fährt);
  gibt es keine, kommt ein Hinweis statt eines Fehlers.
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

## Raum absuchen

`vision.search_area` („Such im Poolhaus nach meinen Schlüsseln“):

1. **Schwenk über den ganzen Raum**: von Home aus 5 Richtungen (ganz links … ganz
   rechts, ±1,6 Bildbreiten ≈ ±150° bei der C200) auf zwei Höhen (geradeaus und
   ~25° nach unten für Tische und Boden), als Schlangenlinie: 10 Bilder. Gibt es
   mindestens drei eigene Kamera-Presets (außer „home“), werden stattdessen diese
   angefahren.
2. **Auswertung**: Für Klassen des lokalen Detektors (Person, Hund, Auto …) sucht
   YOLOX lokal. Für alles andere (Schlüssel, Brille, Handy …) bekommt das
   Vision-Modell **alle Bilder in einer Anfrage** und nennt Bild und Stelle („auf dem
   Schreibtisch rechts neben dem Laptop-Ständer“). Datenschutzregeln des Raums gelten
   (Bilder nicht in die Cloud → lokales Vision-Modell oder Ablehnung).
3. **Ergebnis**: Bei einem Fund richtet sich die Kamera auf die Stelle aus, sonst
   kehrt sie nach Home zurück.

Dauer mit der C200: knapp 50 s (Motor plus 2 s Beruhigung je Richtung, eine
Modellanfrage). Live geprüft: „Schlüssel“ gefunden (auf dem Schreibtisch, im Bild
bestätigt), „ein Fenster“ gefunden.

Vorher fand die Suche nichts: Sie nutzte nur den lokalen Detektor, der keine
Schlüssel kennt, und fuhr bei einem einzigen Preset nur eine Richtung an, wobei sie
die Bewegungen des Assistenten jedes Mal durch „Home“ zurücknahm.

## Teststatus

* Unit-Tests der Regelung (`tests/unit/test_ptz_tracking.py`): Totzone,
  proportionale und begrenzte Schritte, Ratenlimit, Zielbindung, Halten und
  einmalige Heimkehr, manuelle Übersteuerung, Ziel per Personen-ID.
* Simuliertes PTZ-Gerät für die UI.
* **Mit echter Hardware nicht getestet**: Für die PTZ-Steuerung der Tapo C200
  fehlte beim Test das Cloud-Passwort bzw. ein Kamerakonto (nur der Passwort-Hash
  war bekannt, der nur für den Stream reicht). Sobald eines davon im Gerät
  eingetragen ist, kann der Test nachgeholt werden.
