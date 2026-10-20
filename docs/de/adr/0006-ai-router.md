# 0006 – Eigener KI-Router mit Rollen, Fallback-Ketten und Privacy-Regeln

*Deutsch · [English](../../adr/0006-ai-router.md)*

**Status:** angenommen

## Kontext

Verschiedene Aufgaben (Gespräch, Vision, Gedächtnis, Tool-Generierung, STT, TTS,
Embeddings, Realtime) brauchen unterschiedliche Modelle. Cloud-Modelle fallen aus
(beobachtet: 503 Überlastung, 429 Kontingent) oder dürfen bestimmte Daten nicht
sehen. Lokale Modelle sind langsamer oder schwächer.

## Entscheidung

Ein `AIRouter` im Core löst eine **Rolle** in eine geordnete Provider-Kette auf und
prüft vor jedem Aufruf:

* Lokalität der Rolle (`local_only`, `prefer_local`, `any`),
* globale und raumbezogene Privacy-Regeln (Kamerabilder, Audio, persönliche Erinnerungen),
* Kostenlimits.

Bei Fehlern: nächster Provider, Cooldown für den fehlerhaften (kein erneutes
Warten bei jeder Anfrage), First-Token-Timeout gegen hängende Streams (25 s). Ein
Wechsel von lokal zu Cloud wird nie still gemacht (Event + Audit). Provider sind
Plugins: Neue Anbieter brauchen keine Änderung am Core.

## Alternativen

* **LiteLLM o. ä.**: deckt Chat ab, aber nicht Realtime, lokale STT/TTS/Wakeword,
  Privacy-Regeln pro Datenart und Raum.
* **Fester Provider**: einfacher, aber kein Ausfallschutz und keine Lokal-Option.

## Konsequenzen

* Provider-Wechsel ist reine Konfiguration (nachgewiesen, [TESTING.md](../TESTING.md)).
* Tool-Aufrufe und Streaming müssen pro Provider-Plugin auf das gemeinsame
  Port-Modell abgebildet werden.
