# 0001 – Modular monolith with ports & adapters, Python

*[Deutsch](../de/adr/0001-modular-monolith.md) · English*

**Status:** accepted

## Context

JuStAI5 runs on a single home server. Audio needs low latency between microphone, echo
handling, wakeword and conversation logic. The functional areas (audio, vision, memory,
automations, displays) are closely coupled but should stay separately maintainable and
movable later. The required models (openWakeWord, Silero, faster-whisper, Piper,
fastembed, OpenCV) are Python-first.

## Decision

One core process (Python 3.12, asyncio, FastAPI) with clearly separated modules. Modules
only depend on ports (protocols in the SDK `justai_sdk.ports`); concrete hardware and
providers are plugins. A composition root (`container.py`) wires everything explicitly.
Communication between domain modules goes through the event bus and the job queue, whose
interfaces could also be implemented with NATS/Redis or separate processes.
Compute-intensive work (APM, VAD, ONNX inference) runs in thread pools outside the event
loop.

## Alternatives

* **Microservices per function**: more operational effort, network hops in the audio
  path, oversized for a home server.
* **Go/Rust core with Python sidecars for ML**: better latency control, but two
  ecosystems, IPC in the critical path, duplicate models of the data types.
* **Node.js**: hardly any ML libraries.

## Consequences

* Simple operation (one container + database + media server).
* An error in the core process affects everything. Cushioned by the supervisor, error
  isolation in the bus and the sandbox for foreign code.
* The GIL limits CPU parallelism; the heavy parts run in native libraries that release the
  GIL.
