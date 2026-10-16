# Sicherheit und Datenschutz

JuStAI5 hat Zugriff auf Kameras, Mikrofone und persönliche Informationen. Die
Grundsätze: lokal zuerst, minimale Rechte, nichts Stilles (Cloud-Fallbacks und
sicherheitsrelevante Aktionen werden protokolliert), deterministische Regeln statt
Modellentscheidungen bei Ausgabe und Rechten.

## Netzwerk und Container

| Maßnahme | Umsetzung |
| --- | --- |
| Nur ein Port nach außen | `core:8080` (UI/API). Postgres, go2rtc und Sandbox sind von außen nicht erreichbar. |
| Datenbanknetz intern | `db` ist `internal: true` |
| Sandbox ohne Netz | `sandbox` ist `internal: true`: kein Internet, kein LAN, nur der Core. Geprüft: Postgres, go2rtc, LAN und Internet sind aus der Sandbox nicht erreichbar. |
| Sandbox gehärtet | read-only Root-FS, `tmpfs /tmp`, `cap_drop: ALL`, `no-new-privileges`, pids/mem/cpu-Limits, eigener UID (10002), rlimits pro Plugin-Prozess |
| Core ohne Root | UID 10001 |
| go2rtc ohne Zugangsdaten auf Platte | Streams werden zur Laufzeit im Speicher angelegt (`PATCH /api/streams`), `go2rtc.yaml` ist read-only gemountet und enthält keine Kameras |
| Talkback-Endpunkt | `/internal/talkback/<zufälliges Token>.wav`, Token pro Lautsprecher, nur für go2rtc gedacht |

Für den Zugriff aus dem Internet: JuStAI5 nicht direkt freigeben, sondern über VPN
(z. B. WireGuard) oder einen Reverse-Proxy mit TLS. Dann `JUSTAI_PUBLIC_URL` auf
`https://…` setzen, damit Cookies als `Secure` markiert werden.

## Authentifizierung (Admin-UI/API)

* Passwörter: Argon2id (argon2-cffi), Rehash bei geänderten Parametern;
  Mindestlänge 8.
* Initiales Admin-Passwort: zufällig erzeugt, nur in
  `/data/initial_admin_password.txt` und einmal im Log (oder per
  `JUSTAI_ADMIN_PASSWORD` gesetzt).
* Sitzungen: JWT (HS256, Schlüssel aus dem Master-Key abgeleitet), als
  `HttpOnly`-, `SameSite=Strict`-Cookie oder als Bearer-Token. *Überall abmelden*
  erhöht die Token-Version des Benutzers und macht alle alten Tokens ungültig.
* CSRF: Schreibende Anfragen brauchen den Header `x-justai: 1`. Ein fremdes
  Formular kann ihn nicht ohne CORS-Preflight setzen; CORS ist standardmäßig aus.
* **Brute-Force-Schutz**: Nach 5 Fehlversuchen in 15 Minuten wird pro Benutzername
  **und** pro Client-Adresse gesperrt: zuerst 30 s, dann verdoppelt bis 15 min.
  Fehlversuche stehen im Audit-Log (`auth.login_failed`).
* Security-Header für alle Antworten: Content-Security-Policy (Skripte nur vom
  eigenen Server, keine Fremd-Frames), `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

## Rollen und Rechte

Rollen `admin`, `resident`, `guest` (`auth/rbac.py`), Rechtevokabular aus dem SDK.

**Gesprochene Gespräche** sind nicht authentifiziert. Eine Session bekommt die
`default_role` ihres Endpoints (Standard `resident`; an öffentlich zugänglichen
Orten auf `guest` setzen). Eine erkannte Person kann die Rechte höchstens auf
`resident` anheben. **Biometrie gewährt nie administrative Rechte**:
`system.manage`, `devices.manage`, `identity.manage`, `devices.provide` und
`ai.provide` sind in Gesprächen grundsätzlich ausgeschlossen.

**Tools** deklarieren benötigte Rechte und Nebenwirkungen. Folgenreiche Aktionen
(`requires_confirmation`) führt der Assistent erst nach einer ausdrücklichen
Bestätigung aus: Gedächtnis löschen, Automation löschen, Gesicht registrieren u. a.
Die Bestätigung ist an Session und Argumente gebunden, muss in einem *späteren*
Benutzerbeitrag kommen (das Modell kann sich nicht selbst bestätigen) und läuft ab. Jede
Tool-Ausführung wird protokolliert (Parameter redigiert).

## Geheimnisse

* `secrets-init` erzeugt beim ersten Start DB-Passwort, Master-Key und
  Sandbox-Token im Volume `secrets` (Master-Key nur für den Core lesbar, 0400).
* Plugin-Secrets (`secret_fields`) und Gerätezugangsdaten werden mit Fernet
  verschlüsselt in der Datenbank gespeichert (Schlüssel aus dem Master-Key). Die
  API liefert sie nie zurück, die UI zeigt nur „gesetzt“.
* Logs: structlog-Prozessor und `common/redact.py` entfernen bekannte
  Schlüsselnamen (password, token, api_key, …) und Zugangsdaten in URLs
  (`rtsp://user:pass@` → `rtsp://***@`).
