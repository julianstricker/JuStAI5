# Events und Automationen

## Event-System

Code: `backend/src/justai/events/`.

* **Typisiert und versioniert**: Jeder Event-Typ steht im Katalog
  (`events/catalog.py`, abrufbar unter `GET /api/events/catalog`) mit
  Beschreibung, Dauerhaftigkeit, Priorität, Sensibilität und optional einem
  Payload-Schema. Plugins registrieren eigene Typen nur unter `plugin.<id>.*`.
* **Felder**: `id` (UUIDv7), `type`, `ts`, `source` (Art, Raum, Gerät, Endpoint,
  Session, Plugin), `payload`, `correlation_id`, `caused_by`, `hop`, `dedup_key`,
  `priority`, `sensitivity`, `durability`.
* **Bus** (`events/bus.py`): Jeder Abonnent hat eine eigene begrenzte Queue und
  einen eigenen Worker. Ein langsamer oder fehlerhafter Abonnent blockiert
  niemanden. Duplikate (gleiche ID oder gleicher `dedup_key` innerhalb der TTL)
  werden verworfen.
* **Persistenz**: Dauerhafte Events speichert der `EventStore` in PostgreSQL vor
  der Zustellung (Aufbewahrung konfigurierbar, Standard 90 Tage).
* **Schleifenschutz**: Folgeevents erben `hop + 1` und `caused_by`. Über dem
  globalen Hop-Limit werden Events gestoppt und `system.event_loop_detected`
  gemeldet.
* Anzeige: Admin-UI → *Diagnose* (Live-Strom über WebSocket, Filter, Historie).
  Manuelles Auslösen zum Testen: `POST /api/events`.

## Automationen

Code: `backend/src/justai/automation/`. Eine Automation ist ein validiertes
JSON-Dokument (Modell: `automation/model.py`, Schema:
`GET /api/automations/schema`):

```json
{
  "trigger":    {"type": "event", "event": "vision.person.recognized",
                 "match": {"person_id": "person-…"}},
  "conditions": [{"type": "time_window", "start": "07:00", "end": "22:00"},
                 {"type": "no_active_conversation", "room": "trigger"}],
  "actions":    [{"type": "assistant.invoke", "instruction": "Begrüße die Person mit Namen.",
                  "room": "trigger"}],
  "options":    {"once": true, "cooldown_s": 0, "max_runs_per_hour": 20}
}
```

### Auslöser

| Typ | Felder |
| --- | --- |
| `event` | `event` (Wildcards erlaubt, z. B. `vision.object.*`), `match` (Payload-Felder müssen gleich sein), optional `room_id` |
| `cron` | 5 Felder: Minute Stunde Tag Monat Wochentag (0 = Sonntag) |
| `interval` | `seconds` (≥ 30) |
| `at` | Zeitpunkt (einmalig) |

Zeitangaben gelten in der Zeitzone aus *Einstellungen → System* (Standard
`Europe/Rome`).

### Bedingungen

`time_window` (Start, Ende, optional Wochentage), `payload` (Pfad, Operator
`== != > >= < <= in contains`, Wert), `no_active_conversation` (Raum),
`visual_state` (Zustandsdetektor ist in Zustand X).

### Aktionen

| Typ | Wirkung |
| --- | --- |
| `assistant.invoke` | startet eine **proaktive Gesprächssession ohne Wakeword** im Raum (`trigger` = Raum des auslösenden Events). Bevorzugt wird der Endpoint, dessen Kamera das Event ausgelöst hat. Die Anweisung geht an das Modell, und mit `start_conversation` hört die Session danach zu. |
| `speak` | Text im Raum ausgeben (über den Output Router) |
| `display.show` | Dokument auf dem Display im Raum zeigen |
| `tool` | Tool mit Argumenten aufrufen (Rechte der Automation) |
| `event.emit` | eigenes Event veröffentlichen |
| `wait` | warten (max. 1 h) |

### Optionen

`once` (nach dem ersten erfolgreichen Lauf deaktivieren; erneutes Aktivieren macht
die Regel wieder scharf), `cooldown_s`, `priority`
(0–3), `max_retries`, `expires_at`, `max_runs_per_hour`.

### Ausführung

```
Event ─► Trigger-Match (im Speicher) ─► Bedingungen
      ─► Schutz: eigene Events ignorieren · Kettenlänge ≤ 4 · once · cooldown · Runs/Stunde
      ─► Job in der Postgres-Queue (überlebt Neustarts, Wiederholungen mit Backoff)
      ─► Aktionen nacheinander ─► Lauf-Protokoll (automation_runs) ─► automation.run.*-Events
```

Ausgaben einer Automation unterliegen denselben Regeln wie Gespräche: Der Raum
kommt aus dem Trigger oder der Konfiguration, nie aus einer Modellausgabe.

### Anlegen

* **Im Gespräch**: Tool `automation.create`, z. B. „Wenn du Anna das nächste Mal
  siehst, begrüße sie mit Namen.“ Regeln auf `vision.person.recognized` bekommen
  automatisch die Bedingung `away_s >= 600` (mindestens 10 Minuten nicht gesehen),
  sonst würde die Begrüßung irgendwann auslösen, während die Person noch vor der
  Kamera sitzt (so im Live-Test passiert). Andere Abstände kann das Modell setzen
  („wenn ich heimkomme“ ≥ 3600, „jedes Mal“ ≥ 0). Das Tool akzeptiert Personennamen (wird zur
  Personen-ID aufgelöst), `self` (die sprechende, erkannte Person) und `here` (der
  aktuelle Raum). Fehlende `type`-Angaben werden aus den Feldern ergänzt.
  Validierungsfehler gehen mit Details an das Modell zurück, damit es korrigieren
  kann.
* **Admin-UI** → *Automationen*: Liste, JSON-Editor mit Schema-Validierung,
  Aktivieren/Deaktivieren, *Jetzt ausführen*, Lauf-Historie.
* Tools für den Assistenten: `automation.list`, `automation.set_enabled`,
  `automation.delete` (mit Bestätigung).

## Getestet

* Unit (`tests/unit/test_automation_model.py`): gültige/ungültige Definitionen,
  Ergänzung fehlender Typen, Cron-Matching, Vergleichsoperatoren.
* E2E (`tests/e2e/test_simulated_rooms.py::test_automation_greets_recognised_person_in_the_trigger_room`):
  Ein (eingespeistes) `vision.person.recognized` im Wohnzimmer startet dort eine
  proaktive Session mit Begrüßung, die Küche bleibt still, `once` deaktiviert die
  Automation danach.
* Manuell gegen die Docker-Instanz: „Wenn du Anna Test das nächste Mal siehst,
  begrüße sie bitte mit ihrem Namen.“ legt eine korrekte Automation an
  (Event-Trigger mit aufgelöster Personen-ID, `assistant.invoke`, `once`).
* Die vollständige Kette mit **echter** Gesichtserkennung an der Kamera ist noch
  nicht getestet ([VISION.md](VISION.md#getestet)).
