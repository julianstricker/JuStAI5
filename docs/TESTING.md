# Tests und Teststatus

Stand: 2026-10-15. Dieses Dokument trennt klar zwischen **automatisiert getestet**,
**live gegen die laufende Docker-Instanz geprüft**, **mit echter Hardware geprüft**
und **nicht getestet**.

## Testsuiten

| Suite | Ort | Braucht | Ergebnis |
| --- | --- | --- | --- |
| Unit | `backend/tests/unit` | nichts | 100 bestanden |
| Audio mit echten Modellen | `backend/tests/audio` | Modelle (`JUSTAI_TEST_MODELS_DIR`) | 5 bestanden |
| Datenbank | `backend/tests/db` | PostgreSQL + pgvector (`JUSTAI_TEST_DATABASE_URL`) | 2 bestanden |
| End-to-End | `backend/tests/e2e` | laufende Instanz (`JUSTAI_E2E_URL`, `JUSTAI_E2E_PASSWORD`), Gemini | 5 bestanden |
| Beispiel-Plugin | `plugins/example-weather/tests` | nichts | 5 bestanden |
| Frontend | `frontend` | Node | `tsc` und ESLint fehlerfrei |
| Statische Analyse | ganzes Repo | – | ruff fehlerfrei, mypy `--strict` fehlerfrei (Backend, SDK, Sandbox) |

```bash
uv run pytest backend/tests/unit
uv run python scripts/fetch_models.py .models
JUSTAI_TEST_MODELS_DIR=$PWD/.models uv run pytest backend/tests/audio
JUSTAI_TEST_DATABASE_URL=postgresql+asyncpg://justai:pw@127.0.0.1:55432/justai_test uv run pytest backend/tests/db
JUSTAI_E2E_URL=http://localhost:8080 JUSTAI_E2E_PASSWORD=… uv run pytest backend/tests/e2e
uv run pytest plugins/example-weather/tests     # getrennt aufrufen (eigene pytest-Konfiguration)
cd frontend && npm run typecheck && npm run lint
```

Eine Test-Datenbank startet man z. B. mit
`docker run -d --name j5-testdb -e POSTGRES_USER=justai -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=justai_test -p 127.0.0.1:55432:5432 pgvector/pgvector:0.8.1-pg17`.

### Was die Suiten abdecken

* **Unit**: Event-Bus (Isolation, Duplikate, Hop-Limit), Output Router (alle
  Regeln), Tool-Executor (Rechte, Bestätigung, Timeout, Fehler), Display-Komponenten,
  Echo-Bausteine (Referenzpuffer, GCC-PHAT, Tracker), Wakeword-Arbitrierung (inkl.
  später Duplikate), Kalibrierung (Onset), KI-Router (Fallback, hängender Provider,
  Cooldown, Rollen-Autokonfiguration), Gesprächs-Zustandsautomat, Vision-Logik,
  Automationsmodell (inkl. Ergänzung fehlender Typen), PTZ-Regelung, statische
  Prüfung generierten Codes, Login-Drosselung, Discovery-Zusammenführung.
