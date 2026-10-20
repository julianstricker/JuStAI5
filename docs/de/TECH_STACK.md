# Technologie-Stack

*Deutsch · [English](../TECH_STACK.md)*

Alle Versionen sind in `uv.lock`, `frontend/package-lock.json` und den Dockerfiles
gepinnt. Entscheidungen mit Alternativen stehen in den [ADRs](adr/).

## Backend

| Bereich | Wahl | Begründung / verworfene Alternativen |
| --- | --- | --- |
| Sprache | Python 3.12 | ML-/Audio-Ökosystem (onnxruntime, faster-whisper, openWakeWord, OpenCV). Go/Rust hätten bei Audio-Latenz Vorteile, aber kaum fertige Modelle. Die latenzkritischen Teile (AEC, VAD, ONNX) laufen ohnehin in nativen Bibliotheken. |
| Paketverwaltung | uv (Workspace: backend, sdk, sandbox) | reproduzierbares Lockfile, schnell; Poetry war langsamer und ohne Workspaces |
| Web | FastAPI + Uvicorn | async, Pydantic-Validierung, OpenAPI, WebSockets |
| Datenbank | PostgreSQL 17 + pgvector, SQLAlchemy 2 (async, asyncpg), Alembic | eine Datenbank für Relationen, JSONB und Vektoren ([ADR 0003](adr/0003-postgres-pgvector.md)) |
| Logging | structlog (JSON), Secret-Redaktion | strukturierte Logs, keine Zugangsdaten im Log |
| Auth | argon2-cffi, PyJWT, Fernet (cryptography) | Passwort-Hashing nach aktuellem Stand; Token per Cookie (UI) oder Bearer (API) |
| Metriken | prometheus-client (`/api/metrics`), eigene Telemetrie (`/api/telemetry`) | |

## Medien und Audio

| Bereich | Wahl | Hinweise |
| --- | --- | --- |
| Medienserver | go2rtc 1.9.14 | unterstützt `tapo://` inkl. Backchannel, RTSP, ONVIF, HTTP-Snapshots, `ffmpeg:`-Quellen ([ADR 0004](adr/0004-go2rtc-media.md)) |
| Audio-Eingang | ffmpeg (RTSP von go2rtc → 16 kHz s16le) | |
| Audio-Ausgang | Live-WAV-Stream vom Core, go2rtc zieht ihn als `ffmpeg:`-Quelle in den Kamera-Backchannel | |
| AEC/NS/HPF | WebRTC Audio Processing (AEC3) über `livekit` | zusätzlich eigene Bulk-Delay-Kompensation ([AUDIO.md](AUDIO.md), [ADR 0005](adr/0005-echo-handling.md)) |
| VAD | Silero VAD (ONNX) | |
| Wakeword | openWakeWord 0.6.0 (ONNX) | Modelle `hey_jarvis` u. a.; eigene Modelle als Datei |
| STT | faster-whisper (lokal) | Cloud-STT optional über KI-Provider |
| TTS | Piper (lokal) | Stimmen pro Sprache konfigurierbar |

## KI

| Bereich | Wahl |
| --- | --- |
| Cloud | Google Gemini über `google-genai` (Chat, Vision, Live-Realtime); Standardmodell `gemini-3.8-flash`, Fallback `gemini-flash-lite-latest`, Realtime `gemini-3.8-live` |
| Lokal | jeder OpenAI-kompatible Endpoint (Ollama, llama.cpp-Server, vLLM) über das Plugin `openai-compat` |
| Embeddings | fastembed `paraphrase-multilingual-MiniLM-L12-v2` (384 Dim., lokal, mehrsprachig) |
| Routing | eigener `AIRouter`: Rollen → Provider-Ketten, Lokalitäts- und Privacy-Regeln, Kostenlimits, Cooldown, First-Token-Timeout ([ADR 0006](adr/0006-ai-router.md)) |

## Vision

| Bereich | Wahl |
| --- | --- |
| Objekterkennung | YOLOX (ONNX, OpenCV Zoo, `object_detection_yolox_2022nov`) über onnxruntime |
| Gesichtserkennung | YuNet (Detektion) + SFace (Embedding) aus dem OpenCV Zoo |
| Tracking | eigener IoU-Tracker |
| Zustandsdetektoren | Referenzbild-Vergleich (ohne Training) |

Alle Modelle werden beim Image-Build von `scripts/fetch_models.py` mit SHA-256-Prüfung
geladen und liegen im Image unter `/models`.

## Frontend

React 19, Mantine 8, TanStack Query 5, React Router 7, Vite 7, TypeScript 5.9,
uPlot (Diagramme), react-markdown (Markdown-Komponente ohne HTML). Admin-UI und
Display-Client werden aus einer Codebasis gebaut und vom Core ausgeliefert.

## Sandbox

Eigenes Image, Python 3.12, JSON-RPC-Host pro Plugin als Unterprozess mit
rlimits (Speicher, CPU, Dateien), Container read-only, `cap_drop: ALL`,
`no-new-privileges`, internes Netz. Netzwerkzugriffe von Plugins laufen
ausschließlich über das Plugin-Gateway des Core (Allowlist aus dem Manifest).
[ADR 0002](adr/0002-plugin-isolation.md).
