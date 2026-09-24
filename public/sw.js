// Never cache authenticated data, documents or generated code.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate' || new URL(event.request.url).pathname !== '/') return;
  event.respondWith(fetch(event.request, {cache: 'no-store'}).catch(() => new Response(
    '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PABLO OS sin conexión</title><body style="font:18px system-ui;padding:32px;background:#e8f1fa;color:#172b50"><h1>No hay conexión</h1><p>Conéctate a Internet para abrir PABLO OS. Tus datos siguen guardados en el servidor.</p><p><a href="/">Volver a intentar</a></p></body></html>',
    {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}}
  )));
});
