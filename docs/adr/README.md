# Architecture Decision Records

*[Deutsch](../de/adr/README.md) · English*

Short reasons for decisions that are hard to reverse. Format: context → decision →
alternatives → consequences.

| No. | Decision | Status |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Modular monolith with ports & adapters, Python | accepted |
| [0002](0002-plugin-isolation.md) | Two plugin runtimes: in process (trusted) and sandbox container | accepted |
| [0003](0003-postgres-pgvector.md) | PostgreSQL + pgvector as the only database | accepted |
| [0004](0004-go2rtc-media.md) | go2rtc as media server, streams only in memory | accepted |
| [0005](0005-echo-handling.md) | Multi-layer echo handling with own bulk delay compensation | accepted |
| [0006](0006-ai-router.md) | Own AI router with roles, fallback chains and privacy rules | accepted |
| [0007](0007-display-render-schema.md) | Displays only render typed components, success only after confirmation | accepted |
| [0008](0008-deterministic-output-routing.md) | The output room is determined deterministically, never by the model | accepted |
