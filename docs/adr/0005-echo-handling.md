# 0005 – Mehrschichtige Echo-Behandlung mit eigener Bulk-Delay-Kompensation

**Status:** angenommen

## Kontext

Der Assistent darf nie auf seine eigene Stimme reagieren. Bei Netzwerkkameras als
Mikrofon und Lautsprecher kommt die eigene Ausgabe mit 1–2 s Verzögerung zurück
(C200: ~1,8 s), schwankend mit der Netzlast. Manche Geräte schalten ihr Mikrofon
während der Wiedergabe stumm.

Messung (`scripts/measure_aec.py`): WebRTC AEC3 dämpft bis ~0,4 s Verzögerung
32–40 dB, ab 0,6 s nur noch ~10 dB. Mit vorgeschalteter Bulk-Delay-Kompensation
bleiben es ~40 dB auch bei 1,8 s.

## Entscheidung

Mehrere unabhängige Schichten statt eines einzelnen Echo-Cancellers
([AUDIO.md](../AUDIO.md#schutzschichten-gegen-selbstgespräche)):

1. AEC3 (über livekit) mit Referenz, die um die per GCC-PHAT gemessene Verzögerung
   verschoben ist,
2. deterministisches Echo-Fenster mit Half-Duplex-Gate (Standard), Full Duplex
   nur nach gemessener Echodämpfung ≥ 18 dB,
3. Wakeword-Unterdrückung während der eigenen Wiedergabe,
4. Transkript-Echo-Filter gegen kürzlich Gesagtes,
5. Ignorieren des Wakeword-Nachlaufs, Inaktivitäts-Timer erst nach dem Echo-Fenster.

Die Kalibrierung misst die Verzögerung mit Sweeps und erkennt Geräte, die ihr
Mikrofon stummschalten.

## Alternativen

* **Nur AEC3 / Speex**: versagt bei Netzwerklatenz (Messung oben).
* **Immer Half Duplex ohne AEC**: sicher, aber kein Barge-in auf geeigneten Geräten.
* **Nur Transkript-Vergleich**: reagiert erst nach STT, also zu spät für das Wakeword.

## Konsequenzen

* Sicher auch auf Geräten mit unbekannter, schwankender Latenz.
* Barge-in nur auf Geräten mit echtem Full Duplex und gemessener Echodämpfung;
  mit der C200 nicht möglich.
