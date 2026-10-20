# 0002 – Zwei Plugin-Laufzeiten: im Prozess und Sandbox-Container

*Deutsch · [English](../../adr/0002-plugin-isolation.md)*

**Status:** angenommen

## Kontext

Plugins reichen von Gerätetreibern mit Echtzeit-Audio (müssen schnell und eng
angebunden sein) bis zu fremdem oder vom Assistenten selbst generiertem Code (darf
nichts Unerwartetes tun können).

## Entscheidung

* `builtin`/`trusted` Plugins laufen im Core-Prozess, aber nur über einen
  rechtegeprüften `PluginContext`.
* `untrusted` Plugins (alle hochgeladenen und alle generierten) laufen im
  Sandbox-Container: eigenes internes Netz ohne Internet und LAN, read-only,
  `cap_drop: ALL`, eigener UID, rlimits pro Plugin-Prozess. Zugriffe auf
  Core-Funktionen nur über ein Gateway mit plugin-gebundenem Token, das jede
  Operation gegen die gewährten Rechte prüft. HTTP führt der Core aus (Allowlist,
  keine privaten Ziele).
* Bestimmte Rechte (`devices.provide`, `ai.provide`, `network.lan`, …) sind für
  untrusted Plugins grundsätzlich ausgeschlossen.

## Alternativen

* **Alles in-process mit Python-Sandboxing (RestrictedPython o. ä.)**: in Python
  nicht verlässlich zu sichern.
* **Ein Container pro Plugin**: stärkere Isolation, aber Docker-Socket-Zugriff für
  den Core nötig (selbst ein Sicherheitsrisiko) und hoher Ressourcenbedarf.
* **WebAssembly**: Python-Ökosystem in WASM noch eingeschränkt.

## Konsequenzen

* Untrusted Plugins können keine Gerätetreiber oder KI-Provider sein.
* Plugins teilen sich den Sandbox-Container; rlimits und getrennte Prozesse
  begrenzen gegenseitige Störung, ersetzen aber keine VM ([SECURITY.md](../SECURITY.md#bekannte-grenzen)).
