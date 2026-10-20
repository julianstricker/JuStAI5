# 0007 – Displays rendern nur typisierte Komponenten, Erfolg erst nach Bestätigung

*Deutsch · [English](../../adr/0007-display-render-schema.md)*

**Status:** angenommen

## Kontext

Der Assistent soll auf Fernsehern und Tablets Inhalte zeigen (Kurse, Wetter,
Kamerabilder). Inhalte entstehen aus Modellausgaben und Plugins, beides darf keinen
Code im Browser ausführen. Der Assistent soll nicht behaupten, etwas werde angezeigt,
wenn das Display aus ist.

## Entscheidung

* Ein JSON-Dokument aus **typisierten, eingebauten Komponenten**, serverseitig
  validiert (Schema, Tiefe, Anzahl, erlaubte URL-Schemata). Plugin-Komponenten
  sind Vorlagen, die der Core in eingebaute Komponenten übersetzt. Kein HTML, kein
  Skript.
* Der Browser-Client bestätigt jede Darstellung erst nach dem Rendern (`ack`). Bei
  unsichtbarer Seite oder Renderfehler meldet er den Grund. Das Tool berichtet
  Erfolg nur bei `displayed`.

## Alternativen

* **HTML aus dem Modell in einer Sandbox (iframe/CSP)**: XSS-Risiko, schwer
  vorhersagbares Layout auf großen Bildschirmen.
* **Bilder serverseitig rendern**: keine Interaktion, schlechte Lesbarkeit.

## Konsequenzen

* Neue Darstellungsarten brauchen eine neue eingebaute Komponente oder eine
  Plugin-Vorlage.
* Das Verhalten ist prüfbar (E2E und Browser-Test).