* Backups enthalten Secrets und werden mit `chmod 600` geschrieben
  ([DEPLOYMENT.md](DEPLOYMENT.md#backup-und-wiederherstellung)).

## Plugins und generierter Code

* Hochgeladene Plugins sind immer `untrusted`, laufen in der Sandbox und starten
  ohne Rechte, bis ein Admin sie gewährt ([PLUGINS.md](PLUGINS.md#berechtigungen)).
* Netzwerkzugriff nur über das Core-Gateway auf die Hosts der Allowlist; private,
  Loopback-, Link-Local- und Multicast-Adressen sind gesperrt (auch nach
  DNS-Auflösung).
* **Selbst entwickelte Tools** (`tools.develop`): Code wird statisch geprüft
  (verbotene Module wie `os`, `subprocess`, `socket`, `importlib`; verbotene
  Aufrufe wie `eval`, `exec`, `open`, `getattr`), in der Sandbox getestet,
  dann von einem Modell auf Sicherheit geprüft und **erst nach Freigabe durch einen
  Admin** aktiviert. Er wird immer ein `untrusted`-Plugin mit eingeschränkter
  Rechteliste. Der Core selbst wird nie verändert. Versionen, Rollback und
  Deaktivierung in der Admin-UI unter *Tools → Entwicklung*.

## Datenschutz

| Thema | Umsetzung |
| --- | --- |
| Cloud-KI | global abschaltbar; pro Rolle `local_only`/`prefer_local`/`any`; getrennte Schalter für Kamerabilder, Gesprächsaudio und persönliche Erinnerungen; pro Raum `cloud_media_allowed`. Ein Wechsel von lokal zu Cloud wird nie still gemacht: Event `ai.provider.fallback` und Audit-Eintrag. |
| Sichtbarkeit | Displays zeigen, ob im Raum gerade zugehört oder gesprochen wird und ob ein Cloud-Realtime-Modell aktiv ist. Die Admin-UI zeigt das für alle Räume. |
| Kameras | Privatsphärenzonen werden vor jeder Analyse geschwärzt; Vision pro Raum abschaltbar; keine Speicherung von Kamerabildern zu Sichtungen |
| Biometrie | Gesicht und Stimme nur mit dokumentierter Einwilligung (getrennt je Merkmal); Widerruf löscht alle Merkmale dieser Art; Export möglich; Ähnlichkeitswerte werden nie als Wahrscheinlichkeit dargestellt ([VISION.md](VISION.md#stimmprofile)) |
| Gedächtnis | Herkunft sichtbar, private Erinnerungen nur für ihre Person, Vergessen dauerhaft ([MEMORY.md](MEMORY.md)) |
| Audio | Es wird kein Audio gespeichert. Ausnahme: ausdrücklich angeforderte Diagnoseaufnahmen (max. 30 s, Download) |
| Stimmvergleich | Für „Gespräch fortsetzen?“ wird aus Wakeword und Sprache eines Gesprächs ein Stimm-Fingerabdruck berechnet: nur im Arbeitsspeicher, keiner Person zugeordnet, nach dem Fortsetzungsfenster verworfen; die Sprachdaten selbst werden direkt nach der Berechnung gelöscht. Abschaltbar pro Endpoint (`speaker_check`). |
| Personenbezogene Ausgaben | nicht auf Displays in gemeinsam genutzten Räumen |

### Aufbewahrung

Einstellbar unter *Einstellungen → Aufbewahrung*; ein täglicher Job löscht ältere
Daten:

| Daten | Standard |
| --- | --- |
| dauerhafte Events | 90 Tage |
| Gesprächstranskripte | 365 Tage |
| Sichtungen | 60 Tage |
| Tool-Protokoll | 90 Tage |
| Display-Darstellungen | 30 Tage |
| erledigte Jobs | 14 Tage |

## Audit-Log

`GET /api/audit` und Admin-UI → *Diagnose → Audit-Log*: Anmeldungen und
Fehlversuche, Änderungen an Benutzern, Plugins (Installation, Rechte), Einstellungen,
Geräten, Automationen, Gedächtnis, Biometrie, Cloud-Fallbacks, Netzwerksuche,
PTZ-Tracking, Display-Darstellungen.

## Bekannte Grenzen

* Gesprochene Befehle sind nicht authentifiziert. Wer im Raum spricht, hat die
  Rechte des Endpoints. Für sensible Räume `default_role: guest` wählen.
* Gesichtserkennung lässt sich mit Fotos täuschen (keine Lebenderkennung), Stimmerkennung
  mit Aufnahmen. Deshalb dienen beide nur der Personalisierung, nie der Autorisierung.
* Die Sandbox ist eine Container-Isolation mit rlimits, keine VM. Für Code
  unbekannter Herkunft ist das eine Schutzschicht, kein Freibrief.
* Der Brute-Force-Schutz hält seinen Zustand im Speicher; ein Neustart setzt ihn zurück.
