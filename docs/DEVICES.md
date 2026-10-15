# Geräte

Ein **Gerät** ist ein physisches oder virtuelles Gerät mit Fähigkeiten
(Capabilities). Geräte sind unabhängig von Endpoints: Eine Kamera kann Bild und
Mikrofon liefern, der Lautsprecher kann ein anderes Gerät sein
([ROOMS.md](ROOMS.md)).

## Fähigkeiten

Definiert in `justai_sdk/ports/devices.py` (`Capability`). Sie werden **zur
Laufzeit ermittelt** (Probe beim Hinzufügen und bei jeder Verbindung), nicht aus
dem Modellnamen geraten:

`video.input`, `audio.input`, `audio.output`, `audio.full_duplex`,
`camera.snapshot`, `camera.ptz.pan|tilt|zoom|presets|absolute`,
`camera.motion_events`, `camera.privacy_mode`, `display.text|image|dashboard|video|interactive|notifications|fullscreen`,
`sensor.motion`, `sensor.contact`.

Ob ein Stream tatsächlich Audio enthält, misst der Core über go2rtc
(`probe_medias`), nicht über Herstellerangaben.

## Hinzufügen

* **Netzwerksuche** (Admin-UI → Geräte → Suchen): Tapo (Port-Signatur),
  ONVIF WS-Discovery (Unicast an alle Hosts des Bereichs, weil Multicast aus
  Docker-Bridge-Netzen meist nicht durchkommt), mDNS. Gescannt werden nur
  Bereiche, die der Admin unter *Einstellungen → Netzwerksuche* freigegeben hat,
  und nur private Netze (`devices/discovery.py`).
* **Manuell**: Treiber wählen, Formular aus dem `config_schema` des Treibers
  ausfüllen, *Testen* (Probe ohne Speichern) und *Speichern*.

Zugangsdaten werden verschlüsselt gespeichert. go2rtc-Streams mit Zugangsdaten
legt der Core nur im Speicher an (`PATCH /api/streams`), sie landen nie in
`go2rtc.yaml` ([ADR 0004](adr/0004-go2rtc-media.md)).

## Treiber

### TP-Link Tapo (`tapo`)

| Feld | Bedeutung |
| --- | --- |
| `host` | IP/Hostname |
| `cloud_password` | Tapo-Cloud-Passwort: Tapo-Stream mit Zwei-Wege-Audio und lokale Steuerung (PTZ, Presets, Privatsphäre-Modus) |
| `password_hash` | alternativ Hash des Cloud-Passworts – reicht für den Stream inkl. Talkback, **nicht** für die lokale Steuerung |
| `camera_username` / `camera_password` | Kamerakonto aus der Tapo-App: RTSP und ONVIF (PTZ über ONVIF Port 2020) |
| `stream` | `tapo` (Standard, mit Backchannel) oder `rtsp` (ohne Lautsprecher) |
| `horizontal_fov_deg` / `vertical_fov_deg` | Bildwinkel für PTZ-Tracking (Standard 95°/54°) |

Getestet mit echter Hardware:

* **C200**: Video, Snapshots, fMP4-Livestream, Mikrofon und Lautsprecher über
  go2rtc `tapo://`. Die Kamera **schaltet ihr Mikrofon stumm, solange ihr
  Lautsprecher spielt** (Hardware-Half-Duplex). Die Kalibrierung erkennt das:
  Es kommt kein Echo an, die konservative Latenz bleibt aktiv. Gemessene
  Ende-zu-Ende-Latenz Wiedergabe → Mikrofon: etwa 1,8 s. Barge-in während der
  Ausgabe ist mit diesem Gerät physikalisch nicht möglich.
* **PTZ der C200**: über die lokale Tapo-API (Cloud-Passwort) oder ONVIF
  (Kamerakonto). Die C200-Firmware kennt `getMotorCapability` nicht; die
  Schwenkfunktion wird deshalb über die Preset-API erkannt (die gibt es nur bei
  Schwenkmodellen), ersatzweise über ONVIF. Die lokale API scheitert gelegentlich
  beim Verbindungsaufbau (`pake_share failed`); dann übernimmt ONVIF. Getestet:
  Schwenken rechts und zurück aus der Admin-UI bzw. API.
* **C410** (Akku-Kamera): war beim Test meist nicht erreichbar (schläft) und bietet
  kein RTSP. Für den Dauerbetrieb als Mikrofon ist sie ungeeignet.

### ONVIF / RTSP (`onvif`)

Zwei Gerätetypen:

* **ONVIF**: `host`, `port` (Tapo: 2020), `username`, `password`, `backchannel`,
  Bildwinkel. Stream-URLs, PTZ-Fähigkeiten und Presets werden über ONVIF ermittelt.
* **RTSP**: `url` (ohne Zugangsdaten), optional `sub_url`, `username`, `password`,
  `backchannel` (ONVIF-Profile-T-Backchannel über go2rtc, falls die Kamera es kann).

### Simuliert (`simulated`)

Für Entwicklung, Tests und Vorführung ohne Hardware: Kamera (Bild aus Datei),
Mikrofon und Lautsprecher, optional PTZ. Der Lautsprecher speist das Ausgegebene
mit `echo_delay_s`/`echo_gain` wieder ins Mikrofon (Raumakustik, Rauschen,
optional `hardware_ducking` wie bei der C200). Mit dem Tool `simulator.say`
„spricht“ ein simulierter Benutzer (Piper-Stimme) in einen oder mehrere Räume
gleichzeitig (`also_devices`, `also_gain`), damit lassen sich z. B. Wakewords
hören, die zwei Räume gleichzeitig erreichen.

Abschaltbar mit `JUSTAI_ENABLE_SIMULATED_DEVICES=false`.

### Browser-Display (`browser-display`)

Wird beim Koppeln eines Display-Clients angelegt ([DISPLAYS.md](DISPLAYS.md)).

## Status und Wiederverbindung

Der `DeviceManager` hält pro Gerät eine Laufzeit (Handle, Fähigkeiten, Status
`online`/`offline`/`no_driver`). Fällt ein Gerät aus, wird mit Backoff neu
verbunden; Statuswechsel erzeugen `device.status.changed`. Der Talkback-Pfad
verbindet sich automatisch neu. Endpoints mit fehlenden Geräten melden ihren
Zustand in der UI, statt auf andere Räume auszuweichen.

## Diagnose

* `POST /api/devices/{id}/test-tone`: Testton über den Lautsprecher (über den Output Router)
* `GET /api/devices/{id}/snapshot.jpg`, `GET /api/devices/{id}/live.mp4`
  (Live-Video im Geräte-Dialog: startet automatisch, bleibt an der Live-Kante,
  beendet die Kameraverbindung beim Schließen)
* Admin-UI → *Audio*: Pegel, VAD, Wakeword-Score, Echo-Fenster, Duplex-Modus pro Endpoint
* Admin-UI → *Diagnose*: Event-Strom, Telemetrie, Audit-Log
