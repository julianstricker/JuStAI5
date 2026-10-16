# Was JuStAI5 kann – Beispiele zum Ausprobieren

Jedes Gespräch beginnt mit **„Hey Jarvis“**. Danach einfach normal sprechen;
Rückfragen gehen ohne neues Wakeword. Wer innerhalb von 5 Minuten wieder
„Hey Jarvis“ sagt, setzt das Gespräch fort („Und wie viele Einwohner hat sie?“).
Alles geht auch getippt: *Gespräche* in der Oberfläche.

Antworten kommen immer im Raum, in dem gefragt wurde, nie woanders, außer man
bittet ausdrücklich darum.

✔ = mit echter Hardware oder im automatischen Test ausprobiert.
In Klammern steht, was dafür nötig ist.

## Erinnern, wenn er dich sieht

* „Wenn du mich das nächste Mal ab morgen um 9 Uhr siehst, erinnere mich, dass
  ich den Müll rausbringen soll.“ ✔ *(Gesicht registriert)*
  Legt eine einmalige Regel an, die erst ab morgen 9:00 scharf ist. Der
  Assistent spricht dich an, sobald dich danach eine Kamera erkennt, und du kannst
  direkt antworten.
* „Wenn du Anna das nächste Mal siehst, begrüße sie mit Namen.“ ✔
* „Wenn ich heimkomme, sag mir, wie das Wetter morgen wird.“
  *(„heimkommen“ = mindestens eine Stunde nicht gesehen)*
* „Wenn du Lukas nach 22 Uhr siehst, sag ihm, dass er ins Bett gehen soll.“
* „Jedes Mal, wenn du mich in der Küche siehst, erinnere mich ans Trinken.“

Ohne Angabe gilt „das nächste Mal“ erst nach mindestens 10 Minuten Abwesenheit.
Sonst würde die Begrüßung losgehen, während man ohnehin vor der Kamera sitzt.

## Zeitgesteuert

* „Erinnere mich morgen um 7:30 an den Zahnarzttermin.“
* „Sag mir jeden Werktag um 7 Uhr hier im Bad das Wetter.“
* „Erinnere mich jeden Sonntagabend um 20 Uhr daran, die Mülltonne rauszustellen.“
* „Welche Erinnerungen hast du für mich?“ · „Lösch die Erinnerung mit dem
  Zahnarzt.“ *(fragt vor dem Löschen nach)*

## Suchen und finden

* „Wo sind meine Autoschlüssel? Such mal im Poolhaus.“ ✔ *(schwenkbare Kamera,
  Gemini)*
  Die Kamera fährt den ganzen Raum ab (10 Blickrichtungen, auch nach unten),
  sucht in allen Bildern und bleibt auf dem Fund stehen: „Auf dem Tisch links
  neben dem Laptop.“
* „Such im Wohnzimmer nach meiner Brille.“
* „Wo ist Lucky?“ *(Lucky als Haustier mit Tierart `dog` oder `cat` angelegt)*
  Antwort aus den Kamerasichtungen: „Zuletzt im Garten gesehen, vor 12 Minuten.“
* „Wo hast du Julian zuletzt gesehen?“
* „Ist gerade jemand im Garten?“ · „Wie viele Leute sind im Wohnzimmer?“
  *(lokal, ohne Cloud)*

## Hinschauen

* „Was siehst du gerade?“ *(Gemini)*
* „Steht die Haustür offen?“ · „Brennt in der Garage noch Licht?“
* „Liegt mein Handy auf dem Schreibtisch?“
* „Lies mir vor, was auf dem Zettel am Kühlschrank steht.“
* „Folge mir mit der Kamera.“ · „Schau nach links.“ · „Kamera zurück in die
  Ausgangsposition.“ *(schwenkbare Kamera)*

Was an Google geht und was lokal bleibt, lässt sich pro Raum einstellen
([AI.md](AI.md)).

## Aufpassen und Bescheid sagen

* „Sag mir Bescheid, wenn ein Auto in die Einfahrt fährt.“
* „Melde dich, wenn der Hund in den Garten geht.“
* „Pass bis heute Abend auf, ob jemand ans Gartentor kommt.“
* Zustände lernen: „Merk dir, so sieht das Garagentor aus, wenn es offen ist.“ …
  (Tor schließen) … „Und so, wenn es zu ist.“ Danach: „Ist das Garagentor zu?“
  oder „Sag mir jeden Abend um 22 Uhr Bescheid, wenn das Garagentor noch offen
  ist.“

