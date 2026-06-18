// Service Worker for STATZ Corporation - Self-Unregistering
// This SW exists solely to clean up caches from previous versions
// and then remove itself. No static file caching is performed.

// On install, skip waiting to activate immediately
self.addEventListener('install', event => {
    self.skipWaiting();
});

// On activate, delete ALL caches and unregister this service worker
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    console.log('[SW] Deleting cache:', cacheName);
                    return caches.delete(cacheName);
                })
            );
        }).then(() => {
            console.log('[SW] All caches cleared. Unregistering service worker.');
            return self.registration.unregister();
        }).then(() => {
            return self.clients.matchAll();
        }).then(clients => {
            // Notify all open tabs to reload so they get fresh resources
            clients.forEach(client => client.navigate(client.url));
        })
    );
});

// Pass all fetch requests straight to the network - no caching at all
self.addEventListener('fetch', event => {
    return;
});
