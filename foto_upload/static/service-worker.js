self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  if (event.request.mode !== "navigate" || event.request.method !== "GET") return;
  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline · Foto-Upload</title><main><h1>Du bist offline</h1><p>Verbinde dein Gerät mit dem Internet und öffne das Album erneut.</p><a href="/">Erneut verbinden</a></main></html>',
    {headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}}
  )));
});
