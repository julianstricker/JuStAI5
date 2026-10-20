# 0004 – go2rtc als Medienserver, Streams nur im Speicher

*Deutsch · [English](../../adr/0004-go2rtc-media.md)*

**Status:** angenommen

## Kontext

Kameras sprechen unterschiedliche Protokolle (Tapo-Protokoll, RTSP, ONVIF), haben
begrenzte Verbindungszahlen und oft einen Audio-Rückkanal (Backchannel) nur über
herstellerspezifische Wege. Mehrere Verbraucher (Audio, Vision, Live-Ansicht,
Snapshots) brauchen dieselben Streams.

## Entscheidung

go2rtc (1.9.14) als eigener Container. Der Core registriert Streams zur Laufzeit per
API und verbraucht sie per RTSP (ffmpeg) bzw. HTTP. Audio-Ausgabe: Der Core stellt
einen in Echtzeit getakteten Live-WAV-Stream bereit, den go2rtc in den Backchannel
der Kamera zieht. Streams mit Zugangsdaten werden **nur im Speicher** angelegt
(`PATCH /api/streams`). Die Konfigurationsdatei ist read-only und enthält keine
Kameras.

## Alternativen

* **Direkt aus dem Core per ffmpeg/PyAV**: jede Kamera mehrfach verbunden, kein
  Tapo-Backchannel.
* **Frigate/MediaMTX**: Frigate bringt eine eigene Vision-Pipeline mit; MediaMTX
  kann den Tapo-Backchannel nicht.

## Konsequenzen

* Eine Kameraverbindung, viele Verbraucher.
* go2rtc vergisst die Streams bei einem Neustart. Ein Watchdog im Core vergleicht alle
  5 s die registrierten Streams mit denen in go2rtc und stellt fehlende wieder her.
  Getestet: Nach `docker compose restart go2rtc` gingen Snapshots der C200 nach 2 s
  wieder, die Mikrofone liefen weiter. Vorher (ohne Watchdog) blieb die Kamera
  dauerhaft unerreichbar. Das wurde erst bei der Prüfung dieser ADR entdeckt.
* Der Core taktet die Ausgabe selbst und kennt deshalb für jedes Frame den
  Ausgabezeitpunkt. Das ist die Grundlage der Echo-Behandlung ([0005](0005-echo-handling.md)).
* Gefunden beim Test: Ein `PUT` auf `/api/streams` schreibt die Quelle mit
  Zugangsdaten in `go2rtc.yaml`. Deshalb wird ausschließlich `PATCH` verwendet.
