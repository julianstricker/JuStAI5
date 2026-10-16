# KI-Provider, Rollen und Datenschutz

Code: `backend/src/justai/ai/`. Begründung: [ADR 0006](adr/0006-ai-router.md).

## Rollen

Jede Aufgabe ist eine **Rolle** mit einer Provider-Kette (erster Eintrag = primär,
danach Fallbacks), einer Lokalitätsregel und einem Timeout:

| Rolle | Wofür | Standard ohne Google-Key | Standard mit Google-Key |
| --- | --- | --- | --- |
| `conversation` | Antworten im Pipeline-Modus | – (zuordnen!) | gemini-3.8-flash → gemini-flash-lite-latest |
| `reasoning` | komplexe Fragen, Sicherheitsreview generierter Tools | – | wie oben |
| `vision` | „Was siehst du?“ | – | wie oben |
| `memory` | Extraktion/Konsolidierung von Erinnerungen | – | wie oben |
| `tool_generation` | neue Tools schreiben | – | wie oben |
| `background` | Zusammenfassungen u. a. | – | wie oben |
| `realtime` | Sprache-zu-Sprache (Gemini Live) | – | gemini-3.8-live |
| `stt` | Spracherkennung | faster-whisper `small` (lokal) | gleich |
| `tts` | Sprachausgabe | Piper (lokal) | gleich |
| `embedding` | Gedächtnis-Vektoren | fastembed multilingual (nur lokal) | gleich |

Wakeword und VAD laufen immer lokal und sind keine KI-Rollen.

**Ohne Google-Key und ohne lokales LLM kann der Assistent hören und sprechen,
aber nicht antworten.** Ein lokales LLM (z. B. Ollama, [DEPLOYMENT.md](DEPLOYMENT.md#lokale-ki-mit-ollama))
muss unter *KI-Provider → Modelle & Fallbacks* den Rollen zugeordnet werden. Das
geschieht nicht automatisch, weil Größe und Qualität lokaler Modelle stark variieren.

Sobald ein Google-Key eingetragen wird, füllt JuStAI5 **leere** Rollen mit den
Gemini-Standards. Vom Admin konfigurierte Rollen bleiben unverändert.

## Gesprächsmodus

* **Realtime** (Standard mit Google-Key): Audio geht direkt an Gemini Live,
  Antworten kommen als Audio zurück. Niedrigste Latenz, Unterbrechen im Modell.
  JuStAI5 schickt nur Audio, das das Echo-Gate passiert hat.
* **Pipeline**: lokale STT → LLM der Rolle `conversation` → lokale TTS. Jeder Schritt
  ist einzeln austauschbar und kann komplett lokal laufen. Sätze werden gestreamt
  (TTS beginnt mit dem ersten Satz).

Pro Endpoint kann der Modus überschrieben werden (`conversation.mode`).

### Spracherkennung

* **Sprachen**: Die konfigurierten Sprachen (Hauptsprache zuerst) gehen als erwartete
  Sprachen an die Erkennung, an Gemini Live als `language_codes`. Vorher erkannte die
  automatische Spracherkennung kurze Schnipsel oft als Spanisch oder Hindi. In der
  Pipeline wird ein Ergebnis in einer nicht erlaubten Sprache in der Gesprächssprache
  neu erkannt.
* **Vokabular**: Name des Assistenten, „Jarvis“, Räume und Namen von Personen und
  Tieren gehen als bevorzugte Begriffe an die Erkennung (Gemini `custom_vocabulary`,
  faster-whisper `initial_prompt`).
* **Pausen**: Gemini beendet den Benutzerbeitrag erst nach 1,0 s Stille mit
  unempfindlicher Ende-Erkennung (Plugin-Einstellung `vad_silence_ms`). Vorher wurde
  eine Denkpause von 0,7 s als Satzende gewertet. Der Assistent begann zu antworten,
  und bei Halbduplex-Kameras fiel der Rest des Satzes in die Echosperre.
* **Messung**: Jedes Gespräch speichert, wie viel sprachähnlicher Ton in die
  Echosperre fiel (`gated_speech_ms` im Gesprächsverlauf, Log „speech during echo
  gate“). Viel davon heißt: Die Sperre ist für dieses Gerät zu lang.

Prüfstand (`scripts`-unabhängig, im Container): deutsche Testsätze in
Kameraqualität (8 kHz, Raumrauschen) erkennt Gemini Live mit und ohne diese
Einstellungen zu ~99 % richtig. Die Fehler im echten Betrieb entstehen also vor allem
durch abgeschnittene oder zerteilte Sätze, nicht durch die Erkennung selbst.

## Fallback und Ausfälle

* Fällt der primäre Provider aus (Fehler, Timeout, kein erstes Token nach 25 s), wird
  der nächste der Kette genommen. Der fehlerhafte Provider pausiert danach kurz
  (Cooldown), damit nicht jede Anfrage erst auf den Fehler wartet. Pausierte Modelle
  zeigt das Dashboard orange.
* Jeder Fallback erzeugt `ai.provider.fallback`. Ein Wechsel von lokal zu Cloud steht
  **immer** im Audit-Log. Mit `announce_cloud_fallback` (Standard: an) sagt der
  Assistent im laufenden Gespräch (Pipeline-Modus) vor der Antwort, dass sie aus der
  Cloud kommt.
* Beobachtet im Betrieb: `gemini-3.8-flash` lieferte zeitweise 503 (Überlastung) und
  429 (Kontingent). Die Kette wechselte automatisch auf `gemini-flash-lite-latest`.

## Datenschutzregeln

*KI-Provider → Datenschutz & Kosten*:

| Schalter | Wirkung |
| --- | --- |
| `cloud_allowed` | global: Cloud-Provider überhaupt zulassen |
| `camera_images_to_cloud` | Kamerabilder an Cloud-Modelle |
| `conversation_audio_to_cloud` | Gesprächsaudio an Cloud (betrifft Realtime und Cloud-STT) |
| `personal_memories_to_cloud` | Erinnerungen und persönliche Kontexte an Cloud-Modelle |
| `announce_cloud_fallback` | Wechsel zur Cloud im Gespräch ansagen (protokolliert wird er immer) |
| pro Rolle `locality` | `local_only` / `prefer_local` / `any` |
| pro Raum `cloud_media_allowed` | Bilder/Audio aus diesem Raum nie in die Cloud |

Verbietet eine Regel alle Provider einer Kette, schlägt die Anfrage mit einem klaren
Grund fehl, statt die Regel zu umgehen.

## Kosten

Jeder Aufruf wird mit Tokens, Audiosekunden, Latenz und geschätzten Kosten
protokolliert (*KI-Provider → Nutzung*, Dashboard „KI-Kosten heute“). Tages- und
Monatslimits (`cost_limits.daily_usd`, `monthly_usd`) sperren Cloud-Provider beim
Erreichen; lokale laufen weiter. Die Kosten sind Schätzungen aus Token-Zahlen und
Listenpreisen, keine Abrechnung.

## Provider hinzufügen

Provider sind Plugins mit dem Recht `ai.provide` (Ports in `justai_sdk.ports.ai`:
Chat mit Tools und Streaming, Realtime, STT, TTS, Embeddings). Jeder
OpenAI-kompatible Server lässt sich ohne Code über das Plugin *OpenAI-kompatibel*
als weiterer Endpoint eintragen. Getestet wurde das mit der OpenAI-kompatiblen
Schnittstelle von Gemini: Die Rolle `conversation` wurde nur per Konfiguration
umgestellt ([TESTING.md](TESTING.md), Kriterium 16).
