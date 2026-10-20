# Technology stack

*[Deutsch](de/TECH_STACK.md) · English*

All versions are pinned in `uv.lock`, `frontend/package-lock.json` and the Dockerfiles.
Decisions with alternatives are in the [ADRs](adr/).

## Backend

| Area | Choice | Reason / rejected alternatives |
| --- | --- | --- |
| Language | Python 3.12 | ML/audio ecosystem (onnxruntime, faster-whisper, openWakeWord, OpenCV). Go/Rust would have advantages for audio latency but hardly any ready models. The latency-critical parts (AEC, VAD, ONNX) run in native libraries anyway. |
| Package management | uv (workspace: backend, sdk, sandbox) | reproducible lockfile, fast; Poetry was slower and had no workspaces |
| Web | FastAPI + Uvicorn | async, Pydantic validation, OpenAPI, WebSockets |
| Database | PostgreSQL 17 + pgvector, SQLAlchemy 2 (async, asyncpg), Alembic | one database for relations, JSONB and vectors ([ADR 0003](adr/0003-postgres-pgvector.md)) |
| Logging | structlog (JSON), secret redaction | structured logs, no credentials in the log |
| Auth | argon2-cffi, PyJWT, Fernet (cryptography) | current password hashing; token by cookie (UI) or bearer (API) |
| Metrics | prometheus-client (`/api/metrics`), own telemetry (`/api/telemetry`) | |

## Media and audio

| Area | Choice | Notes |
| --- | --- | --- |
| Media server | go2rtc 1.9.14 | supports `tapo://` incl. backchannel, RTSP, ONVIF, HTTP snapshots, `ffmpeg:` sources ([ADR 0004](adr/0004-go2rtc-media.md)) |
| Audio input | ffmpeg (RTSP from go2rtc → 16 kHz s16le) | |
| Audio output | live WAV stream from the core; go2rtc pulls it as an `ffmpeg:` source into the camera backchannel | |
| AEC/NS/HPF | WebRTC Audio Processing (AEC3) via `livekit` | plus own bulk delay compensation ([AUDIO.md](AUDIO.md), [ADR 0005](adr/0005-echo-handling.md)) |
| VAD | Silero VAD (ONNX) | |
| Wakeword | openWakeWord 0.6.0 (ONNX) | models `hey_jarvis` and others; own models as a file |
| STT | faster-whisper (local) | cloud STT optional through AI providers |
| TTS | Piper (local) | voices configurable per language (English, German, Italian included) |

## AI

| Area | Choice |
| --- | --- |
| Cloud | Google Gemini via `google-genai` (chat, vision, live realtime); default model `gemini-3.8-flash`, fallback `gemini-flash-lite-latest`, realtime `gemini-3.8-live` |
| Local | any OpenAI-compatible endpoint (Ollama, llama.cpp server, vLLM) through the plugin `openai-compat` |
| Embeddings | fastembed `paraphrase-multilingual-MiniLM-L12-v2` (384 dim., local, multilingual) |
| Routing | own `AIRouter`: roles → provider chains, locality and privacy rules, cost limits, cooldown, first-token timeout ([ADR 0006](adr/0006-ai-router.md)) |

## Vision

| Area | Choice |
| --- | --- |
| Object detection | YOLOX (ONNX, OpenCV Zoo, `object_detection_yolox_2022nov`) via onnxruntime |
| Face recognition | YuNet (detection) + SFace (embedding) from the OpenCV Zoo |
| Tracking | own IoU tracker |
| State detectors | reference image comparison (no training) |

All models are downloaded during the image build by `scripts/fetch_models.py` with
SHA-256 check and live in the image under `/models`.

## Frontend

React 19, Mantine 8, TanStack Query 5, React Router 7, Vite 7, TypeScript 5.9, uPlot
(charts), react-markdown (markdown component without HTML). Admin UI, display client and
device app are built from one code base and served by the core. Translations: own typed
catalogue (`src/shared/i18n`, English/German/Italian), no runtime library.

## Sandbox

Own image, Python 3.12, JSON-RPC host per plugin as a subprocess with rlimits (memory,
CPU, files), container read-only, `cap_drop: ALL`, `no-new-privileges`, internal network.
Network access of plugins goes exclusively through the plugin gateway of the core
(allowlist from the manifest). [ADR 0002](adr/0002-plugin-isolation.md).
