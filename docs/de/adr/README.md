# Architecture Decision Records

*Deutsch · [English](../../adr/README.md)*

Kurze Begründungen für Entscheidungen, die schwer rückgängig zu machen sind.
Format: Kontext → Entscheidung → Alternativen → Konsequenzen.

| Nr. | Entscheidung | Status |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Modularer Monolith mit Ports & Adapters, Python | angenommen |
| [0002](0002-plugin-isolation.md) | Zwei Plugin-Laufzeiten: im Prozess (vertrauenswürdig) und Sandbox-Container | angenommen |
| [0003](0003-postgres-pgvector.md) | PostgreSQL + pgvector als einzige Datenbank | angenommen |
| [0004](0004-go2rtc-media.md) | go2rtc als Medienserver, Streams nur im Speicher | angenommen |
| [0005](0005-echo-handling.md) | Mehrschichtige Echo-Behandlung mit eigener Bulk-Delay-Kompensation | angenommen |
| [0006](0006-ai-router.md) | Eigener KI-Router mit Rollen, Fallback-Ketten und Privacy-Regeln | angenommen |
| [0007](0007-display-render-schema.md) | Displays rendern nur typisierte Komponenten, Erfolg erst nach Bestätigung | angenommen |
| [0008](0008-deterministic-output-routing.md) | Ausgaberaum wird deterministisch bestimmt, nie vom Modell | angenommen |
