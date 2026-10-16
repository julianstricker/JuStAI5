// Minimal service worker: makes the JuStAI5 app installable. No offline cache on purpose -
// the app is only useful while connected to the core, and stale code must not stay around.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {
  /* network only */
});
