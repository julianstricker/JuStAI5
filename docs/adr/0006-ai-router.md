# 0006 – Own AI router with roles, fallback chains and privacy rules

*[Deutsch](../de/adr/0006-ai-router.md) · English*

**Status:** accepted

## Context

Different tasks (conversation, vision, memory, tool generation, STT, TTS, embeddings,
realtime) need different models. Cloud models fail (observed: 503 overload, 429 quota) or
must not see certain data. Local models are slower or weaker.

## Decision

An `AIRouter` in the core resolves a **role** into an ordered provider chain and checks
before every call:

* the role's locality (`local_only`, `prefer_local`, `any`),
* global and room-related privacy rules (camera images, audio, personal memories),
* cost limits.

On errors: next provider, cooldown for the failing one (no waiting again on every
request), first-token timeout against hanging streams (25 s). A switch from local to
cloud is never silent (event + audit). Providers are plugins: new vendors need no change
to the core.

## Alternatives

* **LiteLLM or similar**: covers chat, but not realtime, local STT/TTS/wakeword, privacy
  rules per data kind and room.
* **A fixed provider**: simpler, but no failover and no local option.

## Consequences

* Switching providers is pure configuration (shown, [TESTING.md](../TESTING.md)).
* Tool calls and streaming have to be mapped to the common port model per provider
  plugin.
