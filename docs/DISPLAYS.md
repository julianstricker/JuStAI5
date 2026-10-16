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

## Geräte-App (Handy, Tablet, PC als Mikrofon, Lautsprecher, Kamera)

Unter `https://HOST:8443/app` läuft derselbe Client als installierbare Web-App
(PWA). Damit wird ein beliebiges Gerät zu einem vollwertigen JuStAI5-Gerät:

| Funktion | Weg |
| --- | --- |
| Mikrofon | `getUserMedia` mit Echo-Unterdrückung, Rauschunterdrückung und AGC des Browsers → AudioWorklet → PCM16, 16 kHz, 20-ms-Rahmen → Wakeword, Gespräche, Sprecherkennung |
| Lautsprecher | Sprachausgabe des Output Routers als PCM16, 16 kHz → AudioWorklet mit 60 ms Jitterpuffer |
| Kamera | vordere oder hintere Kamera, alle 500 ms ein JPEG (max. 960 px breit) → Vision, Gesichtserkennung, Snapshot, Live-Ansicht (MJPEG `GET /api/devices/{id}/live.mjpeg`) |
| Bildschirm | wie jedes Display (Darstellungen, Indikator „hört zu“) |

**Einrichten**

1. Admin-UI → *Einstellungen* → *Geräte-App*: Wird die Admin-UI über eine
   Adresse geöffnet, die noch nicht im HTTPS-Zertifikat steht (z. B. die
   LAN-IP des Servers), dort **Hinzufügen** klicken. Das Zertifikat wird neu
   ausgestellt und ohne Neustart geladen.
2. Das **JuStAI5-Zertifikat** (lokale Zertifizierungsstelle) auf dem Gerät
   installieren; die Schritte für Android, iPhone/iPad, Windows und macOS stehen
   in derselben Karte. Ohne Installation genügt meist, die Browser-Warnung zu
   bestätigen; als App installieren lässt sich die Seite dann nicht.
3. Auf dem Gerät `https://HOST:8443/app` öffnen, Mikrofon, Lautsprecher und
   Kamera (aus/vorne/hinten) wählen, *Starten*. Danach über das Browser-Menü
   „App installieren“ bzw. „Zum Home-Bildschirm“.
4. Den angezeigten Code unter *Displays & Geräte-App* freigeben und einen Raum
   wählen. Mit Mikrofon **und** Lautsprecher legt JuStAI5 im Raum automatisch
   einen Endpoint an (Rollen Mikrofon, Lautsprecher, ggf. Kamera und Display,
   Arbitrierungsgruppe des Raums). Werden Mikrofon und Lautsprecher erst später
   eingeschaltet, entsteht der Endpoint beim nächsten Verbinden.

Die Auswahl lässt sich über das Zahnrad oben rechts ändern; das Gerät meldet sich
dann mit den neuen Fähigkeiten an. Browser starten Audio erst nach einer
Berührung: Nach dem Öffnen erscheint deshalb „Tippen zum Starten“. Solange die App
offen ist, verhindert eine Wake-Lock-Sperre, dass der Bildschirm ausgeht. Läuft
die Seite im Hintergrund, schicken Browser keine Kamerabilder mehr, und mobile
Browser beenden oft auch das Mikrofon. Für ein dauerhaftes Raumgerät deshalb ein
Tablet mit Netzteil und App im Vordergrund verwenden.

Warum HTTPS: Browser erlauben Mikrofon, Kamera, Service Worker und die
Installation als App nur auf sicheren Ursprüngen (HTTPS oder `localhost`). Der
reine Display-Client unter `http://HOST:8080/display` braucht das nicht.

**Medien im WebSocket** (`display/media.py`): binäre Nachrichten mit einem
Typ-Byte am Anfang.

| Byte | Richtung | Inhalt |
| --- | --- | --- |
| `0x01` | Client → Core | Mikrofon, PCM16 LE, mono, 16 kHz |
| `0x02` | Client → Core | Kamerabild, JPEG (≤ 2 MB) |
| `0x11` | Core → Client | Lautsprecher, PCM16 LE, mono, 16 kHz |

Ein Browser-Gerät darf nur die Fähigkeiten `display.*`, `audio.input`,
`audio.output`, `video.input` und `camera.snapshot` anmelden. Kamerabilder, die
älter als 10 s sind, gelten als nicht verfügbar.

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
