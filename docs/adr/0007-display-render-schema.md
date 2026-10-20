# 0007 – Displays only render typed components, success only after confirmation

*[Deutsch](../de/adr/0007-display-render-schema.md) · English*

**Status:** accepted

## Context

The assistant should show content on TVs and tablets (prices, weather, camera images).
Content comes from model output and plugins; neither may execute code in the browser.
The assistant should not claim something is shown when the display is off.

## Decision

* A JSON document of **typed, built-in components**, validated on the server (schema,
  depth, count, allowed URL schemes). Plugin components are templates that the core
  translates into built-in components. No HTML, no script.
* The browser client confirms every presentation only after rendering (`ack`). With an
  invisible page or a render error it reports the reason. The tool only reports success
  on `displayed`.

## Alternatives

* **HTML from the model in a sandbox (iframe/CSP)**: XSS risk, hard to predict layout on
  large screens.
* **Rendering images on the server**: no interaction, poor readability.

## Consequences

* New kinds of presentation need a new built-in component or a plugin template.
* The behaviour can be tested (E2E and browser test).