## Durchsagen in andere Räume

* „Sag in der Küche Bescheid, dass das Essen fertig ist.“
* „Ruf im Kinderzimmer: In fünf Minuten gibt's Abendessen!“

## Gedächtnis

* „Merk dir, dass Lucky jeden Abend um 18 Uhr Futter bekommt.“ … später: „Wann
  bekommt Lucky Futter?“
* „Merk dir: Annas Geburtstag ist am 3. Mai, sie mag Lilien.“
* „Was habe ich dir letzte Woche über den Urlaub erzählt?“
* „Was weißt du über mich?“
* „Vergiss, was ich dir über meinen Job erzählt habe.“ *(zeigt vorher, was
  gelöscht wird)*

Der Assistent merkt sich auch von selbst Wichtiges aus Gesprächen und
kennzeichnet Vermutungen als solche. Einsehen und löschen: *Gedächtnis*.

## Wer spricht?

* „Ich bin Anna.“
* „Merk dir mein Gesicht.“ *(fragt nach der Einwilligung)*
* „Merk dir meine Stimme.“ ✔ Danach erkennt er schon am „Hey Jarvis“, wer
  spricht, und Erinnerungen, Termine und Begrüßungen sind persönlich.
* „Vergiss meine Stimme.“

## Auf dem Bildschirm

Mit einem gekoppelten Display, Tablet oder Fernseher im selben Raum:

* „Zeig mir den Kurs von Apple der letzten drei Monate.“ ✔
* „Wie stehen Bitcoin, der DAX und der Euro zum Dollar? Zeig's mir.“
* „Zeig mir das Wetter für die nächsten Tage.“
* „Zeig mir die Kamera vom Garten.“ *(Livebild auf dem Bildschirm)*

## Wissen und Alltag

* „Wie wird das Wetter morgen in Bozen?“
* „Wie steht die Tesla-Aktie?“
* „Was ist die Hauptstadt von Australien?“ … „Hey Jarvis, und wie viele
  Einwohner hat sie?“ ✔ *(Fortsetzung innerhalb von 5 Minuten)*
* „Erklär mir kurz, wie eine Wärmepumpe funktioniert.“
* Mehrsprachig: Fragen auf Deutsch, Italienisch oder Englisch werden in der
  jeweiligen Sprache beantwortet.

## Neue Fähigkeiten

* „Ich hätte gern eine Funktion, die mir sagt, in welcher Kalenderwoche ein Datum
  liegt.“ ✔
  Gibt es dafür noch kein Werkzeug, schreibt der Assistent eines: mit Tests und
  Sicherheitsprüfung, in einer abgeschotteten Umgebung. Freigeben muss es ein
  Admin unter *Tools*; danach kann er es sofort benutzen.
* „Was kannst du alles?“

## Rund ums System

* „Welche Geräte sind gerade offline?“
* „Welche Kameras gibt es im Haus?“
* „Danke, das war's.“ beendet das Gespräch (sonst endet es nach ein paar
  Sekunden Stille von selbst).

## Grenzen

* Erkennen setzt voraus, dass eine Kamera die Person oder Sache sieht. Wer
  regungslos sitzt, wird seltener neu erkannt; „das nächste Mal“ heißt deshalb:
  sobald man wieder ins Bild kommt.
* Suchen im ganzen Raum geht nur mit schwenkbaren Kameras; sonst sieht der
  Assistent nur den aktuellen Bildausschnitt.
* Hinschauen und Suchen nach beliebigen Dingen (Schlüssel, Zettel, Licht) braucht
  ein Bildmodell, im Standard Gemini. Lokal erkennt JuStAI5 Personen, Gesichter,
  Tiere und etwa 80 Alltagsgegenstände (Auto, Fahrrad, Flasche, Laptop, Handy …).
* Kameras, die beim Abspielen ihr Mikrofon stummschalten (z. B. Tapo C200), lassen
  sich nicht unterbrechen, während der Assistent spricht.
