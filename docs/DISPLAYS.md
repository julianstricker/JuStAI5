# Displays

Jeder Browser kann ein JuStAI5-Display sein: Fernseher mit Browser, Tablet, alter
Laptop. Code: `backend/src/justai/display/`, Client: `frontend/src/display/`,
Renderer: `frontend/src/shared/render/`.

## Koppeln

1. Auf dem Gerät `http://HOST:8080/display` öffnen. Der Client meldet sich per
   WebSocket (`/api/display/ws`) mit seinen Fähigkeiten und zeigt einen
   **6-stelligen Kopplungscode**.
2. Admin-UI → *Displays* → Code eingeben, Namen und Raum wählen.
3. Der Core legt ein Gerät mit dem Treiber `browser-display` an und schickt dem
   Client ein zufälliges Token. Der Client speichert es lokal; im Core liegt nur
   der Hash. Bei jedem neuen Verbinden genügt das Token.

Entfernen des Geräts in der Admin-UI macht das Token ungültig.

## Protokoll (WebSocket, JSON)

| Richtung | Nachricht |
| --- | --- |
| Client → Core | `hello {token?, user_agent, capabilities[]}` |
| Core → Client | `pairing {code}` · `paired {token, name}` · `ready {name, room, build}` · `error` |
| Core → Client | `show {presentation_id, document}` · `close {presentation_id}` · `indicator {listening, cloud}` |
| Client → Core | `ack {presentation_id, status: displayed\|failed, reason?: hidden\|render_error}` · `interaction {presentation_id, action, value}` |

## Lebenszyklus einer Darstellung

```
CREATED ─► SENT ─► DISPLAYED (ack vom Client) ─► UPDATED … ─► CLOSED
                └► FAILED (mit Grund)
```

Das Tool `display.show` meldet dem Assistenten erst Erfolg, wenn das Display den
Empfang **und das erfolgreiche Rendern** bestätigt hat: Der Client bestätigt erst,
nachdem React die Darstellung übernommen hat und der Browser gezeichnet hat.
Fehlgründe, die der Assistent nennen kann:

| Grund | Ursache |
| --- | --- |
| Display nicht verbunden | kein WebSocket |
| Display ist nicht sichtbar | Seite im Hintergrund / Bildschirm aus (`visibilityState = hidden`), sofortige Antwort |
| Inhalt konnte nicht dargestellt werden | Renderfehler einer Komponente (Error Boundary; das Display bleibt bedienbar) |
| keine Bestätigung vom Display | kein `ack` innerhalb von 8 s |

Optional schließt `duration_s` die Darstellung automatisch.

**Updates:** Der Core schickt mit `ready` eine Build-Kennung. Hat sich JuStAI5
seit dem Laden der Seite geändert, lädt der Client nach dem Wiederverbinden
automatisch neu. Displays wie Fernseher müssen also nach einem Update nicht von
Hand aktualisiert werden. Wiederverbindung mit Backoff bis 15 s.

## Sicheres Render-Schema

Ein Dokument ist ein Baum **typisierter Komponenten**. Es wird nie HTML oder
JavaScript aus dem Sprachmodell oder aus Plugins ausgeführt.

Eingebaute Komponenten (`display/components.py`):

| Komponente | Fähigkeit |
| --- | --- |
| `text`, `heading`, `markdown` (ohne HTML), `kv`, `stat`, `list`, `table`, `clock`, `notification` | `display.text` |
| `image` (nur `https://`, `/api/media/…` oder `data:image/…`) | `display.image` |
| `chart` (Linie/Balken, uPlot), `grid` | `display.dashboard` |
| `weather`, `stock-quote` | `display.text` |
| `camera` (Livestream, kurzlebige signierte URL, braucht `camera.read`) | `display.video` |
| `choice`, `button` (Interaktion → Event `display.interaction`) | `display.interactive` |
| `card`, `row`, `grid` (Container) | |

Grenzen: Tiefe ≤ 6, ≤ 200 Komponenten, Textlängen begrenzt, unbekannte Felder
werden abgelehnt. Fehler gehen mit Feldpfad an das Modell zurück.

**Plugin-Komponenten** (z. B. `weather-card` aus dem Beispiel-Plugin) sind
*Vorlagen*: Das Plugin liefert ein JSON-Schema für die Eigenschaften und eine
Vorlage aus eingebauten Komponenten. Der Core füllt die Vorlage aus; der Client
sieht nur eingebaute Komponenten.

## Routing

Displays werden wie Lautsprecher über den Output Router gewählt
([ROOMS.md](ROOMS.md#output-router)):

* Display des auslösenden Endpoints, sonst ein passendes Display im selben Raum.
* Kein passendes Display im Raum → Fehler, kein Ausweichen in andere Räume.
* `personal: true` (Kalender, Gesundheit, Finanzen) wird in Räumen mit
  `shared_space` nicht gezeigt.
* Andere Räume nur mit expliziter Cross-Room-Anfrage und Recht.

## Statusanzeige

Gekoppelte Displays zeigen dezent an, ob der Assistent im Raum gerade zuhört und
ob ein Cloud-Realtime-Modell aktiv ist (`indicator`).

## Tools

`display.show`, `display.update`, `display.close`, `display.list`.

## Getestet

* Unit (`tests/unit/test_display_components.py`): Validierung, unsichere URLs,
  Tiefe/Anzahl, Plugin-Vorlagen, Fähigkeitsableitung.
* E2E (`tests/e2e/test_simulated_rooms.py::test_display_pairing_presentation_ack_and_room_routing`):
  WebSocket-Client koppelt sich mit Code, wird dem Wohnzimmer zugeordnet, bekommt
  eine Darstellung; das Tool wartet nachweislich auf das `ack` und meldet erst
  danach `displayed`.
* Echter Browser (Chromium im eingebauten Browser der Entwicklungsumgebung):
  Kopplung per Code, Dashboard mit Überschrift, Kurs, Linienchart und Key-Value
  gerendert und bestätigt (ack nach 11 ms); im Hintergrund sofort „nicht
  sichtbar“; nach einem Core-Update automatisch neu geladen. Dabei gefunden und
  behoben: doppelte Achsenbeschriftung bei Kategorien, Gesprächsanzeige durch
  Text-Chats, fehlende Fehlgründe.
* Ein Test auf einem echten Fernseher steht aus.
