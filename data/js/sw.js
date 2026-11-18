/*
 * LazyLibrarian service worker: lets the web interface be installed as an app.
 *
 * Served at <http_root>/sw.js so its scope covers the whole interface. It keeps
 * a copy of the static files (css, js, images) for when the server can not be
 * reached, and shows a short "server unreachable" page instead of the browser's
 * own error when a page can not be loaded. Pages themselves are never served
 * from the cache, they always come from the server, and nothing else (the api,
 * downloads, covers, feeds) goes through the worker at all.
 */
'use strict';

var CACHE = 'll-static-v1';
var STATIC = /^(css|js|images|interfaces)\//;
var LOGO = 'images/ll192.png';

self.addEventListener('install', function (event) {
  // the logo is shown on the offline page, so keep a copy from the start
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.add(LOGO); })
      .catch(function () {})
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) {
        return key.indexOf('ll-') === 0 && key !== CACHE;
      }).map(function (key) { return caches.delete(key); }));
    }).then(function () { return self.clients.claim(); })
  );
});

function offlinePage() {
  var html = '<!doctype html><html><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<title>LazyLibrarian</title><style>' +
    'body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;' +
    'font-family:system-ui,sans-serif;background:#272727;color:#eee;text-align:center;padding:1rem}' +
    'img{width:96px;height:96px}button{margin-top:1rem;padding:.5rem 1.25rem;border:0;' +
    'border-radius:999px;background:#56a3da;color:#111;font-size:1rem;cursor:pointer}' +
    '</style></head><body><div><img src="' + new URL(LOGO, self.registration.scope).href + '" alt="">' +
    '<h1>LazyLibrarian</h1><p>The LazyLibrarian server can not be reached right now.</p>' +
    '<button onclick="location.reload()">Try again</button></div></body></html>';
  return new Response(html, {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8'}});
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') {
    return;
  }
  var url = new URL(request.url);
  var scope = new URL(self.registration.scope);
  if (url.origin !== scope.origin || url.pathname.indexOf(scope.pathname) !== 0) {
    return;
  }
  var path = url.pathname.slice(scope.pathname.length);

  if (request.mode === 'navigate') {
    // pages always come from the server, the worker only steps in when it is unreachable
    event.respondWith(fetch(request).catch(offlinePage));
    return;
  }

  if (STATIC.test(path)) {
    // network first, so a LazyLibrarian update is picked up straight away, the copy is for when it is offline
    event.respondWith(
      fetch(request).then(function (response) {
        if (response.ok) {
          var copy = response.clone();
          caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
        }
        return response;
      }).catch(function () {
        return caches.match(request).then(function (cached) {
          return cached || Response.error();
        });
      })
    );
  }
});
