# Installation Schritt für Schritt

*Deutsch · [English](../INSTALLATION.md)*

Diese Anleitung führt von einem leeren Rechner bis zum ersten Gespräch mit dem
Assistenten. Sie braucht keine Programmierkenntnisse, nur ein paar Befehle im
Terminal, die man kopieren kann. Wer schon Docker hat, beginnt bei
[Schritt 2](#schritt-2-justai5-herunterladen).

## Der schnellste Weg: ein Befehl

Auf einem Linux-Rechner (x86_64) im Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/julianstricker/JuStAI5/main/scripts/install.sh | bash
```

Das Installationsskript
* prüft den Rechner und installiert Docker, falls es fehlt (fragt vorher),
* lädt JuStAI5 in den Ordner `JuStAI5`,
* fragt nach dem Google-API-Key ([Schritt 3](#schritt-3-den-assistenten-zum-sprechen-bringen-google-api-key)
  erklärt, wo es ihn gibt; leer lassen geht auch) und einem Admin-Passwort,
* erkennt die Adresse des Rechners im Heimnetz (für das HTTPS-Zertifikat und die
  Kamerasuche) und weicht auf freie Ports aus, wenn 8080/8443 belegt sind,
* baut und startet alles und zeigt am Ende Adresse, Benutzer und Passwort.

Es spricht Deutsch, Englisch oder Italienisch, je nach Systemsprache
(`JUSTAI_INSTALL_LANG=de`, `en` oder `it` zum Festlegen). Ein erneuter Aufruf auf einem
installierten System behält Einstellungen, Ports und Passwort und baut nur neu.

Danach weiter mit [Schritt 6](#schritt-6-ein-handy-oder-tablet-als-mikrofon-und-lautsprecher)
(erstes Gespräch). Wurde Docker eben erst installiert, einmal ab- und wieder
anmelden. Wer lieber jeden Schritt selbst macht, folgt der Anleitung unten.

Was am Ende läuft: ein Assistent, der auf „Hey Jarvis“ hört, über Kameras sieht,
sich Dinge merkt und im selben Raum antwortet, in dem er angesprochen wurde.
Beispiele, was man ihn fragen kann: [BEISPIELE.md](BEISPIELE.md).

## Was du brauchst

| | Mindestens | Empfohlen |
| --- | --- | --- |
| Rechner | PC, Mini-PC (z. B. Intel NUC) oder Server mit **x86_64**-Prozessor, der dauerhaft läuft | 4 Kerne |
| Betriebssystem | Linux (getestet: Ubuntu/Debian) | Ubuntu 24.04 LTS |
| Arbeitsspeicher | 4 GB (JuStAI5 belegt gemessen ca. 1,7 GB) | 8 GB |
| Festplatte | 15 GB frei (Programm ca. 3 GB plus Datenbank) | 30 GB |
| Netzwerk | im selben Heimnetz wie Kameras, Handys und Tablets | Netzwerkkabel |
| Sprachmodell | ein kostenloser Google-API-Key ([Schritt 3](#schritt-3-den-assistenten-zum-sprechen-bringen-google-api-key)) **oder** ein lokales Modell (Ollama) | |

Eine Grafikkarte ist nicht nötig. Raspberry Pi und andere ARM-Rechner werden
nicht unterstützt. Windows und macOS (Docker Desktop) sind nicht getestet.

**Zum Sprechen und Hören** reicht für den Anfang ein Handy, Tablet oder Laptop mit
der [Geräte-App](#schritt-6-ein-handy-oder-tablet-als-mikrofon-und-lautsprecher).
Kameras mit Mikrofon und Lautsprecher (getestet: **TP-Link Tapo C200**, auch
schwenkbar) machen ganze Räume zu Gesprächsorten.

## Schritt 1: Docker installieren

Docker ist das Programm, in dem JuStAI5 läuft. Im Terminal (Ubuntu/Debian):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo usermod -aG docker $USER
```

Danach **einmal abmelden und wieder anmelden** (oder den Rechner neu starten),
damit der eigene Benutzer Docker verwenden darf. Prüfen:

```bash
docker compose version
```

Die Ausgabe muss `Docker Compose version v2.24` oder neuer zeigen.

## Schritt 2: JuStAI5 herunterladen

```bash
sudo apt-get install -y git
```

```bash
git clone https://github.com/julianstricker/JuStAI5.git
```

```bash
cd JuStAI5
```

Alle weiteren Befehle laufen in diesem Ordner.

## Schritt 3: Den Assistenten zum Sprechen bringen (Google-API-Key)

Wakeword, Spracherkennung, Sprachausgabe und Bildanalyse laufen lokal. Für das
Verstehen und Antworten braucht der Assistent ein Sprachmodell. Am einfachsten ist
Google Gemini:

1. <https://aistudio.google.com> öffnen und mit einem Google-Konto anmelden.
2. **Get API key** → **Create API key**. Den Schlüssel (beginnt mit `AIza…`)
   kopieren.
3. Im JuStAI5-Ordner die Einstellungsdatei anlegen und den Schlüssel eintragen:

```bash
cp .env.example .env
```

```bash
nano .env
```

   Die Zeile `# GOOGLE_API_KEY=` ändern in `GOOGLE_API_KEY=AIza…` (ohne `#`,
   eigenen Schlüssel einsetzen). Speichern mit `Strg+O`, `Enter`, beenden mit
   `Strg+X`.

Der Schlüssel lässt sich auch später in der Oberfläche eintragen (*Plugins →
Gemini*). Die kostenlose Stufe hat Tageslimits; ist ein Limit erreicht, sagt der
Assistent das und weicht, wo möglich, auf ein anderes Modell aus. Eine
Kostengrenze lässt sich unter *KI-Provider* setzen. Ganz ohne Cloud geht es mit
einem lokalen Modell über Ollama ([AI.md](AI.md),
[DEPLOYMENT.md](DEPLOYMENT.md#lokale-ki-mit-ollama)). Was dabei an Google geht
und was nicht, steht in [AI.md](AI.md) und [SECURITY.md](SECURITY.md).

Optional in derselben Datei:

| Zeile | Wozu |
| --- | --- |
| `JUSTAI_ADMIN_PASSWORD=…` | eigenes Admin-Passwort statt eines zufälligen (mindestens 8 Zeichen) |
| `JUSTAI_DISCOVERY_DEFAULT_CIDRS=["192.168.0.0/24"]` | Heimnetz, in dem nach Kameras gesucht werden darf |
| `JUSTAI_TLS_NAMES=["192.168.0.10"]` | IP-Adresse des Rechners fürs HTTPS-Zertifikat (geht auch später in der Oberfläche) |

## Schritt 4: Starten

```bash
docker compose up -d --build
```

Beim ersten Mal baut Docker JuStAI5 und lädt dabei etwa 3 GB (Programm und
Sprachmodelle). Das dauert je nach Internetverbindung einige Minuten bis eine
halbe Stunde. Danach startet JuStAI5 in Sekunden, auch automatisch nach einem
Neustart des Rechners.

Fertig ist es, wenn dieser Befehl `{"ok":true,…` ausgibt:

```bash
curl -s http://localhost:8080/api/health
```

## Schritt 5: Anmelden

1. Die IP-Adresse des Rechners herausfinden (die erste Zahl der Ausgabe, z. B.
   `192.168.0.10`):

```bash
hostname -I
```

2. Im Browser (auf demselben oder einem anderen Gerät im Heimnetz)
   `http://IP-ADRESSE:8080` öffnen, also z. B. `http://192.168.0.10:8080`.
3. Benutzer `admin`. Das Passwort ist das aus `.env` oder, wenn dort keins steht,
   ein zufälliges:

```bash
docker compose exec core cat /data/initial_admin_password.txt
```

4. Eigenes Passwort setzen: *Einstellungen → Benutzer → admin → Neues Passwort*.

Die Sprache der Oberfläche (Deutsch, Englisch, Italienisch) lässt sich oben rechts
umstellen; sie folgt anfangs der Browsersprache. Der Assistent antwortet in der Sprache,
in der man ihn anspricht.

Weitere Personen im Haushalt bekommen unter *Einstellungen → Benutzer* eigene
Zugänge (Rolle „resident“). Sprechen kann jeder, auch ohne Zugang.

## Schritt 6: Ein Handy oder Tablet als Mikrofon und Lautsprecher

Der schnellste Weg zum ersten Gespräch, ganz ohne Kamera:

1. In der Oberfläche *Räume* → **+ Raum**, z. B. „Wohnzimmer“.
2. *Einstellungen → Geräte-App*: Wenn dort „Diese Adresse fehlt im Zertifikat“
   steht, **Hinzufügen** klicken. Dann **JuStAI5-Zertifikat herunterladen** und
   auf dem Handy/Tablet installieren; die Schritte für Android, iPhone/iPad,
   Windows und macOS stehen direkt darunter. (Das Zertifikat ist nötig, weil
   Browser Mikrofon und Kamera nur über eine sichere Verbindung freigeben.)
3. Auf dem Handy/Tablet `https://IP-ADRESSE:8443/app` öffnen, Mikrofon und
   Lautsprecher anlassen, Kamera nach Wunsch, **Starten**.
4. Das Gerät zeigt einen 6-stelligen Code. In der Oberfläche unter *Displays &
   Geräte-App* den Code eingeben, einen Namen und den Raum wählen.
5. „**Hey Jarvis**“ sagen, kurz warten, dann die Frage stellen, z. B. „Wie wird
   das Wetter morgen?“.

JuStAI5 legt dabei im Raum automatisch einen *Interaction Endpoint* an (die
Kombination aus Mikrofon und Lautsprecher, über die gesprochen wird). Als App
installieren: in Chrome/Edge Menü → „App installieren“, in Safari Teilen → „Zum
Home-Bildschirm“. Details: [DISPLAYS.md](DISPLAYS.md#geräte-app-handy-tablet-pc-als-mikrofon-lautsprecher-kamera).

Tippen statt sprechen geht in der Oberfläche unter *Gespräche* (Feld „Nachricht
an den Assistenten …“).

## Schritt 7: Kameras hinzufügen

**Tapo-Kameras vorbereiten** (in der Tapo-App, einmalig):

* *Kamera → Einstellungen → Erweiterte Einstellungen → Kamerakonto*: Benutzername
  und Passwort anlegen.
* Für Lautsprecher und Schwenken braucht JuStAI5 zusätzlich das Passwort des
  TP-Link-Kontos (Tapo-Cloud-Passwort). Es wird verschlüsselt gespeichert und nur
  im Heimnetz an die Kamera geschickt.

**In JuStAI5:**

1. *Geräte* → **Suchen**. Bei „Autorisierte Netzbereiche“ das Heimnetz eintragen,
   meist `192.168.0.0/24` oder `192.168.1.0/24` (die ersten drei Zahlen der
   eigenen IP-Adresse, dann `.0/24`). **Suchen**.
2. Bei der gefundenen Kamera **Hinzufügen**, Namen, Raum und Zugangsdaten
   eintragen, *Testen*, *Speichern*. Kameras, die nicht gefunden werden: *Geräte*
   → **+ Gerät**, Treiber `tapo` oder `onvif` (andere ONVIF/RTSP-Kameras), IP
   eintragen.
3. Nach wenigen Sekunden steht die Kamera auf `online`, im Geräte-Dialog unter
   *Bild* läuft das Livebild.

**Damit die Kamera auch zuhört und spricht:** *Räume* → im Raum **+ Endpoint**,
Kamera als Mikrofon und Lautsprecher (und Kamera) wählen, speichern. Dann beim
Endpoint auf das Wellen-Symbol (**Echo-Latenz kalibrieren**) klicken: Die Kamera
spielt kurze Töne, und JuStAI5 misst, wie lange es dauert, bis es sie selbst hört.
So reagiert der Assistent nie auf seine eigene Stimme.

Ein Raum kann mehrere Endpoints haben (z. B. Kamera und Tablet); geantwortet wird
immer dort, wo das Wakeword am deutlichsten zu hören war.

## Schritt 8: Personen und Haustiere

Unter *Personen* Familienmitglieder und Haustiere anlegen. Bei Tieren als
*Tierart* `dog` (Hund) oder `cat` (Katze) eintragen, so heißen die Klassen der
lokalen Bilderkennung. Damit der Assistent jemanden erkennt:

* **Gesicht**: Vor eine Kamera stellen und sagen „Hey Jarvis, ich bin Anna. Merk
  dir bitte mein Gesicht.“ Der Assistent fragt nach der Einwilligung.
* **Stimme**: „Merk dir meine Stimme.“ (nach ein paar Sätzen im Gespräch). Dann
  erkennt er schon am „Hey Jarvis“, wer spricht.

Gesichter und Stimmen werden nur mit ausdrücklicher Einwilligung gespeichert und
lassen sich jederzeit löschen ([VISION.md](VISION.md#personen-tiere-gesichter)).
Ein Haustier, das als einziges seiner Art angelegt ist, wird automatisch
zugeordnet, wenn eine Kamera einen Hund bzw. eine Katze sieht.

## Fertig, und jetzt?

* Ideen zum Ausprobieren: [BEISPIELE.md](BEISPIELE.md).
* Wakeword ändern, Lautstärke, Echo: *Audio* und [AUDIO.md](AUDIO.md).
* Was in die Cloud geht, pro Raum einstellbar: *Räume → Raum → Richtlinien* und
  *KI-Provider → Datenschutz*.
* Fernseher oder alter Monitor als Bildschirm für Antworten:
  `http://IP-ADRESSE:8080/display` öffnen und unter *Displays* koppeln.

## Aktualisieren, sichern, entfernen

Neue Version installieren (Einstellungen und Daten bleiben erhalten), im
JuStAI5-Ordner:

```bash
git pull
```

```bash
./scripts/install.sh
```

(oder statt des Skripts `docker compose up -d --build`)

Gekoppelte Handys, Tablets und Displays laden die neue Version selbst.

Sicherung (enthält Datenbank, Einstellungen und Schlüssel, deshalb sicher
aufbewahren):

```bash
./scripts/backup.sh
```

Wiederherstellen und Deinstallieren: [DEPLOYMENT.md](DEPLOYMENT.md#backup-und-wiederherstellung).

## Wenn etwas nicht klappt

| Problem | Lösung |
| --- | --- |
| `permission denied … docker.sock` | Nach Schritt 1 ab- und wieder anmelden. |
| Oberfläche nicht erreichbar | `docker compose ps`: läuft `core` und ist `healthy`? Sonst `docker compose logs core`. Firewall: Ports 8080 und 8443 im Heimnetz freigeben. |
| Port 8080 belegt | In `.env` `JUSTAI_HTTP_PORT=8090` setzen, `docker compose up -d`. |
| Assistent sagt nur „Entschuldigung, dabei ist ein Fehler aufgetreten.“ | Meist fehlt der API-Key oder das Tageslimit ist erreicht: *Plugins → Gemini* und *Dashboard → KI-Provider* (pausierte Modelle sind orange). |
| Handy zeigt Zertifikatswarnung | Zertifikat aus *Einstellungen → Geräte-App* installieren; die verwendete Adresse muss dort unter „Zertifikat gilt für“ stehen. |
| Kamera wird nicht gefunden | Netzbereich bei *Suchen* prüfen; manuell mit IP hinzufügen. |
| Kamera `offline` | IP geändert? (Im Router eine feste IP vergeben.) Akku-Kameras schlafen und eignen sich nicht als Mikrofon. |
| „Hey Jarvis“ wird nicht erkannt | *Audio*: bewegt sich der Pegel beim Sprechen? Deutlich und nicht zu weit weg sprechen. |
| Assistent hört sich selbst | Beim Endpoint kalibrieren (Wellen-Symbol). |
| Kein Ton von einer Kamera | „Verbinde die Kamera im Büro neu“ per Sprache oder *Geräte → Neu verbinden*; siehe [AUDIO.md](AUDIO.md). |

Mehr: [DEPLOYMENT.md](DEPLOYMENT.md#fehlersuche).
