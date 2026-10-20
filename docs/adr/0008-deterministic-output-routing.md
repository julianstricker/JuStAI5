# 0008 – The output room is determined deterministically, never by the model

*[Deutsch](../de/adr/0008-deterministic-output-routing.md) · English*

**Status:** accepted

## Context

A question from the living room must not produce output in the kitchen. Language models
can mix up rooms, hallucinate tool parameters or be influenced by content (prompt
injection).

## Decision

A single `OutputRouter` decides on every output device by fixed rules
([ROOMS.md](../ROOMS.md#output-router)): room of the triggering endpoint; other rooms only
with an explicit cross-room request, permission and approval of the target room;
fallback devices only in the same room; offline means an error instead of moving
elsewhere. Sessions are bound to their endpoint, also across tool calls and provider
switches. Models and plugins at most hand over wishes that the router checks.

## Alternatives

* **Room as a tool parameter from the model**: error-prone and manipulable.

## Consequences

* Announcements in other rooms need a dedicated tool built for it
  (`conversation.announce`) and the permission `output.cross_room`.
* Refusals are logged with a reason.
