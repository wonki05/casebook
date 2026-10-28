'use strict';
// Only shell assets: the data provider verifies and caches corpus files.
// Personal notes are not stored here and are never deleted by cache rotation.
const SHELL = 'lawbook-shell-__SHELL_VERSION__';
const FILES = ['./index.html', './manifest.webmanifest', './icons/icon.svg',
  './icons/icon-192.png', './icons/icon-512.png'];
const absolute = path => new URL(path, self.registration.scope).href;
const shellUrls = new Set(FILES.map(absolute));
self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    await cache.addAll(FILES.map(path => new Request(absolute(path), {cache: 'reload'})));
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('lawbook-shell-') && key !== SHELL) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (!url.href.startsWith(self.registration.scope)) return;
  if (event.request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const response = await fetch(new Request(event.request, {cache: 'no-store'}));
        if (response.ok) return response;
      } catch (_) {}
      return (await caches.open(SHELL)).match(absolute('./index.html'));
    })());
  } else if (shellUrls.has(url.href)) {
    event.respondWith((async () => (await (await caches.open(SHELL)).match(url.href)) || fetch(event.request))());
  }
});
