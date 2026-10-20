# 0008 – Ausgaberaum wird deterministisch bestimmt, nie vom Modell

*Deutsch · [English](../../adr/0008-deterministic-output-routing.md)*

**Status:** angenommen

## Kontext

Eine Frage aus dem Wohnzimmer darf keine Ausgabe in der Küche erzeugen. Sprachmodelle
können Räume verwechseln, Tool-Parameter halluzinieren oder durch Inhalte
(Prompt-Injection) beeinflusst werden.

## Entscheidung

Ein einziger `OutputRouter` entscheidet über jedes Ausgabegerät nach festen Regeln
([ROOMS.md](../ROOMS.md#output-router)): Raum des auslösenden Endpoints; andere
Räume nur mit expliziter Cross-Room-Anfrage, Recht und Freigabe des Zielraums;
Ersatzgeräte nur im selben Raum; offline heißt Fehler statt Ausweichen. Sessions
sind fest an ihren Endpoint gebunden, auch über Tool-Aufrufe und Provider-Wechsel
hinweg. Modelle und Plugins übergeben höchstens Wünsche, die der Router prüft.

## Alternativen

* **Raum als Tool-Parameter vom Modell**: fehleranfällig und manipulierbar.

## Konsequenzen

* Durchsagen in andere Räume brauchen ein eigenes, dafür gebautes Tool
  (`conversation.announce`) und das Recht `output.cross_room`.
* Ablehnungen werden mit Grund geloggt.
