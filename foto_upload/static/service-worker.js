self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  if (event.request.mode !== "navigate" || event.request.method !== "GET") return;
  event.respondWith(fetch(event.request).catch(() => new Response(
    '<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline · Foto-Upload</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f4ef;color:#182b24;font:17px system-ui;text-align:center}main{max-width:28rem;padding:2rem}h1{font-size:2rem}a{display:inline-block;margin-top:1rem;padding:.8rem 1.2rem;border-radius:.7rem;background:#173c34;color:white;text-decoration:none;font-weight:700}</style><main><h1>Keine Verbindung</h1><p>Prüfe deine Internetverbindung. Deine Fotos bleiben auf dem Gerät.</p><a href="">Erneut versuchen</a></main></html>',
    {headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}}
  )));
});
