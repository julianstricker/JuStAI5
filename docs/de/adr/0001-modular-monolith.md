# 0001 – Modularer Monolith mit Ports & Adapters, Python

*Deutsch · [English](../../adr/0001-modular-monolith.md)*

**Status:** angenommen

## Kontext

JuStAI5 läuft auf einem einzelnen Heimserver. Audio braucht niedrige Latenz zwischen
Mikrofon, Echo-Behandlung, Wakeword und Gesprächslogik. Die Funktionsbereiche
(Audio, Vision, Gedächtnis, Automationen, Displays) sind eng gekoppelt, sollen aber
getrennt wartbar und später auslagerbar bleiben. Die benötigten Modelle (openWakeWord,
Silero, faster-whisper, Piper, fastembed, OpenCV) sind Python-first.

## Entscheidung

Ein Core-Prozess (Python 3.12, asyncio, FastAPI) mit klar getrennten Modulen. Module
hängen nur von Ports ab (Protokolle im SDK `justai_sdk.ports`); konkrete Hardware und
Provider sind Plugins. Ein Composition Root (`container.py`) verdrahtet alles
explizit. Kommunikation zwischen Fachmodulen über den Event-Bus und die Job-Queue,
deren Schnittstellen auch mit NATS/Redis bzw. getrennten Prozessen umsetzbar wären.
Rechenintensives (APM, VAD, ONNX-Inferenz) läuft in Thread-Pools außerhalb des
Event-Loops.

## Alternativen

* **Microservices pro Funktion**: mehr Betriebsaufwand, Netzwerk-Hops im
  Audio-Pfad, für einen Heimserver überdimensioniert.
* **Go/Rust-Core mit Python-Sidecars für ML**: bessere Latenzkontrolle, aber zwei
  Ökosysteme, IPC im kritischen Pfad, doppelte Modelle der Datentypen.
* **Node.js**: kaum ML-Bibliotheken.

## Konsequenzen

* Einfacher Betrieb (ein Container + Datenbank + Medienserver).
* Ein Fehler im Core-Prozess betrifft alles. Abgefedert durch Supervisor,
  Fehlerisolation im Bus und die Sandbox für fremden Code.
* Der GIL begrenzt CPU-Parallelität; die schweren Teile laufen in nativen
  Bibliotheken, die den GIL freigeben.