* **Audio**: Selbstgespräch mit echten Modellen in einem simulierten Raum
  ([AUDIO.md](AUDIO.md#getestet)).
* **DB**: dauerhaftes Vergessen im Gedächtnis ([MEMORY.md](MEMORY.md)).
* **E2E**: zwei simulierte Räume mit akustischem Echo, echte lokale STT/TTS/Wakeword,
  Gemini als LLM: Gespräch, Raum-Routing, kein Echo, Timeout, doppelte Wakewords,
  parallele Gespräche, Display-Kopplung mit Bestätigung, proaktive Automation.

**Hinweis zu E2E:** Die Suite nutzt das konfigurierte Cloud-LLM (Gemini). Am
2026-10-15 lieferte Gemini zeitweise gleichzeitig 429 (Kontingent erschöpft) für
`gemini-3.8-flash` und 503 (Überlastung) für den Fallback. In diesem Fall
antwortet der Assistent korrekt mit einer Fehlermeldung, und drei Tests schlugen
fehl. Die direkte Wiederholung bestand 5/5, obwohl im selben Zeitraum 8 weitere
429/503-Fehler über die Fallback-Kette abgefangen wurden. Für stabile Läufe ein
lokales LLM als zusätzlichen Fallback eintragen.

## Abnahmekriterien

Legende: ✅ nachgewiesen · 🟡 teilweise (was fehlt, steht dabei) · ⏳ offen.

| # | Kriterium | Status | Nachweis |
| --- | --- | --- | --- |
| 1 | Geräteerkennung | ✅ | Netzwerksuche findet die **Tapo C200** in 6 s, schlägt den Tapo-Treiber mit Modell „C200“ vor und erkennt sie als bereits angelegt. Eingerichtet zeigt sie die gemessenen Fähigkeiten (Video, Audio rein/raus, Snapshot). PTZ fehlt in der Liste, weil dafür das Cloud-Passwort fehlt. Das ist korrekt ermittelt, nicht geraten. Die C410 (Akku) war meist im Schlaf. |
| 2 | Raumzuordnung | ✅ | Echte Hardware: C200 (Kamera, Mikrofon, Lautsprecher) als Endpoint „Poolhaus Kamera“ im Raum Poolhaus. E2E: kombinierte Geräte pro Raum. |
| 3 | Sprachgespräch | ✅ | Echte Hardware: „Hey Jarvis“ an der C200 → Session → Antwort (Gemini Live) über den Lautsprecher der C200. E2E: Pipeline-Modus mit Antwort im selben Raum. |
| 4 | Keine Echo-Schleife | ✅ | Echte Hardware (C200): keine Selbstauslösung. Audio-Tests: Antwort enthält absichtlich das Wakeword → kein Wake, kein durchgelassenes Echo. E2E: keine Echo-Turns im Transkript. |
| 5 | Timeout | ✅ | Echte Hardware und E2E: Ende durch Inaktivität (`end_reason = inactivity`), danach ist wieder ein Wakeword nötig. |
| 6 | Keine falsche Raumausgabe | ✅ | E2E: Küchenlautsprecher bekommt kein einziges Frame, wenn im Wohnzimmer gefragt wird. Unit: Output-Router-Regeln. |
| 7 | Doppelte Wakewords | ✅ | E2E: dasselbe Wakeword in zwei Räumen (leiser in der Küche) → genau eine Session, im lauteren Raum. Unit: Arbitrierung inkl. verspäteter Duplikate. Mit zwei echten Mikrofonen nicht getestet (C410 nicht dauerhaft erreichbar). |
| 8 | Parallele Gespräche | ✅ | E2E: zwei Räume in getrennten Arbitrierungsgruppen fragen gleichzeitig, jeder bekommt seine Antwort. |
| 9 | Personenregistrierung | 🟡 | Vorstellen per Sprache (`identity.introduce`), Einwilligung mit Nachweis und Registrierung mit Qualitätsprüfung sind implementiert; `identity.register_face` verlangt eine ausdrückliche Bestätigung (Mechanismus unit-getestet). **Offen:** der Ablauf mit einer echten Person vor der Kamera. |
| 10 | Wiedererkennung | 🟡 | YuNet/SFace sind im Container geladen (Plugin `vision-opencv` läuft, Gesichtsprüfung in der Vision-Pipeline aktiv); Abstimmung über starke und schwache Treffer ist implementiert. **Offen:** Test mit echter Person. |
| 11 | PTZ-Tracking | 🟡 | Regelung unit-getestet (Totzone, Schrittweite, Rate, Zielbindung, Heimkehr, manuelle Übersteuerung). Echte C200: manuelles Schwenken funktioniert (rechts und zurück, per Bildvergleich bestätigt). **Offen:** Verfolgen einer Person. |
| 12 | Erinnerung | ✅ | Live: „Merk dir …“ in Session A, richtige Antwort in neuer Session B. Vergessen mit Rückfrage; dauerhaft (DB-Test und live). |
| 13 | Automation | 🟡 | Live: der Satz aus dem Kriterium (mit Personenname) legt eine korrekte Automation an. E2E: das Erkennungs-Event startet im richtigen Raum eine proaktive Begrüßung, `once` greift. **Offen:** Auslösung durch eine echte Gesichtserkennung (hängt an 9/10). |
| 14 | Display-Ausgabe | ✅ | E2E: Display im Wohnzimmer gekoppelt und gewählt. Echter Browser: Dashboard mit Kurs, Chart und Tabelle gerendert. |
| 15 | Display-Bestätigung | ✅ | E2E: das Tool wartet nachweislich auf das `ack`. Echter Browser: `ack` nach dem Zeichnen; Hintergrundseite meldet sofort „nicht sichtbar“, statt Erfolg vorzutäuschen. |
| 16 | Provider-Wechsel | ✅ | Live: Rolle `conversation` nur per Konfiguration auf einen neuen OpenAI-kompatiblen Endpoint umgestellt (Gemini über dessen OpenAI-Schnittstelle); die Antwort kam laut Nutzungsprotokoll von `oai:gemini-oai`. Keine Codeänderung. Fallback bei Überlastung (503/429) im Betrieb beobachtet. |
| 17 | Plugin-Installation | ✅ | Live: Zip hochgeladen → als `untrusted` in der Sandbox → Start ohne Rechte abgelehnt → Recht gewährt → aktiv, Tool erscheint, der Assistent nutzt es → deaktiviert → Tool verschwindet. |
| 18 | Tool-Entwicklung | ✅ | Live: „Kalenderwoche und Wochentag zu einem Datum“ → Spezifikation, Code, Tests → statische Prüfung → Tests in der Sandbox (2 bestanden) → Sicherheitsreview → Freigabe → der Assistent beantwortet „KW von 24.12.2026?“ korrekt mit dem neuen Tool → Deaktivierung. |
| 19 | Neustart | ✅ | `docker compose down` + `up`: Räume, Geräte, Endpoints, Plugins (aktiv), Personen, Erinnerungen, Automationen, KI- und Systemeinstellungen identisch. Zusätzlich Backup in ein getrenntes Projekt wiederhergestellt. |
| 20 | Fehlerbehandlung | ✅ | Live: die C410 ist meist offline, die C200 arbeitet unbeeinflusst. Neustarts einzelner Dienste: Medienserver → Kameras nach 2 s wieder da; Datenbank → API nach 3 s; Sandbox → Sandbox-Plugins nach 44 s automatisch neu gestartet. Ein fehlschlagendes Plugin (fehlende Rechte) wird `failed` markiert, alles andere läuft weiter. Gemini-Überlastung: Fallback statt Ausfall. Unit: Bus-Fehlerisolation, hängende Provider. |

### Was nur der Benutzer machen kann (offene Punkte)

* **9/10/13 mit echter Person**: vor die C200 stellen, „Ich bin …“ sagen, der
  Gesichtsregistrierung zustimmen. Später erneut vor die Kamera gehen; die
  Begrüßungs-Automation sollte dann auslösen.
* **11**: Im Gerät *Tapo C200* das Tapo-Cloud-Passwort oder ein Kamerakonto
  (Tapo-App → Kamera → Erweitert → Kamerakonto) eintragen, dann `ptz.follow`.
* **Barge-in mit echter Hardware**: Die C200 schaltet ihr Mikrofon während der
  Wiedergabe stumm, damit ist Unterbrechen physikalisch unmöglich. Für einen Test
  braucht es ein Gerät mit echtem Full-Duplex (z. B. USB-Freisprecheinrichtung).
* **Display auf einem Fernseher**: bisher nur im Desktop-Browser geprüft.

## Durch Live-Tests gefundene und behobene Fehler

Live-Prüfungen gegen die laufende Instanz haben Fehler gefunden, die keine
Unit-Tests abgedeckt hatten:

| Fehler | Behebung |
| --- | --- |
| Vergessenes kam durch die Gedächtnis-Extraktion der alten Session zurück | Grabsteine, DB-Test |
| Dashboard stürzte nach dem Login ab (`_cooldowns` als Rolle in `/api/ai/status`) | eigenes Feld, defensive UI |
| „Begrüße X das nächste Mal“: Modell ließ `type` weg und nutzte den Namen statt der ID; Antwort blieb leer | Typen ergänzen, Namen auflösen, Validierungsdetails an das Modell, Ersatzantwort |
| Sandbox-Testlauf je nach Zufalls-Verzeichnisname nicht importierbar | fester Pfad, `pythonpath` |
| Generierter Klassenname umbenannt, Tests fanden ihn nicht | Alias statt Umbenennen |
| Zweites Tool-Projekt mit gleichem Namen brach ab (Unique-Constraint) | eindeutige Plugin-IDs |
| Display: doppelte Achsenbeschriftung, „Gespräch“-Anzeige durch Text-Chats, unklare Fehler bei unsichtbarer Seite, kein Neuladen nach Updates | behoben, im Browser geprüft |
| Zeitzone der Einstellungen wurde von Automationen ignoriert; Schalter ohne Funktion in den Einstellungen | verdrahtet bzw. entfernt |
| Kein Schutz gegen Passwort-Raten, keine Security-Header | Drosselung, CSP u. a. |
| Discovery schlug für Tapo den ONVIF-Treiber vor (ohne Lautsprecher) | herstellerspezifischer Treiber hat Vorrang |
| Nach einem Neustart von go2rtc blieben alle Kameras unerreichbar (Streams nur im Speicher) | Watchdog stellt Streams wieder her; live: 2 s |

## Bekannte Instabilität

Die beiden Full-Duplex-Tests in `backend/tests/audio` sind nicht deterministisch,
weil Piper die Testsprache bei jedem Lauf leicht anders erzeugt. Im Mittel schlägt
etwa einer von drei bis sechs Läufen fehl: mal wird eine echte Unterbrechung zu spät
erkannt, mal (seltener seit der Toleranz um die geschätzte Echoverzögerung) Echo als
Unterbrechung gewertet. Half Duplex, der Modus der C200, ist davon nicht betroffen.
Offen: reproduzierbare Testsprache und eine Abstimmung über viele Varianten.

## Nicht automatisiert getestet

* Konsolidierung des Gedächtnisses (Zusammenführen, Widersprüche)
* Realtime-Modus (Gemini Live) nur manuell mit der C200, nicht in der E2E-Suite
* Plugin-Abhängigkeiten und Updates hochgeladener Plugins
* Retention-Job
* Lastverhalten mit vielen Kameras
